"""Order 59 G3: render enabled hooks into the family's own document shape.

Both declarative families take the same *shape* (stage A pinned it): a mapping
of event name to a list of matcher groups, each group carrying its `hooks`
array of handlers. They differ in where that mapping lives - Claude Code keeps
it under the `hooks` key of `settings.json`, Codex's `hooks/hooks.json` *is*
the mapping - so the renderer produces the fragment and the target/key come
from the registry declaration.

The renderer never touches a user's native configuration: the fragment is
written into our own store and reaches an execution as a read-only projection
(here: a file written into the Profile's working copy at the declared target).
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from ordessa_server_compat.hooks.model import HookModelError, schema_for


class HookRenderError(RuntimeError):
    """A typed refusal of one render request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def render_hooks_fragment(family: str, models: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The family's own hook mapping for the models given, in event order.

    Grouping matches the families' documented shape: one matcher group per
    (event, matcher) pair, its `hooks` array preserving the order the user
    configured. `timeout` and `async` are always written, so what the family
    runs is exactly what the ledger shows.
    """
    try:
        schema_for(family)
    except HookModelError as refusal:
        raise HookRenderError(refusal.code, refusal.message) from refusal
    fragment: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        event = str(model["event"])
        matcher = model.get("matcher")
        group: dict[str, Any] = {}
        if matcher is not None:
            group["matcher"] = matcher
        group["hooks"] = [
            {
                "type": handler["type"],
                **({"command": handler["command"]} if handler["type"] == "command" else {}),
                **({"url": handler["url"]} if handler["type"] == "http" else {}),
                **({"tool": handler["tool"]} if handler["type"] == "mcp_tool" else {}),
                **({handler["type"]: handler[handler["type"]]}
                   if handler["type"] in {"prompt", "agent"} else {}),
                "timeout": handler["timeout"],
                "async": handler["async"],
            }
            for handler in model["handlers"]
        ]
        fragment.setdefault(event, []).append(group)
    return fragment


def merge_fragments(
    target: str, fragments: Sequence[tuple[str | None, Mapping[str, Any]]],
) -> str:
    """Assemble one JSON document from fragments, keyed or at the root.

    A fragment with no key *is* the document (Codex's `hooks/hooks.json`); a
    keyed fragment becomes one entry of it (Claude's `settings.json` gathers
    `mcpServers` and `hooks`). Two fragments claiming the same key is a
    refusal, not a silent overwrite.
    """
    document: dict[str, Any] = {}
    for key, fragment in fragments:
        if key is None:
            overlap = set(document) & set(fragment)
            if overlap:
                raise HookRenderError(
                    "HOOK_TARGET_CONFLICT",
                    f"root fragments overlap at {sorted(overlap)}",
                )
            document.update(fragment)
            continue
        if key in document:
            raise HookRenderError(
                "HOOK_TARGET_CONFLICT", f"two fragments claim the key {key!r}",
            )
        document[key] = dict(fragment)
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


def hooks_target_for(profile_spec: Any) -> tuple[str | None, str | None]:
    """The family's declared hooks location, or (None, None) when unsupported."""
    return getattr(profile_spec, "hooks_target", None), getattr(profile_spec, "hooks_key", None)
