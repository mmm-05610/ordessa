"""Manager idempotency: durable claim before the effect, conflicts, crash windows.

The ledger is the only authority: a reservation that never completed reports
unknown and is never re-sent, a replay is served after a read check only, and an
unreadable ledger fails closed instead of reading as "nothing happened".
"""
import asyncio
import hashlib
import sqlite3

import pytest

from ordessa_execution_agents.sdk.endpoint import BoundEndpoint, SendObservation
from ordessa_execution_agents.sdk.instances import AgentInstanceRef, EndpointRef
from ordessa_execution_agents.sdk.manager import AgentManager, ManagerRefused, Records
from ordessa_execution_agents.sdk.prepare import (
    BoundPath, EndpointError, LaunchObservation, LaunchPlan, SessionBootstrap,
)

DIGEST = 'sha256:' + 'a' * 64


def _ref(name='endpoint-1'):
    return EndpointRef('issuer-1', name, 'rev-1', DIGEST)


def _plan(argv=('/bin/true',)):
    return LaunchPlan(argv=tuple(argv), cwd_ref=BoundPath('workdir', '.'), environment_values={},
                      secret_bindings=(), configuration_artifacts=(),
                      prepared_configuration_refs=(), material_refs=(),
                      session_bootstrap=SessionBootstrap('none'),
                      required_capabilities=('launcher',))


def _invocation(principal='principal'):
    # Mirrors the platform owner scope: (kind, ref), not a bare principal name.
    scope = type('S', (), {'kind': 'principal', 'ref': principal})()
    return type('I', (), {'owner_scope': scope})()


class _Launcher:
    def __init__(self, status='completed', fail=False):
        self.calls = 0
        self.status = status
        self.fail = fail

    async def launch(self, plan, request_id, invocation):
        self.calls += 1
        if self.fail:
            raise OSError('launcher crashed after the effect')
        return LaunchObservation('ref-' + request_id, self.status, _ref(), {'argv': list(plan.argv)})


class _Terminate:
    """T018: the lifecycle effect runs only through the guarded entry."""

    def __init__(self):
        self.calls = 0

    async def terminate(self, request_id, force, deadline, invocation):
        raise AssertionError('unguarded terminate must not be reachable')

    async def terminate_guarded(self, request_id, force, invocation, *, binding, guard):
        with guard():
            self.calls += 1
        return LaunchObservation(request_id, 'completed',facts={'action':'terminate','cancellation':'requested','processState':'unknown'})


class _Detach:
    def __init__(self):
        self.calls = 0

    async def detach(self, request_id, invocation):
        raise AssertionError('unguarded detach must not be reachable')

    async def detach_guarded(self, request_id, invocation, *, binding, guard):
        with guard():
            self.calls += 1
        return LaunchObservation(request_id, 'completed',
                                 facts={'action':'detach','associationDetached': True, 'exitClaimed': False})


class _Communicate:
    def __init__(self):
        self.calls = 0

    async def send(self, effect_id, frame, deadline, invocation):
        self.calls += 1
        return SendObservation('completed', len(frame), 'confirmed')


class _Resolver:
    def __init__(self, bound):
        self.bound = bound
        self.calls = 0

    async def resolve(self, ref, invocation):
        self.calls += 1
        return self.bound


def _manager(tmp_path, **members):
    launcher = members.pop('launcher', _Launcher())
    bound = BoundEndpoint(_ref(), {}, launcher=launcher, **members)
    resolver = _Resolver(bound)
    return AgentManager(resolver, Records(tmp_path / 'ledger.sqlite')), launcher, resolver


def test_reservation_is_durable_before_the_effect(tmp_path):
    launcher = _Launcher(fail=True)
    manager, _, _ = _manager(tmp_path, launcher=launcher)
    with pytest.raises(OSError):
        asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    # The claim survived the crash and is not a completed launch.
    record = manager.records.operation('r1', 'start')
    assert record.status == 'reserved'
    # A retry reports unknown and never launches a second process.
    replay = asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    assert replay.status == 'unknown'
    assert replay.error.code == 'OPERATION_UNCONFIRMED'
    assert launcher.calls == 1


def test_same_request_with_different_input_or_principal_conflicts(tmp_path):
    manager, launcher, _ = _manager(tmp_path)
    asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    with pytest.raises(ManagerRefused, match='REQUEST_CONFLICT'):
        asyncio.run(manager._launch_once('r1', _plan(('/bin/false',)), _ref(), _invocation()))
    with pytest.raises(ManagerRefused, match='REQUEST_CONFLICT'):
        asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation('another-principal')))
    # A different endpoint identity for the same request id is a conflict, not a
    # replay: the resolver must hand back the endpoint that was actually asked for.
    other = AgentManager(_Resolver(BoundEndpoint(_ref('endpoint-2'), {}, launcher=launcher)),
                         manager.records)
    with pytest.raises(ManagerRefused, match='REQUEST_CONFLICT'):
        asyncio.run(other._launch_once('r1', _plan(), _ref('endpoint-2'), _invocation()))
    assert launcher.calls == 1


