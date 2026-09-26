"""Order 59: per-family hook models - one schema each, no invented unity.

Stage A pinned two families to one *shape*: Claude Code and Codex both take a
declarative hook (an event, an optional matcher, a list of handlers with a
type, a payload and a timeout), differ in which events and handler types they
accept and in their manager-only switches, and OpenCode is not declarative at
all (its hooks are code plugins, handled as code assets elsewhere). So this
module holds one declarative schema *per family* and refuses, per family, with
a typed code - the order's "不支持的事件 → 类型化拒绝，不静默丢弃".

Nothing here writes a user's native configuration. The model is what the
ledger stores and what the materialiser renders into a read-only projection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
#: Handler types the two declarative families accept. `command` is the only
#: one that runs a process in our model; the rest are declared by the families
#: and passed through verbatim so the projection is the family's own form.
HANDLER_TYPES = ("command", "http", "mcp_tool", "prompt", "agent")
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 600
MAX_HANDLERS = 8


class HookModelError(RuntimeError):
    """A typed refusal of one hook model."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class FamilyHookSchema:
    """One family's declared hook model."""

    family: str
    #: Events the family accepts. Empty means "this family has no declarative
    #: hooks" and any model for it is refused.
    events: tuple[str, ...] = ()
    supports_matcher: bool = True
    handler_types: tuple[str, ...] = HANDLER_TYPES
    #: A manager-only switch the family exposes; recorded so the projection can
    #: state it instead of us guessing whether hooks are restricted.
    managed_only_flag: str | None = None


#: First-hand (order 59 stage A): the observed event sets per family. Codex
#: shares the naming with Claude Code but is a narrower set, so each family
#: keeps its own list rather than one merged "everyone supports everything".
SCHEMAS: dict[str, FamilyHookSchema] = {
    "claude-code": FamilyHookSchema(
        family="claude-code",
        events=("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
                "PostToolUse", "PreCompact", "Notification", "Stop", "SubagentStop"),
        handler_types=HANDLER_TYPES,
        managed_only_flag="disableAllHooks",
    ),
    "codex": FamilyHookSchema(
        family="codex",
        events=("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
                "PostToolUse", "PreCompact", "Notification", "Stop", "SubagentStop"),
        handler_types=("command",),
        managed_only_flag="hooks_only",
    ),
}


def schema_for(family: str) -> FamilyHookSchema:
    """The family's declared hook model, or a typed refusal.

    A family absent from the table is *unsupported on purpose* (stage A found
    no hook surface for it): the refusal is how the UI learns to say so,
    instead of drawing a switch that would do nothing.
    """
    schema = SCHEMAS.get(family)
    if schema is None:
        raise HookModelError(
            "HOOK_FAMILY_UNSUPPORTED",
            f"the {family!r} family declares no hook model",
            field="family",
        )
    if not schema.events:
        raise HookModelError(
            "HOOK_FAMILY_UNSUPPORTED",
            f"the {family!r} family has no declarative hooks",
            field="family",
        )
    return schema


