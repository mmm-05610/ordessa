"""Current report/plan/issuer through actual SQLite and controlled Agent pipe.

The existing report fixture owns consent/source capture; only local peer answers
and external workspace/identity admission are controlled. No model is called.
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, replace
import hashlib
import threading

import pytest
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_engineering.adapters.declared_agent_implementation_review import DeclaredAgentImplementationReviewBindings
from ordessa_engineering.adapters.native_records.declared_agent_reviewer import DeclaredAgentReviewerSource
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.agent_report_review import AgentReportReviewLocator, AgentReportAuthorship, AGENT_REPORT_REVIEW_CONTRACT
from ordessa_engineering.application.contracts.work_context import decode_work_binding
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.application.usecases.reviews.assignments import ReviewerAssignmentUseCases
from ordessa_engineering.domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ordessa_engineering.domain.changes.submission_codec import submission_projection
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.codec import encode_plan
import test_agent_work_report_v2 as actual_report
from test_real_source_chain import SCOPE


@asynccontextmanager
async def review_case(tmp_path,monkeypatch,verdict='passed'):
    physical=tmp_path/'physical-prompt-frames.txt'
    original_peer=actual_report.peer
    judgement={'verdict':verdict,'rationale':'Controlled holistic judgement; report assertions are not verified effects.',
               'findings':['Verification remains explicitly not_run.']}
    def peer(case):
        source=original_peer(case)
        marker="assert method=='session/prompt' and params['sessionId']==session"
        assert marker in source
        source=source.replace(marker,marker+";open("+repr(str(physical))+",'a').write('frame\n')")
        expression=("report=json.dumps({'package_digest':'sha256:'+task['package_ref']['digest']['hex'],"
            "'profile_ref':task['profile_ref'],'changed_paths':['src/x.py'],"
            "'verification':[{'check':'controlled','result':'not_run'}],'status':'completed'})")
        assert expression in source
        replacement='sys.exit(0)' if verdict=='native-unknown' else 'json.dumps('+repr(judgement)+')'
        return source.replace(expression,'report='+replacement+" if task.get('schemaVersion')=='ordessa.agent-report-review-input/1' else "+expression[len('report='):])
    monkeypatch.setattr(actual_report,'peer',peer)
    async with actual_report.report_case(tmp_path,monkeypatch) as fixture:
        native=fixture['native']; access=fixture['access']; factory=fixture['factory']; env=fixture['env']
        grants=('engineering.executions.dispatch','engineering.submissions.record_report',
            'engineering.reviews.request','engineering.reviews.record','engineering.reviews.assign_reviewer',
            'engineering.reviews.revoke_reviewer','engineering.reviewer.agent')
        access.authority.replace_grants((AccessGrant(fixture['wire'],grants),))
        caller=access.authority.authenticate('Bearer controlled-agent-report-token')
        with access.admit(caller,fixture['wire'],'engineering.submissions.record_report',request_id='source-report',trace_id='source') as ctx:
            submission=actual_report.report(fixture,ctx)
            sealed=await fixture['service'].execute('engineering.submissions.record_report',{'record':submission_projection(submission)},ctx)
            assert sealed.status=='completed' and decode_json(sealed.result_bytes)['accepted'] is False
        report_source=fixture['service']._submission_reports.report_source
        profiles=native.owner.service; profile=native.request.profile_revision_ref
        bindings=DeclaredAgentImplementationReviewBindings(factory,env.controls,profiles,profile,
            report_source=report_source,source_materials=env.materials)
        records=fixture['execution'].records
        assignments=ReviewerAssignmentUseCases(factory,env.controls,records,expected_access=access,expected_scope=SCOPE,
            agent_query_factory=lambda *_args,**_kwargs:native.fixture.invocation)
        source=DeclaredAgentReviewerSource(factory,access=access,scope=SCOPE,bindings=bindings,records=records,
            blobs=env.blobs,query_factory=lambda *_:native.fixture.invocation,review_paths=())
        admission=EngineeringReviewAdmission(factory,env.controls,bindings,source,
            source_materials=env.materials,method_guard=env.controls)
        service=EngineeringService(factory,access,review_admission=admission,blobs=env.blobs,
            source_materials=env.materials,method_guard=env.controls,reviewer_assignments=assignments)
        with factory.begin(SCOPE,'read') as uow:
            package=uow.implementation.resolve_package(submission.package_ref)
            work=decode_work_binding(uow.workflow.read(fixture['head']))
        from ordessa_execution_agents.profiles import encode_revision_ref
        from ordessa_engineering.domain.changes.agent_submission_report import AgentSubmissionReport
        assert type(submission) is AgentSubmissionReport
        with access.admit(caller,fixture['wire'],'engineering.reviews.request',request_id='request-independent',trace_id='review') as ctx:
            with env.controls.guard(ctx,work.method_ref) as definition:
                step=next(s for a in definition.actions if a.action_id=='incremental.implement-package'
                    for s in a.steps if s.name=='independently-review-report')
                resources={i.name:env.controls.read_resource(ctx,env.controls.resource_ref(ctx,work.method_ref,i.source_name))
                    for i in step.inputs if i.source_kind=='resource'}
            requirement=bindings.requirement_id(work,submission.ref,encode_revision_ref(profile))
            plan=bindings.implementation_plan(ctx,work,review_id='independent-agent-report',submission=submission,
                package=package,reviewer_profile_ref=encode_revision_ref(profile),requirement_id=requirement,resources=resources)
            requested=await service.execute('engineering.reviews.request',{'plan':decode_json(encode_plan(plan))},ctx)
            assert requested.status=='completed'
        # A second actual Manager start on the same fixed Profile. The fixture
        # explicitly admits this start; no business role comes from its labels.
        reviewer_start=replace(native.request,request_id='independent-reviewer-start')
        native.authority.request=reviewer_start
        reviewer=await native.manager.start(reviewer_start,native.endpoint,native.fixture.invocation)
        assert reviewer.state=='running'
        with factory.begin(SCOPE,'read') as uow:request=uow.reviews.get_request(plan.review_id)
        with access.admit(caller,fixture['wire'],'engineering.reviews.assign_reviewer',request_id='assign-independent',trace_id='review') as ctx:
            assigned=assignments.assign_reviewer(ctx,review_id=plan.review_id,expected_plan_digest=plan.plan_digest,
                request_version=request.version,fence=request.fence,reviewer_agent_ref=reviewer.instance_ref.projection())
            assert assigned.status=='completed'
        with factory.begin(SCOPE,'read') as uow:assignment,control=uow.reviewer_assignments.active_for_review(plan.review_id)
        with access.admit(caller,fixture['wire'],'engineering.reviews.request',request_id='prepare-independent',trace_id='review') as ctx:
            params=source.prompt_parameters(ctx,plan,request,assignment,reviewer.session_id)
            with env.controls.guard(ctx,plan.requirement.method_ref) as definition:
                standard=bindings.resolve_declared_submission_plan(ctx,plan,definition).standard
        params_raw=canonical_bytes(params)
        params_ref=env.blobs.put_verified(params_raw,Digest('sha256',hashlib.sha256(params_raw).hexdigest()),'application/json')
        origin_task,origin_thread=asyncio.current_task(),threading.get_ident()
        cut_calls=[]
        with records.prepared_dispatch(reviewer.instance_ref.projection(),params_raw,request_id='independent-review-turn',
                engineering_attempt_ref='independent-review-attempt',send_invocation=native.fixture.invocation,
                read_invocation=native.fixture.invocation) as prepared:
            if verdict=='revoked-before-cut':
                with access.admit(caller,fixture['wire'],'engineering.reviews.revoke_reviewer',request_id='revoke-before-cut',trace_id='review') as ctx:
                    assignments.revoke_reviewer(ctx,assignment_ref=assignment.ref,expected_control_version=0,reason='controlled role revoked before frame')
            class Cut:
                @contextmanager
                def guard_write(self,binding,invocation):
                    cut_calls.append(binding)
                    with access.admit(caller,fixture['wire'],'engineering.reviews.request',request_id='independent-frame-cut',trace_id='review') as ctx:
                        with source.guard_prepared_review(ctx,plan,request,assignment,prepared,binding,
                                actual_invocation=invocation,expected_invocation=native.fixture.invocation,
                                read_invocation=native.fixture.invocation,origin_task=origin_task,origin_thread=origin_thread):
                            yield
            prompt=fixture['execution'].source.freeze_prompt(reviewer.instance_ref,params_raw)
            receipt=await fixture['execution'].source.prompt_recorded(reviewer.instance_ref,prompt,
                request_id='independent-review-turn',engineering_attempt_ref='independent-review-attempt',
                invocation=native.fixture.invocation,write_guard=Cut(),deadline=asyncio.get_running_loop().time()+3)
            if verdict in ('native-unknown','revoked-before-cut'):
                replay=await fixture['execution'].source.prompt_recorded(reviewer.instance_ref,prompt,
                    request_id='independent-review-turn',engineering_attempt_ref='independent-review-attempt',
                    invocation=native.fixture.invocation,write_guard=Cut(),deadline=asyncio.get_running_loop().time()+3)
                assert replay.state=='unknown' and len(cut_calls)==1
            captured=records.capture(prepared,read_invocation=native.fixture.invocation)
        assert receipt.state==('unknown' if verdict in ('native-unknown','revoked-before-cut') else 'completed')
        execution=AgentExecutionRecordRef(prepared.agent_ref_bytes,prepared.turn_ref_bytes,native.prepared.source_revision,
            prepared.agent_operation_ref,'independent-review-attempt',Digest('sha256',prepared.prompt_input_digest[7:]),
            prepared.query_digest,captured.blob_ref)
        locator=AgentReportReviewLocator(SCOPE,plan.plan_digest,request.version,request.fence,assignment.ref,submission.ref,
            submission.execution_ref,submission.output_refs[0],execution,params_ref)
        raw=canonical_bytes(locator.projection()); raw_ref=env.blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
        fixture.update(caller=caller,review_service=service,review_source=source,review_bindings=bindings,
            review_plan=plan,review_request=request,assignment=assignment,locator=locator,raw_ref=raw_ref,
            review_standard=standard,submission=submission,package=package,work=work,assignments=assignments,physical_frames=physical,cut_calls=cut_calls)
        yield fixture


def test_actual_report_plan_preserves_original_target_full_criterion_and_original_issuer(tmp_path,monkeypatch):
    async def scenario():
        async with review_case(tmp_path,monkeypatch) as f:
            plan=f['review_plan']; standard=f['review_standard']; locator=f['locator']
            assert plan.requirement.expected_targets.targets[0].ref==f['submission'].ref
            assert plan.check_keys[0].criterion_id=='implementation-review' and len(plan.check_keys)==1
            assert standard.criteria[0].checks[0].capability_id=='engineering.reviewer.agent'
            expected=(actual_report.METHOD/'criteria/implementation-review.md').read_text()
            assert standard.criteria[0].statement==expected
            assert plan.reviewer_requirements==('reviewer',)
            assert plan.check_policies[0].required and plan.check_policies[0].blocking
            assert AgentReportReviewLocator.from_projection(locator.projection())==locator
            assert locator.author_execution_ref.agent_ref_bytes!=locator.reviewer_execution_ref.agent_ref_bytes
            for name in ('grant','roles','invocation','delivery_refs'):
                assert name not in locator.projection()
            assert decode_json((actual_report.METHOD/'schemas/agent-report-review-contract.json').read_bytes())==AGENT_REPORT_REVIEW_CONTRACT
            assert f['native'].records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==2
            assert f['physical_frames'].read_text().splitlines()==['frame','frame']
            assert len(f['cut_calls'])==1
            with f['access'].admit(f['caller'],f['wire'],'engineering.reviews.assign_reviewer',request_id='refuse-self-review',trace_id='review') as ctx:
                from ordessa_engineering.application.contracts.errors import ApplicationError
                with pytest.raises(ApplicationError,match='UNTRUSTED_REVIEWER'):
                    f['assignments'].assign_reviewer(ctx,review_id=plan.review_id,expected_plan_digest=plan.plan_digest,
                        request_version=f['review_request'].version,fence=f['review_request'].fence,
                        reviewer_agent_ref=f['submission'].execution_ref.agent_ref)
    asyncio.run(scenario())


def test_agent_report_dto_cannot_relabel_old_artifact_delivery_or_self_review():
    import runpy
    from pathlib import Path
    old=runpy.run_path(str(Path(__file__).parents[1]/'domain/test_agent_submission_report.py'))['fixture']()[0]
    author=AgentReportAuthorship(old.scope,old.method_content.schema_ref.method_ref,old.ref,old.execution_ref,old.output_refs[0])
    assert author.projection()['schemaVersion']=='engineering-agent-report-authorship/1'
    from ordessa_engineering.domain.reviews.assignments import ReviewerAssignmentRef
    assignment=ReviewerAssignmentRef(old.scope,'synthetic-assignment',Digest('sha256','a'*64))
    with pytest.raises(ReferenceError,match='UNTRUSTED_REVIEWER'):
        AgentReportReviewLocator(old.scope,Digest('sha256','b'*64),0,1,assignment,old.ref,
            old.execution_ref,old.output_refs[0],old.execution_ref,old.output_refs[0])
    with pytest.raises(ReferenceError):
        AgentReportAuthorship(old.scope,old.method_content.schema_ref.method_ref,old.ref,object(),old.output_refs[0])
