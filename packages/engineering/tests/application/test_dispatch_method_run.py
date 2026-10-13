"""Method-graph package resolution over the original run and SQLite UoW.

The package repository is an explicit fixture stub. These checks do not claim
production Grant admission, dispatch reservation, or native execution.
"""
import contextlib
import hashlib
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.implementation_repository import SQLiteImplementationRepository
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT, WAIT_EVENT, WorkSeed
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities
from ordessa_engineering.methods.loading.loader import load_method
from test_method_work import call, env
from test_review_usecases import _context


@pytest.fixture
def dispatch_setup(env):
    e=env
    descriptor=next(item for item in owner_capabilities()
                    if item.capability_id=='engineering.executions.dispatch')
    caps=CompilationCapabilities((*command_capabilities().capabilities,descriptor),trust_class='host')
    root=e['root'].parent/'dispatch-method'
    root.mkdir()
    workflow={'schema_version':1,'workflow_id':'dispatch-binding','entry':'gate',
        'resume_contract':WORK_CONTRACT,
        'context_slots':['package_ref','dispatch_input'],'wait_kinds':['owner_reconciliation'],
        'stop_outcomes':['accepted','rejected'],'steps':[
            {'id':'gate','kind':'wait','event':WAIT_EVENT,'next':'dispatch'},
            {'id':'dispatch','kind':'operation','operation':'engineering.executions.dispatch',
             'config':{'package_slot':'package_ref'},'inputs':{'dispatch':'dispatch_input'},
             'outcomes':{'completed':{'next':'done'},'failed':{'stop':'rejected'},
                         'unknown':{'stop':'rejected'}}},
            {'id':'done','kind':'stop','outcome':'accepted'}]}
    raw=json.dumps(workflow).encode()
    (root/'workflow.yaml').write_bytes(raw)
    manifest=json.loads((e['root']/'method.yaml').read_text())
    manifest['method_id']='test.dispatch-method-run'
    manifest['resources'][0]['sha256']=hashlib.sha256(raw).hexdigest()
    manifest['requires']=[{'capability_id':descriptor.capability_id,'kind':descriptor.kind,
        'interface_version':descriptor.interface_version,'contract_digest':descriptor.contract_digest}]
    (root/'method.yaml').write_text(json.dumps(manifest))
    loaded=load_method(MethodSource(root),FileResourceReader())
    assert loaded.ok,loaded.error
    compiled=compile_method(loaded.value,caps,'fixture/compiler')
    assert compiled.ok,compiled.error
    published=freeze_method(compiled.value,e['store'],e['store'],
        capability_catalog=SimpleNamespace(read_current=lambda:caps))
    assert published.ok,published.error
    sref=published.value.ref
    method=MethodRef(sref.method_id,sref.release_version,sref.schema_version,
                     Digest('sha256',sref.snapshot_digest))
    e['management'].adopt(method,_context(e['scope'],'adopt-dispatch-method'),expected_version=1)

    package_ref=ImplementationPackageRef(e['scope'].realm_id,e['scope'].project_id,
        'method-bound-package',Digest('sha256','b'*64))
    package=SimpleNamespace(scope=e['scope'],ref=package_ref,
                            payload=SimpleNamespace(method_ref=method))
    @contextlib.contextmanager
    def guard_start(context,snapshot, *, run_id, selection):
        assert type(run_id) is str and selection is None
        slots={'package_ref':asdict(package_ref),'dispatch_input':{
            'run_id':'dispatch-run','step_id':'dispatch','attempt':1,
            'unit_ref':{'environmentNamespace':'fixture','unitId':'unit',
                'ownerProviderRef':{'provider':'fixture'},'sourceRevision':'r1'},
            'params':{},'actions':['run_checks'],'timeout':1}}
        yield WorkSeed(slots,e['source'].start_reads)
    e['source'].guard_start=guard_start
    return {'env':e,'method':method,'package':package,'bindings':e['bindings']}


def _begin_running(setup,run_id='dispatch-run'):
    e=setup['env']
    call(e,'engineering.work.start',{'run_id':run_id},'start-'+run_id)
    ready=e['facade']
    import asyncio
    state=asyncio.run(ready.query('engineering.work.current_condition',{'run_id':run_id},
                                  _context(e['scope'],'condition-'+run_id)))
    asyncio.run(ready.execute('engineering.runs.resume',{'run_id':run_id,
        'expected_row_digest':state['row_digest'],'expected_condition_digest':state['condition_digest'],
        'expected_next_step_ordinal':state['next_step_ordinal']},
        _context(e['scope'],'resume-'+run_id)))


