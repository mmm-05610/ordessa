"""NativeSandboxIntent: closed per-brand vocabulary, refusal at construction."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import claude_config, claude_intent, codex_config, codex_intent, pi_config

from ordessa_sandbox_api import (
    ClaudeSandboxConfig,
    CodexSandboxConfig,
    NativeSandboxIntent,
    PiSandboxConfig,
    SandboxApiError,
    SandboxErrorCode,
    ToolCategory,
)


def _mapping(**overrides):
    intent = codex_intent()
    data = {
        "sandbox_id": intent.sandbox_id,
        "revision": intent.revision,
        "harness_id": intent.harness_id,
        "brand": intent.brand,
        "config": {
            "sandbox_mode": "workspace-write",
            "writable_roots": ("src",),
            "network_access": False,
        },
        "read_scope": ("workspace",),
        "write_scope": ("src",),
        "network": "disabled",
        "covered_categories": ("bash", "edit"),
        "required_coverage": ("bash",),
        "platform_gate": {"allowed_os": ("linux", "macos")},
        "scope": "session",
        "declared_impact_set": (),
    }
    data.update(overrides)
    return data


def test_valid_intent_constructs():
    intent = codex_intent()
    assert intent.required_coverage == frozenset({ToolCategory.BASH})
    assert intent.brand == "codex"


def test_from_mapping_accepts_known_keys_only():
    intent = NativeSandboxIntent.from_mapping(_mapping())
    assert intent.sandbox_id == "sbx-codex-1"


def test_unknown_top_level_key_refused_at_construction():
    data = _mapping()
    data["surprise_key"] = 1
    with pytest.raises(SandboxApiError) as excinfo:
        NativeSandboxIntent.from_mapping(data)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID


def test_unknown_brand_config_field_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        NativeSandboxIntent.from_mapping(
            _mapping(config={
                "sandbox_mode": "workspace-write",
                "writable_roots": ("src",),
                "network_access": False,
                "allow_any_shell": True,
            }))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID


def test_codex_mode_outside_pinned_vocabulary_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        codex_config(sandbox_mode="total-access")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID


def test_wildcard_required_coverage_all_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        codex_intent(required_coverage=frozenset({"all"}))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_wildcard_path_scope_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        codex_intent(write_scope=("*",))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_INTENT_INVALID


def test_pi_without_sandbox_extension_is_native_unsupported():
    # Pi has no built-in brand sandbox config: absence of the extension is an
    # explicit unsupported refusal, never `unknown` and never an allow.
    with pytest.raises(SandboxApiError) as excinfo:
        pi_config(sandbox_extension=None)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_pi_with_declared_extension_constructs():
    config = pi_config(sandbox_extension="sandbox-bwrap")
    assert config.sandbox_extension == "sandbox-bwrap"


def test_claude_cannot_claim_coverage_beyond_subprocess_kinds():
    # The Claude native sandbox covers Bash/PowerShell/Monitor subprocesses
    # only; claiming read/edit coverage is refused, not approximated.
    with pytest.raises(SandboxApiError) as excinfo:
        claude_intent(covered_categories=frozenset({ToolCategory.BASH, ToolCategory.EDIT}))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_claude_bash_only_coverage_claim_accepted():
    intent = claude_intent(covered_categories=frozenset({ToolCategory.BASH}))
    assert intent.config == claude_config()


def test_unsupported_and_unknown_stay_distinct_results():
    from ordessa_sandbox_api import SandboxVerificationOutcome

    assert (SandboxVerificationOutcome.UNSUPPORTED
            is not SandboxVerificationOutcome.UNKNOWN)
    from ordessa_sandbox_api import code_for_outcome

    assert (code_for_outcome(SandboxVerificationOutcome.UNSUPPORTED)
            != code_for_outcome(SandboxVerificationOutcome.UNKNOWN))
