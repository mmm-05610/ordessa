"""qwen's native-config dialect facts: **nothing is pinned, by rule** (P-A② split).

qwen is env-only (OPENAI_BASE_URL with no per-protocol native file). Pinned to
nothing here - every protocol-specific write is refused by the shared engine,
never guessed. The empty table and the absent target are **explicit family
rules**, not omissions (before P-A② they lived as ``{}``/absent entries in the
shared module's literals).
"""
from __future__ import annotations

DIALECTS: dict[str, tuple[str, str | None]] = {}

#: No first-hand-pinned native config target path for this family.
NATIVE_TARGET: str | None = None
