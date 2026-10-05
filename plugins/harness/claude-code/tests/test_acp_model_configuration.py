"""Pure historical ACP model compilation; no SDK/native/model calls."""
from dataclasses import replace
import pytest
from ordessa_harness_api.model_compilation import (
    AdapterContext, BindSecret, ChoiceRequest, CompileIntent, Refusal, TargetHandle)
from ordessa_harness_claude_code.acp_model_configuration import ClaudeAdapter


def context(session="original-session"):
    return AdapterContext(TargetHandle("claude-code", "instance", "fixture"), "0.81.2",
                          {"native_session_id": session})


def choice(**fields):
    return ChoiceRequest("provider", "new-model", "https://fixture.test", "anthropic-messages",
                         "ref://fixture-secret", "fixture", fields)


@pytest.mark.parametrize("session", [None, "", " ", True, 1, "default", "bad\x00identity", "bad\ud800identity"])
def test_missing_session_identity_cannot_confirm_matching_model(session):
    observed = {"desired_model": "new-model", "readback": {"model": "new-model"},
                "native_session_id": session}
    assert ClaudeAdapter().verify(context(session), observed).verdict == "unknown"


def test_credential_only_change_preserves_binding_and_requires_same_session_restore():
    result = ClaudeAdapter().compile(context(), {}, choice(credential_changed=True))
    assert result.reconfiguration == "restart-resume"
    assert result.resume_expectation == {"native_session_id": "original-session"}
    assert any(isinstance(intent, BindSecret) and intent.secret_ref == "ref://fixture-secret"
               and intent.slot == "ANTHROPIC_AUTH_TOKEN" for intent in result.intents)
    assert any(isinstance(intent, CompileIntent) and intent.field_path == ("session", "model")
               and intent.typed_value == "new-model" for intent in result.intents)
    assert not any(isinstance(intent, CompileIntent) and intent.field_path == ("env", "ANTHROPIC_BASE_URL")
                   for intent in result.intents)


def test_endpoint_and_model_change_compiles_both_without_secret_content():
    result = ClaudeAdapter().compile(context(), {}, choice(endpoint_changed=True))
    fields = {intent.field_path: intent.typed_value for intent in result.intents if isinstance(intent, CompileIntent)}
    assert fields[("env", "ANTHROPIC_BASE_URL")] == "https://fixture.test"
    assert fields[("session", "model")] == "new-model"
    assert result.reconfiguration == "restart-resume"
    assert result.resume_expectation == {"native_session_id": "original-session"}
    assert all(not isinstance(intent, BindSecret) or intent.secret_ref == "ref://fixture-secret" for intent in result.intents)


def test_credential_change_without_reference_refuses_instead_of_dropping_it():
    result = ClaudeAdapter().compile(context(), {}, replace(choice(credential_changed=True), credential_ref=None))
    assert isinstance(result, Refusal)


@pytest.mark.parametrize("desired,actual", [(None, None), ("", ""), (True, 1)])
def test_missing_or_untyped_model_cannot_be_confirmed(desired, actual):
    assert ClaudeAdapter().verify(context(), {"desired_model": desired, "readback": {"model": actual},
                                            "native_session_id": "original-session"}).verdict == "unknown"


def test_real_same_session_model_readback_is_positive_and_ack_alone_unknown():
    adapter = ClaudeAdapter()
    sample = {"desired_model": "new-model", "readback": {"model": "new-model"},
              "native_session_id": "original-session"}
    result = adapter.verify(context(), sample)
    assert result.verdict == "match" and result.evidence == {"applied_layer": "session-readback"}
    assert adapter.verify(context(), {"desired_model": "new-model", "rpc_ack": True}).verdict == "unknown"
    sample["native_session_id"] = "replacement-session"
    assert adapter.verify(context(), sample).verdict == "mismatch"


def test_acp_version_axis_does_not_claim_sdk_pin_support():
    adapter = ClaudeAdapter()
    assert adapter.assess(context(), choice()).verdict == "supported"
    assert adapter.assess(replace(context(), harness_version="0.2.163"), choice()).verdict == "unsupported"
    assert adapter.assess(replace(context(), harness_version=None), choice()).verdict == "unknown"


@pytest.mark.parametrize("reference", [True, {}, 1, "", "bad\x00reference"])
def test_malformed_credential_reference_is_never_a_secret_binding(reference):
    result = ClaudeAdapter().compile(context(), {}, replace(choice(credential_changed=True), credential_ref=reference))
    assert isinstance(result, Refusal)


@pytest.mark.parametrize("endpoint", [None, True, "", "bad\x00endpoint"])
def test_malformed_routing_endpoint_is_not_compiled(endpoint):
    assert isinstance(ClaudeAdapter().compile(context(), {}, replace(choice(endpoint_changed=True), endpoint=endpoint)), Refusal)


def test_foreign_harness_target_never_receives_claude_config_fields():
    foreign = replace(context(), target_handle=TargetHandle("codex", "instance", "foreign"))
    assert isinstance(ClaudeAdapter().compile(foreign, {}, choice(endpoint_changed=True)), Refusal)


@pytest.mark.parametrize("flag", ["true", 1, {}])
def test_nonboolean_change_flag_cannot_drop_or_add_configuration(flag):
    assert isinstance(ClaudeAdapter().compile(context(), {}, choice(credential_changed=flag)), Refusal)


@pytest.mark.parametrize("target", [TargetHandle("codex", "instance", "fixture"),
    TargetHandle("claude-code", "project", "fixture"), TargetHandle("claude-code", "instance", None)])
def test_foreign_or_missing_target_cannot_compile_or_confirm(target):
    wrong = replace(context(), target_handle=target)
    assert isinstance(ClaudeAdapter().compile(wrong, {}, choice()), Refusal)
    assert ClaudeAdapter().verify(wrong, {"desired_model": "new-model", "readback": {"model": "new-model"},
                                          "native_session_id": "original-session"}).verdict == "unknown"