def _bounded_text(value: Any, field_name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise HookModelError(
            "HOOK_FIELD_INVALID", f"{field_name} must be a bounded non-empty string",
            field=field_name,
        )
    return value


def validate_model(family: str, model: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one hook model against the family's schema.

    Returns the canonical model (what the ledger stores and the materialiser
    renders). Every refusal names the field it is about, so the form can point
    at the offending input rather than saying "invalid".
    """
    schema = schema_for(family)
    if not isinstance(model, Mapping):
        raise HookModelError("HOOK_MODEL_INVALID", "the model must be an object")
    if set(model) - {"event", "matcher", "handlers"}:
        raise HookModelError(
            "HOOK_MODEL_INVALID",
            f"unknown model fields: {sorted(set(model) - {'event', 'matcher', 'handlers'})}",
        )
    event = model.get("event")
    if event not in schema.events:
        raise HookModelError(
            "HOOK_EVENT_UNSUPPORTED",
            f"{family!r} does not declare the event {event!r} "
            f"(declared: {sorted(schema.events)})",
            field="event",
        )
    matcher = model.get("matcher")
    if matcher is not None:
        if not schema.supports_matcher:
            raise HookModelError(
                "HOOK_MATCHER_UNSUPPORTED",
                f"{family!r} does not support matchers", field="matcher",
            )
        matcher = _bounded_text(matcher, "matcher", 128)
    handlers = model.get("handlers")
    if not isinstance(handlers, Sequence) or isinstance(handlers, (str, bytes)):
        raise HookModelError("HOOK_FIELD_INVALID", "handlers must be a list", field="handlers")
    if not 1 <= len(handlers) <= MAX_HANDLERS:
        raise HookModelError(
            "HOOK_FIELD_INVALID", f"handlers must hold 1..{MAX_HANDLERS} entries",
            field="handlers",
        )
    canonical_handlers: list[dict[str, Any]] = []
    for index, handler in enumerate(handlers):
        if not isinstance(handler, Mapping):
            raise HookModelError(
                "HOOK_FIELD_INVALID", f"handler {index} must be an object",
                field=f"handlers[{index}]",
            )
        allowed = {"type", "command", "url", "tool", "prompt", "timeout", "async"}
        if set(handler) - allowed:
            raise HookModelError(
                "HOOK_FIELD_INVALID",
                f"handler {index} has unknown fields: {sorted(set(handler) - allowed)}",
                field=f"handlers[{index}]",
            )
        handler_type = handler.get("type")
        if handler_type not in schema.handler_types:
            raise HookModelError(
                "HOOK_HANDLER_UNSUPPORTED",
                f"{family!r} does not declare handler type {handler_type!r} "
                f"(declared: {sorted(schema.handler_types)})",
                field=f"handlers[{index}].type",
            )
        canonical: dict[str, Any] = {"type": handler_type}
        if handler_type == "command":
            canonical["command"] = _bounded_text(handler.get("command"), "command", 4096)
        elif handler_type == "http":
            url = _bounded_text(handler.get("url"), "url", 512)
            if not (url.startswith("https://") or url.startswith("http://127.0.0.1")):
                raise HookModelError(
                    "HOOK_FIELD_INVALID",
                    "an http handler needs an https (or loopback) url",
                    field=f"handlers[{index}].url",
                )
            canonical["url"] = url
        elif handler_type == "mcp_tool":
            canonical["tool"] = _bounded_text(handler.get("tool"), "tool", 128)
        else:
            canonical[handler_type] = _bounded_text(
                handler.get(handler_type), handler_type, 4096)
        timeout = handler.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        if (isinstance(timeout, bool) or not isinstance(timeout, int)
                or not 1 <= timeout <= MAX_TIMEOUT_SECONDS):
            raise HookModelError(
                "HOOK_TIMEOUT_INVALID",
                f"timeout must be 1..{MAX_TIMEOUT_SECONDS} seconds",
                field=f"handlers[{index}].timeout",
            )
        canonical["timeout"] = timeout
        asynchronously = handler.get("async", False)
        if not isinstance(asynchronously, bool):
            raise HookModelError(
                "HOOK_FIELD_INVALID", "async must be a boolean",
                field=f"handlers[{index}].async",
            )
        canonical["async"] = asynchronously
        canonical_handlers.append(canonical)
    result: dict[str, Any] = {"event": event, "handlers": canonical_handlers}
    if matcher is not None:
        result["matcher"] = matcher
    return result


def command_preview(model: Mapping[str, Any]) -> list[str]:
    """Every command the model would run, in order - what the UI must show.

    The order's rule is that enabling a hook requires seeing the full command
    text; this is that view, derived from the canonical model so it cannot
    drift from what the projection will contain.
    """
    return [
        handler["command"]
        for handler in model.get("handlers", ())
        if handler.get("type") == "command"
    ]
