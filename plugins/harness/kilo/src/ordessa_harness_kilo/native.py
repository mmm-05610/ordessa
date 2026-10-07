"""kilo's native-config dialect facts (P-A② split: approvals/PA2-dialect-release.md).

Only this family's facts; the shared engine consumes the table and refuses
whatever is not pinned here. kilo is a fork of opencode with the same dialect
value, but the table is held here on purpose - no import of ``opencode`` from
this module (each family owns its facts).
"""
from __future__ import annotations

#: first-hand source: deploy/kilo/kilo.json is a fork of opencode; same @ai-sdk dialect.
DIALECTS: dict[str, tuple[str, str | None]] = {
    "openai-chat": ("npm", "@ai-sdk/openai-compatible"),
}

#: First-hand-pinned native config target path (relative to the guest home).
NATIVE_TARGET = "kilo.json"
