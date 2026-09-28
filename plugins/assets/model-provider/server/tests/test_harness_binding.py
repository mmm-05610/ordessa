"""PB-3: ``HarnessConfigPort`` bound to the real C4
``ConfigurationApplicationService`` — the MP-05 production submit gate at the
controlled evidence level (E2 per verification.md).

Every gate below was red before ``harness_binding.py`` existed (the port's
only implementations were the ``testing`` fakes). The suite asserts BOTH
halves of the dispatch's honesty rule:

- 受控级: with a controlled one-use permit source the full
  ``plan → apply(permit) → adapter verify → read-back`` chain confirms and the
  downstream route really changes;
- 生产级: with no permit source (S-06 admission not flipped) every apply
  refuses ``AUTHORIZATION_REFUSED`` before any native effect — asserted here,
  restated in the report, never reported green.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from _controlled_harness import ControlledComposition, TARGET  # noqa: E402

from ordessa_model_provider.harness_binding import ConfigurationServiceHarnessPort  # noqa: E402
from ordessa_model_provider.ports import (  # noqa: E402
    SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED,
    SESSION_CONFIG_UNSUPPORTED, SessionConfigError,
)

SESSION_A = {"serverInstanceId": "test-server", "harnessId": "pi",
             "acpSessionId": "acp-session-a"}
SESSION_B = {"serverInstanceId": "test-server", "harnessId": "pi",
             "acpSessionId": "acp-session-b"}

#: (brand, brand_fields, model) triples that exercise each brand's semantics
BRAND_CASES = [
    ("pi", {"provider_in_instance": True, "credential_changed": False}, "acme/m1"),
    ("codex", {"before_provider": "legacy"}, "m1"),
    ("claude-code", {}, "claude-y"),
]


def _port(comp):
    return ConfigurationServiceHarnessPort(
        comp.service, target=TARGET,
        permit_source=comp.permit.mint,
        revision_source=lambda session_ref: comp.runtime.revision)


@pytest.mark.parametrize("brand,fields,model", BRAND_CASES)
def test_apply_confirms_with_readback_and_changes_the_downstream_route(brand, fields, model, tmp_path):
    comp = ControlledComposition(brand, tmp_path)
    try:
        port = _port(comp)
        session_ref = {**SESSION_A, "harnessId": brand}
        assert port.eligibility(brand, {"providerConfigId": "p-1"}, session_ref) == "ready"
        old_route = comp.prompt_route()
        receipt = port.apply(session_ref, comp.choice_payload(model=model, brand_fields=fields))
        assert receipt["readBack"]["model"] == model
        assert receipt["readBack"]["nativeSessionId"] == comp.instance.native_session_id
        assert receipt["readBack"]["evidenceRef"]
        assert port.read_back(session_ref)["model"] == model
        new_route = comp.prompt_route()
        assert new_route["routed_model"] == model != old_route["routed_model"]
        assert len(comp.endpoint.requests) == 2  # both prompts really left
    finally:
        comp.stop()


def test_bare_apply_without_permit_source_refuses_before_any_effect(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = ConfigurationServiceHarnessPort(
            comp.service, target=TARGET, permit_source=None,
            revision_source=lambda session_ref: comp.runtime.revision)
        with pytest.raises(SessionConfigError) as excinfo:
            port.apply(SESSION_A, comp.choice_payload(
                brand_fields={"provider_in_instance": True, "credential_changed": False}))
        assert excinfo.value.code == SESSION_CONFIG_REJECTED
        assert "permit refused" in str(excinfo.value)
        assert comp.runtime.apply_count == 0
        assert comp.endpoint.requests == []
    finally:
        comp.stop()


def test_one_use_permit_replay_returns_the_durable_result_without_new_effect(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = _port(comp)
        fields = {"provider_in_instance": True, "credential_changed": False}
        first = port.apply(SESSION_A, comp.choice_payload(brand_fields=fields))
        second = port.apply(SESSION_A, comp.choice_payload(brand_fields=fields))
        assert second == first
        assert comp.runtime.apply_count == 1  # the effect happened exactly once
        assert comp.permit.verified == [_operation_key_once(comp, SESSION_A, fields)]
    finally:
        comp.stop()


def _operation_key_once(comp, session_ref, fields):
    from ordessa_model_provider.harness_binding import _operation_key
    choice = comp.choice_payload(brand_fields=fields)
    return _operation_key(session_ref, choice)


def test_expired_permit_refuses(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = _port(comp)
        fields = {"provider_in_instance": True, "credential_changed": False}
        choice = comp.choice_payload(brand_fields=fields)
        key = _operation_key_once(comp, SESSION_A, fields)
        comp.permit.expire(key)
        with pytest.raises(SessionConfigError) as excinfo:
            port.apply(SESSION_A, choice)
        assert excinfo.value.code == SESSION_CONFIG_REJECTED
        assert comp.runtime.apply_count == 0
    finally:
        comp.stop()


def test_cross_session_isolation_session_b_never_consumes_session_a_operation(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = _port(comp)
        fields = {"provider_in_instance": True, "credential_changed": False}
        a_receipt = port.apply(SESSION_A, comp.choice_payload(brand_fields=fields))
        # session B re-using A's choice is a different operation key: it runs
        # its own chain, and A's readback never appears under B.
        b_receipt = port.apply(SESSION_B, comp.choice_payload(brand_fields=fields))
        assert b_receipt["operationId"] != a_receipt["operationId"]
        assert port.read_back(SESSION_B)["nativeSessionId"] == comp.instance.native_session_id
        with pytest.raises(SessionConfigError) as excinfo:
            port.read_back({"serverInstanceId": "other", "harnessId": "pi",
                            "acpSessionId": "acp-session-c"})
        assert excinfo.value.code == SESSION_CONFIG_OUTCOME_UNKNOWN
    finally:
        comp.stop()


def test_effect_failure_after_native_activation_is_unknown_and_blocks(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        comp.runtime.fail_after_effect = True
        port = _port(comp)
        with pytest.raises(SessionConfigError) as excinfo:
            port.apply(SESSION_A, comp.choice_payload(
                brand_fields={"provider_in_instance": True, "credential_changed": False}))
        assert excinfo.value.code == SESSION_CONFIG_OUTCOME_UNKNOWN
        # the durable record answers reconcile; nothing pretends it applied
        record = comp.service.query(_operation_key_once(
            comp, SESSION_A, {"provider_in_instance": True, "credential_changed": False}))
        assert record.result.kind == "unknown"
    finally:
        comp.stop()


def test_unsupported_harness_and_unknown_facet_are_typed(tmp_path):
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = _port(comp)
        assert port.describe("codex") is not None
        assert port.describe("not-a-harness") is None
        assert port.eligibility("not-a-harness", {}, SESSION_A) == "unknown"
    finally:
        comp.stop()


def test_secret_bearing_choice_is_refused_before_materialization(tmp_path):
    """MP-10 at the C4 boundary: a credential-carrying choice compiles to a
    BindSecret, which this C4 slice's materialization refuses (secrets need a
    separate controlled executor) — refused before any effect, nothing leaks."""
    comp = ControlledComposition("pi", tmp_path)
    try:
        port = _port(comp)
        with pytest.raises(SessionConfigError) as excinfo:
            port.apply(SESSION_A, comp.choice_payload(
                credential_ref="ref://controlled-cred",
                brand_fields={"provider_in_instance": False, "credential_changed": True}))
        assert excinfo.value.code in {SESSION_CONFIG_REJECTED, SESSION_CONFIG_UNSUPPORTED}
        assert comp.runtime.apply_count == 0
        assert comp.endpoint.requests == []
    finally:
        comp.stop()
