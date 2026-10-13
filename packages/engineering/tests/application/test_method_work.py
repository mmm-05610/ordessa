"""Actual loader/compiler/store/control/run/journal/CAS; explicit test authorities.

Tiny test method is generated in its own temp root. No 2.5 publication, actual
user answer, production Grant, native execution, or model call is claimed.
"""
import asyncio, hashlib, json
from contextlib import contextmanager
from dataclasses import asdict, replace
import pytest
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT, WAIT_EVENT, WorkSeed, WorkWaitSelection
from ordessa_engineering.application.contracts.run_waits import BoundRunWait, run_wait_row_digest
from ordessa_engineering.application.contracts.commands import ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from test_method_control_admission import TestManagement
from test_review_usecases import SyntheticAccess, _scope, _context, _create_source


@pytest.fixture
def env(tmp_path):
    lib=EngineeringLibrary.create((tmp_path/'work.sqlite').resolve(),library_id='work-fixture',schema_version=14)
    factory=SQLiteUoWFactory(lib);scope=_scope();access=SyntheticAccess();ref=_create_source(factory,scope)
    caps=command_capabilities();d=next(d for d in caps.capabilities if d.capability_id=='engineering.artifacts.create')
    root=tmp_path/'method';root.mkdir()
    workflow={'schema_version':1,'workflow_id':'tiny','entry':'seed','resume_contract':WORK_CONTRACT,
        'context_slots':['kind','initial','artifact_ref'],'wait_kinds':['owner_reconciliation'],
        'outputs':{'primary_artifact':'artifact_ref'},
        'stop_outcomes':['accepted','rejected'],'steps':[
            {'id':'seed','kind':'wait','event':WAIT_EVENT,'bind':{'artifact_ref':'event.artifact_ref'},'next':'capture'},
            {'id':'capture','kind':'operation','operation':d.capability_id,
             'inputs':{'kind':'kind','initial':'initial'},'outcomes':{'completed':{'next':'result'},'rejected':{'stop':'rejected'}}},
            {'id':'result','kind':'wait','event':WAIT_EVENT,'match':{'artifact_ref':'artifact_ref'},'next':'done'},
            {'id':'done','kind':'stop','outcome':'accepted'}]}
    raw=json.dumps(workflow).encode();(root/'workflow.yaml').write_bytes(raw)
    manifest={'schema_version':1,'method_id':'test.current-work','release_version':'1.0.0','compiler_contract':'ordessa.methods/v1',
        'entry':{'resource':'workflow'},'documents':[], 'resources':[{'id':'workflow','kind':'workflow','path':'workflow.yaml',
            'media_type':'application/yaml','sha256':hashlib.sha256(raw).hexdigest()}],
        'requires':[{k:getattr(d,k) for k in ('capability_id','kind','interface_version','contract_digest')}]}
    (root/'method.yaml').write_text(json.dumps(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,caps,'fixture/compiler');assert compiled.ok,compiled.error
    class Catalog:
        def read_current(self): return caps
    store=SQLiteSnapshotStore(lib);published=freeze_method(compiled.value,store,store,capability_catalog=Catalog())
    assert published.ok,published.error
    sref=published.value.ref;method=MethodRef(sref.method_id,sref.release_version,sref.schema_version,Digest('sha256',sref.snapshot_digest))
    controls=SQLiteMethodControl(factory,store);management=MethodUseCases(factory,access,store,TestManagement())
    management.adopt(method,_context(scope,'select-method'),expected_version=0)
    registry={'registry_id':'test-original-registry','revision':1,'registry_digest':'sha256:'+'c'*64}
    class Source:
        revoked=False
        mismatch=False
        before_condition_yield=None
        before_start_yield=None
        start_reads=ReadSet(scope,())
        @contextmanager
        def guard_start(self,context,snapshot, *, run_id, selection):
            assert type(run_id) is str and selection is None
            assert not lib._connection.in_transaction
            if self.before_start_yield is not None:
                self.before_start_yield()
            yield WorkSeed({'kind':'other','initial':{'media_type':'application/json','schema_id':'urn:test:work','inline_value':{'fixture':True}}},self.start_reads)
        @contextmanager
        def guard_condition(self,context,snapshot,node,view):
            assert not lib._connection.in_transaction
            if self.revoked: raise ApplicationError('WORK_SOURCE_REVOKED')
            condition=BoundRunWait(scope,view['run_id'],view['row_digest'],view['next_step_ordinal'],'object_exists',(ref,))
            if self.before_condition_yield is not None:
                race,self.before_condition_yield=self.before_condition_yield,None
                race(view)
            yield WorkWaitSelection(condition,{'artifact_ref':{'tampered':True} if self.mismatch else asdict(ref)})
        @contextmanager
        def guard_step_completion(self,context,snapshot,node,view):
            if self.revoked: raise ApplicationError('WORK_SOURCE_REVOKED')
            yield ReadSet(scope,())
    source=Source();bindings=MethodRunBindings(factory,controls,source,lambda:registry)
    facade=EngineeringService(factory,access,current_wait_bindings=bindings)
    try: yield locals()
    finally: lib.close()


def call(e,op,params,rid):return asyncio.run(e['facade'].execute(op,params,_context(e['scope'],rid)))
def query(e,name,params,rid='read'):return asyncio.run(e['facade'].query(name,params,_context(e['scope'],rid)))
def resume_params(state):return {'run_id':'work','expected_row_digest':state['row_digest'],'expected_condition_digest':state['condition_digest'],'expected_next_step_ordinal':state['next_step_ordinal']}


def prepare_operation_completion(e,request_id='actual-capture'):
    call(e,'engineering.work.start',{'run_id':'work'},'start')
    ready=query(e,'engineering.work.current_condition',{'run_id':'work'})
    call(e,'engineering.runs.resume',resume_params(ready),'resume-seed')
    row=query(e,'engineering.work.get',{'run_id':'work'})
    actual=call(e,'engineering.artifacts.create',
        {'kind':row['inputs']['slots']['kind'],'initial':row['inputs']['slots']['initial']},request_id)
    assert actual.status=='completed'
    current=e['lib'].run_row('work')
    return {'run_id':'work','operation_request_id':request_id,
        'expected_row_digest':asdict(run_wait_row_digest(current)),
        'expected_next_step_ordinal':0}


def adopt_workflow_variant(e, workflow, method_id):
    root=e['root'].parent/method_id;root.mkdir()
    raw=json.dumps(workflow).encode();(root/'workflow.yaml').write_bytes(raw)
    manifest=json.loads((e['root']/'method.yaml').read_text())
    manifest['method_id']=method_id
    manifest['resources'][0]['sha256']=hashlib.sha256(raw).hexdigest()
    (root/'method.yaml').write_text(json.dumps(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader());assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,e['caps'],'fixture/compiler');assert compiled.ok,compiled.error
    class Catalog:
        def read_current(self): return e['caps']
    published=freeze_method(compiled.value,e['store'],e['store'],capability_catalog=Catalog())
    assert published.ok,published.error
    sref=published.value.ref
    method=MethodRef(sref.method_id,sref.release_version,sref.schema_version,
        Digest('sha256',sref.snapshot_digest))
    e['management'].adopt(method,_context(e['scope'],method_id+'-adopt'),expected_version=1)
    return method


def test_real_wait_command_wait_chain_and_history_do_not_dispatch(env):
    e=env
    start=call(e,'engineering.work.start',{'run_id':'work'},'start');assert start.result['dispatched'] is False
    pending=query(e,'engineering.work.get',{'run_id':'work'})
    assert pending['outputs']==({'name':'primary_artifact','context_slot':'artifact_ref',
        'available':False,'reference':None},)
    ready=query(e,WAIT_EVENT,{'run_id':'work'});result=call(e,'engineering.runs.resume',resume_params(ready),'resume-seed')
    assert result.result['status']=='RUNNING' and result.result['cursor']==1
    row=query(e,'engineering.work.get',{'run_id':'work'});assert row['inputs']['slots']['artifact_ref']==asdict(e['ref'])
    assert row['outputs']==({'name':'primary_artifact','context_slot':'artifact_ref',
        'available':True,'reference':asdict(e['ref'])},)
    assert row['method_run']['method_binding']==row['inputs']['method_ref']
    # Actual owner command is independently called once by the main agent.
    actual=call(e,'engineering.artifacts.create',{'kind':row['inputs']['slots']['kind'],'initial':row['inputs']['slots']['initial']},'actual-capture')
    assert actual.status=='completed'
    step={'run_id':'work','operation_request_id':'actual-capture','expected_row_digest':asdict(run_wait_row_digest({**row,'method_ref':e['lib'].run_row('work')['method_ref']})),'expected_next_step_ordinal':0}
    # Remove query projection-only ordinal before hashing the exact original row.
    step['expected_row_digest']=asdict(run_wait_row_digest(e['lib'].run_row('work')))
    recorded=call(e,'engineering.work.record_command_step',step,'record-step');assert recorded.result['status']=='WAITING_FOR_CONDITION'
    history=query(e,'engineering.work.get',{'run_id':'work'})['method_run']['steps']
    assert len(history)==1 and history[0]['attempt']==1 and history[0]['status']=='completed'
    assert call(e,'engineering.work.record_command_step',step,'record-step')==recorded
    ready=query(e,'engineering.runs.get_wait',{'run_id':'work'});done=call(e,'engineering.runs.resume',resume_params(ready),'resume-result')
    assert done.result['status']=='SLICE_DONE' and done.result['dispatched'] is False
    e['source'].revoked=True
    assert query(e,'engineering.work.get',{'run_id':'work'})['next_step_ordinal']==1
    assert call(e,'engineering.work.start',{'run_id':'work'},'start')==start


def test_source_revoke_and_wrong_match_do_not_advance_or_leave_command(env):
    e=env;call(e,'engineering.work.start',{'run_id':'work'},'start')
    ready=query(e,'engineering.runs.get_wait',{'run_id':'work'});e['source'].revoked=True
    with pytest.raises(ApplicationError,match='WORK_SOURCE_REVOKED'):
        call(e,'engineering.runs.resume',resume_params(ready),'revoked-resume')
    e['source'].revoked=False;call(e,'engineering.runs.resume',resume_params(ready),'resume-seed')
    with pytest.raises(ApplicationError,match='WORK_COMMAND_RESULT_MISMATCH'):
        call(e,'engineering.work.record_command_step',{'run_id':'work','operation_request_id':'missing',
            'expected_row_digest':asdict(run_wait_row_digest(e['lib'].run_row('work'))),'expected_next_step_ordinal':0},'missing-step')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'missing-step').key) is None
        assert uow.workflow.next_step_ordinal('work')==0


