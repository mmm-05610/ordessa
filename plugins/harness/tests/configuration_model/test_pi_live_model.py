"""Native Pi model mapping uses observed options, never labels or guessed IDs."""
from types import SimpleNamespace
import pytest
from ordessa_harness_api import ApplicationTarget, AdapterRefusal, IntentSource, InvokeAction


def compile_choice(snapshot, desired):
    from ordessa_harness.pi.configuration.live_model import compile_live_model
    return compile_live_model(snapshot, snapshot.target, desired,
                              IntentSource("assets.model-provider", "choice", "1"))


def snapshot():
    return SimpleNamespace(
        target=ApplicationTarget("server", "uid", "channel", 1), busy=False,
        native_generation="observed-generation",
        config_options=[{"id": "model", "type": "select", "currentValue": "provider/old",
                         "options": [{"value": "provider/model/path", "name": "not-the-id"}]}])


def test_pi_live_model_compiles_only_native_action_with_observed_value():
    result = compile_choice(snapshot(), {"provider": "provider", "model": "model/path"})
    assert isinstance(result, InvokeAction)
    assert result.action_id == "acp.session.set-config-option"
    assert result.typed_payload == {"configId": "model", "value": "provider/model/path"}


@pytest.mark.parametrize("desired", [
    {"provider": "missing", "model": "model/path"},
    {"provider": "provider", "model": "not-the-id"},
    {"provider": "provider", "model": "model/path", "endpoint": "https://changed.test"},
    {"provider": "provider", "model": "model/path", "credentialRef": "ref://changed"},
    {"provider": "provider", "model": "model/path", "brandFields": {"provider_in_instance": True}},
    {"provider": "provider", "model": "model/path", "requestParams": {"retry": {}}},
])
def test_pi_live_model_refuses_unobserved_or_unproven_configuration(desired):
    assert isinstance(compile_choice(snapshot(), desired), AdapterRefusal)


def test_pi_live_model_refuses_busy_duplicate_option_and_wrong_target():
    from ordessa_harness.pi.configuration.live_model import compile_live_model
    value = snapshot()
    value.busy = True
    assert isinstance(compile_choice(value, {"provider": "provider", "model": "model/path"}), AdapterRefusal)
    value.busy = False
    value.config_options.append(value.config_options[0])
    assert isinstance(compile_choice(value, {"provider": "provider", "model": "model/path"}), AdapterRefusal)
    value = snapshot()
    result = compile_live_model(value, ApplicationTarget("other", "uid", "channel", 1),
        {"provider": "provider", "model": "model/path"}, IntentSource("assets.model-provider", "choice", "1"))
    assert isinstance(result, AdapterRefusal)


def observed_snapshot():
    value = snapshot()
    value.config_options[0]["options"][0]["_meta"] = {"ordessaModel": {
        "provider": "provider", "model": "model/path", "api": "openai-completions",
        "baseUrl": "https://fixture.test/v1"}}
    return value


def full_choice():
    return {"provider": "provider", "model": "model/path", "protocol": "openai-chat",
            "endpoint": "https://fixture.test/v1", "credentialRef": None}


def test_full_business_choice_requires_independently_observed_native_routing():
    assert isinstance(compile_choice(observed_snapshot(), full_choice()), InvokeAction)
    assert isinstance(compile_choice(snapshot(), full_choice()), AdapterRefusal)


@pytest.mark.parametrize("patch", [
    {"endpoint": "https://changed.test/v1"}, {"protocol": "openai-responses"},
    {"credentialRef": "ref://new-secret"}, {"requestParams": {"maxTokens": 10}},
    {"brandFields": {"provider_in_instance": True}}, {"unexpected": True},
])
def test_full_choice_never_discards_requested_configuration_changes(patch):
    assert isinstance(compile_choice(observed_snapshot(), {**full_choice(), **patch}), AdapterRefusal)


def test_routing_metadata_must_match_option_identity_and_closed_shape():
    for patch in ({"provider": "other"}, {"model": "other"}, {"extra": "secret"}):
        value = observed_snapshot()
        value.config_options[0]["options"][0]["_meta"]["ordessaModel"].update(patch)
        assert isinstance(compile_choice(value, full_choice()), AdapterRefusal)
