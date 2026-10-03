"""Coverage proof: Bash-only evidence never proves read/edit/MCP/network."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import codex_intent, verified_evidence

from ordessa_sandbox_api import (
    SandboxApiError,
    SandboxErrorCode,
    SandboxVerificationOutcome,
    ToolCategory,
    coverage_proves,
    parse_coverage,
)


def test_bash_required_bash_observed_proves():
    intent = codex_intent(required_coverage=frozenset({ToolCategory.BASH}))
    evidence = verified_evidence(observed_covered_categories=frozenset({ToolCategory.BASH}))
    proof = coverage_proves(intent, evidence)
    assert proof.proven is True


def test_bash_only_evidence_cannot_prove_edit_requirement():
    intent = codex_intent(
        required_coverage=frozenset({ToolCategory.BASH, ToolCategory.EDIT}))
    evidence = verified_evidence(observed_covered_categories=frozenset({ToolCategory.BASH}))
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_bash_only_evidence_cannot_prove_mcp_requirement():
    intent = codex_intent(required_coverage=frozenset({ToolCategory.MCP}))
    evidence = verified_evidence(observed_covered_categories=frozenset({ToolCategory.BASH}))
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_bash_only_evidence_cannot_prove_network_requirement():
    intent = codex_intent(required_coverage=frozenset({ToolCategory.NETWORK}))
    evidence = verified_evidence(observed_covered_categories=frozenset({ToolCategory.BASH}))
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_wildcard_all_coverage_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        parse_coverage(("all",))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_wildcard_star_coverage_refused():
    with pytest.raises(SandboxApiError) as excinfo:
        parse_coverage(("*",))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN


def test_explicit_categories_accepted():
    parsed = parse_coverage(("bash", "mcp"))
    assert parsed == frozenset({ToolCategory.BASH, ToolCategory.MCP})


def test_unknown_evidence_yields_effect_unknown_not_coverage():
    intent = codex_intent(required_coverage=frozenset({ToolCategory.BASH}))
    evidence = verified_evidence(
        outcome=SandboxVerificationOutcome.UNKNOWN,
        observed_covered_categories=frozenset({ToolCategory.BASH}))
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unsupported_evidence_yields_native_unsupported_not_coverage():
    intent = codex_intent(required_coverage=frozenset({ToolCategory.BASH}))
    evidence = verified_evidence(
        outcome=SandboxVerificationOutcome.UNSUPPORTED,
        observed_covered_categories=frozenset())
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_stale_evidence_against_moved_pin_refused_in_proof():
    intent = codex_intent(native_version_pin="0.148.0")
    evidence = verified_evidence(native_version="0.147.0")
    with pytest.raises(SandboxApiError) as excinfo:
        coverage_proves(intent, evidence)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
