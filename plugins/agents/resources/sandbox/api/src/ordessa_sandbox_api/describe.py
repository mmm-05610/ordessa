"""`sandbox.describe@1` (§C2): the menu is built from evidence, not the brand.

A UI may only show what the matrix rows for the current brand/pin mark as
supported; unknown options are absent from the menu and refuse when
selected, so an unproven cell can never be clicked into existence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .ceiling import SandboxCeiling
from .errors import SandboxApiError, SandboxErrorCode
from .matrix import BRAND_OPTIONS, CellStatus, DescribeOption
from .platform import PlatformAssessment, PlatformResult, assess_platform

_READY = "ready"
_BUSY_STATES = frozenset({"busy", "unloaded", "deferred"})

#: only the codex mode options carry a schema strictness today
_OPTION_STRICTNESS = {
    "sandbox_mode=read-only": 3,
    "sandbox_mode=workspace-write": 2,
    "sandbox_mode=danger-full-access": 1,
}


@dataclass(frozen=True)
class SandboxOption:
    option_id: str
    status: CellStatus
    source: str
    platforms: tuple[str, ...]
    coverage: tuple[str, ...]
    locked_by_administrator: bool = False
    note: str = ""


@dataclass(frozen=True)
class SandboxDescription:
    api_version: str
    harness_id: str
    native_version: str
    options: tuple[SandboxOption, ...]
    platform_assessment: PlatformAssessment
    locked_by_administrator: bool

    def options_for_ui(self) -> tuple[SandboxOption, ...]:
        """Only supported options may reach a menu; unknown/unsupported are
        absent rather than greyed guesses."""
        return tuple(option for option in self.options
                     if option.status is CellStatus.SUPPORTED)

    def select(self, option_id: str) -> SandboxOption:
        option = next((o for o in self.options if o.option_id == option_id), None)
        if option is None:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"option {option_id!r} is not offered for "
                f"{self.harness_id} on this pin",
                suggestion="call sandbox.describe for the current pin first")
        if self.platform_assessment.result is PlatformResult.UNSUPPORTED:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED,
                self.platform_assessment.reason)
        if option.status is CellStatus.UNSUPPORTED:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"{option_id} is unsupported on this pin: {option.source}")
        if option.status is CellStatus.UNKNOWN:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN,
                f"{option_id} is not yet proven for this pin; selecting it "
                "would guess",
                suggestion="run the controlled probe (T05) to fill the cell")
        return option


def _to_option(proto: DescribeOption, ceiling: SandboxCeiling | None) -> SandboxOption:
    locked = bool(
        ceiling is not None and ceiling.enforce
        and _OPTION_STRICTNESS.get(proto.option_id, 0) >= ceiling.minimum_strictness)
    return SandboxOption(option_id=proto.option_id, status=proto.status,
                         source=proto.source, platforms=proto.platforms,
                         coverage=proto.coverage, note=proto.note,
                         locked_by_administrator=locked)


def describe_sandbox(*, harness_id: str, native_version: str,
                     platform_os: str, platform_version: str,
                     admin_lock: SandboxCeiling | None = None,
                     provider_state: str = _READY) -> SandboxDescription:
    """Assemble the describe view for one harness pin; refuse lifecycle states."""
    if provider_state in _BUSY_STATES:
        raise SandboxApiError(
            SandboxErrorCode.PROVIDER_BUSY,
            f"the sandbox provider is {provider_state}; its descriptions are "
            "deferred until it settles",
            suggestion="retry after the provider disposes or reloads")
    if provider_state != _READY:
        raise SandboxApiError(SandboxErrorCode.SANDBOX_INTENT_INVALID,
                              f"unknown provider state {provider_state!r}")
    assessment = assess_platform(platform_os, platform_version, brand=harness_id)
    protos: Sequence[DescribeOption] = BRAND_OPTIONS.get(harness_id, ())
    options = tuple(_to_option(p, admin_lock) for p in protos)
    return SandboxDescription(
        api_version="sandbox.describe@1",
        harness_id=harness_id,
        native_version=native_version,
        options=options,
        platform_assessment=assessment,
        locked_by_administrator=bool(admin_lock is not None and admin_lock.enforce),
    )
