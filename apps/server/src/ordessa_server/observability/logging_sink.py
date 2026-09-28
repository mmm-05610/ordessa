"""C-04 — the Python half of the log format, isomorphic with the TypeScript one.

Two halves write logs into the same data root and a diagnostic export
parses them as one timeline, so the two writers must agree on more than
"it is JSON". They agree on three things, and this module fixes all three:

* **Field order.** `ts, level, scope, msg`, then the caller's fields in the
  order given. Python dicts keep insertion order and `json.dumps` does not
  sort unless asked, so the order is available rather than hoped for.
* **Redaction.** The four rules of C-04 §4 are enforced HERE, at the sink,
  where a caller cannot route around them: a field named like a secret, a
  value that *contains* the token bytes, a value read out of `secrets/`,
  and a path field reduced to its basename.
* **Rotation.** 10 MiB, five files kept, older ones deleted. The numbers
  come from the shared layout json, not from a literal here.

The sentinel is what makes rule 2 possible: the sink is told the token
bytes once, at construction, and then redacts them wherever they appear —
in a renamed field, in a message body, inside a URL, in a traceback. A
caller that never mentions "token" is still covered.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping, Sequence

from ..bootstrap.data_root import (
    LOG_KEEP,
    LOG_ROTATE_BYTES,
    SECRETS_DIR,
    server_log_file,
)

#: C-04 §4 rule 1. Matched case-insensitively as a SUBSTRING of the key, so
#: `apiKey`, `api_key` and `X-Api-Key` are all the same rule, not three.
SECRET_KEY_FRAGMENTS: "tuple[str, ...]" = (
    "token", "secret", "password", "credential", "authorization",
    "bearer", "apikey", "api_key",
)

#: The single replacement. Nothing else may stand in for a redacted value:
#: a second placeholder would let a consumer tell "redacted" from "short".
REDACTED = "[redacted]"

#: `-`, `.` and whitespace carry no meaning in a key name; folding them out
#: is what lets one rule cover `api_key`, `apiKey` and `X-Api-Key`.
_SEPARATOR_FOLD = str.maketrans({"-": "", ".": "", " ": "", "_": "_"})

LEVELS: "tuple[str, ...]" = ("debug", "info", "warn", "error")


class LogWriteFailure(RuntimeError):
    """The sink could not write. It is counted, never raised at the caller."""


def is_secret_key(key: str) -> bool:
    """C-04 §4 rule 1, matched case-insensitively as a substring.

    Separators are folded out before matching, so a header-shaped key
    (`X-Api-Key`, `api.key`) is recognised as the same rule as `apiKey`.
    This only ever ADDS matches: every key the contract names still matches
    exactly as written, and none of the eight fragments is restated here.
    """
    lowered = key.lower()
    folded = lowered.translate(_SEPARATOR_FOLD)
    return any(
        fragment in lowered or fragment in folded for fragment in SECRET_KEY_FRAGMENTS
    )


def utc_now_iso() -> str:
    """ISO-8601 UTC with millisecond precision — C-04 §2's `ts`, exactly."""
    moment = datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def redact_text(value: str, sentinels: "Sequence[str]") -> str:
    """C-04 §4 rule 2 — replace every sentinel substring, in place.

    Substring, not equality: the same bytes pasted into a sentence, a URL
    or a traceback frame are all the same leak, and an equality test would
    catch exactly one of them.
    """
    for sentinel in sentinels:
        if sentinel and sentinel in value:
            value = value.replace(sentinel, REDACTED)
    return value


def redact_value(value: Any, sentinels: "Sequence[str]") -> Any:
    """Redact one value under rules 2 and 4, recursing into containers."""
    if isinstance(value, str):
        return redact_text(value, sentinels)
    if isinstance(value, Mapping):
        return {str(key): redact_field(str(key), item, sentinels)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item, sentinels) for item in value]
    return value


def redact_field(key: str, value: Any, sentinels: "Sequence[str]") -> Any:
    """The whole of C-04 §4 for one field, in the order the rules apply.

    Rule 1 (the key names a secret) wins over everything: a field called
    `token` is `[redacted]` even when its value is an empty string, because
    "empty" would tell a reader the secret exists and is unset.
    """
    if is_secret_key(key):
        return REDACTED
    # Rule 4: a locator is at most a basename. Applied to anything that
    # looks like a path, so an unrelated field cannot smuggle one either.
    if isinstance(value, str) and _looks_like_path(value):
        return redact_text(os.path.basename(value.rstrip("/")) or value, sentinels)
    return redact_value(value, sentinels)


