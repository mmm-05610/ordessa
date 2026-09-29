"""The injection pipeline (MB-6): one profile's memories → one instruction
context block.

Semantics pinned here (and by tests):

* the block carries the facet name ``ordessa.memory`` and is produced
  SELF-CONTAINED — the prompts facet's absence never blocks it (AR-4
  counterexample), and when neither side has content the instruction slot
  receives an empty string, never an empty shell;
* the AR-4 merge order is "instructions first, memory block after": this
  producer emits only the block; the actual merge point is the prompts
  domain's instruction-slot facet merge (EXT, not on this baseline —
  registered as the pending mount);
* memory absence, server unreachable, endpoint 500 — all render an empty
  block with a recorded diagnostic: memory absent ≠ error, the session
  proceeds (MB-8 counterexample);
* mounting is per brand from the binding's ``boundBrands`` (default: the
  four brands without native memory); the four native-memory brands carry
  the recorded coexistence note wherever the mount decision is exposed.

Pure module: no HOME, no network of its own (the client does the REST), no
spawn, no file writes, no secret content.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import common
from .mem0_client import Mem0Client, Mem0ClientError, Mem0ServerError, Mem0Unreachable

COEXISTENCE_NOTE = "与原生记忆并存可能重复（可配置挂载）"


@dataclass(frozen=True)
class InjectionBlock:
    """The produced block plus the facts a diagnostics surface needs."""

    text: str
    count: int
    mounted: bool
    reason: str | None = None
    attribution: str = common.ATTRIBUTION

    @property
    def empty(self) -> bool:
        return self.text == ""


def is_mounted(brand: str | None, binding: dict[str, Any]) -> bool:
    """The mount decision for one brand: the binding's ``boundBrands``; a
    brand-less caller (the block is brand-independent) reads ``enabled``."""
    if not binding.get("enabled"):
        return False
    if brand is None:
        return True
    return brand in binding.get("boundBrands", [])


def mount_note(brand: str | None) -> str | None:
    """The coexistence note for native-memory brands; None otherwise."""
    if brand is not None and brand in common.NATIVE_MEMORY_BRANDS:
        return COEXISTENCE_NOTE
    return None


class InjectionProducer:
    def __init__(self, client_getter: Any, server_scope_getter: Any = lambda: None) -> None:
        self._client_getter = client_getter
        self._server_scope_getter = server_scope_getter

    def block(self, profile_id: str, query: str, binding: dict[str, Any], *,
              brand: str | None = None) -> InjectionBlock:
        if not is_mounted(brand, binding):
            return InjectionBlock(text="", count=0, mounted=False,
                                  reason="memory binding disabled or brand not mounted")
        if not query.strip():
            # No query, no retrieval: an honest empty, not a stale dump.
            return InjectionBlock(text="", count=0, mounted=True,
                                  reason="no query context to retrieve with")
        client: Mem0Client | None = self._client_getter()
        if client is None:
            return InjectionBlock(text="", count=0, mounted=True,
                                  reason="mem0 stack not provisioned/reachable")
        namespace = common.profile_namespace(self._server_scope_getter(), profile_id)
        try:
            answer = client.search(query, namespace)
        except (Mem0Unreachable, Mem0ServerError, Mem0ClientError) as exc:
            return InjectionBlock(text="", count=0, mounted=True,
                                  reason=f"memory lookup failed: {exc}")
        memories = [row for row in (answer.get("results") or [])
                    if isinstance(row, dict) and str(row.get("memory") or "").strip()]
        text = common.render_memory_block(memories, budget_tokens=binding.get("budgetTokens"))
        return InjectionBlock(text=text, count=len(memories), mounted=True)
