"""Probe-policy unit tests: the credential-less scope derivations and the
bounded policy's own validation (pure - run under the intact lockdown).
"""
from __future__ import annotations

import pytest
from backend.probe_policy import (
    BASE_ENVIRONMENT,
    ProbePolicy,
    unproven_remote_headers,
    unproven_stdio_environment,
)


def test_stdio_environment_is_allowlist_plus_literals():
    environment, excluded = unproven_stdio_environment({
        "A": {"literal": "one"},
        "B": {"secretRef": "cred-1"},
        "C": "legacy-bare-credential-ref",
        "D": {"weird": "shape"},
    })
    assert environment == {**BASE_ENVIRONMENT, "A": "one"}
    assert excluded == ["B", "C", "D"]  # secretRef, legacy refs, unknown shapes never run


def test_stdio_environment_empty_definition():
    environment, excluded = unproven_stdio_environment({})
    assert environment == dict(BASE_ENVIRONMENT) and excluded == []


def test_remote_headers_all_excluded():
    assert unproven_remote_headers({
        "X-A": {"secretRef": "c"}, "X-B": {"literal": "v"},
    }) == ["X-A", "X-B"]
    assert unproven_remote_headers({}) == []


def test_policy_bounds_are_validated():
    with pytest.raises(ValueError):
        ProbePolicy(timeout=0)
    with pytest.raises(ValueError):
        ProbePolicy(max_bytes=10)
    with pytest.raises(ValueError):
        ProbePolicy(kill_grace=-1)
    with pytest.raises(ValueError):
        ProbePolicy(supported_protocol_versions=())
    with pytest.raises(ValueError):
        ProbePolicy(supported_protocol_versions=("2025-11-25", ""))


def test_default_policy_negotiation_baseline():
    policy = ProbePolicy()
    assert policy.supported_protocol_versions[0] == "2025-11-25"
    assert "2024-11-05" in policy.supported_protocol_versions  # legacy-pinned version stays offered
    assert policy.timeout > 0 and policy.max_bytes > 0
