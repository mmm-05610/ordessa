"""Actual historical MethodRun/UoW/Agent cold read; no new Agent send recipe.

The method/package/dispatch rows are explicit historical fixture seeds in real
owners. Controlled Agent pipes supply original recorded outcomes; the current
MethodRun resolver and external read admission are not replaced by callbacks.
This does not qualify a new Work dispatch, approval consumption or acceptance.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[3]
SUPPORT = ROOT/'packages/engineering/tests/application'
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from test_method_work import env, seed_historical_run
from test_implementation_dispatch import _fixture_records
from test_agent_guarded_bootstrap import setup
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_execution_agents.public import InteractionService
from ordessa_execution_agents.sdk.interactions import InteractionsRefused
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.adapters.native_records.agent_execution import AgentDispatchSources
from ordessa_engineering.adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority, AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess
from ordessa_server.composition.engineering_dispatch import dispatch_routes_factory

OP = 'engineering.implementation.reconcile'


def historical_method(e, tmp_path):
    descriptor = next(d for d in owner_capabilities() if d.capability_id == 'engineering.executions.dispatch')
    caps = CompilationCapabilities((*command_capabilities().capabilities, descriptor), trust_class='host')
    root = tmp_path/'historical-agent-query-method'
    root.mkdir()
    workflow = {'schema_version':1, 'workflow_id':'historical-agent-query', 'entry':'dispatch',
        'resume_contract':'ordessa.method-work/1', 'context_slots':['package_ref','dispatch_input'],
        'wait_kinds':['owner_reconciliation'], 'stop_outcomes':['accepted','rejected'], 'steps':[
            {'id':'dispatch','kind':'operation','operation':'engineering.executions.dispatch',
             'config':{'package_slot':'package_ref', 'task_prompt':{
                 'template_resource':'task','bindings':{'package':'package_ref'},'actions':['run_checks'],'timeout':1}},
             'inputs':{'dispatch':'dispatch_input'}, 'outcomes':{
                 'completed':{'next':'done'},'failed':{'stop':'rejected'},'unknown':{'stop':'rejected'}}},
            {'id':'done','kind':'stop','outcome':'accepted'}]}
    from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT
    workflow['resume_contract'] = WORK_CONTRACT
    raw = json.dumps(workflow).encode()
    (root/'workflow.yaml').write_bytes(raw)
    (root/'task.md').write_text('{{package}}')
    manifest = {'schema_version':1,'method_id':'test.historical-agent-query','release_version':'1.0.0',
        'compiler_contract':'ordessa.methods/v1','entry':{'resource':'workflow'},'documents':[],
        'resources':[{'id':'workflow','kind':'workflow','path':'workflow.yaml','media_type':'application/yaml',
                      'sha256':hashlib.sha256(raw).hexdigest()},
                     {'id':'task','kind':'document_template','path':'task.md','media_type':'text/markdown',
                      'sha256':hashlib.sha256((root/'task.md').read_bytes()).hexdigest()}],
        'requires':[{k:getattr(descriptor,k) for k in ('capability_id','kind','interface_version','contract_digest')}]}
    (root/'method.yaml').write_text(json.dumps(manifest))
    loaded = load_method(MethodSource(root), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, caps, 'fixture/compiler')
    assert compiled.ok, compiled.error
    published = freeze_method(compiled.value, e['store'], e['store'],
        capability_catalog=SimpleNamespace(read_current=lambda:caps))
    assert published.ok, published.error
    ref = published.value.ref
    return compiled, ref, MethodRef(ref.method_id, ref.release_version, ref.schema_version, Digest('sha256',ref.snapshot_digest))


@pytest.mark.parametrize('sent', [False, True])
@pytest.mark.parametrize('refused', [None, 'method-input', 'agent-read'])
def test_original_agent_reconcile_uses_real_method_package_uow_and_read_admission(env, tmp_path, sent, refused):
    async def scenario():
        case = await setup(tmp_path/'agent')
        try:
            started = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert started.state == 'running'
            source = InteractionService(case.records, case.authority, case.fixture.resolver)
            provenance = source.read_binding(started.instance_ref, invocation=case.fixture.invocation)
            compiled, snapshot, method = historical_method(env, tmp_path)
            _, _, _, _, _, original = _fixture_records()
            profile = provenance.profile_ref
            payload = replace(original.payload, method_ref=method,
                execution_profile_ref=EnvironmentRef(profile.environment_namespace, profile.profile_id, Digest('sha256',profile.digest[7:])))
            package = replace(original, payload=payload)
            with env['factory'].begin(package.scope) as uow:
                uow.implementation.create_package(package)
                uow.commit()
            fixture = {**env, 'scope':package.scope, 'compiled':compiled, 'sref':snapshot}
            seed_historical_run(fixture, 'agent-history', slots={'package_ref':asdict(package.ref),'dispatch_input':{}},
                                cursor=0, status='RUNNING')
            blobs = SQLiteBlobStore(env['lib'])
            execution = RecordedDispatchExecution(source, blobs,
                send_invocation_resolver=lambda *a:case.fixture.invocation,
                read_invocation_resolver=lambda *a:case.fixture.invocation,
                query_factory=lambda binding:case.fixture.invocation, endpoint_resolver=case.fixture.resolver)
            raw = canonical_bytes({'sessionId':started.session_id,'prompt':[]})
            with execution.records.prepared_dispatch(started.instance_ref.projection(), raw, request_id='history-turn',
                    engineering_attempt_ref='recorded-engineering-attempt', send_invocation=case.fixture.invocation,
                    read_invocation=case.fixture.invocation) as prepared:
                prompt = blobs.put_verified(raw, Digest('sha256',hashlib.sha256(raw).hexdigest()), 'application/json')
                binding = AgentDispatchBinding(package.scope,'agent-history','dispatch',1,1,package.ref,
                    package.payload.authorization_refs[0], package.payload.derivation.intent_digest,0,
                    (('run_checks','recorded-action'),),prepared.agent_ref_bytes,'recorded-engineering-attempt',prompt,
                    Digest('sha256',prepared.prompt_input_digest[7:]),prepared.query_digest,('submission',),prepared.turn_ref_bytes)
                with env['factory'].begin(package.scope) as uow:
                    AgentDispatchBindings(uow.dispatch).reserve(binding)
                    uow.dispatch.transition('agent-history','dispatch',1,package.scope,
                        expected_version=0,fence=1,phase='possibly_written')
                    uow.commit()
                if sent:
                    class NativeFixtureCut:
                        @contextmanager
                        def guard_write(self,write,invocation):
                            assert invocation is case.fixture.invocation
                            yield
                    receipt = await source.prompt_recorded(started.instance_ref, source.freeze_prompt(started.instance_ref,raw),
                        request_id='history-turn',engineering_attempt_ref='recorded-engineering-attempt',
                        invocation=case.fixture.invocation,write_guard=NativeFixtureCut(),deadline=asyncio.get_running_loop().time()+2)
                    assert receipt.state == 'completed'
            original_rows = case.records._db.execute('SELECT count(*) FROM operations').fetchone()[0]
            def forbidden_send(*args,**kwargs):
                raise AssertionError('cold read attempted a fresh effect or reservation')
            source.reserve_turn = forbidden_send
            source.prompt_recorded = forbidden_send
            execution.endpoint_resolver.resolve = forbidden_send
            scope = Scope(package.scope.realm_id,package.scope.project_id)
            issuer = InstanceAccessAuthority(lambda:'synthetic-read-only-token',principal_id='cold-reader',
                grants=(AccessGrant(scope,(OP,)),),legacy_principal=None)
            caller = issuer.authenticate('Bearer synthetic-read-only-token')
            access = EngineeringCommandAccess(issuer)
            case.authority.send = False  # Cold reads never reacquire send rights.
            history = AgentDispatchSources(source, lambda *a:case.fixture.invocation)
            if refused == 'method-input':
                @contextmanager
                def refuse_method_input(context, actual_package, agent, request):
                    assert actual_package == package
                    assert agent == started.instance_ref.projection()
                    assert request['agent_ref'] == agent and 'unit_ref' not in request
                    assert canonical_bytes(request['params']) == raw
                    raise ApplicationError('DISPATCH_METHOD_INPUT_CHANGED')
                    yield
                history.guard_dispatch_input = refuse_method_input
            elif refused == 'agent-read':
                case.authority.read = False
            builder = dispatch_routes_factory(execution=execution,blobs=blobs,approvals_factory=None,
                history_sources=history,method_runs=env['bindings'])
            routes = builder(env['factory'],access,scope)
            with access.admit(caller,scope,OP,request_id='read-only',trace_id='query') as context:
                if refused is not None:
                    with pytest.raises(ApplicationError if refused == 'method-input' else InteractionsRefused):
                        routes.invoke(OP,{'run_id':'agent-history','step_id':'dispatch','attempt':1},context)
                    with env['factory'].begin(package.scope, 'read') as uow:
                        stored = uow.dispatch.get('agent-history','dispatch',1,package.scope)
                    assert stored['dispatch_phase'] == 'possibly_written'
                    assert stored['dispatch_version'] == 1 and stored['result_blob_json'] is None
                    assert case.records._db.execute('SELECT count(*) FROM operations').fetchone()[0] == original_rows
                    assert env['lib']._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone() == (0,)
                    return
                result = routes.invoke(OP,{'run_id':'agent-history','step_id':'dispatch','attempt':1},context)
            assert result['phase'] == ('completed' if sent else 'unknown')
            assert result['accepted'] is False and result['engineering_completed'] is False
            assert result['engineering_attempt_ref'] == 'recorded-engineering-attempt'
            assert case.records._db.execute('SELECT count(*) FROM operations').fetchone()[0] == original_rows
            assert source._fresh == {}
            assert env['lib']._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone() == (0,)
        finally:
            case.records.close()
            case.owner.close()
            await case.fixture.cleanup()
    asyncio.run(scenario())
