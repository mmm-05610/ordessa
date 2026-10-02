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


def test_codex_launch_carries_detached_neutral_model_capabilities():
    payload = dict(provider='configured', model='custom-model', endpoint='https://provider.test',
                   protocol='openai-responses', credentialRef='opaque-reference',
                   modelCapabilities={'toolCall': True, 'reasoning': True,
                       'reasoningOptions': [{'type': 'effort', 'values': ['low', 'high']}]})
    result = initial_model_params('codex', payload, 'create:catalog', credential='synthetic-key')
    assert result['modelCapabilities'] == payload['modelCapabilities']
    result['modelCapabilities']['reasoningOptions'][0]['values'].clear()
    assert payload['modelCapabilities']['reasoningOptions'][0]['values'] == ['low', 'high']
    payload['protocol'] = 'anthropic-messages'
    assert 'modelCapabilities' not in initial_model_params('claude-code', payload, 'create:catalog', credential='synthetic-key')
