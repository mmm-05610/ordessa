"""SandboxEvidence: instance-bound proof; version/config/platform change invalidates."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import platform_facts, verified_evidence

from ordessa_sandbox_api import (
    SandboxApiError,
    SandboxErrorCode,
    SandboxEvidence,
    SandboxVerificationOutcome,
    ToolCategory,
)


def test_evidence_bound_to_matching_instance_is_valid():
    evidence = verified_evidence()
    evidence.require_bound_to(
        server_instance_id="srv-1",
        session_id="s1",
        runtime_generation="gen-1",
        native_version="0.147.0",
        config_digest="sha256:aaaa",
        platform=platform_facts(),
    )


def test_native_version_pin_change_invalidates_evidence():
    evidence = verified_evidence(native_version="0.147.0")
    with pytest.raises(SandboxApiError) as excinfo:
        evidence.require_bound_to(
            server_instance_id="srv-1",
            session_id="s1",
            runtime_generation="gen-1",
            native_version="0.148.0",  # pin moved to v2
            config_digest="sha256:aaaa",
            platform=platform_facts(),
        )
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_config_digest_change_invalidates_evidence():
    evidence = verified_evidence()
    with pytest.raises(SandboxApiError) as excinfo:
        evidence.require_bound_to(
            server_instance_id="srv-1", session_id="s1", runtime_generation="gen-1",
            native_version="0.147.0", config_digest="sha256:bbbb",
            platform=platform_facts())
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_platform_change_invalidates_evidence():
    evidence = verified_evidence()
    with pytest.raises(SandboxApiError) as excinfo:
        evidence.require_bound_to(
            server_instance_id="srv-1", session_id="s1", runtime_generation="gen-1",
            native_version="0.147.0", config_digest="sha256:aaaa",
            platform=platform_facts(os_name="macos", os_version="15.1",
                                    kernel_features=("seatbelt",)))
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_server_instance_change_invalidates_evidence():
    evidence = verified_evidence()
    with pytest.raises(SandboxApiError) as excinfo:
        evidence.require_bound_to(
            server_instance_id="srv-2", session_id="s1", runtime_generation="gen-1",
            native_version="0.147.0", config_digest="sha256:aaaa",
            platform=platform_facts())
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_three_outcomes_exist_and_are_distinct():
    outcomes = set(SandboxVerificationOutcome)
    assert outcomes == {
        SandboxVerificationOutcome.VERIFIED,
        SandboxVerificationOutcome.UNSUPPORTED,
        SandboxVerificationOutcome.UNKNOWN,
    }


def test_evidence_records_reason_and_observed_categories():
    evidence = verified_evidence(
        outcome=SandboxVerificationOutcome.UNKNOWN,
        reason="probe not run on this pin",
        observed_covered_categories=frozenset(),
    )
    assert evidence.outcome is SandboxVerificationOutcome.UNKNOWN
    assert evidence.reason == "probe not run on this pin"
