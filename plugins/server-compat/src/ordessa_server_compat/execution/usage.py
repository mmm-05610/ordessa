"""Order 51: parse a family's native journal into the neutral usage fact.

The mapping is deliberately boring: every parser turns one family's own
vocabulary into the same optional fields, and a field the family did not
report simply stays absent - never guessed, never substituted by a character
count, never carried over from another family. The parsers are registered by
the deployment's `usageProbe.format`; an unregistered format is a typed
refusal, not a silent fallback.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Any


class UsageParseError(ValueError):
    """A typed failure: the declared source could not be parsed as declared."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


#: The neutral fields and the family vocabulary each comes from. A family's
#: parser only copies what is present; the neutral fact never invents a zero.
def _neutral(
    *, input_tokens: int | None = None, output_tokens: int | None = None,
    cache_read_tokens: int | None = None, cache_write_tokens: int | None = None,
    reasoning_tokens: int | None = None, total_tokens: int | None = None,
) -> dict[str, int]:
    fact: dict[str, int] = {}
    for key, value in (
        ("inputTokens", input_tokens),
        ("outputTokens", output_tokens),
        ("cacheReadTokens", cache_read_tokens),
        ("cacheWriteTokens", cache_write_tokens),
        ("reasoningTokens", reasoning_tokens),
        ("totalTokens", total_tokens),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            fact[key] = value
    return fact


def parse_pi_acp_journal(content: bytes) -> dict[str, Any] | None:
    """The pi-acp session journal: one JSON object per line.

    Assistant rows carry ``usage`` with ``input``/``output``/``cacheRead``/
    ``cacheWrite``/``reasoning``/``totalTokens`` exactly as the harness's
    provider reported them for that turn. The parser returns the *last*
    usage row's neutral fact (the harness's own latest numbers), or None
    when the journal carries none.
    """
    fact: dict[str, int] | None = None
    for line in content.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # not every line is a JSON object; skip silently
        if not isinstance(row, dict):
            continue
        usage = row.get("usage")
        if not isinstance(usage, dict) and isinstance(row.get("message"), dict):
            # The assistant row carries the turn's usage inside its message.
            usage = row["message"].get("usage")
        if not isinstance(usage, dict):
            continue
        candidate = _neutral(
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
            cache_read_tokens=usage.get("cacheRead"),
            cache_write_tokens=usage.get("cacheWrite"),
            reasoning_tokens=usage.get("reasoning"),
            total_tokens=usage.get("totalTokens"),
        )
        if candidate:
            fact = candidate
    return fact


def parse_codex_rollout(content: bytes) -> dict[str, Any] | None:
    """The Codex rollout journal: one JSON object per line.

    Lines carry the harness's own cumulative counters (``total_token_usage``
    with ``input_tokens`` / ``output_tokens`` / ``total_tokens``). The parser
    returns the *last* counters it saw — the harness's own session-to-date
    numbers, copied verbatim; deriving per-turn deltas is the ledger's call,
    not the parser's invention.
    """
    fact: dict[str, int] | None = None
    for line in content.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        # First-hand shape: the counters live at
        # payload.info.total_token_usage — nested, not top-level.
        payload = row.get("payload")
        info = payload.get("info") if isinstance(payload, dict) else None
        usage = info.get("total_token_usage") if isinstance(info, dict) else None
        if not isinstance(usage, dict):
            continue
        candidate = _neutral(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        if candidate:
            fact = candidate
    return fact


def parse_claude_projects_line(content: bytes) -> dict[str, Any] | None:
    """The Claude project journal: one JSON object per line.

    Assistant rows carry ``message.usage`` with ``input_tokens``,
    ``output_tokens`` and the cache-token fields. The parser returns the last
    row whose usage was reported.
    """
    fact: dict[str, int] | None = None
    for line in content.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        message = row.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        candidate = _neutral(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
        )
        if candidate:
            fact = candidate
    return fact


#: The native stores keep their secret-bearing tables right next to the
#: session rows a probe does read. Work Order 084 G2 makes that boundary a
#: machine-checked fact: a statement that reaches for a credential or account
#: table is refused as a typed failure rather than quietly producing a fact
#: that cost the user their secret material.
_FORBIDDEN_QUERY = re.compile(r"\b(?:credentials?|accounts?)\b", re.IGNORECASE)


def _refuse_credential_queries(statements) -> None:
    for sql in statements:
        if _FORBIDDEN_QUERY.search(sql):
            raise UsageParseError(
                "USAGE_PROBE_CREDENTIAL_QUERY",
                "the usage probe issued a statement naming a credential or "
                f"account table; the probe reads session rows only: {sql!r}",
            )


def write_scratch_sqlite(content: bytes, sidecars=None) -> "object":
    """Spool fetched bytes (and any -wal/-shm sidecars) under a unique name.

    A live SQLite store keeps recently committed rows in its ``-wal`` sidecar;
    a fetch that takes only the main file silently loses them. Callers that
    can see the sidecar in their listing fetch it too and hand the bytes here,
    where they are written *next to* the scratch main file so the open sees
    the same database the writer had.
    """
    import os
    import tempfile
    import uuid
    from pathlib import Path

    scratch = (Path(tempfile.gettempdir())
               / f"agentbox-usage-{os.getpid()}-{uuid.uuid4().hex}.db")
    scratch.write_bytes(content)
    for suffix in ("-wal", "-shm"):
        payload = (sidecars or {}).get(suffix)
        if payload:
            scratch.with_name(scratch.name + suffix).write_bytes(payload)
    return scratch


@contextmanager
def _scratch_sqlite(content: bytes, sidecars=None):
    """Open fetched bytes as a read-only scratch database, or yield None.

    The three SQLite-backed families (hermes, opencode, kilo) all parse
    through here: bytes are spooled under a unique scratch name, opened with
    ``mode=ro`` (never the live store), and unlinked afterwards. Every
    statement issued while that handle is open is recorded and checked on the
    way out: a probe that reaches for the secret-bearing tables the same store
    keeps is a typed refusal, not a fact that happens to look correct.
    """
    import sqlite3

    try:
        scratch = write_scratch_sqlite(content, sidecars)
    except OSError:
        scratch = None
    connection = None
    executed: list[str] = []
    if scratch is not None:
        try:
            connection = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
            connection.set_trace_callback(executed.append)
        except sqlite3.Error:
            connection = None
    try:
        yield connection
    finally:
        if connection is not None:
            connection.close()
        if scratch is not None:
            for suffix in ("", "-wal", "-shm"):
                try:
                    scratch.with_name(scratch.name + suffix).unlink()
                except OSError:
                    pass
    _refuse_credential_queries(executed)


def parse_hermes_state_db(content: bytes, *, sidecars=None) -> dict[str, Any] | None:
    """The Hermes session database (SQLite) opened from the fetched bytes.

    ``sessions`` carries the family's own per-session counters
    (``input_tokens`` / ``output_tokens`` / ``cache_read_tokens`` /
    ``cache_write_tokens`` / ``reasoning_tokens``). The parser opens the bytes
    as a read-only scratch database, takes the newest row by the store's own
    ordering (last rowid), and copies exactly the reported fields.
    """
    import sqlite3

    with _scratch_sqlite(content, sidecars) as connection:
        if connection is None:
            return None
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(sessions)")]
            wanted = [name for name in (
                "input_tokens", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "reasoning_tokens",
            ) if name in columns]
            if not wanted:
                return None
            selection = ", ".join(wanted)
            row = connection.execute(
                f"SELECT {selection} FROM sessions ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
    if row is None:
        return None
    return _neutral(**{name: value for name, value in zip(wanted, row)})


def _tokens_blob(tokens: Any) -> dict[str, int] | None:
    """Map the opencode/kilo token blob shape into the neutral fields.

    Both families spell one call's usage as ``total`` / ``input`` / ``output``
    / ``reasoning`` plus ``cache.read`` / ``cache.write``; anything absent
    stays absent.
    """
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    return _neutral(
        input_tokens=tokens.get("input"),
        output_tokens=tokens.get("output"),
        reasoning_tokens=tokens.get("reasoning"),
        total_tokens=tokens.get("total"),
        cache_read_tokens=cache.get("read"),
        cache_write_tokens=cache.get("write"),
    )


def parse_opencode_db(content: bytes, *, sidecars=None) -> dict[str, Any] | None:
    """The opencode state database (SQLite) opened from the fetched bytes.

    Assistant rows of ``message`` carry the family's own per-call ``tokens``
    blob (and ``modelID``/``providerID``) in their ``data`` JSON. The parser
    returns the last assistant row's neutral fact - the newest call's numbers,
    not a re-derived session sum - or None when the store reports none.
    """
    import sqlite3

    with _scratch_sqlite(content, sidecars) as connection:
        if connection is None:
            return None
        try:
            cursor = connection.execute("SELECT data FROM message ORDER BY rowid")
        except sqlite3.Error:
            return None
        fact: dict[str, int] | None = None
        for (data,) in cursor:
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue  # a malformed row is skipped, not fatal
            if not isinstance(payload, dict) or payload.get("role") != "assistant":
                continue
            candidate = _tokens_blob(payload.get("tokens"))
            if candidate:
                fact = candidate
    return fact


def parse_kilo_db(content: bytes, *, sidecars=None) -> dict[str, Any] | None:
    """The kilo state database (SQLite) opened from the fetched bytes.

    ``session`` carries the family's own per-session totals in dedicated
    columns (``tokens_input`` / ``tokens_output`` / ``tokens_reasoning`` /
    ``tokens_cache_read`` / ``tokens_cache_write``). The parser takes the
    newest session by the store's own ``time_updated`` and copies exactly the
    columns that exist; a column the store did not report stays absent.
    """
    import sqlite3

    wanted_names = (
        ("tokens_input", "input_tokens"),
        ("tokens_output", "output_tokens"),
        ("tokens_reasoning", "reasoning_tokens"),
        ("tokens_cache_read", "cache_read_tokens"),
        ("tokens_cache_write", "cache_write_tokens"),
    )
    with _scratch_sqlite(content, sidecars) as connection:
        if connection is None:
            return None
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(session)")]
            wanted = [neutral for store, neutral in wanted_names if store in columns]
            if not wanted:
                return None
            stores = [store for store, neutral in wanted_names if store in columns]
            selection = ", ".join(stores)
            row = connection.execute(
                f"SELECT {selection} FROM session "
                "ORDER BY time_updated DESC, rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
    if row is None:
        return None
    return _neutral(**{name: value for name, value in zip(wanted, row)})


#: The registered formats. A deployment may only declare one of these names;
#: anything else is a deployment refusal.
FORMATS = {
    "pi-acp-journal": parse_pi_acp_journal,
    "codex-rollout": parse_codex_rollout,
    "claude-projects-line": parse_claude_projects_line,
    "hermes-state-db": parse_hermes_state_db,
    "opencode-state-db": parse_opencode_db,
    "kilo-state-db": parse_kilo_db,
}


#: The parsers whose carrier is a live SQLite database: their sidecars must
#: travel with the main file or WAL-resident rows are invisible.
SQLITE_FORMATS = frozenset({"hermes-state-db", "opencode-state-db", "kilo-state-db"})


def parse_usage(
    usage_format: str, content: bytes, *, sidecars=None,
) -> dict[str, int] | None:
    parser = FORMATS.get(usage_format)
    if parser is None:
        raise UsageParseError(
            "USAGE_FORMAT_UNREGISTERED",
            f"no parser is registered for usage format {usage_format!r}",
        )
    if usage_format in SQLITE_FORMATS:
        return parser(content, sidecars=sidecars)
    return parser(content)


__all__ = [
    "FORMATS",
    "UsageParseError",
    "parse_pi_acp_journal",
    "parse_opencode_db",
    "parse_kilo_db",
    "parse_usage",
]