def test_two_concurrent_starts_claim_once(tmp_path):
    launcher = _Launcher()
    manager, _, _ = _manager(tmp_path, launcher=launcher)

    async def scenario():
        return await asyncio.gather(
            manager._launch_once('r1', _plan(), _ref(), _invocation()),
            manager._launch_once('r1', _plan(), _ref(), _invocation()))

    results = asyncio.run(scenario())
    assert launcher.calls == 1, 'the second concurrent start must observe the claim'
    assert {item.operation_ref for item in results} == {'ref-r1'}


def test_two_processes_share_one_claim(tmp_path):
    launcher = _Launcher()
    manager_a, _, _ = _manager(tmp_path, launcher=launcher)
    manager_b = AgentManager(_Resolver(BoundEndpoint(_ref(), {}, launcher=launcher)),
                             Records(tmp_path / 'ledger.sqlite'))
    asyncio.run(manager_a._launch_once('r1', _plan(), _ref(), _invocation()))
    replay = asyncio.run(manager_b._launch_once('r1', _plan(), _ref(), _invocation()))
    assert replay.operation_ref == 'ref-r1'
    assert launcher.calls == 1


def test_replay_needs_read_authority_but_no_write_member(tmp_path):
    manager, launcher, resolver = _manager(tmp_path)
    asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    # The launcher member is revoked afterwards: history stays readable, no resend.
    revoked = BoundEndpoint(_ref(), {})
    manager.resolver = _Resolver(revoked)
    replay = asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    assert replay.status == 'completed' and launcher.calls == 1
    assert manager.resolver.calls >= 1, 'replay still performs a read check'
    # A new request is refused: the revoked member cannot authorize a new launch.
    with pytest.raises(ManagerRefused, match='LAUNCHER_NOT_GRANTED'):
        asyncio.run(manager._launch_once('r2', _plan(), _ref(), _invocation()))


def test_corrupt_ledger_fails_closed(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    manager, _, _ = _manager(tmp_path)
    asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))
    connection = sqlite3.connect(path)
    connection.execute("UPDATE operations SET payload='{not-json' WHERE request_id='r1'")
    connection.commit()
    connection.close()
    with pytest.raises(ManagerRefused, match='RECORD_CORRUPT'):
        manager.records.operation('r1', 'start')


def control_values(endpoint,instance_id='inst-1'):
    from ordessa_execution_agents.instances.contracts import InstanceBindingMaterial
    from ordessa_execution_agents.sdk.harness import HarnessDescriptor
    from ordessa_execution_agents.profiles import ProfileRevisionRef,encode_revision_ref
    from ordessa_execution_agents.sdk.interactions import BindingProvenance
    from ordessa_execution_agents.sdk.prepare import canonical_digest
    digest='sha256:'+'a'*64
    profile=ProfileRevisionRef('ns-1','fixture-profile',1,digest)
    harness=HarnessDescriptor('fixture',{'environmentNamespace':'ns-1','definitionId':'fixture','revision':'1'},digest,None,(),())
    material=InstanceBindingMaterial(profile,harness,endpoint,digest,digest,None,None,'fixture-source')
    instance=AgentInstanceRef('ns-1',instance_id,material.digest)
    facts={'schemaVersion':'agent-binding-provenance/1','instanceRef':instance.projection(),
        'revision':1,'profileRef':encode_revision_ref(profile),'preparedPlanDigest':digest,
        'endpointRef':endpoint.projection(),'directoryBindingDigest':digest,'sourceRevision':'fixture-source',
        'configurationRefs':[],'capturedAt':'2026-10-19T00:00:00Z'}
    return instance,BindingProvenance.decode({**facts,'observationDigest':canonical_digest(facts)}),material


def _instance(tmp_path, manager, instance_id='inst-1'):
    """Seed the sealed original control row for one started instance."""
    from types import SimpleNamespace
    instance,provenance,material=control_values(_ref(),instance_id)
    start = SimpleNamespace(principal='principal:principal', operation_ref='agent-start/op-1')
    manager.records.publish_instance_binding(provenance,None,principal_scope='principal:principal',protocol_id=None)
    manager.records.publish_instance_control(provenance, start, 'principal:principal',binding_material=material)
    return instance


class _LifecycleAuthority:
    def guard_instance_lifecycle(self, invocation, control, *, action):
        from contextlib import nullcontext
        return nullcontext()  # explicit controlled authority fixture only

    def check_read_instance(self, invocation, instance_id):
        return None

    def check_instance_lifecycle(self, invocation, control, *, action):
        if control.get('principalScope') != 'principal:principal':
            raise RuntimeError('owner mismatch')


