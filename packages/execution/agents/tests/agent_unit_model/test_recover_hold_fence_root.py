"""Root independent original Usage/claim recovery ordering counterexamples."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from agent_tools_fixtures.lifecycle import lifecycle
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import UnknownResultError, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import node_holder

@pytest.mark.parametrize('claimed_action', ['stop', 'release'])
def test_live_cleanup_claim_refuses_recover_before_provider(lifecycle, claimed_action):
    coordinator, owner, provider, node_ref, node, env, store, first, pin, current = lifecycle
    entered, proceed = Event(), Event()
    original = getattr(provider, claimed_action)
    def delayed(argument, invocation):
        entered.set()
        assert proceed.wait(10)
        return original(argument, invocation)
    setattr(provider, claimed_action, delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(getattr(coordinator, claimed_action), first, node_ref, {})
        try:
            ready = entered.wait(10)
            if not ready and future.done(): future.result(timeout=1)
            assert ready
            recovery = RequestKey('env', 'principal', 'recover-during-'+claimed_action)
            with pytest.raises(UnknownResultError, match='unresolved effect claim'):
                coordinator.recover(recovery, node_ref, {})
            assert store.read_operation_step(recovery, 'recover') is None
            assert provider.lifecycle_calls == []
            rows = store.read_usages('env', node_holder('env',node_ref.instance_id,node_ref.generation))
            assert rows and all(row['state']=='active' for row in rows)
        finally: proceed.set()
        future.result(timeout=10)
    assert store.read_operation_step(first, claimed_action).outcome=='concluded'
    assert provider.lifecycle_calls.count('recover')==0

@pytest.mark.parametrize('later_action', ['stop','release'])
def test_live_recover_claim_refuses_cleanup_before_provider(lifecycle,later_action):
    coordinator, owner, provider, node_ref, node, env, store, first, pin, current = lifecycle
    entered, proceed = Event(),Event(); original=provider.recover
    def delayed(argument,invocation):
        entered.set(); assert proceed.wait(10)
        return original(argument,invocation)
    provider.recover=delayed
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(coordinator.recover,first,node_ref,{})
        try:
            ready=entered.wait(10)
            if not ready and future.done(): future.result(timeout=1)
            assert ready
            later=RequestKey('env','principal',later_action+'-during-recover')
            with pytest.raises(UnknownResultError,match='unresolved effect claim'):
                getattr(coordinator,later_action)(later,node_ref,{})
            assert store.read_operation_step(later,later_action) is None
            assert provider.lifecycle_calls==[]
            rows=store.read_usages('env',node_holder('env',node_ref.instance_id,node_ref.generation))
            assert rows and all(row['state']=='active' for row in rows)
        finally: proceed.set()
        future.result(timeout=10)
    assert store.read_operation_step(first,'recover').outcome=='concluded'
    assert provider.lifecycle_calls.count(later_action)==0

def test_released_original_usages_refuse_new_recover_without_effect(lifecycle):
    coordinator,owner,provider,node_ref,node,env,store,request,pin,current=lifecycle
    release=RequestKey('env','principal','release-before-recover')
    coordinator.release(release,node_ref,{})
    assert store.read_operation_step(release,'release').outcome=='concluded'
    rows=store.read_usages('env',node_holder('env',node_ref.instance_id,node_ref.generation))
    assert rows and all(row['state']=='released' for row in rows)
    before=list(provider.lifecycle_calls)
    with pytest.raises(GuaranteeUnavailableError):
        coordinator.recover(request,node_ref,{})
    assert provider.lifecycle_calls==before
    assert store.read_operation_step(request,'recover') is None


@pytest.mark.parametrize('target_kind', ['provider', 'unit'])
def test_recover_requires_use_rights_on_original_held_targets(lifecycle,target_kind):
    import json
    coordinator,owner,provider,node_ref,node,env,store,request,pin,current=lifecycle
    rows=store.read_usages('env',node_holder('env',node_ref.instance_id,node_ref.generation))
    target=next(row for row in rows if ('ownerProviderRef' in row['targetRef']) == (target_kind=='unit'))
    store._conn.execute('UPDATE env_usages SET rights=? WHERE usage_id=?',(json.dumps(['read']),target['usageId']))
    store._conn.commit()
    with pytest.raises(GuaranteeUnavailableError):
        coordinator.recover(request,node_ref,{})
    assert store.read_operation_step(request,'recover') is None
    assert provider.lifecycle_calls==[]


@pytest.mark.parametrize('action', ['stop','release','recover'])
@pytest.mark.parametrize('target_kind', ['provider','unit'])
def test_malformed_held_rights_refuse_before_operation_reservation(lifecycle,action,target_kind):
    import json
    coordinator,owner,provider,node_ref,node,env,store,request,pin,current=lifecycle
    rows=store.read_usages('env',node_holder('env',node_ref.instance_id,node_ref.generation))
    target=next(row for row in rows if ('ownerProviderRef' in row['targetRef']) == (target_kind=='unit'))
    store._conn.execute('UPDATE env_usages SET rights=? WHERE usage_id=?',(json.dumps(['use',7]),target['usageId']))
    store._conn.commit()
    assert store.read_operation(request) is None
    with pytest.raises(GuaranteeUnavailableError):
        getattr(coordinator,action)(request,node_ref,{})
    assert store.read_operation(request) is None
    assert store.read_operation_step(request,action) is None
    assert provider.lifecycle_calls==[]
