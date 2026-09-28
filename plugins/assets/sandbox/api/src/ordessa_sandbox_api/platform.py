"""Platform assessment: only encode what the repo/docs actually establish.

Claude limits are documented (research-and-reuse.md): Linux/WSL2 bubblewrap,
macOS Seatbelt, native Windows unsupported for the Bash sandbox. Codex
per-platform variance is NOT measured in this tree, so every codex platform
answer is `unknown` — guessing per-platform support here would fabricate the
very fact coverage proof is supposed to observe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import SandboxApiError, SandboxErrorCode
from .evidence import PlatformFacts
from .intent import NativeSandboxIntent


class PlatformResult(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


@dataclass(frozen=True)
class PlatformAssessment:
    brand: str
    os_name: str
    os_version: str
    result: PlatformResult
    code: SandboxErrorCode | None
    mechanism: str
    reason: str


_LINUX_FAMILY = ("linux", "wsl2")
_UNMEASURED = "platform variance not measured in this tree"


def normalise_os(os_name: str) -> str:
    name = str(os_name).strip().lower()
    if name in ("darwin", "osx", "mac os", "macos"):
        return "macos"
    if name in ("windows", "win32", "win"):
        return "windows"
    if "wsl" in name:
        return "wsl2"
    if name in ("linux", "linux2"):
        return "linux"
    return name


def assess_platform(os_name: str, version: str, *, brand: str) -> PlatformAssessment:
    """supported / unsupported / unknown for one brand on one platform."""
    name = normalise_os(os_name)
    if brand == "claude-code":
        if name in _LINUX_FAMILY:
            return PlatformAssessment(
                brand, name, version, PlatformResult.SUPPORTED, None,
                "bubblewrap (Linux/WSL2)", "documented native mechanism")
        if name == "macos":
            return PlatformAssessment(
                brand, name, version, PlatformResult.SUPPORTED, None,
                "seatbelt (macOS)", "documented native mechanism")
        if name == "windows":
            return PlatformAssessment(
                brand, name, version, PlatformResult.UNSUPPORTED,
                SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED, "",
                "native Windows is documented as unsupported for the Bash "
                "sandbox")
    return PlatformAssessment(
        brand, name, version, PlatformResult.UNKNOWN,
        SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, "",
        f"{_UNMEASURED}; refusing to guess a mechanism for {brand!r}/{name!r}")


def check_platform_gate(intent: NativeSandboxIntent, *, os_name: str,
                        os_version: str) -> PlatformAssessment:
    """Apply the intent's platform gate; unknown never satisfies the gate."""
    assessment = assess_platform(os_name, os_version, brand=intent.brand)
    if assessment.result is PlatformResult.UNSUPPORTED:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED, assessment.reason)
    if assessment.result is PlatformResult.UNKNOWN:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN, assessment.reason,
            suggestion="measure the platform facts on this pin before gating")
    if intent.platform_gate.allowed_os and \
            normalise_os(os_name) not in {normalise_os(o)
                                          for o in intent.platform_gate.allowed_os}:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED,
            f"{normalise_os(os_name)!r} is outside the intent's platform gate "
            f"{intent.platform_gate.allowed_os}")
    return assessment


def platform_facts_of(os_name: str, os_version: str) -> PlatformFacts:
    return PlatformFacts(os_name=normalise_os(os_name), os_version=os_version)