def test_start_requires_real_selection_source_and_wrong_scope_read_refuses(env):
    e=env
    missing=EngineeringService(e['factory'],e['access'])
    with pytest.raises(ApplicationError,match='WORK_WAIT_AUTHORITY_UNAVAILABLE'):
        asyncio.run(missing.execute('engineering.work.start',{'run_id':'missing'},_context(e['scope'],'start-missing')))
    call(e,'engineering.work.start',{'run_id':'work'},'start')
    from ordessa_engineering.domain.common.models.identity import Scope
    bad=replace(_context(e['scope'],'wrong-scope'),scope=Scope(e['scope'].realm_id,'another-project'))
    with pytest.raises(ApplicationError,match='WORK_BINDING_INVALID'):
        asyncio.run(e['facade'].query('engineering.work.get',{'run_id':'work'},bad))


def test_retired_did_method_schema_is_rejected_without_creating_current_work(env):
    e=env
    legacy={'schema_version':'engineering-method/1','method_id':'legacy','revision':1,
        'description':'historical runner input','registry_ref':{},'steps':[]}
    with pytest.raises(ApplicationError,match='INVALID_INPUT'):
        call(e,'engineering.work.start',{'run_id':'legacy-run','method':legacy},'legacy-start')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'legacy-start').key) is None
        with pytest.raises(EngineeringError,match='run_not_found'):
            uow.workflow.run_row('legacy-run')


