"""Stable refusal codes for the native-sandbox domain (contracts.md §C4).

`unsupported` and `unknown` are deliberately two codes; merging them would let
a missing probe read like a documented limit.
"""
from __future__ import annotations

from enum import Enum


class SandboxErrorCode(str, Enum):
    SANDBOX_NATIVE_UNSUPPORTED = "SANDBOX_NATIVE_UNSUPPORTED"
    SANDBOX_COVERAGE_UNPROVEN = "SANDBOX_COVERAGE_UNPROVEN"
    SANDBOX_PLATFORM_UNSUPPORTED = "SANDBOX_PLATFORM_UNSUPPORTED"
    SANDBOX_CONFIG_CONFLICT = "SANDBOX_CONFIG_CONFLICT"
    SANDBOX_EFFECT_UNKNOWN = "SANDBOX_EFFECT_UNKNOWN"
    PROVIDER_BUSY = "PROVIDER_BUSY"
    #: Schema-level refusals (unknown key, wildcard path, bad revision). Kept
    #: distinct from the six stable codes above so a typo never reads as a
    #: platform or coverage verdict.
    SANDBOX_INTENT_INVALID = "SANDBOX_INTENT_INVALID"

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.value


class SandboxApiError(ValueError):
    """Typed refusal: code + human message + fix suggestion, no secrets."""

    def __init__(self, code: SandboxErrorCode, message: str, *,
                 suggestion: str | None = None) -> None:
        full = message if suggestion is None else f"{message}; {suggestion}"
        super().__init__(f"{code.value}: {full}")
        self.code = code
        self.message = message
        self.suggestion = suggestion
