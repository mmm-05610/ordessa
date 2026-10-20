"""Declared report/review/disposition steps on the original Work journal.

The existing trusted plan factory may provide ``implementation_plan``. The
original review runner and ReviewAdmission still own native evidence and trust;
missing producers keep the complete action unavailable. No Artifact adoption,
checkout scan, new store, automatic rework, or replacement reviewer lives here.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import inspect

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..contracts.errors import ApplicationError
from ..contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from ..usecases.changes.declared_acceptance import resolve_declared_review
from ..usecases.reviews.service import _trust
from ..usecases.support import clock
from .steps.declared_implementation_dispatch import (
    _grant_facts, _report_only_disposition_grant_facts)
from .report_only_disposition import ReportOnlyDispositionPermit
from ...domain.artifacts.models import MethodContent
from ...domain.changes.models import ChangeSet
from ...domain.changes.submission import ExecutionRecordRef, Submission, SubmissionCoverage
from ...domain.changes.submission_codec import submission_projection
from ...domain.changes.dispatch_codec import decode_dispatch
from ...domain.common.mechanisms.codec import decode_blob_ref
from ...domain.common.models.refs import BlobRef
from ...domain.common.models.values import Digest
from ...domain.reviews.codec import encode_plan
from ...domain.reviews.models import ReviewPlan
from ...domain.reviews.ref_codec import decode_review_ref
from ...domain.reviews.target_codec import decode_subject_ref
from ...domain.reviews.targets import Target, TargetSet


RESULT_STEPS = frozenset({'independently-review-report',
    'resolve-one-operation-disposition', 'record-operation-result'})


class DeclaredImplementationResults:
    def __init__(self, factory, *, method_guard, blobs, plan_factory, review_run,
                 review_admission, dispatch, agent_records=None, agent_query_factory=None):
        self.factory, self.methods, self.blobs = factory, method_guard, blobs
        self.plans, self.review_run = plan_factory, review_run
        self.admission, self.dispatch = review_admission, dispatch
        self.agent_records, self.agent_query_factory = agent_records, agent_query_factory

    @property
    def runnable(self):
        return (self.factory is not None
            and getattr(self.methods, 'factory', None) is self.factory
            and getattr(self.blobs, 'authority_id', None) == getattr(self.factory, 'authority_id', None)
            and getattr(self.plans, 'factory', None) is self.factory
            and callable(getattr(self.plans, 'implementation_plan', None))
            and callable(self.review_run)
            and getattr(self.admission, 'factory', None) is self.factory
            and callable(getattr(getattr(self.admission, 'bindings', None),
                                 'resolve_declared_submission_plan', None))
            and all(callable(getattr(self.admission, name, None))
                    for name in ('guard_plan', 'verify_response', 'guard_trust')))

    @staticmethod
    def _completed(answer):
        if getattr(answer, 'status', None) != 'completed':
            raise ApplicationError('WORK_ACTION_STEP_REJECTED')
        return answer.result

    def report_record(self, context, work, native):
        """Build only an authored report; the original submission command admits it."""
        if (type(native) is dict and type(native.get('binding')) is dict
                and native['binding'].get('schemaVersion') == 'engineering-agent-work-dispatch-binding/1'):
            return self._agent_report_record(context, work, native)
        binding = decode_dispatch(canonical_bytes(native['binding']))
        capture = decode_blob_ref(native['observation_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.by_operation(binding.execution_operation_ref, context.scope)
            if (decode_dispatch(row['binding_bytes']) != binding or row['dispatch_phase'] != 'completed'
                    or binding.work['work_id'] != work.work_id):
                raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
            package = uow.implementation.resolve_package(binding.package_ref)
        receipt = self.blobs.read_verified(capture)
        if len(receipt) > MAX_EXECUTION_RECEIPT_BYTES:
            raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
        value = decode_json(decode_json(receipt)['summary']['text'].encode('utf-8'))
        raw = canonical_bytes(value)
        report_blob = self.blobs.put_verified(raw,
            Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
        with self.methods.guard(context, work.method_ref):
            schema = self.methods.resource_ref(context, work.method_ref, 'implementation-report-schema')
        payload = package.payload
        unit = decode_json(binding.unit_ref_bytes)
        record = Submission(context.scope,
            'work-report-' + hashlib.sha256(binding.execution_operation_ref.encode()).hexdigest()[:40],
            context.received_at, context.authenticated_actor, ChangeSet((payload.change_ref,)),
            (binding.approval_ref,), package.ref,
            ExecutionRecordRef(unit['environmentNamespace'], unit['unitId'],
                canonical_bytes(unit['ownerProviderRef']), unit['sourceRevision'],
                binding.execution_operation_ref, binding.prompt_input_digest, capture),
            (), (), (), (), (report_blob,), (), (),
            (SubmissionCoverage(payload.change_ref, (report_blob,), (), (), 'implemented'),),
            (payload.baseline, payload.candidate),
            method_content=MethodContent.from_value(schema, value, rendered_body_ref=report_blob),
            schema_version=2)
        return submission_projection(record)

    def _agent_report_record(self, context, work, native):
        """Current Work consumer: capture the original Agent turn, never a Unit alias."""
        from ...domain.changes.agent_dispatch import AgentWorkDispatchBinding
        from ...domain.changes.agent_dispatch_codec import decode_agent_dispatch
        from ...domain.changes.agent_submission_report import AgentSubmissionReport
        if (getattr(self.agent_records, 'blob_store', None) is not self.blobs
                or not callable(getattr(self.agent_records, 'capture_dispatch', None))
                or not callable(self.agent_query_factory)):
            raise ApplicationError('SUBMISSION_AGENT_REPORT_SOURCE_UNAVAILABLE')
        binding = decode_agent_dispatch(canonical_bytes(native['binding']))
        capture = decode_blob_ref(native['observation_ref'])
        if (type(binding) is not AgentWorkDispatchBinding or binding.scope != context.scope
                or work.scope != context.scope or native.get('phase') != 'completed'
                or binding.work['work_id'] != work.work_id):
            raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.by_operation(binding.engineering_attempt_ref, context.scope)
            if (decode_agent_dispatch(row['binding_bytes']) != binding or row['dispatch_phase'] != 'completed'
                    or row['run_id'] != binding.run_id or row['step_id'] != binding.step_id
                    or row['attempt'] != binding.attempt or row['dispatch_fence'] != binding.fence
                    or row['execution_operation_ref'] != binding.engineering_attempt_ref
                    or row['result_blob_json'] != canonical_bytes(asdict(capture)).decode('utf-8')):
                raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
            _grant_facts(uow, binding.work['work_id'], binding.work['action_id'], binding.step_id,
                clock.utc_now(), binding=binding)
            package = uow.implementation.resolve_package(binding.package_ref)
        if package.payload.method_ref != work.method_ref:
            raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
        invocation = self.agent_query_factory(binding)
        if invocation is None:
            raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        execution, observed = self.agent_records.capture_dispatch(binding, read_invocation=invocation)
        if (observed.state != 'completed' or observed.blob_ref != capture
                or execution.captured_observation_ref != capture
                or execution.agent_ref_bytes != binding.agent_ref_bytes or observed.agent_ref_bytes != binding.agent_ref_bytes
                or execution.turn_ref_bytes != binding.turn_ref_bytes or observed.turn_ref_bytes != binding.turn_ref_bytes
                or execution.engineering_attempt_ref != binding.engineering_attempt_ref
                or observed.engineering_attempt_ref != binding.engineering_attempt_ref
                or observed.operation_ref != execution.operation_ref
                or observed.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
                or observed.query_digest != binding.expected_query_digest
                or observed.authority_id != self.factory.authority_id or not observed.report_text):
            raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
        try:
            value = decode_json(observed.report_text.encode('utf-8'))
        except (ValueError, TypeError, UnicodeError):
            raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID') from None
        raw = canonical_bytes(value)
        report_blob = self.blobs.put_verified(raw, Digest('sha256',hashlib.sha256(raw).hexdigest()), 'application/json')
        with self.methods.guard(context, work.method_ref):
            schema = self.methods.resource_ref(context,work.method_ref,'implementation-report-schema')
        payload = package.payload
        record = AgentSubmissionReport(context.scope,
            'work-report-' + hashlib.sha256(binding.engineering_attempt_ref.encode()).hexdigest()[:40],
            context.received_at,context.authenticated_actor,ChangeSet((payload.change_ref,)),
            (binding.approval_ref,),package.ref,execution,(report_blob,),
            (SubmissionCoverage(payload.change_ref,(report_blob,),(),(),'implemented'),),
            (payload.baseline,payload.candidate),
            MethodContent.from_value(schema,value,rendered_body_ref=report_blob))
        return submission_projection(record)

    @staticmethod
    def requirement_id(work, submission_ref, reviewer_profile):
        digest = hashlib.sha256(canonical_bytes({'work_id': work.work_id,
            'revision': work.revision, 'method_ref': asdict(work.method_ref),
            'submission_ref': asdict(submission_ref), 'reviewer_profile': reviewer_profile})).hexdigest()
        return 'implementation-review-' + digest[:40]

    async def request_review(self, context, work, report, reviewer_profile, *,
                             review_id, step_id, resources):
        if not self.runnable:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_REVIEW_UNAVAILABLE')
        subject = decode_subject_ref(report['submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            submission = uow.submissions.resolve(subject)
            package = uow.implementation.resolve_package(submission.package_ref)
        expected_id = self.requirement_id(work, subject, reviewer_profile)
        plan = self.plans.implementation_plan(context, work, review_id=review_id,
            submission=submission, package=package, reviewer_profile_ref=reviewer_profile,
            requirement_id=expected_id, resources=resources)
        if (type(plan) is not ReviewPlan or plan.review_id != review_id
                or plan.requirement.requirement_id != expected_id
                or plan.requirement.schema_version != 2
                or plan.requirement.purpose != 'acceptance'
                or plan.requirement.method_ref != work.method_ref
                or plan.requirement.phase_key != step_id
                or plan.requirement.expected_targets != TargetSet((Target('primary', subject),))):
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        self._completed(await self.dispatch('engineering.reviews.request',
            {'plan': decode_json(encode_plan(plan))}, context))
        with self.factory.begin(context.scope, 'read') as uow:
            request = uow.reviews.get_request(review_id)
        raw_ref = self.review_run(context, plan, request)
        if inspect.isawaitable(raw_ref):
            raw_ref = await raw_ref
        if type(raw_ref) is not BlobRef:
            raise ApplicationError('WORK_ACTION_REVIEW_RESULT_UNCONFIRMED')
        raw = self.blobs.read_verified(raw_ref)
        return {'review_id': review_id, 'request_version': request.version,
            'fence': request.fence, 'raw_response_utf8': raw.decode('utf-8'),
            'submission_ref': asdict(subject), 'reviewer_profile': reviewer_profile}

    async def record_review(self, context, contract):
        answer = self._completed(await self.dispatch('engineering.reviews.record',
            {key: contract[key] for key in ('review_id', 'request_version', 'fence',
                                           'raw_response_utf8')}, context))
        return {'review_ref': answer['review_ref'],
            'submission_ref': contract['submission_ref'],
            'reviewer_profile': contract['reviewer_profile']}

    @contextmanager
    def guard_disposition(self, context, work, report, review_result, *, review_step_id,
                          report_only_permit=None):
        if (report_only_permit is not None
                and type(report_only_permit) is not ReportOnlyDispositionPermit):
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        subject = decode_subject_ref(report['submission_ref'])
        review_ref = decode_review_ref(review_result['review_ref'])
        if review_result['submission_ref'] != asdict(subject):
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        with self.factory.begin(context.scope, 'read') as uow:
            closure = resolve_declared_review(uow, work, subject, review_ref,
                                             review_step_id=review_step_id)
            from ..usecases.changes.dispatch_continuation import (
                resolve_continuation_root, verify_continuation_reservation)
            root = resolve_continuation_root(uow, closure.binding) or closure.binding
        if closure.review.plan.requirement.requirement_id != self.requirement_id(
                work, subject, review_result['reviewer_profile']):
            raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH')
        with self.methods.guard(context, work.method_ref), \
                self.admission.guard_plan(context, closure.review.plan), \
                self.admission.guard_trust(context, (closure.review,)) as trust:
            _trust((closure.review,), trust)
            review = closure.review
            disposition = ('accepted' if review.complete and review.verdict == 'pass'
                else 'rejected' if review.complete and review.verdict == 'fail' else 'unknown')
            # Rejection may propose one explicit further operation. This result
            # grants no execution, does not re-send, and does not bypass a Grant.
            rework = None
            if disposition == 'rejected' and root.attempt == 1:
                rework = {'package_ref': asdict(closure.package.ref),
                    'operation_ref': closure.binding.execution_operation_ref,
                    'review_ref': asdict(review.ref), 'max_additional_attempts': 1,
                    'requires_caller_approval': True, 'automatic_retry': False}
            result = {'work_id': work.work_id, 'work_revision': work.revision,
                'method_ref': asdict(work.method_ref), 'submission_ref': asdict(subject),
                'package_ref': asdict(closure.package.ref), 'review_ref': asdict(review.ref),
                'implementation_operation_ref': closure.binding.execution_operation_ref,
                'disposition': disposition, 'accepted': disposition == 'accepted',
                'rework_request': rework, 'retry_allowed': False}

            def validate(uow):
                current = resolve_declared_review(uow, work, subject, review_ref,
                                                 review_step_id=review_step_id)
                current_root = verify_continuation_reservation(uow, current.binding) or current.binding
                if current != closure or current_root != root:
                    raise ApplicationError('SUBMISSION_REVIEW_BINDING_CHANGED')
                now = clock.utc_now()
                if report_only_permit is None:
                    _grant_facts(uow, work.work_id, closure.binding.work['action_id'],
                        closure.binding.step_id, now, binding=closure.binding)
                else:
                    _report_only_disposition_grant_facts(uow, work.work_id,
                        closure.binding.work['action_id'], closure.binding.step_id,
                        now, binding=closure.binding, permit=report_only_permit,
                        context=report_only_permit.context, work=work,
                        submission_ref=subject, review_ref=review.ref)

            yield result, validate
