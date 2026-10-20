"""Server refusal plus the original selected Unit/SDK effect cut; zero model.

Package/Grant/graph admission remains the original explicitly synthetic owner
fixture. These tests prove consumer wiring and physical revoke-before-write,
not human authorization, checkout baseline or implementation acceptance.
"""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sys,runpy
import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_server.composition.engineering_dispatch import FixedDispatchEffectAuthority
from ordessa_system_access_bindings.engineering_dispatch import EngineeringDispatchRoutes
from test_engineering_dispatch_consumer import FixtureAccess

ROOT=Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('revoked',[False,True])
def test_real_manager_product_execution_keeps_original_sdk_effect_cut(tmp_path,monkeypatch,revoked):
    sys.path.insert(0,str(ROOT/'packages/engineering/tests/application'))
    sys.path.insert(0,str(ROOT/'packages/execution/agents/tests/support'))
    from agent_tools_fixtures import manager_joint
    import ordessa_engineering.adapters.native_records.recorded_dispatch as original
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    native=original.RecordedDispatchExecution;factory=original.engineering_effect_write_guard_factory
    owner_builder=manager_joint.build_joint_owner;holder={};proof={}
    @contextmanager
    def capture_owner(*args,**kwargs):
        with owner_builder(*args,**kwargs) as j:
            holder['j']=j
            yield j
    def capture_factory(owner,context,records,blobs):
        holder.update(owner=owner,context=context)
        return factory(owner,context,records,blobs)
    def consumer(records,unit,lease,blobs,query_factory=None,*,effect_write_guard_factory=None):
        j=holder['j'];assert type(j.manager.records) is type(records) and j.manager.records is records
        ref=unit.prepared_unit['unitRef']
        # The Server's old route no longer resolves or creates a native sender.
        # Verify that refusal separately, then use the public original adapter
        # with the exact selected Unit/Records/lease and trusted effect guard.
        route=EngineeringDispatchRoutes(holder['owner'].factory,FixtureAccess(),
            manager=j.manager,blobs=blobs)
        with pytest.raises(ApplicationError,match='OPERATION_UNAVAILABLE'):
            route.invoke('engineering.implementation.dispatch',{
                'run_id':'r','step_id':'s','attempt':1,'unit_ref':ref,
                'params':{'prompt':[]},'actions':['edit_repository']},
                holder['context'])
        unguarded=native(records,unit,lease,blobs)
        with pytest.raises(ApplicationError,match='RECORDED_DISPATCH_EFFECT_AUTHORITY_REQUIRED'):
            unguarded.freeze_input(ref,{'prompt':[]})
        port=native(records,unit,lease,blobs,
            effect_write_guard_factory=effect_write_guard_factory)
        assert type(port) is native and port.unit_instance is unit and port.records is records
        proof['used']=True
        return port
    monkeypatch.setattr(manager_joint,'build_joint_owner',capture_owner)
    monkeypatch.setattr(original,'engineering_effect_write_guard_factory',capture_factory)
    monkeypatch.setattr(original,'RecordedDispatchExecution',consumer)
    test=runpy.run_path(str(ROOT/'packages/engineering/tests/application/test_dispatch_effect_cut.py'))
    test['test_actual_unit_sdk_factory_and_original_approval_control_cut'](tmp_path,monkeypatch,revoked)
    assert proof['used']


def test_fixed_effect_factory_cannot_cross_original_command_context(tmp_path,monkeypatch):
    sys.path.insert(0,str(ROOT/'packages/engineering/tests/application'))
    test=runpy.run_path(str(ROOT/'packages/engineering/tests/application/test_dispatch_effect_cut.py'))
    lib,factory,owner,grant,package,binding,params,context=test['prepared'](tmp_path,monkeypatch)
    try:
        configured=FixedDispatchEffectAuthority(owner,context,object(),owner.blobs)
        assert configured.resolve(context,{}) is configured.factory
        with pytest.raises(ApplicationError,match='DISPATCH_EFFECT_CONTEXT_MISMATCH'):
            configured.resolve(replace(context),{})
        with pytest.raises(ApplicationError,match='DISPATCH_EFFECT_CONTEXT_MISMATCH'):
            configured.resolve(replace(context,request_id='other-request'),{})
    finally:lib.close()
