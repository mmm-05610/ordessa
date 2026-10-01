"""Model-only actions against a pinned native thread/query construction route.

Business provider labels are not native provider IDs. The native gateway has
one fixed dialect ID; exact protocol/endpoint matching establishes routing.
Credential changes and provider restoration are not model-only actions.
"""
from collections.abc import Mapping
from ordessa_harness_api import AdapterRefusal, ErrorCode, InvokeAction


def compile_native_model(snapshot, desired, source, brand, *, credential_binding=None):
    def refuse():
        return AdapterRefusal(ErrorCode.CAPABILITY_UNSUPPORTED,
                              'Model choice does not match verified native construction routing')
    managed = isinstance(desired, Mapping) and desired.get('authentication') == 'managed-account'
    if (brand not in ('codex', 'claude-code') or snapshot.busy is not False
        or not snapshot.native_generation or not isinstance(desired, Mapping)
        or not {'provider', 'model', 'protocol', 'endpoint'} <= set(desired)
        or set(desired) - {'provider', 'model', 'protocol', 'endpoint', 'credentialRef', 'brandFields', 'requestParams', 'authentication'}
        or desired.get('brandFields') not in (None, {})
        or desired.get('requestParams') not in (None, {})
        or any(type(desired[key]) is not str or not desired[key]
               or desired[key].strip() != desired[key] or len(desired[key]) > 4096
               or any(ord(char) < 32 for char in desired[key])
               for key in (('provider', 'model', 'protocol') if managed else ('provider', 'model', 'protocol', 'endpoint')))):
        return refuse()
    if (managed and (brand != 'codex' or desired['provider'] != 'openai'
            or desired['endpoint'] is not None or desired.get('credentialRef') is not None
            or not callable(credential_binding))
            or not managed and desired.get('authentication') is not None):
        return refuse()
    if desired.get('credentialRef') is not None or callable(credential_binding):
        try:
            if not callable(credential_binding) or credential_binding(snapshot, desired) is not True:
                return refuse()
        except Exception:
            return refuse()
    selectors = [item for item in snapshot.config_options if item.get('id') == 'model']
    if len(selectors) != 1 or selectors[0].get('type') != 'select':
        return refuse()
    def flatten(options, depth=0):
        if not isinstance(options, list) or depth > 2 or len(options) > 512:
            raise ValueError('Malformed native model options')
        for option in options:
            if not isinstance(option, dict):
                raise ValueError('Malformed native model option')
            if 'value' in option:
                yield option
            if 'options' in option:
                yield from flatten(option['options'], depth + 1)
    try:
        matches = [item for item in flatten(selectors[0].get('options', []))
                   if item.get('value') == desired['model']]
    except ValueError:
        return refuse()
    if len(matches) != 1:
        return refuse()
    metadata = matches[0].get('_meta')
    facts = metadata.get('ordessaModel') if isinstance(metadata, dict) else None
    provider, api, protocol = (('openai' if managed else 'custom-gateway', 'responses', 'openai-responses')
                              if brand == 'codex' else ('main', 'anthropic', 'anthropic-messages'))
    expected_keys = {'provider', 'model', 'api', 'baseUrl'} | ({'authentication'} if managed else set())
    if (not isinstance(facts, dict) or set(facts) != expected_keys
        or managed and facts.get('authentication') != 'managed-account'
        or facts['provider'] != provider or facts['model'] != desired['model']
        or facts['api'] != api or desired['protocol'] != protocol
        or facts['baseUrl'] != desired['endpoint']):
        return refuse()
    return InvokeAction(source, 'acp.session.set-config-option', '1',
                        {'configId': 'model', 'value': desired['model']}, brand + '-native-model:' + desired['model'])
