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


def initial_model_params(brand, payload, operation_id, *, credential=None):
    """Never retain this secret-bearing return value as evidence."""
    protocol, provider, api = {'codex': ('openai-responses', 'custom-gateway', 'openai'),
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
    if credential is not None:
        if type(credential) is not str or not credential or len(credential) > 8000 or any(ord(c) < 32 or ord(c) == 127 for c in credential):
            raise ValueError('Invalid initial credential')
        native['headers'] = {'authorization': 'Bearer ' + credential}
    return {'operationId': operation_id, 'model': payload['model'], 'provider': native}
