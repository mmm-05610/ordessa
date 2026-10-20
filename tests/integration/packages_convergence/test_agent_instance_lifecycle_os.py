"""Actual Profile/start/Agent control -> original app/env/local OS lifecycle.

Explicit fixture authority grants lifecycle actions independently of bootstrap;
no production grants or default product authentication are asserted here.
"""
import asyncio
import json
import sqlite3
import threading

import pytest

from ordessa_execution_agents.instances.contracts import InstanceControl
from ordessa_execution_agents.sdk.manager import ManagerRefused
from test_agent_guarded_bootstrap import setup


@pytest.mark.parametrize('action',['stop','detach'])
def test_actual_instance_lifecycle_has_durable_cut_and_separate_os_observation(tmp_path,monkeypatch,action):
    async def scenario():
        case=await setup(tmp_path)
        actions=set();checks=[];effects=[];task=asyncio.current_task();thread=threading.get_ident()
        started=None
        def authorize(invocation,value,*,action):
            case.authority.principal_scope(invocation)
            control=InstanceControl.decode(value)
            if action not in actions:raise ManagerRefused('LIFECYCLE_NOT_AUTHORIZED')
            assert started is not None
            assert (control.namespace,control.instance_id,control.binding_digest)==(
                started.instance_ref.namespace,started.instance_ref.instance_id,started.instance_ref.binding_digest)
            assert control.endpoint_ref==started.process_endpoint_ref
            checks.append(action)
        case.authority.check_instance_lifecycle=authorize
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            ref=started.instance_ref;before=case.records.instance_control(ref)
            # Existing start/send/observe authority does not grant lifecycle.
            with pytest.raises(ManagerRefused,match='LIFECYCLE_NOT_AUTHORIZED'):
                if action=='stop':await case.manager.stop('denied',ref,case.fixture.invocation)
                else:await case.manager.detach('denied',ref,case.fixture.invocation)
            assert case.records.instance_control(ref)==before
            actions.add(action)
            raw=next(iter(case.fixture._manager._owned_process_handles.values()))._target
            def physical():
                assert asyncio.current_task() is task and threading.get_ident()==thread
                assert checks==[action,action]
                assert not case.records._db.in_transaction
                # Another connection sees the ORIGINAL durable possibly-written
                # row before the actual signal/association mutation.
                with sqlite3.connect(case.records.path) as db:
                    rows=db.execute('SELECT status FROM operations WHERE operation=?',(action,)).fetchall()
                assert rows==[('possibly-written',)]
                effects.append(action)
            if action=='stop':
                original=raw.popen.terminate
                def terminate():physical();return original()
                monkeypatch.setattr(raw.popen,'terminate',terminate)
                observation=await case.manager.stop('effect',ref,case.fixture.invocation)
                assert observation.status=='completed' and observation.facts['cancellation']=='requested'
                assert observation.facts.get('exitClaimed') is not True
                assert not case.records._db.in_transaction
                assert (await case.fixture.wait_exit(started.process_endpoint_ref)).state=='exited'
                again=await case.manager.stop('effect',ref,case.fixture.invocation)
            else:
                original=type(raw).release
                def release(handle):physical();return original(handle)
                monkeypatch.setattr(type(raw),'release',release)
                observation=await case.manager.detach('effect',ref,case.fixture.invocation)
                assert observation.status=='completed' and observation.facts['associationDetached'] is True
                assert observation.facts['exitClaimed'] is False and raw.observe().state=='running'
                again=await case.manager.detach('effect',ref,case.fixture.invocation)
            assert again==observation and effects==[action] and checks==[action,action]
            assert observation.operation_ref.startswith('environment-operation/')
            private=case.records._db.execute('SELECT operation_ref FROM operations WHERE operation=?',(action,)).fetchone()[0]
            assert private!=observation.operation_ref
            assert case.fixture.retained_use_count==1
            if action=='stop':
                assert case.records.instance_control(ref)[0].active_action=='stop'
                before=case.records.instance_control(ref)
                case.fixture.denied.add('observe')
                with pytest.raises(Exception):
                    await case.manager.reconcile(ref,case.fixture.invocation)
                assert case.records.instance_control(ref)==before
                case.fixture.denied.remove('observe')
                observed=await case.manager.reconcile(ref,case.fixture.invocation,
                    deadline=asyncio.get_running_loop().time()+2)
                assert observed.state=='exited'
                current,_=case.records.instance_control(ref)
                assert current.association=='stopped' and current.active_operation_ref is None
                actions.add('detach')
                detached=await case.manager.detach('after-observe',ref,case.fixture.invocation)
                assert detached.facts['associationDetached'] is True and detached.facts['exitClaimed'] is False
                assert case.fixture.retained_use_count==1 and effects==['stop']
        finally:
            monkeypatch.undo()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
