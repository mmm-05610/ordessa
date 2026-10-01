from types import SimpleNamespace

import pytest
from ordessa_harness_api import AdapterRefusal, InvokeAction, IntentSource
from ordessa_harness.configuration.model.initial import initial_model_params
from ordessa_harness.configuration.model.live_model import compile_native_model


def model_fixture():
    desired = dict(provider='openai', model='gpt-5.5', protocol='openai-responses',
                   endpoint=None, authentication='managed-account')
    facts = dict(provider='openai', model='gpt-5.5', api='responses', baseUrl=None,
                 authentication='managed-account')
    snapshot = SimpleNamespace(busy=False, native_generation='generation', config_options=[
        dict(id='model', type='select', currentValue='gpt-5.5', options=[
            dict(value='gpt-5.5', _meta=dict(ordessaModel=facts))])])
    return snapshot, desired, facts


def test_official_model_change_requires_prepared_binding_and_native_authentication_facts():
    snapshot, desired, facts = model_fixture()
    source = IntentSource('assets.model-provider', 'choice', '1')
    assert isinstance(compile_native_model(snapshot, desired, source, 'codex'), AdapterRefusal)
    assert isinstance(compile_native_model(snapshot, desired, source, 'codex',
                      credential_binding=lambda *_: True), InvokeAction)
    facts.pop('authentication')
    assert isinstance(compile_native_model(snapshot, desired, source, 'codex',
                      credential_binding=lambda *_: True), AdapterRefusal)


@pytest.mark.parametrize('patch', [dict(provider='third-party'), dict(endpoint='https://api.invalid'),
                                 dict(credentialRef='credential'), dict(protocol='openai-chat')])
def test_official_initial_configuration_never_accepts_an_api_route_or_key(patch):
    _, desired, _ = model_fixture()
    with pytest.raises(ValueError):
        initial_model_params('codex', desired | patch, 'create:probe')


def test_official_route_is_codex_only_and_uses_no_secret():
    _, desired, _ = model_fixture()
    assert initial_model_params('codex', desired, 'create:probe')['provider'] == {
        'providerId': 'openai', 'authentication': 'managed-account'}
    with pytest.raises(ValueError):
        initial_model_params('codex', desired, 'create:probe', credential='synthetic')
