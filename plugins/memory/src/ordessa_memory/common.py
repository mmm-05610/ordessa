"""Shared memory-domain vocabulary and byte-stable rendering.

Byte stability is conformance-pinned: the same inputs render the same bytes
every time (golden tests hold the exact outputs). The one renderer this
package owns is the injection context block — the text the instruction slot
merge (AR-4) places after the user's instructions.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

#: The facet this package contributes (spec P-B: one leaf facet).
FACET_ID = "assets.memory"
FACET_SCHEMA_VERSION = "1"
#: The C2 entry (channel) the adapters serve (same vocabulary as the
#: model-provider / runtime-preferences adapters).
ENTRY = "acp"
#: The facet payload identifier.
PAYLOAD_SCHEMA_ID = "memory.binding.v1"

#: The named facet the injection block claims in the instruction-slot merge
#: (AR-4: instructions first, this block after).
INSTRUCTION_FACET_NAME = "ordessa.memory"

#: The eight harness brands; the four without native long-term memory are the
#: default-mounted set, the four with native memory are default-unmounted
#: (configurable — with the coexistence note, never silently).
BRANDS = ("pi", "codex", "claude-code", "hermes", "opencode", "dsh", "qwen", "kilo")
DEFAULT_MOUNTED = ("pi", "dsh", "qwen", "kilo")
NATIVE_MEMORY_BRANDS = ("codex", "claude-code", "hermes", "opencode")

#: The facet item's value keys. ``enabled``/``budgetTokens``/
#: ``extractionModelRef`` mirror the P-A ``assets.runtime-preferences`` memory
#: item exactly (AR-5 facet contract — key names pinned on both sides by
#: tests); ``boundBrands`` is this facet's own fourth key.
VALUE_KEYS = ("enabled", "budgetTokens", "extractionModelRef", "boundBrands")

#: The extraction budget default: characters carried into one injection block.
#: (Token-exact accounting belongs to the caller's tokenizer; the block bound
#: is characters so the renderer stays dependency-free.)
DEFAULT_BUDGET_TOKENS = 2000
_CHARS_PER_TOKEN = 4

#: The attribution line every memory surface carries (spec red line 4).
ATTRIBUTION = "记忆引擎 mem0（Apache-2.0）· 本地自托管（Docker）· 遥测已关闭"

#: The mem0 upstream pin (recorded first-hand 2026-09-28; see the report).
MEM0_REPO_URL = "https://github.com/mem0ai/mem0"
MEM0_GIT_SHA = "94c3fe9f238f3dbf29c9ce98643bd71eb13077cd"
#: sha256 of the pinned upstream ``server/main.py`` (first-hand download at
#: the SHA above) — the vendor integrity check anchors on this.
MEM0_SERVER_MAIN_SHA256 = "320af32a959fcb6bed8b4420757714e8824fb1e98e9869a2475e1a03eddf3158"
POSTGRES_IMAGE = "pgvector/pgvector:pg17"

#: The memory namespace of one profile: the mem0 ``user_id`` scoping domain
#: (MB-8: two profiles cannot see each other's memories).
def profile_namespace(server_scope: str | None, profile_id: str) -> str:
    scope = server_scope if isinstance(server_scope, str) and server_scope else "local"
    return f"ordessa:{scope}:profile:{profile_id}"


def default_binding() -> dict[str, Any]:
    """The facet item default: injection mounted for the four brands without
    native memory, extraction OFF (a real-model call never happens without
    the explicit authorization, spec red line 3)."""
    return {
        "enabled": True,
        "budgetTokens": DEFAULT_BUDGET_TOKENS,
        "extractionModelRef": None,
        "boundBrands": list(DEFAULT_MOUNTED),
    }


def _sanitize_line(text: str) -> str:
    """One memory's text made instruction-safe: control characters collapse
    to spaces, and ``&``/``<``/``>`` are escaped so a memory can neither
    forge tags nor close the block's own fence early. The consumer reads the
    lines as escaped text."""
    cleaned = "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in text)
    cleaned = " ".join(cleaned.split())
    return cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_memory_block(memories: Sequence[Mapping[str, Any]], *,
                        budget_tokens: int | None = None) -> str:
    """The injection block: the opened facet tag, one bullet per memory
    (score order, capped by the budget), the closing tag. No memories, no
    block — an empty string, never an empty shell."""
    if not memories:
        return ""
    limit = (budget_tokens if budget_tokens is not None else DEFAULT_BUDGET_TOKENS) * _CHARS_PER_TOKEN
    lines = [f'<memory-context facet="{INSTRUCTION_FACET_NAME}" source="mem0 self-hosted">']
    used = 0
    for item in memories:
        text = _sanitize_line(str(item.get("memory") or item.get("text") or "")).strip()
        if not text:
            continue
        remaining = limit - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining].rstrip() + " …"
        used += len(text)
        lines.append(f"• {text}")
    if len(lines) == 1:
        return ""
    lines.append("</memory-context>")
    return "\n".join(lines)