def test_historical_runner_rows_remain_readable_but_are_not_current_work(env):
    e=env
    with e['factory'].begin(e['scope']) as uow:
        old_method=uow.workflow.write_material(kind='method',stable_id='legacy-method',revision=1,
            body={'schema_version':'engineering-method/1','steps':[{'operation':'did.apply'}]},generated=False)
        uow.workflow.insert_run(run_id='legacy-history',method_ref=old_method,registry_ref={'legacy':True},
            inputs={'schema_version':'engineering-method/1','refs':{'did':'historical'}},now='2026-10-09T12:00:00Z')
        receipt=uow.workflow.create_generated(kind='step-receipt',stable_id='legacy-history-0',
            body={'schema_version':'engineering-step-receipt/1','historical':True})
        uow.workflow.insert_step_log(run_id='legacy-history',ordinal=0,step_id='apply',operation='did.apply',
            attempt=1,status='APPLIED',receipt_ref=receipt)
        uow.workflow.update_run(run_id='legacy-history',status='WAITING_FOR_ACCEPTANCE',cursor=1,
            wait_reason='WAITING_FOR_ACCEPTANCE',now='2026-10-09T12:00:01Z')
        uow.commit()
    with e['factory'].begin(e['scope'],'read') as uow:
        row_before=uow.workflow.run_row('legacy-history')
        steps_before=e['lib'].step_rows('legacy-history')
        material_before=uow.workflow.read(old_method)
        receipt_before=uow.workflow.read(receipt)
    with pytest.raises(ApplicationError,match='WORK_BINDING_INVALID'):
        query(e,'engineering.work.get',{'run_id':'legacy-history'},'legacy-read')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.workflow.run_row('legacy-history')==row_before
        assert e['lib'].step_rows('legacy-history')==steps_before
        assert uow.workflow.read(old_method)==material_before
        assert uow.workflow.read(receipt)==receipt_before


