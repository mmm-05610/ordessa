from ordessa_harness_codex.configuration.initial import initial_model_params as codex_initial
from ordessa_harness_claude_code.configuration.initial import initial_model_params as claude_initial


def test_anthropic_native_provider_supplies_standard_api_key_without_changing_other_brands():
    payload = dict(provider='configured', model='custom-model', endpoint='https://provider.test',
                   protocol='anthropic-messages', credentialRef='opaque-reference')
    result = claude_initial(payload, 'create:test', credential='synthetic-key')
    assert result['provider']['headers'] == {
        'authorization': 'Bearer synthetic-key', 'x-api-key': 'synthetic-key'}
    payload['protocol'] = 'openai-responses'
    result = codex_initial(payload, 'create:test', credential='synthetic-key')
    assert result['provider']['headers'] == {'authorization': 'Bearer synthetic-key'}


def test_codex_launch_carries_detached_neutral_model_capabilities():
    payload = dict(provider='configured', model='custom-model', endpoint='https://provider.test',
                   protocol='openai-responses', credentialRef='opaque-reference',
                   modelCapabilities={'toolCall': True, 'reasoning': True,
                       'reasoningOptions': [{'type': 'effort', 'values': ['low', 'high']}]})
    result = codex_initial(payload, 'create:catalog', credential='synthetic-key')
    assert result['modelCapabilities'] == payload['modelCapabilities']
    result['modelCapabilities']['reasoningOptions'][0]['values'].clear()
    assert payload['modelCapabilities']['reasoningOptions'][0]['values'] == ['low', 'high']
    payload['protocol'] = 'anthropic-messages'
    assert 'modelCapabilities' not in claude_initial(payload, 'create:catalog', credential='synthetic-key')
