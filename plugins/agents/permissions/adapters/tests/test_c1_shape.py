"""T03 red/green: the §C1 adapter shape (contracts.md §C1).

Every adapter exposes exactly `supports(evidence) -> supported|unsupported|
unknown`, `compilePolicy(snapshot) -> IntentSet|Refusal` and
`verifyPolicy(observation) -> Confirmed|Unknown|Mismatch`, keyed by
`(harnessId, nativeVersionRange)`. `unsupported` and `unknown` are distinct
answers and never merged (contracts §C4).
"""
from __future__ import annotations

import inspect

import pytest

from ordessa_permissions_adapters import (
    CompiledIntentSet,
    CompileRefusal,
    CodexAdapter,
    ClaudeAdapter,
    PiAdapter,
    PolicyCompileSnapshot,
    PolicyObservation,
    SupportOutcome,
    SupportReport,
    VerifyOutcome,
    VerifyResult,
)

ADAPTER_CLASSES = (PiAdapter, CodexAdapter, ClaudeAdapter)
VALID_OUTCOMES = {item for item in VerifyOutcome}


@pytest.mark.parametrize("cls", ADAPTER_CLASSES, ids=lambda c: c.__name__)
def test_c1_methods_exist_with_the_contracted_names(cls) -> None:
    adapter = cls()
    for name in ("supports", "compilePolicy", "verifyPolicy"):
        method = getattr(adapter, name, None)
        assert callable(method), f"{cls.__name__} lacks {name}"
        assert len(inspect.signature(method).parameters) == 1, \
            f"{cls.__name__}.{name} must take exactly one argument"


@pytest.mark.parametrize("cls", ADAPTER_CLASSES, ids=lambda c: c.__name__)
def test_descriptor_identity_fields(cls) -> None:
    adapter = cls()
    descriptor = adapter.descriptor()
    assert descriptor.adapter_id
    assert descriptor.harness_id == adapter.harness_id
    assert descriptor.version_range is not None
    assert descriptor.contract_id == "permissions.policy-adapters@1"


@pytest.mark.parametrize("cls", ADAPTER_CLASSES, ids=lambda c: c.__name__)
def test_supports_answers_from_the_closed_set_never_merged(cls) -> None:
    adapter = cls()
    outcome = adapter.supports(None)
    assert isinstance(outcome, SupportReport)
    assert outcome.outcome in {SupportOutcome.SUPPORTED, SupportOutcome.UNSUPPORTED,
                               SupportOutcome.UNKNOWN}
    # unsupported and unknown are different members, not spellings of one value
    assert SupportOutcome.UNSUPPORTED is not SupportOutcome.UNKNOWN


def test_compile_returns_intent_set_or_refusal_not_raise() -> None:
    adapter = ClaudeAdapter()
    # A foreign harness is a refusal result, not an exception.
    result = adapter.compilePolicy(PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0"))
    assert isinstance(result, CompileRefusal)
    assert result.outcome == "refusal"
    assert result.code is not None and result.source and result.remedy


def test_successful_compile_is_an_intent_set_with_digest() -> None:
    from _permissions_adapters_helpers import make_intent
    adapter = CodexAdapter()
    snapshot = PolicyCompileSnapshot.of(
        harness_id="codex", native_version="2.0",
        intent=make_intent("codex", [{"key": "edit", "action": "deny"}]))
    result = adapter.compilePolicy(snapshot)
    assert isinstance(result, CompiledIntentSet), getattr(result, "code", None)
    assert result.outcome == "intent-set"
    assert result.harness_id == "codex"
    assert len(result.digest) == 64
    # Same input, same digest: compile is pure and deterministic.
    again = adapter.compilePolicy(snapshot)
    assert again.digest == result.digest


def test_verify_returns_a_three_way_result() -> None:
    adapter = CodexAdapter()
    result = adapter.verifyPolicy(PolicyObservation.of(harness_id="codex"))
    assert isinstance(result, VerifyResult)
    assert result.outcome in VALID_OUTCOMES
    # A bare observation with no bindings cannot confirm anything.
    assert result.outcome is VerifyOutcome.UNKNOWN
