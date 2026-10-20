"""Initial channel admission against the existing registry and session owner."""
from ordessa_execution_agents.harness.definitions.native_channels import NativeConfigurationUnavailable


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