def test_competing_resume_claim_after_observation_is_rejected_without_receipt(env):
    e=env
    call(e,'engineering.work.start',{'run_id':'work'},'start')
    ready=query(e,'engineering.runs.get_wait',{'run_id':'work'})
    competitor=EngineeringLibrary.open(e['lib'].path,library_id=e['lib'].library_id)
    try:
        def claim_before_resume(_view):
            with competitor.transaction() as connection:
                connection.execute("UPDATE runs SET status='RUNNING', wait_reason=NULL WHERE run_id='work'")
        e['source'].before_condition_yield=claim_before_resume
        with pytest.raises(ApplicationError,match='RUN_WAIT_CHANGED'):
            call(e,'engineering.runs.resume',resume_params(ready),'raced-resume')
    finally:
        competitor.close()
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.workflow.run_row('work')['status']=='RUNNING'
        assert e['lib'].step_rows('work')==[]
        assert uow.workflow.next_step_ordinal('work')==0
        assert uow.commands.get(_context(e['scope'],'raced-resume').key) is None


def test_registry_capability_drift_before_record_refuses_without_work_receipt(env):
    e=env;step=prepare_operation_completion(e,'drifted-command')
    e['registry']['revision']+=1
    with pytest.raises(ApplicationError,match='METHOD_CAPABILITY_CHANGED'):
        call(e,'engineering.work.record_command_step',step,'drifted-record')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.workflow.run_row('work')['status']=='RUNNING'
        assert e['lib'].step_rows('work')==[]
        assert uow.workflow.next_step_ordinal('work')==0
        assert uow.commands.get(_context(e['scope'],'drifted-record').key) is None
        assert uow.commands.get(_context(e['scope'],'drifted-command').key).state=='completed'


def test_step_receipt_write_failure_rolls_back_record_command_and_cursor(env,monkeypatch):
    e=env;step=prepare_operation_completion(e,'receipt-command')
    original=e['lib']._create_generated
    def fail_receipt(connection,*,kind,stable_id,body):
        if kind=='step-receipt':
            raise EngineeringError('injected_work_receipt_failure')
        return original(connection,kind=kind,stable_id=stable_id,body=body)
    monkeypatch.setattr(e['lib'],'_create_generated',fail_receipt)
    with pytest.raises(EngineeringError,match='injected_work_receipt_failure'):
        call(e,'engineering.work.record_command_step',step,'receipt-record')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.workflow.run_row('work')['status']=='RUNNING'
        assert e['lib'].step_rows('work')==[]
        assert uow.workflow.next_step_ordinal('work')==0
        assert uow.commands.get(_context(e['scope'],'receipt-record').key) is None
        assert uow.commands.get(_context(e['scope'],'receipt-command').key).state=='completed'


