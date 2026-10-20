"""One-shot report-content rework consumption on the original Engineering owners.

The consumer creates no authority. It delegates report qualification and
checkpoint validation to the original submission source, requires a separately
selected caller-approval guard, and uses the original CommandJournal and Work
tail owners for the only permitted report and review operations.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import datetime
import hashlib
from typing import Any, Mapping

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ..contracts.commands import CommandContext, CommandResult
from ..contracts.errors import ApplicationError
from ...domain.common.models.refs import BlobRef
from ...domain.common.models.values import Digest
from ...domain.common.mechanisms.codec import decode_blob_ref
from ...domain.common.mechanisms.hashing import record_digest
from .report_only_disposition import ReportOnlyDispositionPermit


_CLAIM_OPERATION = 'engineering.report_content_rework.claim'
_CLAIM_OPERATION_ID = 'report-content-rework-claim/'
_APPROVAL_CONTRACT = 'ordessa.report-content-rework-approval/1'
_APPROVAL_FIELDS = frozenset({'contract', 'plan_ref', 'principal_id', 'decision',
                              'not_before', 'expires_at', 'max_uses'})
_PREPARE_FIELDS = frozenset({'invoke_parameters', 'origin', 'supplement_refs'})
_COMPLETE_FIELDS = frozenset({'invoke_parameters', 'plan_ref', 'approval_ref',
                              'checkpoint_ref'})
_ORIGIN_FIELDS = frozenset({'parent_operation_id', 'expected_parent_version',
                            'review_ref', 'submission_ref'})


def _contains_session_id(value):
    """Native session identity is assigned by the selected Unit owner."""
    if type(value) is dict:
        return any(key == 'sessionId' or _contains_session_id(item)
                   for key, item in value.items())
    if type(value) is list:
        return any(_contains_session_id(item) for item in value)
    return False


class ReportContentReworkConsumer:
    """Consume one explicitly approved report-content rework on an old Work."""

    def __init__(self, service):
        self.service = service

    def _admit(self, invoke_parameters, context):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        access = getattr(self.service, '_access', None)
        if access is None or access.current_context() is not context:
            raise ApplicationError('REPORT_CONTENT_REWORK_CONTEXT_REQUIRED')
        access.require(context, 'engineering.work.invoke')
        works = getattr(self.service, '_works', None)
        if not callable(getattr(works, '_input', None)):
            raise ApplicationError('REPORT_CONTENT_REWORK_OWNER_UNAVAILABLE')
        value, reads, digest = works._input('engineering.work.invoke', invoke_parameters,
                                             context, None)
        return value, reads, digest

    def _source(self):
        source_owner = self.service._report_correction_source()
        source = getattr(source_owner, 'content_rework', None)
        required = ('prepare_plan', 'load_plan', 'prompt', 'validate_checkpoint',
                    'record', 'guard_report', 'review_evidence', 'review_materials',
                    'claim_key', 'claim_digest', 'claim_operation_id')
        if (source is None or any(not callable(getattr(source, name, None))
                                  for name in required)):
            raise ApplicationError('REPORT_CONTENT_REWORK_SOURCE_UNAVAILABLE')
        return source_owner, source

    def _approval_port(self, source_owner):
        approval = getattr(source_owner, 'content_rework_approval', None)
        if approval is None:
            return None
        if (getattr(approval, 'factory', None) is not self.service._factory
                or getattr(approval, 'access', None) is not self.service._access
                or getattr(approval, 'blobs', None) is not self.service._blobs
                or not callable(getattr(approval, 'guard', None))):
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_UNAVAILABLE')
        return approval

    @contextmanager
    def _checked_approval(self, approval, context, plan_ref, expected_ref=None):
        if approval is None:
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_REQUIRED')
        access = self.service._access
        if access.current_context() is not context:
            raise ApplicationError('REPORT_CONTENT_REWORK_CONTEXT_REQUIRED')
        access.require(context, 'engineering.work.invoke')
        with approval.guard(context, plan_ref=plan_ref) as ref:
            if type(ref) is not BlobRef or expected_ref is not None and ref != expected_ref:
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
            raw = self.service._blobs.read_verified(ref)
            if (type(raw) is not bytes or len(raw) != ref.byte_length
                    or hashlib.sha256(raw).hexdigest() != ref.digest.hex):
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
            try:
                proof = decode_json(raw)
            except Exception as error:
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID') from error
            if (type(proof) is not dict or set(proof) != _APPROVAL_FIELDS
                    or proof.get('contract') != _APPROVAL_CONTRACT
                    or proof.get('plan_ref') != asdict(plan_ref)
                    or proof.get('principal_id') != context.principal_id
                    or proof.get('decision') != 'approved'
                    or type(proof.get('max_uses')) is not int or proof['max_uses'] != 1
                    or canonical_bytes(proof) != raw):
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
            try:
                not_before = datetime.fromisoformat(proof['not_before'].replace('Z', '+00:00'))
                expires_at = datetime.fromisoformat(proof['expires_at'].replace('Z', '+00:00'))
                received_at = datetime.fromisoformat(context.received_at.replace('Z', '+00:00'))
            except (AttributeError, TypeError, ValueError) as error:
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID') from error
            if (not_before.tzinfo is None or expires_at.tzinfo is None or received_at.tzinfo is None
                    or not not_before <= received_at < expires_at):
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_EXPIRED')
            yield ref

    def _plan(self, source, result):
        if type(result) is not dict or set(result) != {'plan_ref', 'plan', 'operation_ref'}:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        plan_ref = result['plan_ref']
        if type(plan_ref) is not BlobRef:
            try:
                plan_ref = decode_blob_ref(plan_ref)
            except Exception as error:
                raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID') from error
        if (type(result['plan']) is not dict
                or result['operation_ref'] != 'report-content-rework/' + plan_ref.digest.hex):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        return plan_ref, result['plan']

    @staticmethod
    def _claim_identity(source, plan, plan_ref, approval_ref):
        from ..contracts.commands import CommandKey
        key = source.claim_key(plan)
        digest = source.claim_digest(plan_ref, approval_ref)
        if type(key) is not CommandKey or type(digest) is not Digest:
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
        origin = plan.get('origin')
        operation = origin.get('execution_operation_ref') if type(origin) is dict else None
        if type(operation) is not str or not operation:
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
        operation_id = source.claim_operation_id(plan)
        expected = _CLAIM_OPERATION_ID + hashlib.sha256(operation.encode('utf-8')).hexdigest()
        if type(operation_id) is not str or operation_id != expected:
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
        return key, digest, operation_id

    def _claim(self, source, plan, plan_ref, approval_ref, context):
        key, digest, operation_id = self._claim_identity(source, plan, plan_ref, approval_ref)
        if (key.realm_id != context.scope.realm_id
                or key.principal_id != context.principal_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
        with self.service._factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(key, project_id=context.scope.project_id,
                operation=_CLAIM_OPERATION, operation_id=operation_id,
                request_digest=digest)
            entry = reservation.entry
            if (entry.operation != _CLAIM_OPERATION or entry.operation_id != operation_id
                    or entry.request_digest != digest or entry.project_id != context.scope.project_id):
                raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_CONFLICT')
            uow.commit()
        return key, digest, operation_id, reservation

    @staticmethod
    def _command_result(factory, entry):
        if entry.state != 'completed' or entry.result_bytes is None:
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
        return CommandResult(factory.authority_id, entry.operation_id, entry.state,
                             entry.result_bytes)

    def _work(self, value, context):
        work, view = self.service._report_correction_work(context, value)
        declared, action_inputs, resources = self.service._report_correction_tail_inputs(
            context, value, work, view)
        return work, view, declared, action_inputs, resources

    def prepare(self, parameters, context):
        if type(parameters) is not dict or set(parameters) != _PREPARE_FIELDS:
            raise ApplicationError('REPORT_CONTENT_REWORK_INPUT_INVALID')
        value, _reads, invoke_digest = self._admit(parameters['invoke_parameters'], context)
        origin = parameters['origin']
        if (type(origin) is not dict or set(origin) != _ORIGIN_FIELDS
                or type(origin['parent_operation_id']) is not str or not origin['parent_operation_id']
                or type(origin['expected_parent_version']) is not int
                or origin['expected_parent_version'] < 0
                or type(parameters['supplement_refs']) is not list):
            raise ApplicationError('REPORT_CONTENT_REWORK_INPUT_INVALID')
        work, _view, _declared, _action_inputs, _resources = self._work(value, context)
        source_owner, source = self._source()
        plan_result = source.prepare_plan(context, work=work, invoke_digest=invoke_digest,
            origin=origin, supplement_refs=parameters['supplement_refs'])
        plan_ref, plan = self._plan(source, plan_result)
        approval = self._approval_port(source_owner)
        if approval is None:
            return {'state': 'approval_required', 'plan_ref': asdict(plan_ref),
                    'operation_ref': plan_result['operation_ref'], 'params': None}
        with self._checked_approval(approval, context, plan_ref) as approval_ref:
            _key, _digest, operation_id, reservation = self._claim(
                source, plan, plan_ref, approval_ref, context)
            entry = reservation.entry
            if entry.state == 'completed':
                return self._command_result(self.service._factory, entry)
            if not reservation.created:
                return {'state': 'pending_query_only', 'operation_id': operation_id,
                        'operation_ref': plan_result['operation_ref'],
                        'plan_ref': asdict(plan_ref), 'approval_ref': asdict(approval_ref),
                        'params': None}
            params = source.prompt(context, plan_ref, approval_ref)
            if type(params) is not dict or _contains_session_id(params):
                raise ApplicationError('REPORT_CONTENT_REWORK_PROMPT_INVALID')
            return {'state': 'ready', 'operation_id': operation_id,
                    'operation_ref': plan_result['operation_ref'],
                    'plan_ref': asdict(plan_ref), 'approval_ref': asdict(approval_ref),
                    'params': params}

    async def complete(self, parameters, context):
        if type(parameters) is not dict or set(parameters) != _COMPLETE_FIELDS:
            raise ApplicationError('REPORT_CONTENT_REWORK_INPUT_INVALID')
        value, _reads, _digest = self._admit(parameters['invoke_parameters'], context)
        work, view, declared, action_inputs, resources = self._work(value, context)
        source_owner, source = self._source()
        approval = self._approval_port(source_owner)
        if approval is None:
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_REQUIRED')
        try:
            plan_ref = decode_blob_ref(parameters['plan_ref'])
            approval_ref = decode_blob_ref(parameters['approval_ref'])
            checkpoint_ref = decode_blob_ref(parameters['checkpoint_ref'])
        except Exception as error:
            raise ApplicationError('REPORT_CONTENT_REWORK_INPUT_INVALID') from error
        plan = source.load_plan(context, plan_ref)
        if type(plan) is not dict:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        if plan.get('origin', {}).get('parent_request_digest') != asdict(_digest):
            raise ApplicationError('REPORT_CONTENT_REWORK_PARENT_CONFLICT')
        with self._checked_approval(approval, context, plan_ref,
                                    expected_ref=approval_ref):
            key, claim_digest, claim_operation_id = self._claim_identity(
                source, plan, plan_ref, approval_ref)
            if (key.realm_id != context.scope.realm_id
                    or key.principal_id != context.principal_id):
                raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
            with self.service._factory.begin(context.scope, 'read') as uow:
                claim = uow.commands.get(key)
                authority_id = uow.authority_id
            if claim is None or claim.operation != _CLAIM_OPERATION:
                raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_REQUIRED')
            if (claim.project_id != context.scope.project_id
                    or claim.operation_id != claim_operation_id
                    or claim.request_digest != claim_digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_CONFLICT')
            if claim.state == 'completed':
                if claim.result_bytes is None:
                    raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')
                completed = decode_json(claim.result_bytes)
                link = completed.get('report_content_rework') if type(completed) is dict else None
                if (type(link) is not dict or link.get('plan_ref') != asdict(plan_ref)
                        or link.get('approval_ref') != asdict(approval_ref)
                        or link.get('checkpoint_ref') != asdict(checkpoint_ref)):
                    raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_CONFLICT')
                return self._command_result(self.service._factory, claim)
            if claim.state != 'pending':
                raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_INVALID')

        validated_plan, binding, original_observation = source.validate_checkpoint(
            context, checkpoint_ref=checkpoint_ref, fresh=True)
        origin = plan.get('origin')
        if (validated_plan != plan or type(origin) is not dict
                or origin.get('work_id') != work.work_id
                or origin.get('work_revision') != work.revision
                or origin.get('action_id') != value.get('action_id')
                or binding.execution_operation_ref != origin.get('execution_operation_ref')
                or binding.work.get('work_id') != work.work_id
                or binding.work.get('action_id') != value.get('action_id')):
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        record_key = 'rework-record-' + plan_ref.digest.hex[:48]
        with self.service._work_step_admission(context,
                'engineering.submissions.record_report', record_key) as child:
            with self.service._factory.begin(context.scope, 'read') as uow:
                prior_record = uow.commands.get(child.key)
            if prior_record is None:
                record_projection = source.record(child, checkpoint_ref=checkpoint_ref)
                result = await self.service.execute(
                    'engineering.submissions.record_report',
                    {'record': record_projection}, child)
                stored = self.service._implementation_results._completed(result)
            else:
                if (prior_record.operation != 'engineering.submissions.record_report'
                        or prior_record.state != 'completed'):
                    raise ApplicationError('REPORT_CONTENT_REWORK_RECONCILE_REQUIRED')
                stored = decode_json(prior_record.result_bytes)
        from ...domain.reviews.target_codec import decode_subject_ref
        from ...domain.reviews.refs import SubmissionRef
        from ..usecases.changes.declared_report import resolve_declared_report_binding
        submission_ref = decode_subject_ref(stored['submission_ref'])
        if type(submission_ref) is not SubmissionRef:
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        with self.service._factory.begin(context.scope, 'read') as uow:
            registered = uow.submissions.resolve(submission_ref)
            if (resolve_declared_report_binding(uow, registered) != binding
                    or registered.checkpoint_ref != checkpoint_ref
                    or registered.submission_id != 'content-rework-' + plan_ref.digest.hex[:40]):
                raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')

        first, review_step, disposition_step, record_step = declared['steps']
        from ...domain.changes.dispatch_codec import encode_dispatch
        observation_blob = getattr(original_observation, 'blob_ref', original_observation)
        if type(observation_blob) is not BlobRef:
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        report = {'binding': decode_json(encode_dispatch(binding)),
            'observation_ref': asdict(observation_blob),
            'params_assembly': 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT',
            'phase': 'completed', 'reason': None, 'engineering_completed': False,
            'accepted': False, 'submission_ref': asdict(submission_ref)}
        tail_suffix = hashlib.sha256(canonical_bytes({
            'plan_ref': asdict(plan_ref), 'approval_ref': asdict(approval_ref)})).hexdigest()
        from ..contracts.commands import CommandKey
        tail_key = CommandKey(context.scope.realm_id, context.principal_id,
            'report-content-rework-tail-' + tail_suffix[:48])
        tail_operation = 'engineering.report_content_rework.tail'
        tail_digest = record_digest('report-content-rework-tail', {
            'claim_key': asdict(key), 'claim_digest': asdict(claim_digest),
            'checkpoint_ref': asdict(checkpoint_ref),
            'submission_ref': asdict(submission_ref)})
        with self._checked_approval(approval, context, plan_ref,
                                    expected_ref=approval_ref):
            with self.service._factory.begin(context.scope) as uow:
                current_claim = uow.commands.get(key)
                if current_claim != claim:
                    raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_CONFLICT')
                tail_reservation = uow.commands.reserve(tail_key,
                    project_id=context.scope.project_id, operation=tail_operation,
                    operation_id='report-content-rework-tail/' + tail_suffix,
                    request_digest=tail_digest)
                tail_entry = tail_reservation.entry
                if (tail_entry.operation != tail_operation
                        or tail_entry.operation_id != 'report-content-rework-tail/' + tail_suffix
                        or tail_entry.request_digest != tail_digest
                        or tail_entry.project_id != context.scope.project_id):
                    raise ApplicationError('REPORT_CONTENT_REWORK_TAIL_CONFLICT')
                if tail_entry.state != 'pending':
                    # The global claim and tail complete atomically below.
                    # An occupied completed tail with a pending claim is not
                    # enough evidence to resume an external review operation.
                    raise ApplicationError('REPORT_CONTENT_REWORK_RECONCILE_REQUIRED')
                uow.commit()
        review_suffix = tail_suffix
        review_request = 'rework-review-' + review_suffix[:48]
        review_record_request = 'rework-review-record-' + review_suffix[:40]
        review_key = CommandKey(context.scope.realm_id, context.principal_id,
                                review_record_request)
        with self.service._factory.begin(context.scope, 'read') as uow:
            prior_review = uow.commands.get(review_key)
        if prior_review is not None:
            if (prior_review.operation != 'engineering.reviews.record'
                    or prior_review.state != 'completed'):
                raise ApplicationError('REPORT_CONTENT_REWORK_RECONCILE_REQUIRED')
            prior = decode_json(prior_review.result_bytes)
            review_result = {'review_ref': prior['review_ref'],
                'submission_ref': asdict(submission_ref),
                'reviewer_profile': action_inputs['reviewer_profile']}
            review_operation_id = prior_review.operation_id
        else:
            if not tail_reservation.created:
                raise ApplicationError('REPORT_CONTENT_REWORK_RECONCILE_REQUIRED')
            with self.service._factory.begin(context.scope, 'read') as uow:
                try:
                    uow.reviews.get_request('report-content-rework-review-' + review_suffix)
                except ApplicationError as error:
                    if error.code != 'NOT_FOUND':
                        raise
                else:
                    raise ApplicationError('REPORT_CONTENT_REWORK_RECONCILE_REQUIRED')
            payload = {}
            for item in review_step['inputs']:
                if item['source_kind'] == 'action_input':
                    payload[item['name']] = action_inputs[item['source_name']]
                elif item['source_kind'] == 'step_output':
                    if (item['step_id'] != first['step_id']
                            or item['source_name'] != 'implementation_report'):
                        raise ApplicationError('REPORT_CONTENT_REWORK_METHOD_UNSUPPORTED')
                    payload[item['name']] = report
                else:
                    payload[item['name']] = resources[(review_step['step_id'], item['name'])]
            with self.service._work_step_admission(context,
                    'engineering.reviews.request', review_request) as child:
                contract = await self.service._implementation_results.request_review(
                    child, work, payload['report'], payload['reviewer_profile'],
                    review_id='report-content-rework-review-' + review_suffix,
                    step_id=review_step['step_id'], resources=payload)
            with self.service._work_step_admission(context,
                    'engineering.reviews.record', review_record_request) as child:
                review_result = await self.service._implementation_results.record_review(
                    child, contract)
                review_operation_id = self.service._works.read_command_operation_id(child)

        with ExitStack() as guards:
            from ...domain.reviews.ref_codec import decode_review_ref
            origin = plan['origin']
            parent_key = CommandKey(origin['parent_key']['realm_id'],
                origin['parent_key']['principal_id'], origin['parent_key']['request_id'])
            parent_digest = Digest(origin['parent_request_digest']['algorithm'],
                                   origin['parent_request_digest']['hex'])
            permit = ReportOnlyDispositionPermit(
                approval_port=approval, factory=self.service._factory,
                access=self.service._access, blobs=self.service._blobs,
                context=context, plan_ref=plan_ref, approval_ref=approval_ref,
                parent_operation_id=origin['parent_operation_id'],
                parent_key=parent_key, parent_request_digest=parent_digest,
                parent_version=origin['parent_version'], work_id=work.work_id,
                work_revision=work.revision, binding=binding,
                origin_review_ref=decode_review_ref(origin['review_ref']),
                source_submission_ref=decode_subject_ref(origin['source_submission_ref']),
                submission_ref=submission_ref,
                review_ref=decode_review_ref(review_result['review_ref']),
                claim_key=key, claim_operation_id=claim_operation_id,
                claim_digest=claim_digest, tail_key=tail_key,
                tail_operation_id='report-content-rework-tail/' + tail_suffix,
                tail_digest=tail_digest)
            with self.service._work_step_admission(context, 'engineering.reviews.record',
                    'rework-disposition-' + review_suffix[:40]) as child:
                method_result, validate_disposition = guards.enter_context(
                    self.service._implementation_results.guard_disposition(
                        child, work, report, review_result,
                        review_step_id=review_step['step_id'],
                        report_only_permit=permit))
                method_result = dict(method_result)
                method_result['rework_request'] = None

            # Leave the child operation lease before asking the source to
            # revalidate under the original parent caller context.
            current_plan, current_binding, current_observation = source.validate_checkpoint(
                context, checkpoint_ref=checkpoint_ref, fresh=True)
            if (current_plan != plan or current_binding != binding
                    or current_observation != original_observation):
                raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_CHANGED')
            from ..usecases.queries.works import GUARD_STEP
            steps = ({'step_id': first['step_id'], 'kind': first['kind'],
                'operation': 'engineering.executions.dispatch', 'journal_request_id': None,
                'operation_id': binding.execution_operation_ref, 'state': 'completed',
                'completion_semantics': 'historical_business_execution_preserved',
                'business': report},
                {'step_id': review_step['step_id'], 'kind': review_step['kind'],
                 'operation': 'engineering.reviews.record',
                 'journal_request_id': review_record_request,
                 'operation_id': review_operation_id, 'state': 'completed',
                 'completion_semantics': 'independent_report_review_recorded_not_acceptance',
                 'business': review_result},
                {'step_id': disposition_step['step_id'], 'kind': disposition_step['kind'],
                 'operation': GUARD_STEP, 'journal_request_id': None,
                 'operation_id': None, 'state': 'completed',
                 'completion_semantics': 'method_disposition_pending_journal_commit',
                 'business': method_result},
                {'step_id': record_step['step_id'], 'kind': record_step['kind'],
                 'operation': GUARD_STEP, 'journal_request_id': None,
                 'operation_id': None, 'state': 'completed',
                 'completion_semantics': 'method_result_in_content_rework_claim',
                 'business': method_result})
            outcome = {'work_id': work.work_id, 'action_id': value['action_id'],
                'revision': work.revision, 'state': 'completed',
                'method_result': method_result, 'steps': steps,
                'report_content_rework': {'plan_ref': asdict(plan_ref),
                    'approval_ref': asdict(approval_ref),
                    'checkpoint_ref': asdict(checkpoint_ref),
                    'origin_parent_operation_id': plan['origin']['parent_operation_id'],
                    'origin_review_ref': plan['origin']['review_ref'],
                    'new_submission_ref': asdict(submission_ref)}}
            outcome_bytes = canonical_bytes(outcome)
            with self.service._factory.begin(context.scope) as uow:
                validate_disposition(uow)
                current_claim = uow.commands.get(key)
                current_tail = uow.commands.get(tail_key)
                if (current_claim != claim or current_tail != tail_entry
                        or current_claim.state != 'pending'
                        or current_tail.state != 'pending'):
                    raise ApplicationError('REPORT_CONTENT_REWORK_PARENT_CONFLICT')
                uow.commands.complete(tail_key, expected_version=current_tail.version,
                    result_bytes=canonical_bytes({'claim_operation_id': claim_operation_id,
                        'review_operation_id': review_operation_id}), state='completed')
                uow.commands.complete(key, expected_version=current_claim.version,
                    result_bytes=outcome_bytes, state='completed')
                authority_id = uow.authority_id
                with permit.guard_commit():
                    uow.commit()
        return CommandResult(authority_id, claim_operation_id, 'completed', outcome_bytes)
