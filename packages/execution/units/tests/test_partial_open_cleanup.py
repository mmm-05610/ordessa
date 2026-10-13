"""Fault injection on real Local handles and the official SDK, without models."""
import asyncio
import pytest

from test_unit_instance import flow
from ordessa_environments import EnvironmentRefused
from ordessa_execution_agents.harness.transport import ProcessChannel
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.sessions.sdk_client import SdkAcpClient


@pytest.mark.parametrize('stage', ['attach', 'sdk-before', 'sdk-after', 'handshake'])
def test_partial_open_retains_original_owner_and_releases_only_its_use(flow, monkeypatch, stage):
    foreign = flow.environments.instance.acquire('foreign-agent', sharing=True)
    prepared = flow.instance.prepare(flow.plan, flow.authority.issue('prepare'))
    factory = flow.instance.channel_factory
    use = factory.environment
    assert flow.environments.instance.snapshot.active_uses == 2

    def fail(*args, **kwargs):
        raise RuntimeError('controlled partial-open ' + stage)

    original_open = SdkAcpClient._open
    if stage == 'attach':
        monkeypatch.setattr(ProcessChannel, 'attach', fail)
    elif stage.startswith('sdk-'):
        async def failed_open(client):
            if stage == 'sdk-after':
                await original_open(client)
                assert client.sdk_connection is not None
            fail()
        monkeypatch.setattr(SdkAcpClient, '_open', failed_open)
    else:
        monkeypatch.setattr(factory, 'handshake', fail)

    with pytest.raises(UnitLifecycleRefused, match='creation unknown'):
        flow.instance.start(prepared, flow.authority.issue('start'))
    unit = prepared['unitRef']
    record = factory.owned_record
    assert record is not None
    assert record.environment_use_identity == use.identity
    assert record.environment_identity == foreign.environment_id
    assert record.process.observe().state == 'running'
    assert flow.records.owner_read_session(unit['unitId']).state == 'unknown'
    if stage.startswith('sdk-'):
        assert type(record.entry) is SdkAcpClient
        assert record.channel is not None
        assert record.entry.has_io_loop
        with pytest.raises(RuntimeError, match='no reopen'):
            record.entry.open_connection()
    with pytest.raises(Exception):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert flow.events.count('spawn') == 1
    assert flow.instance.stop(unit, flow.authority.issue('stop'))['state'] == 'confirmed'
    assert record.process.observe().state == 'exited'
    assert flow.instance.release(unit, flow.authority.issue('release'))['state'] == 'confirmed'
    assert flow.environments.release_receipts[use.identity]['resourcePreserved'] is True
    assert flow.environments.instance.snapshot.active_uses == 1
    assert foreign.files.root()
    with pytest.raises(EnvironmentRefused):
        record.process.observe()
    if type(record.entry) is SdkAcpClient:
        assert not record.entry.has_io_loop
    foreign.release()
    assert flow.environments.instance.snapshot.active_uses == 0


def test_before_spawn_failure_keeps_unknown_and_never_fakes_termination(flow, monkeypatch):
    prepared = flow.instance.prepare(flow.plan, flow.authority.issue('prepare'))
    factory = flow.instance.channel_factory
    calls = []
    def fail(request):
        calls.append(request)
        raise EnvironmentRefused('controlled before original spawn')
    monkeypatch.setattr(factory.environment.execution, 'start', fail)
    with pytest.raises(UnitLifecycleRefused, match='creation unknown'):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert factory.owned_record is None
    assert flow.events.count('spawn') == 0
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state == 'unknown'
    with pytest.raises(Exception):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert len(calls) == 1
    with pytest.raises(UnitLifecycleRefused):
        flow.instance.stop(prepared['unitRef'], flow.authority.issue('stop'))
    # No process exists; a confirmed Use release does not confirm the Unit.
    factory.release_environment()
    assert flow.environments.instance.snapshot.active_uses == 0
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state == 'unknown'


def test_lost_spawn_return_has_no_invented_owner_handle_or_replay(flow, monkeypatch):
    prepared = flow.instance.prepare(flow.plan, flow.authority.issue('prepare'))
    factory = flow.instance.channel_factory
    original = factory.environment.execution.start
    captured = []
    def lose_return(request):
        captured.append(original(request))
        raise RuntimeError('controlled loss after actual spawn before return')
    monkeypatch.setattr(factory.environment.execution, 'start', lose_return)
    with pytest.raises(UnitLifecycleRefused, match='creation unknown'):
        flow.instance.start(prepared, flow.authority.issue('start'))
    unit = prepared['unitRef']
    assert factory.owned_record is None
    assert captured[0].observe().state == 'running'
    with pytest.raises(Exception):
        flow.instance.start(prepared, flow.authority.issue('start'))
    assert len(captured) == flow.events.count('spawn') == 1
    with pytest.raises(UnitLifecycleRefused):
        flow.instance.stop(unit, flow.authority.issue('stop'))
    with pytest.raises(EnvironmentRefused):
        factory.release_environment()
    assert flow.environments.instance.snapshot.active_uses == 1
    # Only the fault injector retained the actual return value. Its explicit
    # test teardown is not a confirmed Unit termination/recovery receipt.
    async def cleanup_original():
        await captured[0].cancel()
        return await captured[0].wait_exit(timeout=2)
    assert asyncio.run(cleanup_original()).state == 'exited'
    captured[0].release()
    factory.release_environment()
    assert flow.environments.instance.snapshot.active_uses == 0
    assert flow.records.owner_read_session(unit['unitId']).state == 'unknown'
