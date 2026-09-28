"""Cross-session safety for process-level native sandbox changes.

A native sandbox/ceiling applied at PROCESS scope can alter sessions that
merely share the process. Unless the plan declares the impact set covering
every co-resident session, the change is refused — the effect on others is
unknown, and unknown fails closed (data-model.md 多会话/变更).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .errors import SandboxApiError, SandboxErrorCode
from .intent import NativeSandboxIntent, SandboxApplyScope


@dataclass(frozen=True)
class SessionSlot:
    session_id: str
    runtime_generation: str = ""


def check_cross_session_impact(requested: NativeSandboxIntent, *,
                               current_session_id: str,
                               co_resident: Sequence[SessionSlot]) -> None:
    """Refuse a process-scoped native change that silently touches others."""
    if requested.scope is not SandboxApplyScope.PROCESS:
        return
    others = [slot.session_id for slot in co_resident
              if slot.session_id != current_session_id]
    if not others:
        return
    declared = set(requested.declared_impact_set)
    unlisted = sorted(set(others) - declared)
    if unlisted:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
            "this is a process-level native sandbox change while sessions "
            f"{unlisted} share the process without a declared impact set; "
            "their isolation state after the change is unknown",
            suggestion="declare declared_impact_set covering every affected "
                       "session, or apply at session scope")
