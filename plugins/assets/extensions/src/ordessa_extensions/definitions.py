"""EXT-2 — the hook definition model.

Every executable hook carries the 机制 D red-line fields (specs/016-
overnight-batch/tasks.md EXT-2): executable content is admitted ONLY with
a mandatory approval, a source hash and a version pin. The model itself is
pure data: frozen shapes, strict validation, typed refusals — nothing here
touches a process, a path or a network.

Event vocabulary honesty: only event names evidenced IN-REPO are admitted.
`SessionStart` is named first-hand in the pinned Codex closure
(`plugins/harness/src/ordessa_harness/codex/hooks.py:16` requires exactly
`hook_event_name == "SessionStart"`) and in the registry comment
(`harnesses.toml:38-40`, "SessionStart…SubagentStop"); `PreToolUse` is the
only other event the registry comment names with an observation count
(`harnesses.toml:117-119`, "PreToolUse 108 refs"). The familiar fuller
Claude event list lives in vendor docs only — per the capability rule
("no in-repo evidence 就不声称") those names are REFUSED here, not
silently accepted; extending `KNOWN_EVENTS` requires an in-repo citation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

HOOK_ID = re.compile(r"\A[a-z][a-z0-9._-]{0,63}\Z")
_SHA256 = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_PIN = re.compile(r"\A\d+\.\d+\.\d+\Z")
_HANDLER_REF = re.compile(r"\A[a-z][a-z0-9._-]{0,63}\Z")

#: Bounded hook fields (tasks EXT-2: 超时/异步 are part of the definition).
MAX_MATCHER_LENGTH = 512
MAX_ARGV = 16
MAX_ARG_BYTES = 4096
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600

#: Event names with an in-repo first-hand or comment-grade citation (see
#: module docstring). A definition naming anything else is refused —
#: "unknown" would silently widen the projection surface.
KNOWN_EVENTS: Mapping[str, str] = {
    "SessionStart": (
        "plugins/harness/src/ordessa_harness/codex/hooks.py:16 (first-hand,"
        " pinned closure); plugins/harness/src/ordessa_harness/"
        "harnesses.toml:38-40 (Order 59 stage A comment)"),
    "PreToolUse": (
        "plugins/harness/src/ordessa_harness/harnesses.toml:117-119"
        " (Order 59 stage A comment, claude settings.json, 108 refs)"),
    "SubagentStop": (
        "plugins/harness/src/ordessa_harness/harnesses.toml:38-40"
        " (Order 59 stage A comment, range end; comment-grade)"),
}


class ExtensionDefinitionError(ValueError):
    """A typed definition refusal; `code` is stable diagnostic vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HookDefinition:
    """One executable hook definition (tasks EXT-2).

    `action_kind` selects the action face: `"command"` requires a bounded
    argv TUPLE (a shell string is refused at construction — the injection
    surface must never be expressible in the first place), `"handler"`
    requires a handler reference into a registry that does not exist yet
    (the handler route is modelled but every loader refuses it tonight —
    the in-repo projection seam for in-process handlers is an open
    api-request, not a silent capability).
    """

    hook_id: str
    event: str
    action_kind: str
    command: tuple[str, ...] | None
    handler_ref: str | None
    timeout_seconds: int
    run_async: bool
    #: 机制 D: version pin of the executable content source.
    pin: str
    #: 机制 D: source hash of the executable content, `sha256:<hex>`.
    content_sha256: str
    matcher: str | None = None

    def __post_init__(self) -> None:
        _validate(self)

    def payload(self) -> dict:
        """Canonical JSON-able form (the approval fingerprint input)."""
        return {
            "hookId": self.hook_id,
            "event": self.event,
            "matcher": self.matcher,
            "actionKind": self.action_kind,
            "command": list(self.command) if self.command is not None else None,
            "handlerRef": self.handler_ref,
            "timeoutSeconds": self.timeout_seconds,
            "runAsync": self.run_async,
            "pin": self.pin,
            "contentSha256": self.content_sha256,
        }


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ExtensionDefinitionError(code, message)


