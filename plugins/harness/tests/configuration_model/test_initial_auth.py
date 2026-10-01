from ordessa_harness.configuration.model.initial import initial_model_params


def test_anthropic_native_provider_supplies_standard_api_key_without_changing_other_brands():
    payload = dict(provider='configured', model='custom-model', endpoint='https://provider.test',
                   protocol='anthropic-messages', credentialRef='opaque-reference')
    result = initial_model_params('claude-code', payload, 'create:test', credential='synthetic-key')
    assert result['provider']['headers'] == {
        'authorization': 'Bearer synthetic-key', 'x-api-key': 'synthetic-key'}
    payload['protocol'] = 'openai-responses'
    result = initial_model_params('codex', payload, 'create:test', credential='synthetic-key')
    assert result['provider']['headers'] == {'authorization': 'Bearer synthetic-key'}