def test_start_rechecks_source_dependency_on_original_write_transaction(env):
    from ordessa_engineering.application.contracts.commands import ReadVersion
    from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
    e=env
    with e['factory'].begin(e['scope'],'read') as uow:
        observed=uow.engineering.get_artifact(e['ref'].artifact_id)
    e['source'].start_reads=ReadSet(e['scope'],(ReadVersion('artifact',observed.artifact_id,observed.version),))
    competitor=EngineeringLibrary.open(e['lib'].path,library_id=e['lib'].library_id)
    try:
        def advance_original_dependency():
            result=ArtifactUseCases(SQLiteUoWFactory(competitor),e['access']).append_revision({
                'artifact_id':observed.artifact_id,'expected_version':observed.version,
                'parents':[asdict(e['ref'])],'payload':{
                    'media_type':'application/json','schema_id':'urn:test:source',
                    'inline_value':{'source':'changed-after-observation'}}},_context(e['scope'],'competing-source'))
            assert result.status=='completed'
        e['source'].before_start_yield=advance_original_dependency
        with pytest.raises(ApplicationError,match='READ_SET_CHANGED'):
            call(e,'engineering.work.start',{'run_id':'stale-start'},'stale-start-command')
    finally:
        competitor.close()
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.engineering.get_artifact(observed.artifact_id).version==observed.version+1
        assert uow.commands.get(_context(e['scope'],'stale-start-command').key) is None
        with pytest.raises(EngineeringError,match='run_not_found'):
            uow.workflow.run_row('stale-start')
    assert e['lib'].head('method','compiled-work:stale-start') is None


def test_start_registry_drift_refuses_before_work_writes(env):
    e=env;calls=[]
    def drifting_registry():
        calls.append(True)
        return {**e['registry'],'revision':len(calls)}
    e['bindings'].registry_loader=drifting_registry
    with pytest.raises(ApplicationError,match='METHOD_CAPABILITY_CHANGED'):
        call(e,'engineering.work.start',{'run_id':'registry-start'},'registry-start-command')
    assert len(calls)==2
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'registry-start-command').key) is None
        with pytest.raises(EngineeringError,match='run_not_found'):
            uow.workflow.run_row('registry-start')
    assert e['lib'].head('method','compiled-work:registry-start') is None


def test_start_owner_read_set_scope_is_required(env):
    from ordessa_engineering.domain.common.models.identity import Scope
    e=env;e['source'].start_reads=ReadSet(Scope('foreign','foreign'),())
    with pytest.raises(ApplicationError,match='WORK_INPUT_INVALID'):
        call(e,'engineering.work.start',{'run_id':'foreign-seed'},'foreign-seed-command')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'foreign-seed-command').key) is None


