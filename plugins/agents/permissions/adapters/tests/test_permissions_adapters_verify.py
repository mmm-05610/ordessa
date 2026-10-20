"""T03 red/green: verifyPolicy semantics (Confirmed | Unknown | Mismatch).

An observation may confirm a compiled intent only when (1) it names fields
this brand has a *measured* read-back oracle for, (2) its pin/version/runtime
generation are the same identity the policy was compiled under, and (3) the
native receipt is confirmed with a stated source. Anything weaker is Unknown;
a contradicting fact is Mismatch. A stale/mismatched observation is never
Confirmed (横向反例 (e)).

Production plumbing note (honest): nothing in this tree produces these
observations yet (api-requests.md G1/G2); this file proves the semantics of
the consumer side only.
"""
from __future__ import annotations

import pytest

from _permissions_adapters_helpers import make_intent
from ordessa_permissions_adapters import (
    ClaudeAdapter,
    CodexAdapter,
    CompiledIntentSet,
    PiAdapter,
    PolicyBinding,
    PolicyCompileSnapshot,
    PolicyObservation,
    VerifyOutcome,
)


def codex_compiled() -> CompiledIntentSet:
    adapter = CodexAdapter()
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0",
        intent=make_intent("codex", [{"key": "edit", "action": "deny"}])))
    assert isinstance(result, CompiledIntentSet)
    return result


def observation(harness_id, *, compiled_version="2.0", observed_version="2.0",
                compiled_generation="gen-1", observed_generation="gen-1",
                expected=None, observed=None, confirmed=True, source="config-readback"):
    return PolicyObservation.of(
        harness_id=harness_id,
        compile_binding=PolicyBinding(native_version=compiled_version,
                                      runtime_generation=compiled_generation),
        observed_binding=PolicyBinding(native_version=observed_version,
                                      runtime_generation=observed_generation),
        expected_fields=expected or {}, observed_values=observed or {},
        receipt_confirmed=confirmed, receipt_source=source)


def test_matching_confirmed_observation_is_confirmed() -> None:
    compiled = codex_compiled()
    result = CodexAdapter().verifyPolicy(observation(
        "codex", expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.CONFIRMED
    assert compiled.harness_id == "codex"


def test_generation_drift_is_mismatch_never_confirmed() -> None:
    result = CodexAdapter().verifyPolicy(observation(
        "codex", observed_generation="gen-2",
        expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.MISMATCH


def test_version_drift_is_not_confirmed() -> None:
    # different pin than compiled under, both measurable -> Mismatch
    result = CodexAdapter().verifyPolicy(observation(
        "codex", observed_version="2.1",
        expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.MISMATCH
    # observed version outside any measured range -> Unknown, never Confirmed
    result = CodexAdapter().verifyPolicy(observation(
        "codex", observed_version="999.0",
        expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.UNKNOWN


def test_value_difference_is_mismatch() -> None:
    result = CodexAdapter().verifyPolicy(observation(
        "codex", expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "workspace-write"}))
    assert result.outcome is VerifyOutcome.MISMATCH


def test_missing_observed_field_is_unknown() -> None:
    result = CodexAdapter().verifyPolicy(observation(
        "codex", expected={"sandbox_mode": "read-only"}, observed={}))
    assert result.outcome is VerifyOutcome.UNKNOWN


def test_unconfirmed_or_unsourced_receipt_is_unknown() -> None:
    for kwargs in ({"confirmed": False}, {"source": None}):
        result = CodexAdapter().verifyPolicy(observation(
            "codex", expected={"sandbox_mode": "read-only"},
            observed={"sandbox_mode": "read-only"}, **kwargs))
        assert result.outcome is VerifyOutcome.UNKNOWN


def test_fields_without_a_measured_oracle_are_unknown() -> None:
    # claude can verify its two writable paths; anything else (even a matching
    # value) is outside the oracle and stays Unknown.
    adapter = ClaudeAdapter()
    result = adapter.verifyPolicy(observation(
        "claude-code", compiled_version="0.81.2", observed_version="0.81.2",
        expected={"permissions.allow": ["Bash"]}, observed={"permissions.allow": ["Bash"]}))
    assert result.outcome is VerifyOutcome.UNKNOWN
    result = adapter.verifyPolicy(observation(
        "claude-code", compiled_version="0.81.2", observed_version="0.81.2",
        expected={"permissions.deny": ["Bash"]}, observed={"permissions.deny": ["Bash"]}))
    assert result.outcome is VerifyOutcome.CONFIRMED


def test_list_order_never_fakes_a_mismatch_or_a_confirmation() -> None:
    result = ClaudeAdapter().verifyPolicy(observation(
        "claude-code", compiled_version="0.81.2", observed_version="0.81.2",
        expected={"permissions.ask": ["Glob", "Read", "Grep"]},
        observed={"permissions.ask": ["Read", "Grep", "Glob"]}))
    assert result.outcome is VerifyOutcome.CONFIRMED
    result = ClaudeAdapter().verifyPolicy(observation(
        "claude-code", compiled_version="0.81.2", observed_version="0.81.2",
        expected={"permissions.ask": ["Glob", "Read"]},
        observed={"permissions.ask": ["Glob", "Read", "Bash"]}))
    assert result.outcome is VerifyOutcome.MISMATCH


def test_pi_has_no_pinned_receipt_oracle_so_never_confirms() -> None:
    result = PiAdapter().verifyPolicy(observation(
        "pi", expected={"toolCallGate.deny": ["bash"]},
        observed={"toolCallGate.deny": ["bash"]}))
    assert result.outcome is VerifyOutcome.UNKNOWN
    # even with a matching receipt, pi verification stays Unknown: no in-tree
    # oracle proves the extension honoured it (harness-adapters matrix row Pi).


def test_absent_bindings_are_unknown_not_guessed() -> None:
    result = CodexAdapter().verifyPolicy(observation(
        "codex", expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.CONFIRMED  # control
    bare = PolicyObservation.of(harness_id="codex")
    assert CodexAdapter().verifyPolicy(bare).outcome is VerifyOutcome.UNKNOWN


def test_foreign_harness_observation_is_mismatch() -> None:
    result = ClaudeAdapter().verifyPolicy(observation(
        "codex", expected={"sandbox_mode": "read-only"},
        observed={"sandbox_mode": "read-only"}))
    assert result.outcome is VerifyOutcome.MISMATCH
