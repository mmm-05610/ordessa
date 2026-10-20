"""Frozen action-specific facts and deadline/guard negatives, no real model."""
import asyncio

import pytest

from test_lifecycle_control import graph
from ordessa_execution_agents.sdk.prepare import LaunchObservation,EndpointError,PrepareValueError,validate_lifecycle_observation
from ordessa_execution_agents.sdk.manager import ManagerRefused
from types import SimpleNamespace


@pytest.mark.parametrize('action,facts',[
    ('stop',{}),('stop',{'action':'terminate'}),
    ('stop',{'action':'stop','cancellation':'requested','processState':'running'}),
    ('stop',{'action':'terminate','cancellation':'confirmed','processState':'running'}),
    ('stop',{'action':'terminate','cancellation':'requested','processState':'stopped'}),
    ('stop',{'action':'terminate','cancellation':'requested','processState':'running','exitClaimed':True}),
    ('detach',{}),('detach',{'action':'detach','associationDetached':False,'exitClaimed':False}),
    ('detach',{'action':'detach','associationDetached':True}),
    ('detach',{'action':'detach','associationDetached':True,'exitClaimed':True}),
    ('detach',{'action':'detach','associationDetached':True,'exitClaimed':False,'released':True}),
])
def test_completed_lifecycle_does_not_accept_missing_or_false_native_facts(action,facts):
    with pytest.raises(PrepareValueError):
        validate_lifecycle_observation(action,LaunchObservation('original-resource-op','completed',facts=facts))


@pytest.mark.parametrize('cancellation',['requested','unsupported','unknown'])
@pytest.mark.parametrize('state',['running','exited','unknown'])
def test_terminate_facts_never_manufacture_exit_claim(cancellation,state):
    observation=LaunchObservation('original-resource-op','completed',facts={
        'action':'terminate','cancellation':cancellation,'processState':state})
    assert validate_lifecycle_observation('stop',observation) is observation


def test_expired_deadline_refuses_before_control_epoch_or_reservation(tmp_path):
    async def scenario():
        manager,records,instance,member=graph(tmp_path)
        invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
        before=records.instance_control(instance);changes=records._db.total_changes
        with pytest.raises(ManagerRefused,match='LIFECYCLE_DEADLINE_ELAPSED'):
            await manager.stop('expired',instance,invocation,deadline=asyncio.get_running_loop().time()-1)
        assert records.instance_control(instance)==before and records._db.total_changes==changes and member.calls==[]
    asyncio.run(scenario())


def test_deadline_rechecked_at_actual_guard_refuses_zero_native_effect(tmp_path):
    async def scenario():
        manager,records,instance,member=graph(tmp_path)
        original=member.terminate_guarded
        async def delayed(*args,**kwargs):
            await asyncio.sleep(.01)
            return await original(*args,**kwargs)
        member.terminate_guarded=delayed
        invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
        with pytest.raises(ManagerRefused,match='LIFECYCLE_DEADLINE_ELAPSED'):
            await manager.stop('expired-at-cut',instance,invocation,deadline=asyncio.get_running_loop().time()+.001)
        assert member.calls==[] and records.instance_control(instance)[0].active_operation_ref is None
        row=records._db.execute("SELECT status FROM operations WHERE operation='stop'").fetchone()
        assert row==('refused',)
    asyncio.run(scenario())


def test_completed_receipt_without_using_physical_guard_stays_unknown_no_replay(tmp_path):
    async def scenario():
        manager,records,instance,member=graph(tmp_path)
        async def unguarded(*args,**kwargs):
            return LaunchObservation('unqualified-resource-op','completed',facts={
                'action':'terminate','cancellation':'requested','processState':'unknown'})
        member.terminate_guarded=unguarded
        invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
        with pytest.raises(ManagerRefused,match='OPERATION_UNCONFIRMED'):
            await manager.stop('missing-cut',instance,invocation)
        replay=await manager.stop('missing-cut',instance,invocation)
        assert replay.status=='unknown' and records.instance_control(instance)[0].active_action=='stop'
        assert member.calls==[]
    asyncio.run(scenario())


def test_endpoint_error_after_physical_cut_remains_unknown_and_fenced(tmp_path):
    from ordessa_execution_agents.sdk.endpoint import EndpointValueError
    async def scenario():
        manager,records,instance,member=graph(tmp_path)
        async def partial(*args,guard,**kwargs):
            with guard():
                member.calls.append('possibly-effected')
            raise EndpointValueError('AFTER_CUT')
        member.terminate_guarded=partial
        invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
        with pytest.raises(ManagerRefused,match='OPERATION_UNCONFIRMED'):
            await manager.stop('partial',instance,invocation)
        assert records.instance_control(instance)[0].active_action=='stop'
        assert (await manager.stop('partial',instance,invocation)).status=='unknown'
        assert member.calls==['possibly-effected']
    asyncio.run(scenario())


@pytest.mark.parametrize('context',['task','thread'])
def test_copied_lifecycle_guard_context_cannot_effect(tmp_path,context):
    async def scenario():
        manager,records,instance,member=graph(tmp_path)
        async def copied(*args,guard,**kwargs):
            async def use():
                with guard():pass
            if context=='task':await asyncio.create_task(use())
            else:await asyncio.to_thread(lambda:asyncio.run(use()))
            member.calls.append('effect')
        member.terminate_guarded=copied
        invocation=SimpleNamespace(owner_scope=SimpleNamespace(kind='principal',ref='alice'))
        with pytest.raises(ManagerRefused,match='LIFECYCLE_GUARD_CONTEXT_CHANGED'):
            await manager.stop('copied',instance,invocation)
        assert member.calls==[]
        assert records.instance_control(instance)[0].active_operation_ref is None
    asyncio.run(scenario())