def _validate(d: HookDefinition) -> None:
    _require(bool(HOOK_ID.fullmatch(d.hook_id or "")), "HOOK_ID_INVALID",
             f"hook_id {d.hook_id!r} must be a lowercase slug")
    _require(d.event in KNOWN_EVENTS, "EVENT_UNEVIDENCED",
             f"event {d.event!r} has no in-repo evidence; known events: "
             f"{sorted(KNOWN_EVENTS)} (extend KNOWN_EVENTS only with a "
             "repo citation)")
    _require(d.action_kind in ("command", "handler"), "ACTION_KIND_INVALID",
             f"action_kind {d.action_kind!r} must be 'command' or 'handler'")
    if d.action_kind == "command":
        _require(d.handler_ref is None, "ACTION_AMBIGUOUS",
                 "a command action must not carry handler_ref")
        _require(isinstance(d.command, tuple) and bool(d.command),
                 "COMMAND_REQUIRED",
                 "command actions need a non-empty argv tuple")
        _require(len(d.command) <= MAX_ARGV, "COMMAND_TOO_LONG",
                 f"argv exceeds {MAX_ARGV} elements")
        for element in d.command:
            _require(isinstance(element, str) and element,
                     "COMMAND_ARG_INVALID", "argv elements must be non-empty"
                     " strings")
            _require(len(element.encode("utf-8")) <= MAX_ARG_BYTES,
                     "COMMAND_ARG_TOO_LONG",
                     f"argv element exceeds {MAX_ARG_BYTES} bytes")
    else:
        _require(d.command is None, "ACTION_AMBIGUOUS",
                 "a handler action must not carry command")
        _require(bool(_HANDLER_REF.fullmatch(d.handler_ref or "")),
                 "HANDLER_REF_INVALID",
                 "handler actions need a lowercase handler reference")
    _require(d.matcher is None or (
        isinstance(d.matcher, str) and bool(d.matcher)
        and len(d.matcher) <= MAX_MATCHER_LENGTH), "MATCHER_INVALID",
        f"matcher must be a string of at most {MAX_MATCHER_LENGTH} chars")
    _require(isinstance(d.timeout_seconds, int)
             and not isinstance(d.timeout_seconds, bool)
             and MIN_TIMEOUT_SECONDS <= d.timeout_seconds
             <= MAX_TIMEOUT_SECONDS, "TIMEOUT_OUT_OF_BOUNDS",
             f"timeout_seconds must be an int in "
             f"[{MIN_TIMEOUT_SECONDS}, {MAX_TIMEOUT_SECONDS}]")
    _require(isinstance(d.run_async, bool), "RUN_ASYNC_INVALID",
             "run_async must be a boolean")
    _require(bool(_PIN.fullmatch(d.pin or "")), "PIN_INVALID",
             f"pin {d.pin!r} must be a machine X.Y.Z triple (机制 D)")
    _require(bool(_SHA256.fullmatch(d.content_sha256 or "")),
             "CONTENT_HASH_INVALID",
             "content_sha256 must be 'sha256:' + 64 hex chars (机制 D)")


def definition_fingerprint(definition: HookDefinition) -> str:
    """Stable fingerprint over the canonical payload (审批链的指纹).

    Two definitions with identical payloads share a fingerprint; any
    content, pin or matching change produces a different one, so a stale
    approval can never bless new content.
    """
    canonical = json.dumps(definition.payload(), sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "KNOWN_EVENTS", "MAX_ARGV", "MAX_ARG_BYTES", "MAX_MATCHER_LENGTH",
    "MAX_TIMEOUT_SECONDS", "MIN_TIMEOUT_SECONDS",
    "ExtensionDefinitionError", "HookDefinition", "definition_fingerprint",
]
