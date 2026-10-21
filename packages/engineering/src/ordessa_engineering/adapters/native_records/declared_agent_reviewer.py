"""Authenticate one captured independent Agent report review; never send/retry.

The original SDK lifecycle owns sends. This synchronous source checks its actual
turn, complete pinned prompt and live Engineering assignment, then retains the
original capability/method/assignment guards through the caller's COMMIT.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
from pathlib import Path
import asyncio
import threading

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...application.contracts.agent_report_review import (AgentReportReviewLocator,
    CAPABILITY, RESPONSE_SCHEMA)
from ...application.contracts.commands import ReadSet, ReadVersion
from ...application.contracts.errors import ApplicationError
from ...application.contracts.reviewer_admission import CriterionAnswer, VerifiedReviewResponse
from ...application.usecases.reviews.admission import review_observations
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.common.models.identity import ActorRef, Scope
from ...domain.common.models.refs import BlobRef
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.reviews.assignments import ReviewerAssignment
from ...domain.reviews.evidence import VerifiedReviewerEvidence
from ...domain.reviews.models import CurrentReviewTrust, observations_digest
from ...domain.reviews.refs import SubmissionRef
from ..declared_agent_implementation_review import DeclaredAgentImplementationReviewBindings
from .agent_execution import AgentExecutionConsumer, PreparedAgentInput


class DeclaredAgentReviewerSource:
    verifier_id='ordessa.declared-agent-report-records'
    verifier_version='1'

    def __init__(self,factory,*,access,scope,bindings,records,blobs,query_factory,review_paths):
        if (type(scope) is not Scope or getattr(getattr(factory,'library',None),'schema_version',None)!=17
                or type(bindings) is not DeclaredAgentImplementationReviewBindings
                or bindings.factory is not factory or type(records) is not AgentExecutionConsumer
                or records.blob_store is not blobs or bindings.report_source.records is not records
                or bindings.report_source.blobs is not blobs
                or getattr(blobs,'authority_id',None)!=factory.authority_id
                or not callable(query_factory) or not callable(getattr(access,'guard_current_capability',None))
                or type(review_paths) is not tuple):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        paths=tuple(Path(p) for p in review_paths)
        if any(not p.is_absolute() or p.resolve()!=p or any(part.is_symlink() for part in (p,*p.parents)) for p in paths):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory,self.access,self.scope=factory,access,scope
        self.bindings,self.methods,self.records,self.blobs=bindings,bindings.methods,records,blobs
        self.query_factory,self.review_paths=query_factory,frozenset(paths)

    @staticmethod
    def is_report(plan):
        targets=plan.requirement.expected_targets.targets
        return len(targets)==1 and targets[0].role=='primary' and type(targets[0].ref) is SubmissionRef

    def prompt_parameters(self,context,plan,request,assignment,session_id):
        if not self.is_report(plan) or type(session_id) is not str or not session_id:
            raise ApplicationError('AGENT_REPORT_REVIEW_TARGET_REQUIRED')
        with self.access.guard_current_capability(context,self.scope,CAPABILITY), self.methods.guard(context,plan.requirement.method_ref) as definition:
            selected=self.bindings.resolve_declared_submission_plan(context,plan,definition)
            with self.bindings.guard_authorship(context,plan) as author:
                if assignment.author_agent_ref_bytes!=author.author_execution_ref.agent_ref_bytes:
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                assignment.require_distinct_author()
                with self.factory.begin(context.scope,'read') as uow:
                    submission=uow.submissions.resolve(author.submission_ref)
                    package=uow.implementation.resolve_package(submission.package_ref)
                    documents=[{'role':doc.role,'source_ref':asdict(doc.source_ref),
                        'text':uow.implementation.read_prepared_document(package.ref,doc.role).decode('utf-8')}
                        for doc in package.payload.documents]
                resources={}
                for name in ('independent-review-prompt','implementation-review-criteria','profile-selection-prompt','agent-report-review-contract'):
                    exact=self.methods.resource_ref(context,plan.requirement.method_ref,name)
                    resources[name]={'ref':asdict(exact),'text':self.methods.read_resource(context,exact).decode('utf-8')}
                binding={'schemaVersion':'ordessa.agent-report-review-input/1','plan':asdict(plan),
                    'request_version':assignment.request_version,'fence':assignment.fence,
                    'assignment_ref':asdict(assignment.ref),'reviewer_agent_ref':assignment.reviewer_agent_ref,
                    'authorship':author.projection()}
                body={'package_ref':asdict(package.ref),'method_ref':asdict(plan.requirement.method_ref),
                    'documents':documents,'report':decode_json(self.blobs.read_verified(author.report_blob_ref)),
                    'released_resources':resources,'criterion':selected.standard.criteria[0].statement,
                    'transport_response':{'instruction':'Judge the complete pinned criterion independently. Return exactly '
                        'one JSON object with verdict, rationale and findings. Report claims are asserted. Do not edit '
                        'files or run commands. Missing evidence stays unknown; never invent passed checks.',
                        'schema':RESPONSE_SCHEMA}}
                return {'sessionId':session_id,'prompt':[{'type':'text','text':canonical_bytes(binding).decode('utf-8')},
                    {'type':'text','text':canonical_bytes(body).decode('utf-8')}]}

    @contextmanager
    def guard_prepared_review(self,context,plan,request,assignment,prepared,write_binding,*,
                              actual_invocation,expected_invocation,read_invocation,origin_task,origin_thread):
        """Additional business check at the ORIGINAL SDK's verified frame cut.

        No writer, ticket or SDK authority is returned. The original CurrentGuard
        has already matched the exact WriteBinding and original frame digest.
        This span is synchronous and surrounds only its bounded physical write.
        """
        from ordessa_agents.sdk.interactions import WriteBinding, TurnReceipt, BindingProvenance
        try:task=asyncio.current_task()
        except RuntimeError:task=None
        if (type(prepared) is not PreparedAgentInput or type(write_binding) is not WriteBinding
                or actual_invocation is not expected_invocation or expected_invocation is None
                or task is None or origin_task is not task or type(origin_thread) is not int
                or threading.get_ident()!=origin_thread or read_invocation is None):
            raise ApplicationError('AGENT_REVIEW_WRITE_BINDING_MISMATCH')
        WriteBinding.decode(write_binding.projection())
        with self.access.guard_current_capability(context,self.scope,CAPABILITY) as caller, \
                self.methods.guard(context,plan.requirement.method_ref) as definition:
            self.bindings.resolve_declared_submission_plan(context,plan,definition)
            with self.bindings.guard_authorship(context,plan) as author:
                with self.factory.begin(context.scope,'read') as uow:
                    current=uow.reviews.get_request(plan.review_id); original=uow.reviews.get_plan(plan.review_id)
                    active,control=uow.reviewer_assignments.active_for_review(plan.review_id)
                if (current!=request or current.state!='requested' or original!=plan
                        or type(active) is not ReviewerAssignment or active!=assignment or control.state!='active'
                        or active.plan_digest!=plan.plan_digest or active.method_ref!=plan.requirement.method_ref
                        or active.request_version!=request.version or active.fence!=request.fence
                        or active.roles!=tuple(sorted(plan.reviewer_requirements))
                        or active.issuer_principal_id!=getattr(caller,'principal_id',None)
                        or active.issuer_credential_epoch!=getattr(caller,'credential_epoch',None)
                        or active.author_agent_ref_bytes!=author.author_execution_ref.agent_ref_bytes
                        or active.reviewer_agent_ref_bytes!=prepared.agent_ref_bytes):
                    raise ApplicationError('REVIEW_REQUEST_CHANGED')
                active.require_distinct_author()
                provenance=self.records.read_agent_binding(decode_json(prepared.agent_ref_bytes),read_invocation=read_invocation)
                if (provenance.profile_ref!=self.bindings.expected_profile_ref
                        or provenance!=BindingProvenance.decode(decode_json(prepared.provenance_bytes))):
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                reserved=self.records.capture(prepared,read_invocation=read_invocation)
                receipt=TurnReceipt.decode(decode_json(self.blobs.read_verified(reserved.blob_ref)))
                expected=self.prompt_parameters(context,plan,request,assignment,prepared.session_id)
                if (reserved.state!='reserved' or receipt.state!='reserved' or receipt.endpoint_operation_ref is not None
                        or canonical_bytes(expected)!=prepared.prompt_bytes
                        or write_binding.turn_ref.projection()!=decode_json(prepared.turn_ref_bytes)
                        or write_binding.session_id!=prepared.session_id
                        or write_binding.agent_operation_ref!=prepared.agent_operation_ref
                        or write_binding.engineering_attempt_ref!=prepared.engineering_attempt_ref
                        or write_binding.input_digest!=prepared.prompt_input_digest
                        or write_binding.endpoint_request_id!=receipt.endpoint_request_id):
                    raise ApplicationError('AGENT_REVIEW_WRITE_BINDING_MISMATCH')
                # Final assignment COMMIT predicates remain the original owner;
                # the original library lock above is retained across this frame.
                yield

    def _read_only_frames(self,frames):
        if type(frames) is not list:raise ApplicationError('REVIEW_READ_ONLY_SCOPE_VIOLATION')
        permissions={}; updates={}
        def allowed(path):
            if type(path) is not str or not path or '..' in Path(path).parts:return False
            p=Path(path)
            return p.is_absolute() and p.resolve() in self.review_paths and not any(x.is_symlink() for x in (p,*p.parents))
        def refuse():raise ApplicationError('REVIEW_READ_ONLY_SCOPE_VIOLATION')
        for frame in frames:
            if type(frame) is not dict:refuse()
            if 'method' not in frame:continue
            method=frame['method'];params=frame.get('params')
            if type(params) is not dict:refuse()
            if method=='fs/read_text_file':
                if not allowed(params.get('path')):refuse()
            elif method=='session/request_permission':
                tool=params.get('toolCall',{}); tool_id=params.get('toolCallId')
                paths=params.get('files');locations=tool.get('locations')
                if (frame.get('id') is None or type(tool_id) is not str or not tool_id or tool_id in permissions
                        or params.get('approval')!='file' or tool.get('toolCallId')!=tool_id or tool.get('kind')!='read'
                        or type(paths) is not list or not paths or not all(allowed(p) for p in paths)
                        or type(locations) is not list or not locations
                        or not all(type(p) is dict and allowed(p.get('path')) for p in locations)
                        or type(params.get('options')) is not list
                        or sum(type(o) is dict and o.get('kind')=='allow_once' for o in params['options'])!=1):refuse()
                permissions[tool_id]=frozenset(paths)
            elif method=='session/update':
                item=params.get('update',{});kind=item.get('sessionUpdate')
                if kind in ('agent_message_chunk','agent_thought_chunk'):continue
                if kind not in ('tool_call','tool_call_update'):refuse()
                key=item.get('toolCallId'); paths=item.get('locations',[])
                if key not in permissions or item.get('kind','read')!='read' or not all(
                        type(p) is dict and allowed(p.get('path')) and p['path'] in permissions[key] for p in paths):refuse()
                state=item.get('status')
                if state not in ('pending','in_progress','completed'):refuse()
                if updates.get(key)=='completed':refuse()
                updates[key]=state
            else:refuse()
        if set(updates)!=set(permissions) or any(state!='completed' for state in updates.values()):refuse()

    @contextmanager
    def _guard(self,context,plan,raw_ref,standard,*,recording):
        try:
            if not self.is_report(plan) or context.scope!=self.scope or plan.scope!=context.scope or type(raw_ref) is not BlobRef:
                raise ApplicationError('AGENT_REPORT_REVIEW_TARGET_REQUIRED')
            with ExitStack() as guards:
                caller=guards.enter_context(self.access.guard_current_capability(context,self.scope,CAPABILITY))
                locator=AgentReportReviewLocator.from_projection(decode_json(self.blobs.read_verified(raw_ref)))
                definition=guards.enter_context(self.methods.guard(context,plan.requirement.method_ref))
                selected=self.bindings.resolve_declared_submission_plan(context,plan,definition)
                if selected.standard!=standard:raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                author=guards.enter_context(self.bindings.guard_authorship(context,plan))
                with self.factory.begin(context.scope,'read') as uow:
                    request=uow.reviews.get_request(plan.review_id); original=uow.reviews.get_plan(plan.review_id)
                    assignment,control=uow.reviewer_assignments.active_for_review(plan.review_id)
                version=locator.request_version
                if (locator.scope!=context.scope or locator.plan_digest!=plan.plan_digest or original!=plan
                        or locator.submission_ref!=author.submission_ref or locator.author_execution_ref!=author.author_execution_ref
                        or locator.report_blob_ref!=author.report_blob_ref
                        or request.fence!=locator.fence or (request.state,request.version)!=(
                            ('requested',version) if recording else ('recorded',version+1))
                        or type(assignment) is not ReviewerAssignment or control.state!='active'
                        or control.ref!=assignment.ref or assignment.ref!=locator.assignment_ref
                        or assignment.review_id!=plan.review_id or assignment.plan_digest!=plan.plan_digest
                        or assignment.method_ref!=plan.requirement.method_ref or assignment.request_version!=version
                        or assignment.fence!=locator.fence or assignment.roles!=tuple(sorted(plan.reviewer_requirements))
                        or assignment.issuer_principal_id!=getattr(caller,'principal_id',None)
                        or assignment.issuer_credential_epoch!=getattr(caller,'credential_epoch',None)
                        or assignment.author_agent_ref_bytes!=author.author_execution_ref.agent_ref_bytes
                        or assignment.reviewer_agent_ref_bytes!=locator.reviewer_execution_ref.agent_ref_bytes):
                    raise ApplicationError('SUBMISSION_REVIEW_ASSIGNMENT_MISMATCH')
                assignment.require_distinct_author()
                guards.enter_context(self.factory.guard_read_set(ReadSet(context.scope,(
                    ReadVersion('unit_reviewer_assignment',assignment.assignment_id,control.version),))))
                execution=locator.reviewer_execution_ref
                invocation=self.query_factory(context,execution)
                provenance=self.records.read_agent_binding(execution.agent_ref,read_invocation=invocation)
                if (provenance.profile_ref!=self.bindings.expected_profile_ref or provenance.source_revision!=execution.source_revision):
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                captured=self.records.capture_reference(execution,read_invocation=invocation)
                if (captured.state!='completed' or captured.authority_id!=self.factory.authority_id
                        or captured.blob_ref!=execution.captured_observation_ref or not captured.report_text):
                    raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
                from ordessa_agents.sdk.interactions import TurnReceipt
                receipt=TurnReceipt.decode(decode_json(self.blobs.read_verified(captured.blob_ref)))
                params=decode_json(self.blobs.read_verified(locator.params_ref))
                expected=self.prompt_parameters(context,plan,request,assignment,receipt.session_id)
                if canonical_bytes(params)!=canonical_bytes(expected):raise ApplicationError('REVIEW_REQUEST_CHANGED')
                if self.records.prompt_input_digest(execution,params)!='sha256:'+execution.prompt_input_digest.hex:
                    raise ApplicationError('REVIEW_REQUEST_CHANGED')
                protocol=decode_json(receipt.observation_bytes).get('protocol',{})
                frames=protocol.get('frames'); self._read_only_frames(frames)
                responses=[f for f in frames if 'method' not in f]
                if (protocol.get('protocolId')!='acp' or 'reason' in protocol or receipt.state!='completed'
                        or len(responses)!=1 or responses[0].get('jsonrpc')!='2.0'
                        or responses[0].get('id')!=execution.operation_ref or 'error' in responses[0]
                        or type(responses[0].get('result')) is not dict or responses[0]['result'].get('stopReason')!='end_turn'):
                    raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
                judgement=decode_json(captured.report_text.encode('utf-8'))
                if (not Draft202012Validator(RESPONSE_SCHEMA).is_valid(judgement)
                        or not judgement['rationale'].strip() or len(plan.check_keys)!=1):
                    raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
                status={'passed':'satisfied','rejected':'violated','cancelled':'unknown','unknown':'unknown'}[judgement['verdict']]
                answers=(CriterionAnswer(plan.check_keys[0],status,(),judgement['rationale']+'\n'+'\n'.join(judgement['findings'])),)
                observations=review_observations(plan,standard,answers)
                actor=ActorRef(record_digest('agent-reviewer-actor',{'agent_ref':assignment.reviewer_agent_ref,
                    'assignment':asdict(assignment.ref)}).hex,'agent','ordessa-agent-records')
                capability=record_digest('declared-agent-report-review',{'assignment':asdict(assignment.ref),
                    'principal_id':caller.principal_id,'credential_epoch':caller.credential_epoch,
                    'roles':assignment.roles,'authorship':author.projection(),'locator':locator.projection(),
                    'profile_ref':asdict(self.bindings.expected_profile_ref)})
                evidence=VerifiedReviewerEvidence(context.scope,actor,assignment.roles,self.verifier_id,self.verifier_version,
                    control.version,plan.request_digest,raw_ref.digest,observations_digest(observations),capability)
                yield request,assignment,control,VerifiedReviewResponse(evidence,answers)
        except ApplicationError:raise
        except ReferenceError as error:raise ApplicationError(error.code) from error
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError) as error:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from error

    def verify_response(self,context,plan,request,raw_response_ref,*,standard):
        with self._guard(context,plan,raw_response_ref,standard,recording=True) as facts:
            if facts[0]!=request:raise ApplicationError('REVIEW_REQUEST_CHANGED')
            return facts[3]

    @contextmanager
    def guard_trust(self,context,records):
        current=[]
        with ExitStack() as guards:
            for record in records:
                with self.factory.begin(context.scope,'read') as uow:request=uow.reviews.get_request(record.plan.review_id)
                recording=request.state=='requested'
                if recording:self.access.require(context,'engineering.reviews.record')
                with self.methods.guard(context,record.plan.requirement.method_ref) as definition:
                    standard=self.bindings.resolve_declared_submission_plan(context,record.plan,definition).standard
                facts=guards.enter_context(self._guard(context,record.plan,record.raw_response_ref,standard,recording=recording))
                if facts[3].reviewer_evidence!=record.reviewer_evidence:raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref,self.verifier_id,facts[2].version))
            yield tuple(current)
