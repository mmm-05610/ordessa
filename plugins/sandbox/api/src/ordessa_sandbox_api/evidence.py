"""`SandboxEvidence`: probe results bound to one runtime instance.

Evidence is per-instance: it names the server instance, session, runtime
generation, native/adapter versions, config digest and platform facts. Any
of those moving invalidates the proof — a v1 receipt replayed against a v2
pin is `unknown`, not a pass and not a documented limit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .coverage import ToolCategory
from .errors import SandboxApiError, SandboxErrorCode


class SandboxVerificationOutcome(str, Enum):
    #: three results, and the last two stay separate verdicts with separate
    #: codes (contracts.md §C4).
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


def code_for_outcome(outcome: SandboxVerificationOutcome) -> SandboxErrorCode | None:
    """The refusal code an outcome maps to when it blocks; None if it does not."""
    if outcome is SandboxVerificationOutcome.UNSUPPORTED:
        return SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    if outcome is SandboxVerificationOutcome.UNKNOWN:
        return SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    return None


@dataclass(frozen=True)
class PlatformFacts:
    os_name: str
    os_version: str = ""
    kernel_features: tuple[str, ...] = ()

    def same_as(self, other: "PlatformFacts") -> bool:
        return (self.os_name == other.os_name
                and self.os_version == other.os_version
                and tuple(sorted(self.kernel_features))
                == tuple(sorted(other.kernel_features)))


@dataclass(frozen=True)
class SandboxEvidence:
    server_instance_id: str
    session_id: str
    runtime_generation: str
    harness_id: str
    native_version: str
    adapter_version: str
    config_digest: str
    platform: PlatformFacts
    observed_covered_categories: frozenset[ToolCategory] = frozenset()
    outcome: SandboxVerificationOutcome = SandboxVerificationOutcome.UNKNOWN
    reason: str = ""

    def require_bound_to(self, *, server_instance_id: str, session_id: str,
                         runtime_generation: str, native_version: str,
                         config_digest: str, platform: PlatformFacts) -> None:
        """Refuse unless this evidence describes exactly that live instance."""
        checks = {
            "server_instance_id": (self.server_instance_id, server_instance_id),
            "session_id": (self.session_id, session_id),
            "runtime_generation": (self.runtime_generation, runtime_generation),
            "native_version": (self.native_version, native_version),
            "config_digest": (self.config_digest, config_digest),
        }
        moved = [name for name, (have, want) in checks.items() if have != want]
        if not platform.same_as(self.platform):
            moved.append("platform")
        if moved:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                f"evidence was taken on a different instance; moved facts: "
                f"{sorted(moved)} — it proves nothing about this one",
                suggestion="re-probe against the current pin/config/platform")