def _stub_package_resolver(monkeypatch, package, calls):
    def resolve(_repository, ref):
        calls.append(ref)
        return package
    monkeypatch.setattr(SQLiteImplementationRepository,'resolve_package',resolve)


def _dispatch_owner(setup, *, bindings=None):
    e=setup['env']
    return ImplementationDispatch(e['factory'],method_runs=setup['bindings'] if bindings is None else bindings)


def test_work_dispatch_resolves_exact_package_from_method_declared_slot(dispatch_setup, monkeypatch):
    setup=dispatch_setup
    _begin_running(setup)
    calls=[]
    _stub_package_resolver(monkeypatch,setup['package'],calls)
    owner=_dispatch_owner(setup)
    with setup['env']['factory'].begin(setup['env']['scope'],'read') as uow:
        package=owner._work_package(uow,'dispatch-run',step_id='dispatch',live=True)
        assert package.ref==setup['package'].ref
        assert calls==[setup['package'].ref]
        row=uow.workflow.run_row('dispatch-run')
        assert row['inputs']['slots']['package_ref']==asdict(setup['package'].ref)
        assert uow.workflow.next_step_ordinal('dispatch-run')==0


def test_dispatch_resolution_refuses_missing_binding_wrong_slot_and_wait_cursor(
        dispatch_setup, monkeypatch):
    setup=dispatch_setup
    e=setup['env']
    call(e,'engineering.work.start',{'run_id':'dispatch-run'},'start-waiting')
    owner=ImplementationDispatch(e['factory'],method_runs=None)
    with e['factory'].begin(e['scope'],'read') as uow:
        with pytest.raises(ApplicationError,match='DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE'):
            owner._work_package(uow,'dispatch-run',step_id='dispatch')
    owner=_dispatch_owner(setup)
    with e['factory'].begin(e['scope'],'read') as uow:
        with pytest.raises(ApplicationError,match='DISPATCH_WORK_STEP_UNAVAILABLE'):
            owner._work_package(uow,'dispatch-run',step_id='dispatch',live=True)
    row=e['lib'].run_row('dispatch-run')
    altered={**row['inputs'],'slots':dict(row['inputs']['slots'])}
    altered['slots'].pop('package_ref')
    with e['factory'].begin(e['scope']) as uow:
        uow.workflow.replace_run_inputs(run_id='dispatch-run',expected_inputs=row['inputs'],inputs=altered)
        uow.commit()
    with e['factory'].begin(e['scope'],'read') as uow:
        with pytest.raises(ApplicationError,match='DISPATCH_METHOD_INPUT_BINDING_UNAVAILABLE'):
            owner._work_package(uow,'dispatch-run',step_id='dispatch')


@pytest.mark.parametrize('mismatch', ['foreign_scope','foreign_method'])
def test_dispatch_resolution_rejects_package_from_wrong_scope_or_method(
        dispatch_setup, monkeypatch, mismatch):
    setup=dispatch_setup
    _begin_running(setup)
    package=setup['package']
    if mismatch=='foreign_scope':
        wrong=SimpleNamespace(scope=replace(package.scope,project_id='foreign-project'),
            ref=package.ref,payload=package.payload)
    else:
        wrong=SimpleNamespace(scope=package.scope,ref=package.ref,
            payload=SimpleNamespace(method_ref=replace(setup['method'],method_id='foreign-method')))
    calls=[]
    _stub_package_resolver(monkeypatch,wrong,calls)
    owner=_dispatch_owner(setup)
    with setup['env']['factory'].begin(setup['env']['scope'],'read') as uow:
        with pytest.raises(ApplicationError,match='DISPATCH_WORK_BINDING_INVALID'):
            owner._work_package(uow,'dispatch-run',step_id='dispatch',live=True)
    assert calls==[package.ref]


def test_dispatch_live_resolution_requires_enabled_method_control(dispatch_setup, monkeypatch):
    setup=dispatch_setup
    _begin_running(setup)
    e=setup['env']
    e['management'].control(setup['method'],_context(e['scope'],'disable-dispatch-method'),
        expected_version=0,enabled=False,reason='fixture disabled control')
    calls=[]
    _stub_package_resolver(monkeypatch,setup['package'],calls)
    owner=_dispatch_owner(setup)
    with e['factory'].begin(e['scope'],'read') as uow:
        with pytest.raises(ApplicationError,match='DISPATCH_WORK_STEP_UNAVAILABLE'):
            owner._work_package(uow,'dispatch-run',step_id='dispatch',live=True)
    assert calls==[]
