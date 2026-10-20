"""Adapter *input* DTOs: the pin, the authorized facts and the Pi extension evidence.

These wrap the consumed domain records (``PlatformFacts``, ``SandboxCeiling``,
``NativeSandboxIntent`` from ``ordessa_sandbox_api``) — nothing there is
redefined. §C2 says the assess input is only version / platform / config-target
handle / authorized facts; ``AuthorizedFacts`` is exactly that, plus the
cross-session co-residency the process-scope gate needs and the single Pi
observation the extension-backed rule consults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ordessa_sandbox_api import SessionSlot

__all__ = ["AdapterPin", "AuthorizedFacts", "PiSandboxExtensionEvidence"]


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value.strip()


@dataclass(frozen=True)
class AdapterPin:
    """Which harness at which native version is being assessed."""

    harness_id: str
    native_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "harness_id", _text(self.harness_id, name="harness_id"))
        object.__setattr__(self, "native_version",
                           _text(self.native_version, name="native_version"))


@dataclass(frozen=True)
class PiSandboxExtensionEvidence:
    """One observation of a loaded Pi sandbox extension.

    Pi's native sandbox is an optional extension, not built-in
    (harness-adapters.md Pi row); without this evidence nothing is compiled.
    Nothing constructs it in production yet — the load observation is the
    blocked T05 L2 seam.
    """

    extension_id: str
    loaded: bool
    observed_native_version: str
    generation: str | None = None

    @classmethod
    def of(cls, *, extension_id: Any, loaded: Any, observed_native_version: Any,
           generation: Any = None) -> "PiSandboxExtensionEvidence":
        if type(loaded) is not bool:
            raise ValueError("loaded must be a bool")
        return cls(
            extension_id=_text(extension_id, name="extension_id"),
            loaded=loaded,
            observed_native_version=_text(observed_native_version,
                                          name="observed_native_version"),
            generation=None if generation is None
            else _text(generation, name="generation"))


@dataclass(frozen=True)
class AuthorizedFacts:
    """The authorized facts a compile/assess may consult (and nothing else)."""

    adapter_available: bool = True
    current_session_id: str | None = None
    co_resident_sessions: tuple[SessionSlot, ...] = field(default_factory=tuple)
    pi_sandbox_extension: PiSandboxExtensionEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.adapter_available) is not bool:
            raise ValueError("adapter_available must be a bool")
        slots = tuple(self.co_resident_sessions)
        for slot in slots:
            if not isinstance(slot, SessionSlot):
                raise ValueError("co_resident_sessions must be SessionSlot values")
        object.__setattr__(self, "co_resident_sessions", slots)
        if self.pi_sandbox_extension is not None and not isinstance(
                self.pi_sandbox_extension, PiSandboxExtensionEvidence):
            raise ValueError("pi_sandbox_extension must be a PiSandboxExtensionEvidence")
