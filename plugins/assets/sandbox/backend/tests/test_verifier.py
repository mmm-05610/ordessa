"""T04b — SandboxVerifier: the §C2 backend half, FR-06 refuse-before-side-effect.

`verified | unsupported | unknown | refused(code)`; unsupported and unknown
never merge; a refusal happens with nothing applied (the package has no
apply path at all — see test_no_fake_apply.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _sandbox_backend_helpers import (
    HARNESSES_TOML,
    claude_config,
    claude_evidence,
    claude_intent,
    codex_config,
    codex_intent,
    facts,
    slot,
    target_facts,
)

from ordessa_sandbox_api import (
    PlatformFacts,
    PlatformGate,
    SandboxApiError,
    SandboxApplyScope,
    SandboxCeiling,
    SandboxErrorCode,
    SandboxVerificationOutcome,
    ToolCategory,
)
from ordessa_sandbox_backend import (
    NativeSandboxRepository,
    SandboxOptionCatalogue,
    SandboxVerifier,
    VerdictKind,
)


@pytest.fixture()
def verifier():
    catalogue = SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))
    return SandboxVerifier(catalogue=catalogue)


# --------------------------------------------------------------- positive path

def test_verified_positive_requires_bound_verified_evidence(verifier):
    verdict = verifier.verify(claude_intent(), facts(), evidence=claude_evidence())
    assert verdict.kind is VerdictKind.VERIFIED
    assert verdict.code is None
    assert verdict.effect_started is False  # verification itself applies nothing
    assert verdict.refused_before_side_effect is False


# ------------------------------------------------------------------- unknowns

def test_missing_evidence_is_unknown_not_verified(verifier):
    verdict = verifier.verify(claude_intent(), facts(), evidence=None)
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    assert verdict.refused_before_side_effect is True


def test_evidence_invalidated_by_version_change_is_not_verified(verifier):
    # the repository drops the record on the version change; the verifier
    # then has no evidence and must answer unknown, never replay the old
    # `verified` receipt
    repo = NativeSandboxRepository()
    repo.record_evidence("th-codex-s-a", claude_evidence())
    repo.update_facts("th-codex-s-a", target_facts(native_version="9.9.9"))
    verdict = verifier.verify(claude_intent(), facts(), repository=repo)
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unknown_outcome_evidence_stays_unknown(verifier):
    ev = claude_evidence(
        outcome=SandboxVerificationOutcome.UNKNOWN, reason="probe inconclusive")
    verdict = verifier.verify(claude_intent(), facts(), evidence=ev)
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unsupported_outcome_evidence_stays_unsupported_not_unknown(verifier):
    ev = claude_evidence(
        outcome=SandboxVerificationOutcome.UNSUPPORTED,
        reason="documented native limit")
    verdict = verifier.verify(claude_intent(), facts(), evidence=ev)
    assert verdict.kind is VerdictKind.UNSUPPORTED
    assert verdict.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_codex_effect_is_unknown_until_the_probe_lands(verifier):
    # repo honesty: codex per-platform support is unmeasured in this tree;
    # no amount of intent text turns it green
    verdict = verifier.verify(
        codex_intent(required_coverage=frozenset({ToolCategory.BASH})),
        facts(native_version="2.0", platform_os="macos",
              platform_version="", kernel_features=()),
        evidence=None,
    )
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


# -------------------------------------------------------------- unsupported

def test_intent_stricter_than_native_can_express_is_refused_at_intake(verifier):
    # claude's closed schema tops out at MAX_STRICTNESS 1; a stricter
    # request is a typed refusal with a stable code, never a clamp to the
    # nearest expressible posture
    with pytest.raises(SandboxApiError) as exc:
        claude_intent(requested_strictness=2)
    assert exc.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_coverage_requirement_native_cannot_express_refuses_never_approximates(verifier):
    # claude's Bash-class sandbox cannot cover MCP no matter what the pin
    # says; verify refuses instead of approximating "protected"
    verdict = verifier.verify(
        claude_intent(
            required_coverage=frozenset({ToolCategory.BASH, ToolCategory.MCP}),
            covered_categories=frozenset({ToolCategory.BASH})),
        facts(),
        evidence=claude_evidence(),
    )
    assert verdict.kind is VerdictKind.UNSUPPORTED
    assert verdict.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_adapter_absent_refuses_before_anything(verifier):
    verdict = verifier.verify(
        claude_intent(),
        facts(adapter_available=False),
        evidence=claude_evidence(),
    )
    assert verdict.kind is VerdictKind.UNSUPPORTED
    assert verdict.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    assert verdict.effect_started is False
    assert verdict.refused_before_side_effect is True


def test_claude_windows_platform_is_its_own_stable_refusal(verifier):
    verdict = verifier.verify(
        claude_intent(platform_gate=PlatformGate()),
        facts(platform_os="windows", platform_version="11", kernel_features=()),
        evidence=claude_evidence(
            platform=PlatformFacts(os_name="windows", os_version="11")),
    )
    assert verdict.kind is VerdictKind.REFUSED
    assert verdict.code is SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED


# ----------------------------------------------------------------- refusals

def test_admin_locked_option_requested_looser_is_refused(verifier):
    ceiling = SandboxCeiling(brand="claude-code", enforce=True, minimum_strictness=1)
    loose = claude_intent(config=claude_config(enable_bash_sandbox=False),
                          covered_categories=frozenset(),
                          required_coverage=frozenset())
    verdict = verifier.verify(loose, facts(), evidence=claude_evidence(),
                              admin_ceilings=(ceiling,))
    assert verdict.kind is VerdictKind.REFUSED
    assert verdict.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT
    assert verdict.refused_before_side_effect is True


def test_admin_enforced_sandbox_cannot_be_switched_off(verifier):
    ceiling = SandboxCeiling(brand="codex", enforce=True)
    verdict = verifier.verify(
        codex_intent(config=codex_config(sandbox_mode="danger-full-access"),
                     covered_categories=frozenset(),
                     required_coverage=frozenset()),
        facts(native_version="2.0"),
        evidence=None,
        admin_ceilings=(ceiling,),
    )
    assert verdict.kind is VerdictKind.REFUSED
    assert verdict.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_cross_session_impact_undeclared_is_refused(verifier):
    process_intent = claude_intent(
        scope=SandboxApplyScope.PROCESS,
        declared_impact_set=(),
    )
    verdict = verifier.verify(
        process_intent,
        facts(co_resident_sessions=(slot("s-a"), slot("s-b"))),
        evidence=claude_evidence(),
    )
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    assert "s-b" in verdict.reason
    assert verdict.refused_before_side_effect is True


def test_cross_session_impact_declared_passes_the_gate(verifier):
    process_intent = claude_intent(
        scope=SandboxApplyScope.PROCESS,
        declared_impact_set=("s-b",),
    )
    verdict = verifier.verify(
        process_intent,
        facts(co_resident_sessions=(slot("s-a"), slot("s-b"))),
        evidence=claude_evidence(),
    )
    assert verdict.kind is VerdictKind.VERIFIED


def test_coverage_gap_with_bound_evidence_refuses_unproven(verifier):
    # evidence proves bash only; the intent requires bash + network ->
    # refuse with COVERAGE_UNPROVEN, never "basically protected"
    verdict = verifier.verify(
        claude_intent(
            required_coverage=frozenset({ToolCategory.BASH, ToolCategory.NETWORK}),
            covered_categories=frozenset({ToolCategory.BASH})),
        facts(),
        evidence=claude_evidence(
            observed_covered_categories=frozenset({ToolCategory.BASH})),
    )
    assert verdict.kind is VerdictKind.REFUSED
    assert verdict.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_evidence_from_a_different_pin_is_not_replayed(verifier):
    verdict = verifier.verify(
        claude_intent(),
        facts(native_version="0.81.2"),
        evidence=claude_evidence(native_version="0.81.1"),
    )
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unknown_pin_never_verifies(verifier):
    # catalogue says UNKNOWN for this pin; verification must not green-path
    # past an unregistered pin
    verdict = verifier.verify(
        claude_intent(),
        facts(native_version="0.0.1"),
        evidence=claude_evidence(native_version="0.0.1"),
    )
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
