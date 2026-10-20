"""Loader/compiler/store/control/run/journal/CAS fixtures for read-only
coverage of the historical compiled line.

The compiled-lifecycle tests that used to live in this module were retired
with the withdrawn create/advance routes; they are named in RETIRED_TESTS
below so the coverage gap stays visible instead of looking like a passing
suite. Read coverage keeps its subject through seed_historical_run, which
seeds the same persisted row at the storage layer.
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
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings, MethodRunOrchestrator
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
HISTORICAL_NOW='2026-10-14T12:00:00.000000Z'
DEFAULT_SLOTS={'kind':'other','initial':{'media_type':'application/json','schema_id':'urn:test:work','inline_value':{'fixture':True}}}
def seed_historical_run(e,run_id,*,slots=None,cursor=None,status='WAITING_FOR_CONDITION',
                        rounds=None):
    """Seed one historical compiled row directly in the original store.

    Reading is the only surviving capability of the compiled line, so coverage of
    the consumers that read compiled rows seeds the same persisted row the
    withdrawn route used to produce, at the storage layer: no Service route, no
    retired owner write method and no source guard is exercised. A historical
    fixture seed, never a product path.
    """
    from ordessa_engineering.methods.compilation.encoding import program_plan_digest
    from ordessa_engineering.application.contracts.operation_registry import registry_ref
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.values import Digest
    program=e['compiled'].value.program
    entry=[(i,n) for i,n in enumerate(program.workflow.steps) if n.id==program.workflow.entry]
    assert len(entry)==1
    entry_cursor,node=entry[0]
    published=e['sref']
    method=MethodRef(published.method_id,published.release_version,published.schema_version,
                     Digest('sha256',published.snapshot_digest))
    marker={'work_contract':WORK_CONTRACT,'scope':asdict(e['scope']),'method_ref':asdict(method),
            'compiled_plan_digest':program_plan_digest(program)}
    inputs={**marker,'slots':DEFAULT_SLOTS if slots is None else slots}
    if program.workflow.loops:
        inputs['rounds']={loop.loop_id:1 for loop in program.workflow.loops} if rounds is None else rounds
    registry=registry_ref(e['registry'])
    final_cursor=entry_cursor if cursor is None else cursor
    wait_reason=node.id if status=='WAITING_FOR_CONDITION' else None
    with e['factory'].begin(e['scope']) as uow:
        material=uow.workflow.write_material(kind='method',stable_id='compiled-work:'+run_id,
            revision=1,body=marker,generated=False)
        uow.workflow.insert_run(run_id=run_id,method_ref=material,registry_ref=registry,
            inputs=inputs,now=HISTORICAL_NOW)
        uow.workflow.update_run(run_id=run_id,status=status,cursor=final_cursor,
            wait_reason=wait_reason,now=HISTORICAL_NOW)
        uow.commit()
    return run_id
def resume_historical_run(e,run_id):
    """Seed the persisted state a claimed wait left behind; never a route call.

    The withdrawn resume used to claim the wait and move the cursor to the next
    declared step. Consumers that read a running row are seeded with exactly that
    persisted state, without exercising the retired advance method.
    """
    program=e['compiled'].value.program
    entry=[i for i,n in enumerate(program.workflow.steps) if n.id==program.workflow.entry][0]
    with e['factory'].begin(e['scope']) as uow:
        uow.workflow.update_run(run_id=run_id,status='RUNNING',cursor=entry+1,
            wait_reason=None,now='2026-10-14T12:01:00.000000Z')
        uow.commit()
    return run_id
def resume_params(state):return {'run_id':'work','expected_row_digest':state['row_digest'],'expected_condition_digest':state['condition_digest'],'expected_next_step_ordinal':state['next_step_ordinal']}


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


WITHDRAWN_COMPILED_ROUTES = (
    'engineering.work.bind_inputs',
    'engineering.work.record_command_step',
    'engineering.work.record_dispatch_step',
    'engineering.runs.resume',
    'engineering.runs.cancel',
)

RETIRED_TESTS = (
    'test_real_wait_command_wait_chain_and_history_do_not_dispatch',
    'test_source_revoke_and_wrong_match_do_not_advance_or_leave_command',
    'test_start_requires_real_selection_source_and_wrong_scope_read_refuses',
    'test_historical_runner_rows_remain_readable_but_are_not_current_work',
    'test_competing_resume_claim_after_observation_is_rejected_without_receipt',
    'test_registry_capability_drift_before_record_refuses_without_work_receipt',
    'test_step_receipt_write_failure_rolls_back_record_command_and_cursor',
    'test_start_rechecks_source_dependency_on_original_write_transaction',
    'test_start_registry_drift_refuses_before_work_writes',
    'test_start_owner_read_set_scope_is_required',
    'test_counted_loop_restarts_from_persisted_rounds_and_rejects_reused_command',
    'test_unmapped_completed_result_refuses_step_advance',
)
"""Original tests retired together with the withdrawn compiled routes.

Each name above was a real test of the compiled run lifecycle: starting at the
declared wait node, source revoke and mismatch handling, competing resume claims,
registry drift before a write, step-receipt rollback of the command, counted loop
rounds, and unmapped-result refusal. They are retired - the routes they drove are
no longer advertised, so the tests cannot pass as written, and they are not
rewritten or weakened here. The behavioural requirements they covered are
registered in the docstrings of the modules that used to satisfy them.
"""


def test_compiled_create_and_advance_routes_are_withdrawn(env):
    """The advertised surface has no route into the compiled lifecycle."""
    e = env
    advertised = set(type(e['facade']).supported_commands)
    for operation in WITHDRAWN_COMPILED_ROUTES:
        assert operation not in advertised
        with pytest.raises(ApplicationError) as refused:
            call(e, operation, {'run_id': 'work'}, 'retired-' + operation)
        assert refused.value.code == 'OPERATION_UNAVAILABLE'


def test_historical_compiled_row_is_readable_without_advancing(env):
    """A historical row reads back through the retained read query only."""
    e = env
    seed_historical_run(e, 'retired-history-run')
    listed = query(e, 'engineering.runs.list', {'limit': 4}, 'retired-history-list')
    assert [row['run_id'] for row in listed['runs']] == ['retired-history-run']
    assert listed['runs'][0]['status'] == 'WAITING_FOR_CONDITION'
    assert listed['runs'][0]['execution'] == {'availability': 'unavailable'}
    assert e['lib'].run_row('retired-history-run')['status'] == 'WAITING_FOR_CONDITION'


def test_legacy_method_schema_is_rejected_without_creating_current_work(env):
    """A legacy method payload is refused on the declarative route too."""
    e=env
    legacy={'schema_version':'engineering-method/1','method_id':'legacy','revision':1,
        'description':'historical runner input','registry_ref':{},'steps':[]}
    with pytest.raises(ApplicationError,match='INVALID_INPUT'):
        call(e,'engineering.work.start',{'run_id':'legacy-run','method':legacy},'legacy-start')
    with e['factory'].begin(e['scope'],'read') as uow:
        assert uow.commands.get(_context(e['scope'],'legacy-start').key) is None
        with pytest.raises(EngineeringError,match='run_not_found'):
            uow.workflow.run_row('legacy-run')