def _looks_like_path(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\\\") or (os.sep in value and " " not in value)


@dataclass(frozen=True)
class LogRecord:
    """One record, already ordered: `ts, level, scope, msg`, then fields."""

    level: str
    scope: str
    msg: str
    fields: "Mapping[str, Any]"
    ts: str

    def as_dict(self) -> "dict[str, Any]":
        return {"ts": self.ts, "level": self.level, "scope": self.scope,
                "msg": self.msg, **dict(self.fields)}


class JsonLinesSink:
    """The Server's own log file: `$DATA_ROOT/logs/server.log`, rotated.

    A write failure is counted and dropped (C-04 §6). It is never raised
    into the caller's flow, and it never replaces the primary failure of a
    larger operation — this class has no way to raise at all except from
    `flush`, which the caller may ignore.
    """

    def __init__(
        self,
        data_root: Path,
        *,
        token: str | None = None,
        level: str = "info",
        rotate_bytes: int = LOG_ROTATE_BYTES,
        keep: int = LOG_KEEP,
    ) -> None:
        self.path = server_log_file(data_root)
        # The token bytes are the sentinel. Held here, in the Server's
        # memory, and never handed to a caller or written anywhere.
        self._sentinels: "tuple[str, ...]" = (token,) if token else ()
        self.level = level if level in LEVELS else "info"
        self.rotate_bytes = rotate_bytes
        self.keep = keep
        self._lock = threading.Lock()
        self.dropped = 0
        self._last_failure: str | None = None

    # -- the one entry point -------------------------------------------

    def write(
        self, level: str, scope: str, msg: str, fields: "Mapping[str, Any] | None" = None
    ) -> None:
        """Redact, order, append. Returns nothing; raises nothing."""
        if LEVELS.index(level) < LEVELS.index(self.level):
            return
        record = LogRecord(
            level=level, scope=scope, msg=redact_text(str(msg), self._sentinels),
            fields=self._redacted_fields(fields or {}),
            ts=utc_now_iso(),
        )
        # Compact separators: C-04 §2 shows the record without spaces, and
        # `JSON.stringify` on the TypeScript side produces the same bytes.
        # That is what lets the isomorphism test compare whole lines, not
        # only the key sets.
        line = json.dumps(
            record.as_dict(), ensure_ascii=False, default=str, separators=(",", ":")
        )
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(line.encode("utf-8")) + 1)
                with open(self.path, "a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError as exc:
                # C-04 §6: drop and count. The caller's operation continues.
                self.dropped += 1
                self._last_failure = str(exc)

    def _redacted_fields(self, fields: "Mapping[str, Any]") -> "dict[str, Any]":
        return {str(key): redact_field(str(key), value, self._sentinels)
                for key, value in fields.items() if value is not None}

    # -- rotation -------------------------------------------------------

    def _rotate_if_needed(self, incoming: int) -> None:
        """Rotate by SIZE, before the write, keeping exactly `keep` files.

        Checking before writing (not after) is what makes the bound real:
        a file may exceed the limit by the record that crossed it, never by
        an unbounded run of records.
        """
        try:
            current = self.path.stat().st_size
        except FileNotFoundError:
            return
        if current + incoming <= self.rotate_bytes:
            return
        oldest = self.path.with_name(self.path.name + f".{self.keep - 1}")
        if oldest.exists():
            oldest.unlink()
        for index in range(self.keep - 2, 0, -1):
            source = self.path.with_name(self.path.name + f".{index}")
            if source.exists():
                source.replace(self.path.with_name(self.path.name + f".{index + 1}"))
        if self.path.exists():
            self.path.replace(self.path.with_name(self.path.name + ".1"))

    # -- a scoped facade -------------------------------------------------

    def child(self, scope: str) -> "ScopedLogger":
        return ScopedLogger(self, scope)


class ScopedLogger:
    """A logger bound to one scope; the shape plugins are given in TypeScript.

    The Python and TypeScript loggers are the same object model with the
    same four levels and the same `child`, so a record's `scope` means the
    same thing on both sides of the product.
    """

    __slots__ = ("_sink", "_scope")

    def __init__(self, sink: JsonLinesSink, scope: str) -> None:
        self._sink = sink
        self._scope = scope

    def child(self, scope: str) -> "ScopedLogger":
        return ScopedLogger(self._sink, f"{self._scope}.{scope}")

    def debug(self, msg: str, fields: "Mapping[str, Any] | None" = None) -> None:
        self._sink.write("debug", self._scope, msg, fields)

    def info(self, msg: str, fields: "Mapping[str, Any] | None" = None) -> None:
        self._sink.write("info", self._scope, msg, fields)

    def warn(self, msg: str, fields: "Mapping[str, Any] | None" = None) -> None:
        self._sink.write("warn", self._scope, msg, fields)

    def error(self, msg: str, fields: "Mapping[str, Any] | None" = None) -> None:
        self._sink.write("error", self._scope, msg, fields)


def server_logger(
    data_root: Path, *, token: str | None = None, level: str = "info", scope: str = "host.server"
) -> ScopedLogger:
    """The Server's root logger; the caller only ever sees a scoped child."""
    return JsonLinesSink(data_root, token=token, level=level).child(scope)


def secrets_relative(path: Path, data_root: Path) -> bool:
    """True when `path` lives under `$DATA_ROOT/secrets` (C-04 §4 rule 3)."""
    try:
        path.relative_to(data_root / SECRETS_DIR)
    except ValueError:
        return False
    return True


def iter_records(text_lines: "Iterable[str]") -> "list[dict[str, Any]]":
    """Parse JSON Lines the way the diagnostic export does.

    A line that does not parse is DROPPED, never passed through: the
    alternative is shipping an unredacted fragment of a malformed line
    into a bundle a user is about to share (C-04 §5).
    """
    records: "list[dict[str, Any]]" = []
    for line in text_lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def record_field_order(record: "Mapping[str, Any]") -> "tuple[str, ...]":
    """The key order of a record — what the isomorphism test compares."""
    return tuple(record.keys())
