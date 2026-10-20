"""Versioned Agent handoff on the original complete Work admission owner.

Real in-memory InstanceAccessAuthority; no business approval, provider or model
claim. The original Unit contract keeps its separate-Thread requirements.
"""
import asyncio, threading, time, contextvars
from dataclasses import replace
import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant,AccessError
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from test_original_access_handoff import other_thread

OP='engineering.executions.dispatch';WORK='engineering.work.invoke'
SCOPE=Scope('full-agent-test','scoped-work');KEY=b'v'*32;ACTIONS=(('run_checks','original-instance'),)
CONTRACT='engineering.agent-effect-write/1'


def setup():
    authority=InstanceAccessAuthority(lambda:'controlled-full-agent-token',principal_id='original-agent-service',
        grants=(AccessGrant(SCOPE,(OP,WORK)),),legacy_principal=None)
    caller=authority.authenticate('Bearer controlled-full-agent-token')
    return authority,caller,EngineeringCommandAccess(authority)


def handoff(access,ctx,**changes):
    values=dict(invocation_key=KEY,action_instances=ACTIONS,target_thread=threading.current_thread(),
                expires_at=time.monotonic()+3,contract=CONTRACT)
    values.update(changes)
    return access.handoff_effect_write(ctx,**values)


def test_same_task_cut_is_single_use_nonexportable_and_releases_original_lock_before_wait():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,OP,request_id='actual-context',trace_id='agent') as ctx:
            with handoff(access,ctx) as token:
                with pytest.raises(ApplicationError):access.require(ctx,OP)
                await other_thread(lambda:authority.verify(caller))
                copied=replace(token)
                with pytest.raises(ApplicationError):
                    with access.consume_effect_write(copied,ctx,invocation_key=KEY,action_instances=ACTIONS):
                        pytest.fail('copied data became a handoff')
                async def stolen():
                    with pytest.raises(ApplicationError):
                        with access.consume_effect_write(token,ctx,invocation_key=KEY,action_instances=ACTIONS):
                            pytest.fail('other Task consumed the original token')
                await asyncio.create_task(stolen())
                with access.consume_effect_write(token,ctx,invocation_key=KEY,action_instances=ACTIONS):
                    access.require(ctx,OP)
                    inside=contextvars.copy_context()
                    with pytest.raises(AccessError,match='AUTHORIZATION_GUARD_ACTIVE'):authority.revoke()
                    # One scheduling turn only tests a captured active context;
                    # production synchronous native writes contain no await.
                    async def copied_cut():
                        with pytest.raises(ApplicationError):access.require(ctx,OP)
                    await asyncio.create_task(copied_cut())
                with pytest.raises(ApplicationError):inside.run(access.require,ctx,OP)
                with pytest.raises(ApplicationError):
                    with access.consume_effect_write(token,ctx,invocation_key=KEY,action_instances=ACTIONS):
                        pytest.fail('second write consumed the same token')
                await other_thread(lambda:authority.verify(caller))
            access.require(ctx,OP)
        assert authority._guard_depth==0 and not access._handoffs
    asyncio.run(scenario())


def test_copied_admission_task_cannot_produce_agent_handoff_and_original_unit_target_rule_remains():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,OP,request_id='origin',trace_id='origin') as ctx:
            async def stolen():
                with pytest.raises(ApplicationError,match='EFFECT_HANDOFF_TARGET_INVALID'):
                    with handoff(access,ctx):pytest.fail('other Task produced a token')
            await asyncio.create_task(stolen())
            with pytest.raises(ApplicationError,match='EFFECT_HANDOFF_TARGET_INVALID'):
                with handoff(access,ctx,contract=None):pytest.fail('Unit admitted same-thread target')
            with pytest.raises(ApplicationError,match='EFFECT_HANDOFF_CONTRACT_INVALID'):
                with handoff(access,ctx,contract='other/version'):pytest.fail('unknown contract admitted')
            access.require(ctx,OP)
    asyncio.run(scenario())


def test_revocation_before_original_agent_cut_refuses_and_does_not_restore_admission():
    async def scenario():
        authority,caller,access=setup();writes=[]
        with access.admit(caller,SCOPE,OP,request_id='revoked',trace_id='revoked') as ctx:
            with pytest.raises(ApplicationError,match='ACCESS_DENIED'):
                with handoff(access,ctx) as token:
                    await other_thread(authority.revoke)
                    with pytest.raises(ApplicationError,match='ACCESS_DENIED'):
                        with access.consume_effect_write(token,ctx,invocation_key=KEY,action_instances=ACTIONS):
                            writes.append('forbidden')
            with pytest.raises(ApplicationError):access.require(ctx,OP)
        assert writes==[] and not access._handoffs and authority._guard_depth==0
    asyncio.run(scenario())


def test_original_work_child_admission_and_parent_resume_keep_the_same_agent_guard():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,WORK,request_id='work-parent',trace_id='work') as parent:
            assert access.check_work_capability(parent,OP) is True
            with access.admit_work_step(parent,OP,request_id='derived-step') as child:
                with handoff(access,child) as token:
                    await other_thread(lambda:authority.verify(caller))
                    with access.consume_effect_write(token,child,invocation_key=KEY,action_instances=ACTIONS):
                        access.require(child,OP)
                        with pytest.raises(ApplicationError):access.require(parent,WORK)
                access.require(child,OP)
            access.require(parent,WORK)
        assert not access._handoffs and authority._guard_depth==0
    asyncio.run(scenario())
