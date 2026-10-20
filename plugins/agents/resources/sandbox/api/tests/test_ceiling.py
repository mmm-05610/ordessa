"""Admin ceiling: enforced native sandbox is never disabled or loosened (FR-06)."""
from __future__ import annotations

import pytest
from _sandbox_api_helpers import claude_config, claude_intent, codex_config, codex_intent

from ordessa_sandbox_api import (
    NativeSandboxIntent,
    NetworkMode,
    SandboxApiError,
    SandboxCeiling,
    SandboxErrorCode,
    check_within_ceiling,
    intersect_ceilings,
)


def test_intent_within_single_ceiling_passes():
    intent = codex_intent()  # workspace-write, network disabled
    ceiling = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=2,
                             network_allowed_max=False)
    effective = check_within_ceiling(intent, [ceiling])
    assert effective.minimum_strictness == 2


def test_intent_looser_than_ceiling_refuses():
    intent = codex_intent(config=codex_config(sandbox_mode="danger-full-access",
                                              network_access=True))
    ceiling = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=2,
                             network_allowed_max=False)
    with pytest.raises(SandboxApiError) as excinfo:
        check_within_ceiling(intent, [ceiling])
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_attempt_to_disable_enforced_sandbox_refuses():
    intent = claude_intent(config=claude_config(enable_bash_sandbox=False))
    ceiling = SandboxCeiling(brand="claude-code", enforce=True, minimum_strictness=1)
    with pytest.raises(SandboxApiError) as excinfo:
        check_within_ceiling(intent, [ceiling])
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_network_allowed_intent_against_network_forbidden_ceiling_refuses():
    intent = codex_intent(network=NetworkMode.ALLOWED)
    ceiling = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=1,
                             network_allowed_max=False)
    with pytest.raises(SandboxApiError) as excinfo:
        check_within_ceiling(intent, [ceiling])
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_positive_network_allowed_when_ceiling_allows():
    intent = codex_intent(network=NetworkMode.ALLOWED)
    ceiling = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=1,
                             network_allowed_max=True)
    check_within_ceiling(intent, [ceiling])


def test_multiple_ceilings_intersect_to_strictest():
    c1 = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=2,
                        network_allowed_max=True)
    c2 = SandboxCeiling(brand="codex", enforce=False, minimum_strictness=3,
                        network_allowed_max=False)
    merged = intersect_ceilings([c1, c2])
    assert merged.minimum_strictness == 3
    assert merged.enforce is True
    assert merged.network_allowed_max is False


def test_intent_satisfying_one_ceiling_but_not_intersection_refuses():
    intent = codex_intent(config=codex_config(sandbox_mode="workspace-write"))
    c1 = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=2)
    c2 = SandboxCeiling(brand="codex", enforce=True, minimum_strictness=3,
                        network_allowed_max=False)
    with pytest.raises(SandboxApiError) as excinfo:
        check_within_ceiling(intent, [c1, c2])
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_ceilings_from_different_brands_conflict():
    with pytest.raises(SandboxApiError) as excinfo:
        intersect_ceilings([
            SandboxCeiling(brand="codex"),
            SandboxCeiling(brand="claude-code"),
        ])
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


def test_over_strict_request_refuses_instead_of_approximating():
    # Claude's schema expresses at most strictness 1 (sandbox on/off); a
    # request at strictness 2 must refuse, not silently round to 1.
    with pytest.raises(SandboxApiError) as excinfo:
        claude_intent(requested_strictness=2)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED


def test_expressible_strictness_accepted():
    intent = codex_intent(requested_strictness=3,
                          config=codex_config(sandbox_mode="read-only"))
    assert intent.requested_strictness == 3
