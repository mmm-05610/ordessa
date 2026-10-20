"""Platform gate on the intent: supported entry, unsupported and unknown."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import claude_intent, codex_intent

from ordessa_sandbox_api import (
    PlatformGate,
    SandboxApiError,
    SandboxErrorCode,
    check_platform_gate,
)


def test_claude_intent_passes_gate_on_linux():
    check_platform_gate(claude_intent(), os_name="linux", os_version="6.6")


def test_claude_intent_macos_gate_passes():
    check_platform_gate(
        claude_intent(platform_gate=PlatformGate(allowed_os=("macos",))),
        os_name="macos", os_version="15.1")


def test_claude_intent_on_native_windows_refuses_platform():
    with pytest.raises(SandboxApiError) as excinfo:
        check_platform_gate(claude_intent(), os_name="windows", os_version="11")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED


def test_gate_refuses_os_not_declared_even_if_mechanism_supported():
    intent = claude_intent()  # gate: linux, macos
    with pytest.raises(SandboxApiError) as excinfo:
        check_platform_gate(intent, os_name="freebsd", os_version="14")
    assert excinfo.value.code in (SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED,
                                  SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN)


def test_codex_gate_cannot_be_satisfied_until_platform_measured():
    # Codex per-platform variance is not measured in this tree, so the gate
    # reports unknown (never a silent allow, never a fabricated unsupported).
    with pytest.raises(SandboxApiError) as excinfo:
        check_platform_gate(codex_intent(), os_name="linux", os_version="6.6")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
