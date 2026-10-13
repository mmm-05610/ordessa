"""Injected host capability descriptions; these values do not authorize execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    kind: str
    interface_version: str
    contract_digest: str
    contract: Mapping[str, Any]



@dataclass(frozen=True)
class CompilationCapabilities:
    capabilities: tuple[CapabilityDescriptor, ...]
    registry_snapshot_ref: str | None = None
    trust_class: str = "host"  # host | fixture



@dataclass(frozen=True)
class CapabilityBinding:
    capability_id: str
    kind: str
    interface_version: str
    contract_digest: str


    def __post_init__(self):
        if any(type(getattr(self, name)) is not str for name in ("capability_id", "kind", "interface_version", "contract_digest")):
            raise TypeError("immutable capability identity strings required")
        if self.kind not in ("operation", "check"):
            raise ValueError("capability binding kind invalid")
        if len(self.contract_digest) != 64 or any(c not in "0123456789abcdef" for c in self.contract_digest):
            raise ValueError("exact capability contract digest required")
