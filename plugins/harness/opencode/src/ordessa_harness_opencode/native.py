"""opencode's native-config dialect facts (P-A② split: approvals/PA2-dialect-release.md).

Only this family's facts; the shared engine consumes the table and refuses
whatever is not pinned here. kilo is a fork with the same dialect but holds
**its own copy** in ``kilo/native.py`` - the two tables are equal by value and
deliberately not the same object (each family owns its facts).
"""
from __future__ import annotations

#: first-hand source: deploy/opencode/opencode.json provider.deepseek.npm = "@ai-sdk/openai-compatible".
DIALECTS: dict[str, tuple[str, str | None]] = {
    "openai-chat": ("npm", "@ai-sdk/openai-compatible"),
}

#: First-hand-pinned native config target path (relative to the guest home).
NATIVE_TARGET = "opencode.json"
