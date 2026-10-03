"""Platform limit assessment: supported / unsupported / unknown, never guessed."""
from __future__ import annotations

import pytest

from ordessa_sandbox_api import PlatformResult, SandboxErrorCode, assess_platform


# ---- Claude documented limits (research-and-reuse.md / harness-adapters.md) ----

@pytest.mark.parametrize("os_name", ["linux", "wsl2"])
def test_claude_linux_family_bash_sandbox_supported(os_name):
    assessment = assess_platform(os_name, "6.6", brand="claude-code")
    assert assessment.result is PlatformResult.SUPPORTED
    assert "bubblewrap" in assessment.mechanism


def test_claude_macos_seatbelt_supported():
    assessment = assess_platform("macos", "15.1", brand="claude-code")
    assert assessment.result is PlatformResult.SUPPORTED
    assert "seatbelt" in assessment.mechanism


def test_claude_native_windows_bash_sandbox_unsupported():
    assessment = assess_platform("windows", "11", brand="claude-code")
    assert assessment.result is PlatformResult.UNSUPPORTED
    assert assessment.code is SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED


def test_claude_unknown_os_is_unknown_not_unsupported():
    assessment = assess_platform("haiku", "0.0", brand="claude-code")
    assert assessment.result is PlatformResult.UNKNOWN
    assert assessment.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


# ---- Codex: platform variance NOT measured in this repo -> unknown ----

@pytest.mark.parametrize("os_name", ["linux", "macos", "windows"])
def test_codex_platform_variance_unmeasured_is_unknown(os_name):
    assessment = assess_platform(os_name, "any", brand="codex")
    assert assessment.result is PlatformResult.UNKNOWN
    assert assessment.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unknown_brand_refuses_to_guess():
    assessment = assess_platform("linux", "6.6", brand="some-other-harness")
    assert assessment.result is PlatformResult.UNKNOWN


def test_unsupported_and_unknown_results_never_merge():
    unsupported = assess_platform("windows", "11", brand="claude-code")
    unknown = assess_platform("haiku", "0.0", brand="claude-code")
    assert unsupported.result is not unknown.result
    assert unsupported.code is not unknown.code
