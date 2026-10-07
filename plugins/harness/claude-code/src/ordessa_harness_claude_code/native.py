"""claude-code's native-config dialect facts (P-A② split: approvals/PA2-dialect-release.md).

Naming note (kept as-is by the approval): the harness id key is ``claude-code``
while the family package directory is ``claude`` - the aggregation in
``native_materialization`` maps this module under the ``claude-code`` key.

first-hand source: deploy/claude/settings.json env.ANTHROPIC_BASE_URL=".../anthropic":
claude speaks anthropic-messages only; there is NO pinned native field for a
chat protocol, so openai-chat/responses/gemini are refused by the shared engine.
"""
from __future__ import annotations

DIALECTS: dict[str, tuple[str, str | None]] = {
    "anthropic-messages": ("ANTHROPIC_BASE_URL", None),  # None -> no dialect token, only the endpoint
}

#: First-hand-pinned native config target path (relative to the guest home).
NATIVE_TARGET = "settings.json"
