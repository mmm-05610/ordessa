"""Native Pi model mapping uses observed options, never labels or guessed IDs."""
from dataclasses import replace
import json
import pytest
from ordessa_agents.harness.definitions import ApplicationTarget, AdapterRefusal, IntentSource, InvokeAction
from ordessa_agents.harness.definitions.native_channels import NativeSessionObservation
from ordessa_server.composition.native_channels.profile_owner import ProfileConfigurationSnapshot


def compile_choice(snapshot, desired):
    from ordessa_harness_pi.configuration.live_model import compile_live_model
    return compile_live_model(snapshot, snapshot.target, desired,
                              IntentSource("assets.model-provider", "choice", "1"))


def snapshot(config_options=None, *, busy=False):
    target = ApplicationTarget("server", "uid", "channel", 1)
    owner = NativeSessionObservation("channel", "execution", "ledger", "native")
    options = config_options if config_options is not None else [{
        "id": "model", "type": "select", "currentValue": "provider/old",
        "options": [{"value": "provider/model/path", "name": "not-the-id"}]}]
    return ProfileConfigurationSnapshot(target, owner, "observed-generation", busy,
                                        json.dumps(options, sort_keys=True, separators=(",", ":")))


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
    from ordessa_harness_pi.configuration.live_model import compile_live_model
    value = replace(snapshot(), busy=True)
    assert isinstance(compile_choice(value, {"provider": "provider", "model": "model/path"}), AdapterRefusal)
    duplicate_options = snapshot().config_options
    duplicate_options.append(duplicate_options[0])
    value = snapshot(duplicate_options)
    assert isinstance(compile_choice(value, {"provider": "provider", "model": "model/path"}), AdapterRefusal)
    value = snapshot()
    result = compile_live_model(value, ApplicationTarget("other", "uid", "channel", 1),
        {"provider": "provider", "model": "model/path"}, IntentSource("assets.model-provider", "choice", "1"))
    assert isinstance(result, AdapterRefusal)


def observed_snapshot():
    options = snapshot().config_options
    options[0]["options"][0]["_meta"] = {"ordessaModel": {
        "provider": "provider", "model": "model/path", "api": "openai-completions",
        "baseUrl": "https://fixture.test/v1"}}
    return snapshot(options)


def full_choice():
    return {"provider": "provider", "model": "model/path", "protocol": "openai-chat",
            "endpoint": "https://fixture.test/v1", "credentialRef": None}


def test_full_business_choice_requires_independently_observed_native_routing():
    assert isinstance(compile_choice(observed_snapshot(), full_choice()), InvokeAction)
    assert isinstance(compile_choice(snapshot(), full_choice()), AdapterRefusal)


def test_pi_key_reference_requires_exact_native_owner_binding_and_route():
    from ordessa_harness_pi.configuration.live_model import compile_live_model
    value = observed_snapshot()
    desired = {**full_choice(), 'credentialRef': 'ref://synthetic'}
    source = IntentSource('assets.model-provider', 'choice', '1')
    for binding in (None, lambda *_: False):
        assert isinstance(compile_live_model(value, value.target, desired, source, credential_binding=binding), AdapterRefusal)
    assert isinstance(compile_live_model(value, value.target, desired, source, credential_binding=lambda *_: True), InvokeAction)
    changed = {**desired, 'endpoint': 'https://changed.invalid'}
    assert isinstance(compile_live_model(value, value.target, changed, source, credential_binding=lambda *_: True), AdapterRefusal)


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
        options = value.config_options
        options[0]["options"][0]["_meta"]["ordessaModel"].update(patch)
        value = snapshot(options)
        assert isinstance(compile_choice(value, full_choice()), AdapterRefusal)
