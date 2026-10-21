import json

import pytest
from ordessa_agents.harness.definitions import AdapterRefusal, InvokeAction, IntentSource
from ordessa_agents.harness.definitions.native_channels import NativeConfigurationObservation, NativeSessionObservation
from ordessa_harness_codex.configuration.initial import initial_model_params as codex_initial
from ordessa_harness_claude_code.configuration.initial import initial_model_params as claude_initial
from ordessa_harness_codex.configuration.live_model import compile_live_model


def model_fixture():
    desired = dict(provider='openai', model='gpt-5.5', protocol='openai-responses',
                   endpoint=None, authentication='managed-account')
    facts = dict(provider='openai', model='gpt-5.5', api='responses', baseUrl=None,
                 authentication='managed-account')
    snapshot = NativeConfigurationObservation(
        NativeSessionObservation('channel', 'execution', 'ledger', 'native'),
        'generation', False, json.dumps([dict(id='model', type='select', currentValue='gpt-5.5', options=[
            dict(value='gpt-5.5', _meta=dict(ordessaModel=facts))])]))
    return snapshot, desired, facts


def test_official_model_change_requires_prepared_binding_and_native_authentication_facts():
    snapshot, desired, facts = model_fixture()
    source = IntentSource('assets.model-provider', 'choice', '1')
    assert isinstance(compile_live_model(snapshot, desired, source), AdapterRefusal)
    assert isinstance(compile_live_model(snapshot, desired, source,
                      credential_binding=lambda *_: True), InvokeAction)
    facts.pop('authentication')
    malformed_snapshot = NativeConfigurationObservation(
        snapshot.owner, snapshot.native_generation, snapshot.busy,
        json.dumps([dict(id='model', type='select', currentValue='gpt-5.5', options=[
            dict(value='gpt-5.5', _meta=dict(ordessaModel=facts))])]))
    assert isinstance(compile_live_model(malformed_snapshot, desired, source,
                      credential_binding=lambda *_: True), AdapterRefusal)


@pytest.mark.parametrize('patch', [dict(provider='third-party'), dict(endpoint='https://api.invalid'),
                                 dict(credentialRef='credential'), dict(protocol='openai-chat')])
def test_official_initial_configuration_never_accepts_an_api_route_or_key(patch):
    _, desired, _ = model_fixture()
    with pytest.raises(ValueError):
        codex_initial(desired | patch, 'create:probe')


def test_official_route_is_codex_only_and_uses_no_secret():
    _, desired, _ = model_fixture()
    assert codex_initial(desired, 'create:probe')['provider'] == {
        'providerId': 'openai', 'authentication': 'managed-account'}
    with pytest.raises(ValueError):
        codex_initial(desired, 'create:probe', credential='synthetic')
