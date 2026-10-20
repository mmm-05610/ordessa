"""Original Manager, Unit/Node records, Local process/ACP peer; no model.

Controlled authority grants exercise the real issuer and claim CAS. No
production human authority or model quality claim is made by this fixture.
"""
import pytest
from agent_tools_fixtures.manager_joint import joint
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.definitions.operations import node_holder
from ordessa_units.bindings.publication import decode_node_ref


def test_actual_manager_prepare_start_publish_stop_same_original_records(joint):
    j=joint;prepare=RequestKey('env','principal','joint-prepare')
    operation=j.services.assembly.prepare(prepare,j.profile,{}, {})
    assert operation.status=='published'
    node_ref=decode_node_ref(operation.intent.node_ref)
    node=j.services.nodes.read(node_ref);unit_ref=node['binding']['harnessUnitRef']
    unit=j.manager.find(unit_ref)
    assert unit.records is j.records and j.events.count('spawn')==1
    assert safe_json(unit.prepared_unit['unitRef'])==safe_json(unit_ref)
    assert j.records.owner_read_session(unit_ref['unitId']).state=='confirmed'
    assert j.services.assembly.prepare(prepare,j.profile,{},{}).result==operation.result
    assert j.events.count('spawn')==1
    j.current.acquired=dict(operation.intent.node_ref)
    j.current.evidence=dict(unit_ref)
    stop=RequestKey('env','principal','joint-stop')
    result=j.services.lifecycle.stop(stop,node_ref,{})
    assert j.store.read_operation_step(stop,'stop').outcome=='concluded'
    assert j.records.owner_read_termination(unit_ref['unitId'],'stop')['state']=='confirmed'
    assert j.manager.find(unit_ref) is unit
    rows=j.store.read_usages('env',node_holder('env',node_ref.instance_id,node_ref.generation))
    assert rows and all(row['state']=='active' for row in rows)
    assert j.services.lifecycle.stop(stop,node_ref,{})==result
    assert j.events.count('spawn')==1


@pytest.fixture
def managed_lifecycle(joint):
    """Real assembled Node with a live Unit; counters wrap original effects."""
    j=joint
    operation=j.services.assembly.prepare(RequestKey('env','principal','prepare'),j.profile,{}, {})
    assert operation.status=='published'
    node_ref=decode_node_ref(operation.intent.node_ref)
    node=j.services.nodes.read(node_ref);unit=j.manager.find(node['binding']['harnessUnitRef'])
    j.current.acquired=dict(operation.intent.node_ref);j.current.evidence=dict(unit.prepared_unit['unitRef'])
    unit.lifecycle_calls=[];unit.fail_lifecycle=None
    original_stop,original_release=unit.stop,unit.release
    def stop(ref,invocation):
        unit.lifecycle_calls.extend([('unit',dict(ref)),'stop'])
        close=unit.channel_factory.close
        if unit.fail_lifecycle=='stop':
            def fail(_): raise ConnectionError('controlled owned-channel close failure')
            unit.channel_factory.close=fail
        try:return original_stop(ref,invocation)
        finally:unit.channel_factory.close=close
    def release(ref,invocation):
        unit.lifecycle_calls.extend([('unit',dict(ref)),'release'])
        return original_release(ref,invocation)
    unit.stop=stop;unit.release=release
    return (j.services.lifecycle,j.services.lifecycle._observation_port,unit,node_ref,node,
            j.env,j.store,RequestKey('env','principal','stop'),node['binding']['harnessProviderRef'],j.current)


def test_release_commit_failure_retains_handle_and_reconciles_original_proof(joint):
    j=joint;prepare=RequestKey('env','principal','prepare-release-fault')
    operation=j.services.assembly.prepare(prepare,j.profile,{}, {})
    assert operation.status=='published'
    node_ref=decode_node_ref(operation.intent.node_ref);node=j.services.nodes.read(node_ref)
    unit_ref=node['binding']['harnessUnitRef'];unit=j.manager.find(unit_ref)
    j.current.acquired=dict(operation.intent.node_ref);j.current.evidence=dict(unit_ref)
    j.services.lifecycle.stop(RequestKey('env','principal','before-release'),node_ref,{})
    release=RequestKey('env','principal','release-commit-fault')
    original=j.store.record_operation_step
    def fail(key,*args,**kwargs):
        if key==release:raise RuntimeError('controlled Node COMMIT failure')
        return original(key,*args,**kwargs)
    j.store.record_operation_step=fail
    with pytest.raises(RuntimeError,match='Node COMMIT'):
        j.services.lifecycle.release(release,node_ref,{})
    j.store.record_operation_step=original
    assert j.manager.find(unit_ref) is unit
    assert j.records.owner_read_termination(unit_ref['unitId'],'release')['state']=='confirmed'
    assert j.store.read_operation_step(release,'release').outcome=='possibly-dispatched'
    assert j.local.instance.snapshot.active_uses==0
    holder=node_holder('env',node_ref.instance_id,node_ref.generation)
    assert all(row['state']=='active' for row in j.store.read_usages('env',holder))
    def forbidden(*_):raise AssertionError('original external release must never replay')
    unit.release=forbidden
    j.services.lifecycle.reconcile_release(release)
    assert j.store.read_operation_step(release,'release').outcome=='concluded'
    assert all(row['state']=='released' for row in j.store.read_usages('env',holder))
    assert j.manager.list()==()
    assert j.events.count('spawn')==1