def test_counted_loop_restarts_from_persisted_rounds_and_rejects_reused_command(env):
    e=env
    workflow={'schema_version':1,'workflow_id':'bounded-loop','entry':'seed','resume_contract':WORK_CONTRACT,
        'context_slots':['kind','initial','artifact_ref'],'wait_kinds':['owner_reconciliation'],
        'stop_outcomes':['rejected'],'outputs':{'primary_artifact':'artifact_ref'},
        'steps':[
            {'id':'seed','kind':'wait','event':WAIT_EVENT,'bind':{'artifact_ref':'event.artifact_ref'},'next':'capture'},
            {'id':'capture','kind':'operation','operation':'engineering.artifacts.create',
             'inputs':{'kind':'kind','initial':'initial'},
             'outcomes':{'completed':{'stop':'rejected'},'rejected':{'stop':'rejected'}},
             'result_routing':{'path':'/revision_ref/project_id','outcomes':{'project-1':{'next':'capture'}}}},
        ],
        'loops':[{'loop_id':'again','from_step':'capture','to_step':'capture','max_rounds':2,'on_exhausted':'rejected'}]}
    adopt_workflow_variant(e,workflow,'test.current-work-loop')
    call(e,'engineering.work.start',{'run_id':'loop-run'},'loop-start')
    ready=query(e,WAIT_EVENT,{'run_id':'loop-run'})
    call(e,'engineering.runs.resume',{'run_id':'loop-run','expected_row_digest':ready['row_digest'],
        'expected_condition_digest':ready['condition_digest'],'expected_next_step_ordinal':ready['next_step_ordinal']},'loop-resume')
    row=query(e,'engineering.work.get',{'run_id':'loop-run'})
    parameters={'kind':row['inputs']['slots']['kind'],'initial':row['inputs']['slots']['initial']}
    first=call(e,'engineering.artifacts.create',parameters,'loop-command-1');assert first.status=='completed'
    state=e['lib'].run_row('loop-run')
    call(e,'engineering.work.record_command_step',{'run_id':'loop-run','operation_request_id':'loop-command-1',
        'expected_row_digest':asdict(run_wait_row_digest(state)),'expected_next_step_ordinal':0},'loop-record-1')
    state=e['lib'].run_row('loop-run')
    assert state['inputs']['rounds']=={'again':2} and state['cursor']==1 and state['status']=='RUNNING'
    with pytest.raises(ApplicationError,match='WORK_COMMAND_ALREADY_CONSUMED'):
        call(e,'engineering.work.record_command_step',{'run_id':'loop-run','operation_request_id':'loop-command-1',
            'expected_row_digest':asdict(run_wait_row_digest(state)),'expected_next_step_ordinal':1},'loop-record-reuse')
    # Recreate the service object to model process recovery; the original rows
    # and counter alone determine the next allowed transition.
    e['facade']=EngineeringService(e['factory'],e['access'],current_wait_bindings=e['bindings'])
    second=call(e,'engineering.artifacts.create',parameters,'loop-command-2');assert second.status=='completed'
    state=e['lib'].run_row('loop-run')
    finished=call(e,'engineering.work.record_command_step',{'run_id':'loop-run','operation_request_id':'loop-command-2',
        'expected_row_digest':asdict(run_wait_row_digest(state)),'expected_next_step_ordinal':1},'loop-record-2')
    assert finished.result['status']=='SLICE_DONE'
    steps=query(e,'engineering.work.get',{'run_id':'loop-run'})['steps']
    assert [(step['attempt'],step['status']) for step in steps]==[(1,'completed'),(2,'completed')]
    assert e['lib'].run_row('loop-run')['inputs']['rounds']=={'again':2}
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.workflow.read(uow.workflow.step_rows('loop-run')[-1]['receipt_ref'])['stop_outcome']=='rejected'


def test_unmapped_completed_result_refuses_step_advance(env):
    e=env
    workflow={'schema_version':1,'workflow_id':'unmapped-result','entry':'seed','resume_contract':WORK_CONTRACT,
        'context_slots':['kind','initial','artifact_ref'],'wait_kinds':['owner_reconciliation'],
        'stop_outcomes':['rejected'],'steps':[
            {'id':'seed','kind':'wait','event':WAIT_EVENT,'bind':{'artifact_ref':'event.artifact_ref'},'next':'capture'},
            {'id':'capture','kind':'operation','operation':'engineering.artifacts.create',
             'inputs':{'kind':'kind','initial':'initial'},
             'outcomes':{'completed':{'stop':'rejected'},'rejected':{'stop':'rejected'}},
             'result_routing':{'path':'/revision_ref/project_id','outcomes':{'other-project':{'stop':'rejected'}}}},
        ]}
    adopt_workflow_variant(e,workflow,'test.current-work-unmapped')
    call(e,'engineering.work.start',{'run_id':'unmapped-run'},'unmapped-start')
    ready=query(e,WAIT_EVENT,{'run_id':'unmapped-run'})
    call(e,'engineering.runs.resume',{'run_id':'unmapped-run','expected_row_digest':ready['row_digest'],
        'expected_condition_digest':ready['condition_digest'],'expected_next_step_ordinal':ready['next_step_ordinal']},'unmapped-resume')
    row=query(e,'engineering.work.get',{'run_id':'unmapped-run'})
    actual=call(e,'engineering.artifacts.create',{'kind':row['inputs']['slots']['kind'],
        'initial':row['inputs']['slots']['initial']},'unmapped-command')
    assert actual.status=='completed'
    state=e['lib'].run_row('unmapped-run')
    with pytest.raises(ApplicationError,match='WORK_RESULT_UNMAPPED'):
        call(e,'engineering.work.record_command_step',{'run_id':'unmapped-run',
            'operation_request_id':'unmapped-command','expected_row_digest':asdict(run_wait_row_digest(state)),
            'expected_next_step_ordinal':0},'unmapped-record')
    assert e['lib'].step_rows('unmapped-run')==[]
    assert e['lib'].run_row('unmapped-run')['status']=='RUNNING'
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'unmapped-record').key) is None
