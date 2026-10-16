"""Revocation after call admission must stop the actual SDK frame write."""
import pytest
from dataclasses import replace
from test_unit_instance import flow
from ordessa_units.sessions.sdk_client import SdkAcpClient
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_execution_agents.preparation import SessionBootstrap


@pytest.mark.parametrize('method', ['initialize', 'session/new', 'session/load'])
def test_revocation_at_original_transport_send_prevents_native_frame(flow, monkeypatch, method):
    if method == 'session/load':
        flow.instance.channel_factory.session_id = 'controlled-native-session'
        prepare = flow.instance.channel_factory.preparation.prepare
        monkeypatch.setattr(flow.instance.channel_factory.preparation, 'prepare',
            lambda roots: replace(prepare(roots), session=SessionBootstrap('resume', 'controlled-native-session')))
    prepared = flow.instance.prepare(flow.plan, flow.authority.issue('prepare'))
    original = flow.instance.channel_factory.open
    attempted, written = [], []
    def open_channel(*args, **kwargs):
        client = original(*args, **kwargs)
        assert type(client) is SdkAcpClient
        send = client.transport.send
        write = client._channel.send_frame_async
        async def observe_write(frame, **kwargs):
            # Record only writes whose inside-lock gate actually succeeds.
            guard = kwargs['before_write']
            def record_after_authority():
                guard()
                written.append(frame)
            return await write(frame, before_write=record_after_authority)
        async def revoke_at_send(payload):
            if payload.get('method') == method:
                attempted.append(payload)
                flow.authority.allowed = False
            return await send(payload)
        client._channel.send_frame_async = observe_write
        client.transport.send = revoke_at_send
        return client
    monkeypatch.setattr(flow.instance.channel_factory, 'open', open_channel)
    with pytest.raises(UnitLifecycleRefused, match='unknown'):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert len(attempted) == 1
    assert all(('"method":"'+method+'"').encode() not in frame for frame in written)
    assert flow.environments.opens == 1 and flow.events.count('spawn') == 1
    assert flow.instance.channel_factory.owned_record is not None
    assert flow.instance.channel_factory.owned_record.entry.session_id is None
    with pytest.raises(UnitRecordsRefused, match='cannot be dispatched again'):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert flow.events.count('spawn') == 1 and len(attempted) == 1
