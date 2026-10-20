"""Harness command and source declarations; no execution or permission effects."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping
from ordessa_infrastructure.encoding.content_identity import digest

def _text(value: str, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\0" in value:
        raise ValueError(f"invalid {name}")
    return value



@dataclass(frozen=True)
class RuntimeSourceDeclaration:
    """Dispatch-local source declaration; never persisted in Core inputs.

    ``kind`` describes the projector's intent only — it is never a provider
    or contract branch key.  The declaring Harness projector owns the guest
    layout; the generic assembler consumes these declarations verbatim.
    """

    kind: str
    source_path: str
    guest_target: str
    access: str
    expected_digest: str
    provenance: str = ""
    authorized_scope: str = "execution"

    def __post_init__(self) -> None:
        for value in (self.kind, self.source_path, self.guest_target, self.access, self.expected_digest):
            _text(value, "runtime source field", 512)
        if self.access not in {"ro", "rw"}:
            raise ValueError("runtime source access must be ro or rw")
        if self.provenance:
            _text(self.provenance, "runtime source provenance", 256)
        _text(self.authorized_scope, "runtime source authorized scope", 128)



@dataclass(frozen=True)
class HarnessCommandSpec:
    argv: tuple[str, ...]
    cwd_token: str
    environment: Mapping[str, str] = field(default_factory=dict)
    io_mode: str = "stdio"
    command_digest: str = ""
    runtime_sources: tuple[RuntimeSourceDeclaration, ...] = field(default_factory=tuple, compare=False, repr=False)
    requires_control_plane_network: bool = False
    tool_network_requirement: str = "unspecified"
    # Declaring projector identity (harness-owned); carried for honest
    # projection receipts, never used as a Root branch key.
    projector_id: str = ""

    def __post_init__(self) -> None:
        if not self.argv or len(self.argv) > 64 or any(not isinstance(x, str) or not x or "\0" in x for x in self.argv):
            raise ValueError("argv must be bounded and non-empty")
        _text(self.cwd_token, "cwd_token")
        if self.io_mode not in {"stdio", "pty"}:
            raise ValueError("unsupported io_mode")
        if not isinstance(self.requires_control_plane_network, bool):
            raise ValueError("requires_control_plane_network must be bool")
        if self.tool_network_requirement not in {"unspecified", "none", "inherit"}:
            raise ValueError("unsupported tool network requirement")
        if self.projector_id:
            _text(self.projector_id, "projector_id", 128)
        if len(self.environment) > 64:
            raise ValueError("environment is too large")
        if len(self.runtime_sources) > 16 or any(not isinstance(item, RuntimeSourceDeclaration) for item in self.runtime_sources):
            raise ValueError("invalid runtime source declarations")
        object.__setattr__(self, "environment", dict(self.environment))

    @property
    def digest(self) -> str:
        return self.command_digest or digest({"argv": self.argv, "cwd": self.cwd_token, "environment": self.environment, "io": self.io_mode, "control_plane_network": self.requires_control_plane_network, "tool_network": self.tool_network_requirement})

