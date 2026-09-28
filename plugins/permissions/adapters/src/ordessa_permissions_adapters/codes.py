"""Adapter-level typed refusal codes (contracts §C4, FR-09).

The enforcement subset (`POLICY_CEILING_VIOLATION`, `POLICY_ADAPTER_MISSING`,
`POLICY_SCOPE_UNVERIFIED`, `PERMISSION_UNKNOWN_TOOL`) reuses the wire spellings
the domain API publishes, so a refusal from an adapter maps onto the same wire
family. `PERMISSION_POSTURE_UNEXPRESSIBLE` is the per-brand compile refusal:
the requested enforcement is not expressible on this brand's writable surface
- shaped exactly like the compat engine's legacy refusal, and never collapsed
into a silent downgrade (FR-03) nor into `unknown` (§C4: the two stay apart).
"""
from __future__ import annotations

from enum import Enum
from typing import Final, Mapping

__all__ = ["AdapterCode", "ADAPTER_REMEDIES"]


class AdapterCode(str, Enum):
    """The closed refusal vocabulary of the policy adapters."""

    PERMISSION_POSTURE_UNEXPRESSIBLE = "PERMISSION_POSTURE_UNEXPRESSIBLE"
    POLICY_CEILING_VIOLATION = "POLICY_CEILING_VIOLATION"
    POLICY_ADAPTER_MISSING = "POLICY_ADAPTER_MISSING"
    POLICY_SCOPE_UNVERIFIED = "POLICY_SCOPE_UNVERIFIED"
    PERMISSION_UNKNOWN_TOOL = "PERMISSION_UNKNOWN_TOOL"


ADAPTER_REMEDIES: Final[Mapping[AdapterCode, str]] = {
    AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE:
        "choose an intent this brand can express natively; the adapter will not"
        " write a looser knob or approximate a narrower rule",
    AdapterCode.POLICY_CEILING_VIOLATION:
        "the administrator ceiling denies or narrows what this intent asks;"
        " a Profile or session choice cannot widen it",
    AdapterCode.POLICY_ADAPTER_MISSING:
        "provide the evidence this adapter compiles against (for Pi: a loaded"
        " tool_call gate extension); without it no enforcement is claimed",
    AdapterCode.POLICY_SCOPE_UNVERIFIED:
        "re-obtain the ceiling, pin and generation identity from a trusted"
        " source; a compile never proceeds on unverified provenance",
    AdapterCode.PERMISSION_UNKNOWN_TOOL:
        "declare the tool in the permission vocabulary; an unknown tool is"
        " never treated as 'no rule'",
}