def test_stop_detach_send_share_one_receipt_shape_and_replay(tmp_path):
    terminate, detach, communicate = _Terminate(), _Detach(), _Communicate()
    manager, launcher, _ = _manager(tmp_path, terminate=terminate, detach=detach,
                                    communicate=communicate)
    manager.lifecycle_authority = _LifecycleAuthority()
    instance = _instance(tmp_path, manager)
    first = asyncio.run(manager.stop('s1', instance, _invocation()))
    assert first.status == 'completed' and first.process_endpoint_ref is None
    again = asyncio.run(manager.stop('s1', instance, _invocation()))
    assert again.operation_ref == first.operation_ref and terminate.calls == 1
    # A signal receipt does not clear pending stop. Shape/replay for detach
    # uses a separate explicit instance, never implicit reconciliation.
    detached_instance = _instance(tmp_path, manager, 'detach-instance')
    assert asyncio.run(manager.detach('d1', detached_instance, _invocation())).status == 'completed'
    assert detach.calls == 1
    # The endpoint reference is no longer an online Agent identity.
    with pytest.raises(ManagerRefused, match='INSTANCE_REF_REQUIRED'):
        asyncio.run(manager.stop('s2', _ref(), _invocation()))
    assert not hasattr(manager, 'send')  # no competing unguarded physical-send ledger


def test_completed_launch_must_name_its_process(tmp_path):
    class NoEndpoint(_Launcher):
        async def launch(self, plan, request_id, invocation):
            return LaunchObservation('ref', 'completed')

    manager, _, _ = _manager(tmp_path, launcher=NoEndpoint())
    with pytest.raises(Exception, match='completed launch'):
        asyncio.run(manager._launch_once('r1', _plan(), _ref(), _invocation()))


def test_send_prompt_records_a_protocol_fact_and_replays_without_resending(tmp_path):
    from interaction_fixtures import original_service,INSTANCE
    from test_interactions import Communicate,Resolver,Guard,PARAMS_BYTES
    async def scenario():
        channel=Communicate();source,authority,sender,reader=original_service(tmp_path/'ledger.sqlite',Resolver(channel))
        manager=AgentManager(Resolver(channel),source.records)
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES);guard=Guard()
        reservation=source.reserve_turn(INSTANCE,prompt,request_id='r1',engineering_attempt_ref='attempt',invocation=sender)
        # Parent exists, with its original id, before the physical writer is called.
        assert source.records.turn(reservation.turn_ref.turn_id) is not None and channel.calls==0
        result=await manager.send_prompt('r1',INSTANCE,sender,prompt=prompt,interaction_service=source,
            engineering_attempt_ref='attempt',write_guard=guard,deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='unknown' and channel.calls==1
        assert result.agent_operation_ref==reservation.agent_operation_ref
        authority.denied.add('send')
        replay=await manager.send_prompt('r1',INSTANCE,reader,prompt=prompt,interaction_service=source,
            engineering_attempt_ref='attempt',write_guard=guard,deadline=asyncio.get_running_loop().time()+2)
        assert replay==result and channel.calls==1
        changed=source.freeze_prompt(INSTANCE,b'{"prompt":[],"sessionId":"session-1"}')
        with pytest.raises(Exception,match='REQUEST_CONFLICT'):
            await manager.send_prompt('r1',INSTANCE,reader,prompt=changed,interaction_service=source,
                engineering_attempt_ref='attempt',write_guard=guard,deadline=asyncio.get_running_loop().time()+2)
    asyncio.run(scenario())


def test_prompt_publication_crash_keeps_parent_unknown_and_never_resends(tmp_path,monkeypatch):
    from interaction_fixtures import original_service,INSTANCE
    from test_interactions import Communicate,Resolver,Guard,PARAMS_BYTES
    async def scenario():
        channel=Communicate();source,authority,sender,reader=original_service(tmp_path/'ledger.sqlite',Resolver(channel))
        manager=AgentManager(Resolver(channel),source.records)
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        reservation=source.reserve_turn(INSTANCE,prompt,request_id='r1',engineering_attempt_ref='attempt',invocation=sender)
        complete=source.records.complete
        def crash(*args,**kwargs):raise OSError('controlled post-effect publication crash')
        monkeypatch.setattr(source.records,'complete',crash)
        with pytest.raises(OSError):
            await manager.send_prompt('r1',INSTANCE,sender,prompt=prompt,interaction_service=source,
                engineering_attempt_ref='attempt',write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        monkeypatch.setattr(source.records,'complete',complete)
        assert channel.calls==1
        result=await manager.send_prompt('r1',INSTANCE,reader,prompt=prompt,interaction_service=source,
            engineering_attempt_ref='attempt',write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='unknown' and channel.calls==1
        assert result.turn_ref==reservation.turn_ref
    asyncio.run(scenario())
