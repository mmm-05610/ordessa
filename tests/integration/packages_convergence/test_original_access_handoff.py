"""Original authority lock/admission handoff only; no business Grant claim.

Synthetic in-memory bearer token provider; no credential, network or model IO.
"""
import asyncio,time,threading,contextvars
from dataclasses import replace
import pytest
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant,AccessError
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess
from ordessa_engineering.application.contracts.errors import ApplicationError

OP='engineering.executions.dispatch'
SCOPE=Scope('realm','project');KEY=b'a'*32;ACTIONS=(('edit_repository','original-action'),)


def setup():
    authority=InstanceAccessAuthority(lambda:'synthetic-local-fixture-token',principal_id='f2-test-instance',
        grants=(AccessGrant(SCOPE,(OP,)),),legacy_principal=None)
    caller=authority.authenticate('Bearer synthetic-local-fixture-token')
    return authority,caller,EngineeringCommandAccess(authority)


async def other_thread(call):
    """Bound real management thread, without a default-executor shutdown wait."""
    finished=threading.Event();result=[];errors=[]
    def run():
        try:result.append(call())
        except BaseException as exc:errors.append(exc)
        finally:finished.set()
    worker=threading.Thread(target=run,daemon=True);worker.start()
    deadline=time.monotonic()+1
    while not finished.is_set() and time.monotonic()<deadline:await asyncio.sleep(.002)
    assert finished.is_set(),'original authority lock remained held across response wait'
    worker.join(.1)
    assert not worker.is_alive()
    if errors:raise errors[0]
    return result[0]


def test_original_single_use_handoff_restores_same_admission_and_releases_lock_across_wait():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,OP,request_id='request',trace_id='trace') as context:
            access.require(context,OP)
            with access.handoff_effect_write(context,invocation_key=KEY,action_instances=ACTIONS,
                    target_thread=threading.current_thread(),expires_at=time.monotonic()+3) as handoff:
                with pytest.raises(ApplicationError):access.require(context,OP)
                with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                    access.require(context,OP)
                    inside=contextvars.copy_context()
                    with pytest.raises(AccessError,match='AUTHORIZATION_GUARD_ACTIVE'):authority.revoke()
                with pytest.raises(ApplicationError):inside.run(access.require,context,OP)
                # If the original authority lock leaked through the response
                # wait, this real other-thread verification would time out.
                await other_thread(lambda:authority.verify(caller))
                with pytest.raises(ApplicationError):
                    with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                        raise AssertionError('second cut admitted')
            access.require(context,OP)
        with pytest.raises(ApplicationError):access.require(context,OP)
        assert authority._guard_depth==0 and authority._guard_bindings==[]
    asyncio.run(scenario())


def test_revoke_during_response_wait_refuses_original_admission_resume_and_cleans_original_guard():
    async def scenario():
        authority,caller,access=setup()
        error=None
        try:
            with access.admit(caller,SCOPE,OP,request_id='request',trace_id='trace') as context:
                with access.handoff_effect_write(context,invocation_key=KEY,action_instances=ACTIONS,
                        target_thread=threading.current_thread(),expires_at=time.monotonic()+3):
                    await other_thread(authority.revoke)
        except AccessError as exc:error=exc.code
        assert error=='AUTHORIZATION_STALE'
        assert authority._guard_depth==0 and authority._guard_bindings==[]
        with pytest.raises(ApplicationError):access.require(context,OP)
    asyncio.run(scenario())


def test_copied_task_thread_context_and_changed_binding_cannot_consume_original_handoff():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,OP,request_id='request',trace_id='trace') as context:
            with access.handoff_effect_write(context,invocation_key=KEY,action_instances=ACTIONS,
                    target_thread=threading.current_thread(),expires_at=time.monotonic()+3) as handoff:
                async def foreign_task():
                    with pytest.raises(ApplicationError):
                        with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                            raise AssertionError('copied task admitted')
                await asyncio.create_task(foreign_task())
                copied=contextvars.copy_context();errors=[]
                def foreign_thread():
                    try:
                        with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                            errors.append('admitted')
                    except ApplicationError:errors.append('refused')
                worker=threading.Thread(target=lambda:copied.run(foreign_thread));worker.start();worker.join(1)
                assert not worker.is_alive() and errors==['refused']
                for key,actions in ((b'b'*32,ACTIONS),(KEY,(('edit_repository','foreign-action'),))):
                    with pytest.raises(ApplicationError):
                        with access.consume_effect_write(handoff,context,invocation_key=key,action_instances=actions):
                            raise AssertionError('changed binding admitted')
                with pytest.raises(ApplicationError):
                    with access.consume_effect_write(replace(handoff),context,invocation_key=KEY,action_instances=ACTIONS):
                        raise AssertionError('constructed token copy admitted')
                with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                    access.require(context,OP)
            with pytest.raises(ApplicationError):
                with access.consume_effect_write(handoff,context,invocation_key=KEY,action_instances=ACTIONS):
                    raise AssertionError('expired flow admitted')
        assert authority._guard_depth==0 and authority._guard_bindings==[]
    asyncio.run(scenario())


def test_nested_original_guard_cannot_be_suspended_and_original_admission_survives_refusal():
    async def scenario():
        authority,caller,access=setup()
        with access.admit(caller,SCOPE,OP,request_id='request',trace_id='trace') as context:
            with authority.guard(caller,SCOPE,OP):
                with pytest.raises(AccessError,match='AUTHORIZATION_GUARD_INVALID'):
                    with access.handoff_effect_write(context,invocation_key=KEY,action_instances=ACTIONS,
                            target_thread=threading.current_thread(),expires_at=time.monotonic()+3):
                        raise AssertionError('nested guard released')
            access.require(context,OP)
        assert authority._guard_depth==0 and authority._guard_bindings==[]
    asyncio.run(scenario())


def test_other_task_reentrant_guard_is_never_substituted_for_original_resume():
    async def scenario():
        authority,caller,access=setup();entered=asyncio.Event();release=asyncio.Event();task=None
        async def other_guard():
            with authority.guard(caller,SCOPE,OP):
                entered.set();await release.wait()
        error=None
        try:
            with access.admit(caller,SCOPE,OP,request_id='request',trace_id='trace') as context:
                with access.handoff_effect_write(context,invocation_key=KEY,action_instances=ACTIONS,
                        target_thread=threading.current_thread(),expires_at=time.monotonic()+3):
                    task=asyncio.create_task(other_guard());await asyncio.wait_for(entered.wait(),1)
        except AccessError as exc:error=exc.code
        finally:
            release.set()
            if task is not None:await task
        assert error=='AUTHORIZATION_BUSY'
        assert authority._guard_depth==0 and authority._guard_bindings==[]
        with pytest.raises(ApplicationError):access.require(context,OP)
    asyncio.run(scenario())
