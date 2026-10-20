"""Real Agent pipe receipt -> actual schema17 report source and COMMIT.

The pipe peer, conversation attestor, source reviewer and external workspace
guard are explicit controlled fixtures. No model, network or user DB is used.
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_execution_agents.public import InteractionService, ManagerRefused
from ordessa_execution_agents.sdk.interactions import InteractionsRefused
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import decode_work_binding
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.changes.agent_submission_report import AgentSubmissionReport
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.submission import SubmissionCoverage
from ordessa_engineering.domain.changes.submission_codec import submission_projection
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.adapters.native_records.agent_selection import OriginalAgentDispatchSelection
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority, AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess

from agent_work_business_fixture import build_agent_work_package_approval
from test_agent_guarded_bootstrap import setup, PEER
from test_real_source_chain import NOW, PRINCIPAL, SCOPE

ROOT = Path(__file__).resolve().parents[3]
METHOD = ROOT / 'methods/incremental-engineering/candidates/2.7.4'


def run_scenario(scenario, directory):
    before = {id(thread) for thread in threading.enumerate()}
    asyncio.run(scenario)
    path = directory / 'report-fixture-lifecycle.json'
    evidence = json.loads(path.read_text())
    evidence['new_threads_after_asyncio_run'] = [thread.name for thread in threading.enumerate()
        if id(thread) not in before and thread.is_alive()]
    path.write_text(json.dumps(evidence, indent=2) + '\n')
    assert evidence['new_threads_after_asyncio_run'] == []


def peer(case):
    make = ("task=json.loads(params['prompt'][0]['text']);"
        "report=json.dumps({'package_digest':'sha256:'+task['package_ref']['digest']['hex'],"
        "'profile_ref':task['profile_ref'],'changed_paths':['src/x.py'],"
        "'verification':[{'check':'controlled','result':'not_run'}],'status':'completed'})")
    if case == 'package': make += ";report=json.dumps({**json.loads(report),'package_digest':'sha256:'+'0'*64})"
    if case == 'profile': make += ";report=json.dumps({**json.loads(report),'profile_ref':{**task['profile_ref'],'profileId':'substituted'}})"
    if case == 'schema': make += ";report=json.dumps({**json.loads(report),'unexpected':True})"
    result = PEER.replace("assert method=='session/prompt' and params['sessionId']==session",
        "assert method=='session/prompt' and params['sessionId']==session;" + make)
    result = result.replace("'original-bootstrap-peer'", 'report')
    if case == 'unknown': result = result.replace(';'+make, ';sys.exit(0)')
    if case == 'missing_text': result = result.replace("'agent_message_chunk'", "'agent_thought_chunk'")
    if case == 'wrong_session': result = result.replace("'params':{'sessionId':session,'update':", "'params':{'sessionId':'other-session','update':")
    if case == 'unsuccessful': result = result.replace("'stopReason':'end_turn'", "'stopReason':'error'")
    if case == 'missing_response': result = result.replace("result={'stopReason'", "sys.exit(0);result={'stopReason'")
    return result


@asynccontextmanager
async def report_case(tmp_path, monkeypatch, case='valid'):
    native = await setup(tmp_path / 'native', peer(case))
    business = None
    try:
        started = await native.manager.start(native.request, native.endpoint, native.fixture.invocation)
        profile = native.request.profile_revision_ref
        environment = EnvironmentRef(profile.environment_namespace, profile.profile_id,
            Digest('sha256', profile.digest.removeprefix('sha256:')))
        business = build_agent_work_package_approval(tmp_path / 'business', issue_grant=True,
            environment_ref=environment, method_directory=METHOD)
        fixture = await asyncio.to_thread(business.__enter__)
        env, factory = fixture['env'], fixture['factory']
        wire = WireScope(SCOPE.realm_id, SCOPE.project_id)
        issuer = InstanceAccessAuthority(lambda: 'controlled-agent-report-token', principal_id=PRINCIPAL,
            grants=(AccessGrant(wire, ('engineering.executions.dispatch','engineering.submissions.record_report')),),
            legacy_principal=None)
        caller = issuer.authenticate('Bearer controlled-agent-report-token')
        access = EngineeringCommandAccess(issuer)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return datetime.fromisoformat(NOW.replace('Z', '+00:00'))
        monkeypatch.setattr('ordessa_system_access_bindings.engineering_access.datetime', Clock)
        monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now', lambda: NOW)
        source = InteractionService(native.records, native.authority, native.fixture.resolver)
        query_calls = []
        def query(binding):
            query_calls.append(binding)
            return native.fixture.invocation
        execution = RecordedDispatchExecution(source, env.blobs,
            send_invocation_resolver=lambda *_: native.fixture.invocation,
            read_invocation_resolver=lambda *_: native.fixture.invocation,
            query_factory=query, endpoint_resolver=native.fixture.resolver)
        service = EngineeringService(factory, access, review_admission=env.admission, blobs=env.blobs,
            conversation_admission=fixture['service']._packages.approvals._admission(),
            method_guard=env.controls, source_materials=env.materials, source_review_bindings=env.bindings,
            execution_records=execution.records, execution_query_factory=execution.query_factory)
        @contextmanager
        def workspace(ctx, package, agent, scopes):
            assert package == fixture['package_ref'] and agent == started.instance_ref.projection()
            assert tuple(action for action, _ in scopes) == fixture['authorization'].actions
            yield
        selection = OriginalAgentDispatchSelection(source, profile,
            read_invocation_resolver=lambda *_: native.fixture.invocation, workspace_scope_guard=workspace)
        from ordessa_server.composition.engineering_dispatch import bind_original_agent_work_dispatch
        owner = bind_original_agent_work_dispatch(service, execution=execution, selection=selection,
            agent_ref_resolver=lambda *_: {'agent_ref':started.instance_ref.projection(),'session_id':started.session_id},
            implementation_timeout=5)
        with factory.begin(SCOPE, 'read') as uow:
            work = decode_work_binding(uow.workflow.read(fixture['head']))
        authorization = fixture['authorization']
        with access.admit(caller, wire, 'engineering.executions.dispatch', request_id='report-native-dispatch', trace_id='report') as ctx:
            envelope = owner.assemble_declared_work_dispatch(work, authorization.action_id, authorization.step_id,
                {'package':asdict(fixture['package_ref']),'profile':{}}, ctx)
            dispatch = await service._execute_declared_dispatch(envelope, ctx, work=work,
                action_id=authorization.action_id, step_id=authorization.step_id)
        binding = dispatch.value['binding']
        fixture.update(native=native, execution=execution, service=service, access=access, caller=caller,
            wire=wire, binding=binding, work=work, dispatch=dispatch, queries=query_calls)
        yield fixture
    finally:
        if business is not None: await asyncio.to_thread(business.__exit__, None, None, None)
        native.owner.close()
        lifecycle = {'owned_process_handles_before_cleanup':len(native.fixture._manager._owned_process_handles),
            'uses_before_cleanup':native.fixture.retained_use_count}
        try:
            await native.fixture.cleanup()
            assert native.fixture.retained_use_count == 0
            lifecycle['owned_process_handles_after_cleanup'] = len(native.fixture._manager._owned_process_handles)
            lifecycle['uses_after_cleanup'] = native.fixture.retained_use_count
            assert lifecycle['owned_process_handles_after_cleanup'] == 0
            lifecycle['agent_records_after_endpoint_cleanup'] = native.records._db.execute('SELECT 1').fetchone() == (1,)
        finally:
            native.records.close()
            with pytest.raises(sqlite3.ProgrammingError, match='closed'):
                native.records._db.execute('SELECT 1')
            lifecycle['agent_records_after_close'] = 'closed'
            (tmp_path / 'report-fixture-lifecycle.json').write_text(json.dumps(lifecycle, indent=2) + '\n')


def report(fixture, context):
    binding = fixture['binding']
    reference, captured = fixture['execution'].records.capture_dispatch(binding,
        read_invocation=fixture['native'].fixture.invocation)
    if captured.report_text is None:
        # A caller may still assert a report after a failed/unknown native turn;
        # its real captured state below must refuse it before any business write.
        params = decode_json(fixture['env'].blobs.read_verified(binding.prompt_ref))
        task = decode_json(params['prompt'][0]['text'].encode())
        content = {'package_digest':'sha256:'+binding.package_ref.digest.hex,'profile_ref':task['profile_ref'],
            'changed_paths':['src/x.py'],'verification':[{'check':'controlled','result':'not_run'}],'status':'completed'}
    else:
        content = decode_json(captured.report_text.encode())
    raw = canonical_bytes(content)
    blob = fixture['env'].blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
    with fixture['factory'].begin(SCOPE, 'read') as uow:
        package = uow.implementation.resolve_package(binding.package_ref)
    with fixture['env'].controls.guard(context, package.payload.method_ref):
        schema = fixture['env'].controls.resource_ref(context, package.payload.method_ref, 'implementation-report-schema')
    value = AgentSubmissionReport(SCOPE, 'actual-agent-report', context.received_at, context.authenticated_actor,
        ChangeSet((package.payload.change_ref,)), (binding.approval_ref,), package.ref, reference, (blob,),
        (SubmissionCoverage(package.payload.change_ref, (blob,), (), (), 'implemented'),),
        (package.payload.baseline, package.payload.candidate),
        MethodContent.from_value(schema, decode_json(raw), rendered_body_ref=blob))
    return value


def test_actual_agent_report_capture_commit_pending_review_replay_and_current_contract(tmp_path, monkeypatch):
    async def scenario():
        async with report_case(tmp_path, monkeypatch) as fixture:
            service, native = fixture['service'], fixture['native']
            with fixture['access'].admit(fixture['caller'], fixture['wire'], 'engineering.submissions.record_report',
                    request_id='actual-agent-report-commit', trace_id='report') as ctx:
                value = report(fixture, ctx)
                answer = await service.execute('engineering.submissions.record_report', {'record':submission_projection(value)}, ctx)
                assert answer.status == 'completed'
                assert decode_json(answer.result_bytes)['accepted'] is False
                assert decode_json(answer.result_bytes)['review_status'] == 'pending_review'
                with fixture['factory'].begin(SCOPE, 'read') as uow:
                    assert uow.submissions.resolve(value.ref) == value
                count = len(fixture['queries'])
                turns = native.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]
                native.authority.read = False
                replay = await service.execute('engineering.submissions.record_report', {'record':submission_projection(value)}, ctx)
                assert replay.result_bytes == answer.result_bytes and len(fixture['queries']) == count
                with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT'):
                    await service.execute('engineering.submissions.record_report', {'record':submission_projection(replace(value, submission_id='other'))}, ctx)
                assert len(fixture['queries']) == count
                assert native.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0] == turns == 1
                described = {item.capability_id:item for item in service.bound_operation_capabilities().capabilities}
                current = {item.capability_id:item for item in command_capabilities().capabilities}
                assert described['engineering.submissions.record_report'] == current['engineering.submissions.record_report']
                assert current['engineering.submissions.record_report'].interface_version == '2'
                assert service.input_schema('engineering.submissions.record_report')['$id'].endswith(':input:2')
    run_scenario(scenario(), tmp_path)


def test_current_work_report_record_uses_original_agent_capture_then_service_commit(tmp_path, monkeypatch):
    async def scenario():
        async with report_case(tmp_path, monkeypatch) as fixture:
            service = fixture['service']
            with fixture['access'].admit(fixture['caller'], fixture['wire'], 'engineering.submissions.record_report',
                    request_id='current-work-agent-report', trace_id='report') as ctx:
                native = service._work_dispatch_business(fixture['dispatch'])
                value = service._implementation_results.report_record(ctx, fixture['work'], native)
                from ordessa_engineering.domain.changes.submission_codec import decode_submission
                record = decode_submission(canonical_bytes(value))
                assert type(record) is AgentSubmissionReport
                assert record.execution_ref.operation_ref != record.execution_ref.engineering_attempt_ref
                assert record.execution_ref.turn_ref_bytes == fixture['binding'].turn_ref_bytes
                result = await service.execute('engineering.submissions.record_report', {'record':value}, ctx)
                assert result.status == 'completed'
                assert decode_json(result.result_bytes)['accepted'] is False
                with fixture['factory'].begin(SCOPE, 'read') as uow:
                    assert uow.submissions.resolve(record.ref) == record
                before = len(fixture['queries'])
                substituted = {**native, 'observation_ref':{**native['observation_ref'],'storage_object_id':'other'}}
                with pytest.raises(ApplicationError, match='SUBMISSION_DISPATCH_BINDING_MISMATCH'):
                    service._implementation_results.report_record(ctx, fixture['work'], substituted)
                assert len(fixture['queries']) == before
    run_scenario(scenario(), tmp_path)


@pytest.mark.parametrize('case', ['unknown','unsuccessful','missing_text','wrong_session','missing_response'])
def test_agent_original_noncompleted_or_incomplete_native_report_never_commits(tmp_path, monkeypatch, case):
    async def scenario():
        async with report_case(tmp_path, monkeypatch, case) as fixture:
            with fixture['access'].admit(fixture['caller'], fixture['wire'], 'engineering.submissions.record_report',
                    request_id='agent-native-report-refusal', trace_id='report') as ctx:
                value = report(fixture, ctx)
                with pytest.raises(ApplicationError):
                    await fixture['service'].execute('engineering.submissions.record_report', {'record':submission_projection(value)}, ctx)
                assert fixture['env'].library._connection.execute('SELECT count(*) FROM eng_submissions').fetchone() == (0,)
                assert fixture['native'].records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0] == 1
                assert fixture['dispatch'].accepted is False
    run_scenario(scenario(), tmp_path)


@pytest.mark.parametrize('case', ['package','profile','schema','body','query','source_revision','actual_operation',
    'engineering_attempt','capture_ref','source_ref','author','checkpoint','read_denied','revoked_at_commit'])
def test_agent_report_keeps_source_approval_attribution_and_commit_negatives(tmp_path, monkeypatch, case):
    async def scenario():
        async with report_case(tmp_path, monkeypatch, case) as fixture:
            with fixture['access'].admit(fixture['caller'], fixture['wire'], 'engineering.submissions.record_report',
                    request_id='agent-report-refusal', trace_id='report') as ctx:
                value = report(fixture, ctx)
                if case == 'body':
                    content = {**value.method_content.value, 'changed_paths':['src/substituted.py']}
                    raw = canonical_bytes(content)
                    blob = fixture['env'].blobs.put_verified(raw, Digest('sha256',hashlib.sha256(raw).hexdigest()), 'application/json')
                    value = replace(value, output_refs=(blob,), coverage=(replace(value.coverage[0],output_refs=(blob,)),),
                        method_content=MethodContent.from_value(value.method_content.schema_ref, content, rendered_body_ref=blob))
                elif case == 'actual_operation': value = replace(value, execution_ref=replace(value.execution_ref,operation_ref='other-operation'))
                elif case == 'query':
                    prompt = Digest('sha256', 'e' * 64)
                    query = {'schemaVersion':'agent-turn-query/1',
                        'turnRef':decode_json(value.execution_ref.turn_ref_bytes),'expectedInputDigest':'sha256:'+prompt.hex}
                    value = replace(value, execution_ref=replace(value.execution_ref, prompt_input_digest=prompt,
                        query_digest='sha256:'+hashlib.sha256(canonical_bytes(query)).hexdigest()))
                elif case == 'source_revision': value = replace(value, execution_ref=replace(value.execution_ref,source_revision='substituted-source-revision'))
                elif case == 'engineering_attempt': value = replace(value, execution_ref=replace(value.execution_ref,engineering_attempt_ref='other-attempt'))
                elif case == 'capture_ref': value = replace(value, execution_ref=replace(value.execution_ref,captured_observation_ref=replace(value.execution_ref.captured_observation_ref,storage_object_id='other-blob')))
                elif case == 'source_ref': value = replace(value, source_refs=(value.source_refs[0],replace(value.source_refs[1],source_id='substituted-source')))
                elif case == 'author': value = replace(value, created_by=replace(value.created_by,actor_id='other-author'))
                elif case == 'checkpoint': value = replace(value, checkpoint_ref=value.output_refs[0])
                elif case == 'read_denied': fixture['native'].authority.read = False
                elif case == 'revoked_at_commit':
                    selected = fixture['service']._submission_reports.report_source
                    original = selected.guard_report
                    @contextmanager
                    def revoke(*args):
                        with original(*args) as admission:
                            with fixture['factory'].begin(SCOPE) as uow:
                                uow.authorization.revoke(value.authorization_refs[0],0,NOW,'controlled report revoke','agent-report-revoke')
                                uow.commit()
                            yield admission
                    monkeypatch.setattr(selected,'guard_report',revoke)
                with pytest.raises((ApplicationError, ManagerRefused, InteractionsRefused)):
                    await fixture['service'].execute('engineering.submissions.record_report', {'record':submission_projection(value)}, ctx)
                assert fixture['env'].library._connection.execute('SELECT count(*) FROM eng_submissions').fetchone() == (0,)
                row = fixture['env'].library._connection.execute('SELECT state FROM eng_commands WHERE request_id=?',('agent-report-refusal',)).fetchone()
                assert row is None or row[0] != 'completed'
                assert fixture['native'].records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0] == 1
    run_scenario(scenario(), tmp_path)
