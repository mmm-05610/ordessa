"""Harness-owned initial channel admission and native provider dialect."""
from collections.abc import Mapping
from urllib.parse import urlsplit
from ...server_acp.registry import NativeConfigurationUnavailable


def initial_channel(registry, connection_id, *, empty=True):
    channel = registry.get(connection_id)
    if channel is None:
        raise NativeConfigurationUnavailable('Initial channel unavailable')
    with channel._lock:
        if (channel._ended or not channel.session_scope_id or
                (empty and (channel._native_sessions or channel._pending_new))):
            raise NativeConfigurationUnavailable('Initial preparation requires dedicated empty channel')
    if registry.get(connection_id) is not channel:
        raise NativeConfigurationUnavailable('Initial channel replaced')
    return channel


def initial_model_params(brand, payload, operation_id, *, credential=None, models=None):
    """Never retain this secret-bearing return value as evidence."""
    protocol, provider, api = {'pi': ('openai-chat', payload.get('provider'), 'openai-completions'),
                              'codex': ('openai-responses', 'custom-gateway', 'openai'),
                              'claude-code': ('anthropic-messages', 'main', 'anthropic')}[brand]
    if (not isinstance(payload, Mapping) or payload.get('protocol') != protocol
            or payload.get('brandFields') not in (None, {}) or payload.get('requestParams') not in (None, {})):
        raise ValueError('Unsupported initial model dialect')
    for key in ('model', 'provider', 'endpoint'):
        value = payload.get(key)
        if (type(value) is not str or not value or value.strip() != value or len(value) > 4096
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError('Invalid bounded initial model')
    endpoint = urlsplit(payload['endpoint'])
    if endpoint.scheme not in ('https', 'http') or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError('Unsafe initial endpoint')
    if (payload.get('credentialRef') is None) != (credential is None):
        raise ValueError('Initial credential binding unavailable')
    native = {'providerId': provider, 'apiType': api, 'baseUrl': payload['endpoint']}
    if brand == 'pi':
        if ('/' in provider or not isinstance(models, list) or not 1 <= len(models) <= 256
                or any(type(m) is not str or not m or m != m.strip() or len(m) > 4096
                       or any(ord(c) < 32 or ord(c) == 127 for c in m) for m in models)
                or len(set(models)) != len(models) or payload['model'] not in models):
            raise ValueError('Invalid bounded Pi model catalogue')
    if credential is not None:
        if type(credential) is not str or not credential or len(credential) > 8000 or any(ord(c) < 32 or ord(c) == 127 for c in credential):
            raise ValueError('Invalid initial credential')
        if brand == 'pi':
            native['apiKey'] = credential
        else:
            native['headers'] = {'authorization': 'Bearer ' + credential}
    if brand == 'pi':
        return {'operationId': operation_id, 'model': payload['model'], 'provider': native, 'models': list(models)}
    return {'operationId': operation_id, 'model': payload['model'], 'provider': native}
