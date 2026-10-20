"""Bounded report-content rework over a registered format-correction report.

The source reuses the original Work, Submission, Review, UnitRecords and
BlobStore owners. It never edits a repository or claims that verification ran.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.errors import ApplicationError
from ...contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from .execution_capture import capture_execution_observation
from ....domain.common.mechanisms.codec import canonical_value, decode_blob_ref
from ....domain.common.mechanisms.hashing import record_digest
from ....domain.common.models.refs import BlobRef
from ....domain.common.models.values import Digest
from ....domain.reviews.ref_codec import decode_review_ref
from ....domain.reviews.target_codec import decode_subject_ref
from ....domain.reviews.refs import ReviewRef, SubmissionRef
from ....domain.artifacts.models import MethodContent
from ....domain.changes.submission import SubmissionCoverage
from ....application.contracts.work_context import work_binding_projection
from .declared_report import (CORRECTION_LIMITATION, _as_ref, _decode_digest,
    _digest_of, _profile, _require_same_blob_bytes, _check_readonly_capture,
    resolve_declared_report_binding, _method_ref)


CONTENT_REWORK_CONTRACT = 'ordessa.declared-report-content-rework/1'
PLAN_CONTRACT = 'ordessa.declared-report-content-rework-plan/1'
OPERATION = 'engineering.report_content_rework.claim'
KEY_PREFIX = 'report-content-rework-'
CLAIM_OPERATION_PREFIX = 'report-content-rework-claim/'
REPORT_OPERATION_PREFIX = 'report-content-rework/'
UNRERUN_NOTE = 'This report content rework did not rerun verification.'
LIMITS = {'report_only': True, 'max_attempts': 1,
          'edit_repository': 0, 'run_checks': 0}
PLAN_FIELDS = frozenset({'contract', 'origin', 'materials', 'limits'})
ORIGIN_FIELDS = frozenset({'parent_key', 'parent_operation_id', 'parent_request_digest',
    'parent_version', 'review_ref', 'submission_ref', 'work_id', 'work_revision',
    'work_digest', 'action_id', 'step_id', 'package_ref', 'method_ref', 'profile_ref',
    'author_unit_ref', 'binding_digest', 'dispatch_version', 'execution_operation_ref',
    'source_submission_ref', 'source_checkpoint_ref', 'observation_ref',
    'observation_revision'})
MATERIAL_FIELDS = frozenset({'files', 'original_check_observation', 'supplement_refs'})
CHECKPOINT_FIELDS = frozenset({'contract', 'plan_ref', 'approval_ref', 'report'})
REPORT_FIELDS = frozenset({'unit_ref', 'operation_ref', 'prompt_input_digest',
    'observation_ref', 'observation_revision', 'output_ref', 'stop_record_digest',
    'release_record_digest'})
APPROVAL_CONTRACT = 'ordessa.report-content-rework-approval/1'
APPROVAL_FIELDS = frozenset({'contract', 'plan_ref', 'principal_id', 'decision',
    'not_before', 'expires_at', 'max_uses'})


def _blob(value):
    return value if type(value) is BlobRef else decode_blob_ref(value)


def _original_check(source):
    """Project a source already verified in this call; retain its limitations."""
    return {'contract': 'ordessa.original-check-observation/1',
        'checkpoint_ref': asdict(source['checkpoint_ref']), 'plan_ref': asdict(source['plan_ref']),
        'origin_operation_ref': source['binding'].execution_operation_ref,
        'journal_ref': asdict(source['journal_ref']), 'excerpt_ref': asdict(source['excerpt_ref']),
        'tool_call_id': source['tool_call_id'], 'command_digest': asdict(source['command_digest']),
        'command_utf8': source['command'], 'excerpt_utf8': source['excerpt_raw'].decode('utf-8', errors='strict'),
        'files': source['plan']['evidence']['files'], 'limitation': CORRECTION_LIMITATION}


def _scope_check(context, reference):
    return (reference.realm_id == context.scope.realm_id
            and reference.project_id == context.scope.project_id)


def _claim_identity(plan):
    origin = plan.get('origin') if type(plan) is dict else None
    if (type(origin) is not dict or set(origin) != ORIGIN_FIELDS
            or type(origin.get('parent_key')) is not dict
            or set(origin['parent_key']) != {'realm_id', 'principal_id', 'request_id'}
            or type(origin.get('execution_operation_ref')) is not str
            or not origin['execution_operation_ref']):
        raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
    key = origin['parent_key']
    suffix = hashlib.sha256(origin['execution_operation_ref'].encode('utf-8')).hexdigest()[:48]
    full_digest = hashlib.sha256(origin['execution_operation_ref'].encode('utf-8')).hexdigest()
    from ...contracts.commands import CommandKey
    return (CommandKey(key['realm_id'], key['principal_id'], KEY_PREFIX + suffix),
            CLAIM_OPERATION_PREFIX + full_digest)


def claim_key(plan):
    """Stable original-business-key claim identity, independent of Review/plan."""
    return _claim_identity(plan)[0]


def claim_operation_id(plan):
    """Stable CommandJournal operation id for the original business operation."""
    return _claim_identity(plan)[1]


def claim_digest(plan_ref, approval_ref):
    """Digest of one plan/approval pair for the original-operation claim."""
    plan_ref, approval_ref = _blob(plan_ref), _blob(approval_ref)
    if type(approval_ref) is not BlobRef:
        raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
    return record_digest('report-content-rework-claim', {
        'plan_ref': asdict(plan_ref), 'approval_ref': asdict(approval_ref)})


@dataclass(frozen=True, slots=True)
class _ReportContentReviewCutPermit:
    """Prepared immutable identity for one later native review byte cut.

    Constructed only by ``ReportContentReworkSource.guard_review`` after its
    full checkpoint/proof/claim/tail checks. It carries no affirmative result:
    the approval port is entered again at the byte cut, and current claim/tail
    state is checked in the runtime's existing fresh read transaction.
    """
    source: object
    approval: object
    context: object
    scope: object
    principal_id: str
    plan_ref: BlobRef
    approval_ref: BlobRef
    checkpoint_ref: BlobRef
    submission_ref: SubmissionRef
    review_id: str
    plan_digest: object
    request_version: int
    request_fence: int
    claim_key: object
    claim_operation_id: str
    claim_digest: object
    claim_version: int
    tail_key: object
    tail_operation_id: str
    tail_digest: object
    tail_version: int

    @contextmanager
    def guard_native_prompt(self, context, plan, request):
        if (context is not self.context or context.scope != self.scope
                or context.principal_id != self.principal_id
                or plan.review_id != self.review_id
                or plan.plan_digest != self.plan_digest
                or request.version != self.request_version
                or request.fence != self.request_fence):
            raise ApplicationError('REPORT_CONTENT_REWORK_REVIEW_PERMIT_INVALID')
        with self.approval.guard(context, plan_ref=self.plan_ref) as selected:
            if type(selected) is not BlobRef or selected != self.approval_ref:
                raise ApplicationError('REPORT_CONTENT_REWORK_REVIEW_PERMIT_INVALID')
            yield

    def validate_current(self, uow, context, plan, request, submission):
        """Check mutable journal rows alongside the runtime's fresh review read."""
        if (context is not self.context or context.scope != self.scope
                or context.principal_id != self.principal_id
                or plan.review_id != self.review_id
                or plan.plan_digest != self.plan_digest
                or request.version != self.request_version
                or request.fence != self.request_fence
                or submission.ref != self.submission_ref
                or submission.checkpoint_ref != self.checkpoint_ref):
            raise ApplicationError('REPORT_CONTENT_REWORK_REVIEW_PERMIT_INVALID')
        claim = uow.commands.get(self.claim_key)
        tail = uow.commands.get(self.tail_key)
        if (claim is None or claim.key != self.claim_key or claim.operation != OPERATION
                or claim.operation_id != self.claim_operation_id
                or claim.request_digest != self.claim_digest
                or claim.project_id != context.scope.project_id
                or claim.state != 'pending' or claim.version != self.claim_version
                or tail is None or tail.key != self.tail_key
                or tail.operation != 'engineering.report_content_rework.tail'
                or tail.operation_id != self.tail_operation_id
                or tail.request_digest != self.tail_digest
                or tail.project_id != context.scope.project_id
                or tail.state != 'pending' or tail.version != self.tail_version):
            raise ApplicationError('REPORT_CONTENT_REWORK_TAIL_CONFLICT')


class ReportContentReworkSource:
    """Source-side plan, report Unit, checkpoint, registration and review facts."""
    claim_key = staticmethod(claim_key)
    claim_digest = staticmethod(claim_digest)
    claim_operation_id = staticmethod(claim_operation_id)

    def __init__(self, owner):
        if (owner is None or getattr(owner, 'factory', None) is None
                or getattr(owner, 'methods', None) is None
                or getattr(owner, 'blobs', None) is None
                or getattr(owner, 'correction_ports', None) is None):
            raise ApplicationError('REPORT_CONTENT_REWORK_UNAVAILABLE')
        self.owner = owner
        self.factory, self.methods, self.blobs = owner.factory, owner.methods, owner.blobs
        self.ports = owner.correction_ports

    def _authorize(self, context):
        from ....application.contracts.commands import CommandContext
        if type(context) is not CommandContext:
            raise ApplicationError('REPORT_CONTENT_REWORK_ACCESS_DENIED')
        self.ports.access.require(context, 'engineering.work.invoke')

    def _authorize_review(self, context):
        from ....application.contracts.commands import CommandContext
        if type(context) is not CommandContext:
            raise ApplicationError('REPORT_CONTENT_REWORK_ACCESS_DENIED')
        denial = None
        for operation in ('engineering.reviews.request', 'engineering.reviews.record',
                          'engineering.reviews.assign_reviewer', 'engineering.work.invoke'):
            try:
                self.ports.access.require(context, operation)
                return
            except ApplicationError as error:
                denial = error
        if denial is not None:
            raise denial
        raise ApplicationError('REPORT_CONTENT_REWORK_ACCESS_DENIED')

    def _authorize_record(self, context):
        from ....application.contracts.commands import CommandContext
        if type(context) is not CommandContext:
            raise ApplicationError('REPORT_CONTENT_REWORK_ACCESS_DENIED')
        self.ports.access.require(context, 'engineering.submissions.record_report')

    def _verify_approval_and_claim(self, context, plan_ref, approval_ref, plan):
        approval = getattr(self.owner, 'content_rework_approval', None)
        if (approval is None or getattr(approval, 'factory', None) is not self.factory
                or getattr(approval, 'access', None) is not self.ports.access
                or getattr(approval, 'blobs', None) is not self.blobs
                or not callable(getattr(approval, 'guard', None))):
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_REQUIRED')
        raw = self.blobs.read_verified(approval_ref)
        _require_same_blob_bytes(self.blobs, approval_ref, raw,
                                 'REPORT_CONTENT_REWORK_APPROVAL_INVALID')
        try:
            proof = decode_json(raw)
            not_before = datetime.fromisoformat(proof['not_before'].replace('Z', '+00:00'))
            expires_at = datetime.fromisoformat(proof['expires_at'].replace('Z', '+00:00'))
            received_at = context.received_at
            if type(received_at) is str:
                received_at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID') from None
        if (type(proof) is not dict or set(proof) != APPROVAL_FIELDS
                or proof.get('contract') != APPROVAL_CONTRACT
                or proof.get('plan_ref') != asdict(plan_ref)
                or proof.get('principal_id') != context.principal_id
                or proof.get('decision') != 'approved'
                or type(proof.get('max_uses')) is not int or proof['max_uses'] != 1
                or not_before.tzinfo is None or expires_at.tzinfo is None
                or received_at.tzinfo is None or not not_before <= received_at < expires_at
                or canonical_bytes(proof) != raw):
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
        key = claim_key(plan)
        digest = claim_digest(plan_ref, approval_ref)
        operation_id = claim_operation_id(plan)
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(key)
        if (entry is None or entry.key != key or entry.operation != OPERATION
                or entry.operation_id != operation_id or entry.request_digest != digest
                or entry.project_id != context.scope.project_id
                or entry.state not in {'pending', 'completed'}):
            raise ApplicationError('REPORT_CONTENT_REWORK_CLAIM_REQUIRED')
        return entry

    def _plan(self, plan_ref):
        plan_ref = _blob(plan_ref)
        if plan_ref.byte_length > 2 * 1024 * 1024:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        raw = self.blobs.read_verified(plan_ref)
        _require_same_blob_bytes(self.blobs, plan_ref, raw,
                                 'REPORT_CONTENT_REWORK_PLAN_INVALID')
        try:
            plan = decode_json(raw)
        except Exception:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID') from None
        if (type(plan) is not dict or set(plan) != PLAN_FIELDS
                or plan.get('contract') != PLAN_CONTRACT
                or plan.get('limits') != LIMITS
                or type(plan.get('origin')) is not dict
                or set(plan['origin']) != ORIGIN_FIELDS
                or type(plan.get('materials')) is not dict
                or set(plan['materials']) != MATERIAL_FIELDS):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        materials = plan['materials']
        files = materials.get('files')
        selected_paths = self.owner._correction_paths(self.ports)
        if (type(files) is not list or not files
                or any(type(item) is not dict or set(item) != {'path', 'blob_ref'}
                       or type(item.get('path')) is not str for item in files)
                or [item['path'] for item in files] != sorted(selected_paths)
                or type(materials.get('supplement_refs')) is not list
                or len(materials['supplement_refs']) > 16
                or type(materials.get('original_check_observation')) is not dict):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        for item in files:
            ref = _blob(item['blob_ref'])
            content = self.blobs.read_verified(ref)
            if (type(content) is not bytes or len(content) != ref.byte_length
                    or _digest_of(content) != ref.digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        for value in materials['supplement_refs']:
            _blob(value)
        seen_supplements, total = set(), 0
        for value in materials['supplement_refs']:
            ref = _blob(value)
            if ref in seen_supplements:
                raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
            raw_material = self.blobs.read_verified(ref)
            total += len(raw_material)
            if (type(raw_material) is not bytes or len(raw_material) != ref.byte_length
                    or _digest_of(raw_material) != ref.digest or total > 2 * 1024 * 1024):
                raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
            try:
                raw_material.decode('utf-8', errors='strict')
            except UnicodeError:
                raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID') from None
            seen_supplements.add(ref)
        check = materials['original_check_observation']
        if (set(check) != {'contract', 'checkpoint_ref', 'plan_ref', 'origin_operation_ref',
                'journal_ref', 'excerpt_ref', 'tool_call_id', 'command_digest',
                'command_utf8', 'excerpt_utf8', 'files', 'limitation'}
                or check.get('contract') != 'ordessa.original-check-observation/1'
                or check.get('limitation') != CORRECTION_LIMITATION):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        if canonical_bytes(plan) != raw:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        return plan_ref, plan

    def _registered_origin(self, context, work, invoke_digest, origin):
        from ....application.contracts.work_context import WorkBinding
        if (type(work) is not WorkBinding or type(invoke_digest) is not Digest
                or type(origin) is not dict or set(origin) != {
                    'parent_operation_id', 'expected_parent_version', 'review_ref', 'submission_ref'}
                or type(origin['parent_operation_id']) is not str or not origin['parent_operation_id']
                or type(origin['expected_parent_version']) is not int
                or type(origin['expected_parent_version']) is bool
                or origin['expected_parent_version'] < 0):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        try:
            review_ref = origin['review_ref'] if type(origin['review_ref']) is ReviewRef else decode_review_ref(origin['review_ref'])
            submission_ref = (origin['submission_ref'] if type(origin['submission_ref']) is SubmissionRef
                              else decode_subject_ref(origin['submission_ref']))
        except Exception:
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID') from None
        if type(submission_ref) is not SubmissionRef or not _scope_check(context, review_ref) or not _scope_check(context, submission_ref):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        with self.factory.begin(context.scope, 'read') as uow:
            parent = uow.commands.find_operation(context.scope, origin['parent_operation_id'],
                operation='engineering.work.invoke')
            submission = uow.submissions.resolve(submission_ref)
            controlled = uow.reviews.get_review(review_ref)
            request = uow.reviews.get_request(review_ref.review_id)
            plan = uow.reviews.get_plan(review_ref.review_id)
        try:
            parent_result = decode_json(parent.result_bytes) if parent is not None else None
        except Exception:
            parent_result = None
        parent_method = (parent_result.get('method_result')
                         if type(parent_result) is dict else None)
        parent_report = (parent_result.get('report_correction')
                         if type(parent_result) is dict else None)
        source = self.owner._registered_correction(context, submission)
        binding, package = source['binding'], source['package']
        if (parent is None or parent.version != origin['expected_parent_version']
                or parent.state not in {'completed', 'rejected'}
                or parent.request_digest != invoke_digest
                or parent.project_id != context.scope.project_id
                or parent.key.realm_id != context.scope.realm_id
                or parent.key.principal_id != context.principal_id
                or request.state != 'recorded'
                or controlled.record.ref != review_ref or controlled.control.state != 'active'
                or controlled.record.plan != plan or not controlled.record.complete
                or controlled.record.verdict != 'fail'
                or plan.requirement.purpose != 'acceptance'
                or plan.requirement.method_ref != package.payload.method_ref
                or len(plan.requirement.expected_targets.targets) != 1
                or plan.requirement.expected_targets.targets[0].role != 'primary'
                or plan.requirement.expected_targets.targets[0].ref != submission_ref
                or submission.checkpoint_ref is None
                or submission.execution_ref.operation_ref != binding.execution_operation_ref
                or binding.package_ref != submission.package_ref
                or work.work_id != binding.work['work_id']
                or work.method_ref != package.payload.method_ref
                or _digest_of(canonical_bytes(work_binding_projection(work))) !=
                    _decode_digest(source['plan']['origin']['work_digest'])
                or type(parent_method) is not dict
                or parent_method.get('disposition') != 'rejected'
                or parent_method.get('review_ref') != asdict(review_ref)
                or parent_method.get('submission_ref') != asdict(submission_ref)
                or parent_method.get('implementation_operation_ref') != binding.execution_operation_ref
                or type(parent_report) is not dict
                or parent_report.get('submission_ref') != asdict(submission_ref)
                or parent_report.get('plan_ref') != asdict(source['plan_ref'])
                or parent_report.get('checkpoint_ref') != asdict(submission.checkpoint_ref)):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        if (source['submission'] != submission or source['binding'] != binding
                or source['checkpoint_ref'] != submission.checkpoint_ref
                or source['plan']['origin']['work_revision'] != work.revision
                or source['plan']['origin']['work_id'] != work.work_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        return parent, controlled, request, submission, package, binding, source

    def prepare_plan(self, context, *, work, invoke_digest, origin, supplement_refs):
        self._authorize(context)
        resolved = self._registered_origin(context, work, invoke_digest, origin)
        parent, controlled, request, submission, package, binding, source = resolved
        if type(supplement_refs) not in (tuple, list) or len(supplement_refs) > 16:
            raise ApplicationError('REPORT_CONTENT_REWORK_SUPPLEMENT_INVALID')
        supplements, total = [], 0
        seen = set()
        for value in supplement_refs:
            ref = _blob(value)
            raw = self.blobs.read_verified(ref)
            if (ref in seen or type(raw) is not bytes or len(raw) != ref.byte_length
                    or _digest_of(raw) != ref.digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_SUPPLEMENT_INVALID')
            try:
                text = raw.decode('utf-8', errors='strict')
            except UnicodeError:
                raise ApplicationError('REPORT_CONTENT_REWORK_SUPPLEMENT_INVALID') from None
            total += len(raw)
            if total > 2 * 1024 * 1024:
                raise ApplicationError('REPORT_CONTENT_REWORK_SUPPLEMENT_INVALID')
            seen.add(ref)
            supplements.append({'ref': asdict(ref), 'text': text})
        observation = _original_check(source)
        materials = {'files': source['plan']['evidence']['files'],
            'original_check_observation': observation,
            'supplement_refs': [item['ref'] for item in supplements]}
        plan_body = {'contract': PLAN_CONTRACT,
            'origin': {'parent_key': asdict(parent.key),
                'parent_operation_id': parent.operation_id,
                'parent_request_digest': asdict(parent.request_digest),
                'parent_version': parent.version,
                'review_ref': asdict(controlled.record.ref),
                'submission_ref': asdict(submission.ref),
                'work_id': work.work_id, 'work_revision': work.revision,
                'work_digest': asdict(_digest_of(canonical_bytes(
                    work_binding_projection(work)))),
                'action_id': binding.work['action_id'], 'step_id': binding.step_id,
                'package_ref': asdict(binding.package_ref),
                'method_ref': asdict(package.payload.method_ref),
                'profile_ref': source['plan']['origin']['profile_ref'],
                'author_unit_ref': decode_json(binding.unit_ref_bytes),
                'binding_digest': asdict(binding.digest),
                'dispatch_version': source['plan']['origin']['dispatch_version'],
                'execution_operation_ref': binding.execution_operation_ref,
                'source_submission_ref': asdict(submission.ref),
                'source_checkpoint_ref': asdict(submission.checkpoint_ref),
                'observation_ref': asdict(submission.execution_ref.captured_observation_ref),
                'observation_revision': source['original_receipt']['revision']},
            'materials': materials, 'limits': dict(LIMITS)}
        # Enforce the exact closed origin contract and derive one immutable plan.
        if set(plan_body['origin']) != ORIGIN_FIELDS:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        raw = canonical_bytes(plan_body)
        plan_ref = self.blobs.put_verified(raw, _digest_of(raw), 'application/json')
        if (type(plan_ref) is not BlobRef or plan_ref.digest != _digest_of(raw)
                or plan_ref.byte_length != len(raw) or plan_ref.media_type != 'application/json'):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        _require_same_blob_bytes(self.blobs, plan_ref, raw,
                                 'REPORT_CONTENT_REWORK_PLAN_INVALID')
        return {'plan_ref': asdict(plan_ref), 'plan': plan_body,
                'operation_ref': REPORT_OPERATION_PREFIX + plan_ref.digest.hex}

    def load_plan(self, context, plan_ref):
        self._authorize(context)
        ref, plan = self._plan(plan_ref)
        if (plan['origin']['parent_key']['realm_id'] != context.scope.realm_id
                or plan['origin']['parent_key']['principal_id'] != context.principal_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        self._verify_plan_origin(context, plan)
        return plan

    def _verify_plan_origin(self, context, plan):
        origin = plan['origin']
        source_ref = _subject(origin['source_submission_ref'])
        review_ref = decode_review_ref(origin['review_ref'])
        if (not _scope_check(context, source_ref) or not _scope_check(context, review_ref)
                or origin['submission_ref'] != asdict(source_ref)
                or origin['parent_key']['realm_id'] != context.scope.realm_id
                or origin['parent_key']['principal_id'] != context.principal_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        with self.factory.begin(context.scope, 'read') as uow:
            submission = uow.submissions.resolve(source_ref)
            controlled = uow.reviews.get_review(review_ref)
            request = uow.reviews.get_request(review_ref.review_id)
            parent = uow.commands.find_operation(context.scope, origin['parent_operation_id'],
                operation='engineering.work.invoke')
        try:
            parent_result = decode_json(parent.result_bytes) if parent is not None else None
        except Exception:
            parent_result = None
        parent_method = (parent_result.get('method_result')
                         if type(parent_result) is dict else None)
        parent_report = (parent_result.get('report_correction')
                         if type(parent_result) is dict else None)
        source = self.owner._registered_correction(context, submission)
        binding, package = source['binding'], source['package']
        if (parent is None or parent.state not in {'completed', 'rejected'}
                or parent.operation_id != origin['parent_operation_id']
                or parent.version != origin['parent_version']
                or parent.request_digest != _decode_digest(origin['parent_request_digest'])
                or asdict(parent.key) != origin['parent_key']
                or type(parent_method) is not dict
                or parent_method.get('disposition') != 'rejected'
                or parent_method.get('review_ref') != origin['review_ref']
                or parent_method.get('submission_ref') != origin['source_submission_ref']
                or parent_method.get('implementation_operation_ref') != origin['execution_operation_ref']
                or type(parent_report) is not dict
                or parent_report.get('submission_ref') != origin['source_submission_ref']
                or parent_report.get('checkpoint_ref') != origin['source_checkpoint_ref']
                or request.state != 'recorded'
                or controlled.record.ref != review_ref or controlled.control.state != 'active'
                or not controlled.record.complete or controlled.record.verdict != 'fail'
                or controlled.record.plan.requirement.purpose != 'acceptance'
                or controlled.record.plan.requirement.method_ref != package.payload.method_ref
                or len(controlled.record.plan.requirement.expected_targets.targets) != 1
                or controlled.record.plan.requirement.expected_targets.targets[0].role != 'primary'
                or controlled.record.plan.requirement.expected_targets.targets[0].ref != source_ref
                or source['submission'] != submission
                or source['checkpoint_ref'] != _blob(origin['source_checkpoint_ref'])
                or submission.checkpoint_ref != _blob(origin['source_checkpoint_ref'])
                or submission.execution_ref.operation_ref != origin['execution_operation_ref']
                or binding.execution_operation_ref != origin['execution_operation_ref']
                or binding.digest != _decode_digest(origin['binding_digest'])
                or binding.package_ref != package.ref
                or package.payload.method_ref != _method_ref(origin['method_ref'])
                or origin['review_ref'] != asdict(controlled.record.ref)
                or origin['work_digest'] != source['plan']['origin']['work_digest']
                or origin['action_id'] != source['plan']['origin']['action_id']
                or origin['step_id'] != source['plan']['origin']['step_id']
                or origin['package_ref'] != source['plan']['origin']['package_ref']
                or origin['profile_ref'] != source['plan']['origin']['profile_ref']
                or origin['author_unit_ref'] != source['plan']['origin']['author_unit_ref']
                or origin['dispatch_version'] != source['plan']['origin']['dispatch_version']
                or origin['observation_ref'] != source['plan']['origin']['observation_ref']
                or origin['observation_revision'] != source['plan']['origin']['observation_revision']
                or source['plan']['origin']['work_id'] != origin['work_id']
                or source['plan']['origin']['work_revision'] != origin['work_revision']
                or source['plan']['evidence']['files'] != plan['materials']['files']
                or _original_check(source) != plan['materials']['original_check_observation']):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        return submission, package, binding, source, controlled

    def prompt(self, context, plan_ref, approval_ref):
        self._authorize(context)
        ref, plan = self._plan(plan_ref)
        if (plan['origin']['parent_key']['realm_id'] != context.scope.realm_id
                or plan['origin']['parent_key']['principal_id'] != context.principal_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        approval_ref = _blob(approval_ref)
        approval_raw = self.blobs.read_verified(approval_ref)
        _require_same_blob_bytes(self.blobs, approval_ref, approval_raw,
                                 'REPORT_CONTENT_REWORK_APPROVAL_INVALID')
        return self._prompt_params(context, ref, plan, approval_ref)

    def _prompt_params(self, context, plan_ref, plan, approval_ref, *, source_facts=None,
                       schema_document=None):
        origin = plan['origin']
        source_ref = _blob(origin['source_checkpoint_ref'])
        submission, package, _binding, source, controlled = (
            self._verify_plan_origin(context, plan) if source_facts is None else source_facts)
        if source['checkpoint_ref'] != source_ref:
            raise ApplicationError('REPORT_CONTENT_REWORK_PLAN_INVALID')
        old_report = submission.method_content.value
        failed_review = {'record': controlled.record.projection(),
                         'control': asdict(controlled.control)}
        raw_review = b''
        if controlled.record.raw_response_ref is not None:
            response_ref = controlled.record.raw_response_ref
            raw_review = self.blobs.read_verified(response_ref)
            if (type(raw_review) is not bytes or len(raw_review) != response_ref.byte_length
                    or _digest_of(raw_review) != response_ref.digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
            failed_review['raw_response_utf8'] = raw_review.decode('utf-8', errors='strict')
        files = []
        for item in plan['materials']['files']:
            ref = _blob(item['blob_ref'])
            raw = self.blobs.read_verified(ref)
            if len(raw) != ref.byte_length or _digest_of(raw) != ref.digest:
                raise ApplicationError('REPORT_CONTENT_REWORK_MATERIALS_INVALID')
            files.append({'path': item['path'], 'text': raw.decode('utf-8', errors='strict')})
        supplements = []
        for value in plan['materials']['supplement_refs']:
            supplement_ref = _blob(value)
            raw = self.blobs.read_verified(supplement_ref)
            if len(raw) != supplement_ref.byte_length or _digest_of(raw) != supplement_ref.digest:
                raise ApplicationError('REPORT_CONTENT_REWORK_SUPPLEMENT_INVALID')
            supplements.append({'ref': asdict(supplement_ref),
                                'text': raw.decode('utf-8', errors='strict')})
        if schema_document is None:
            schema = self._report_schema(context, package.payload.method_ref)
        else:
            schema = schema_document
        body = {'report_content_rework_plan': plan,
            'plan_ref': asdict(plan_ref),
            'report': old_report,
            'approval_ref': asdict(_blob(approval_ref)),
            'failed_review': failed_review,
            'original_check_observation': plan['materials']['original_check_observation'],
            'repository_files': files, 'supplemental_materials': supplements,
            'report_schema': schema,
            'verification_contract': {'result': 'not_run',
                'check_must_include': [CORRECTION_LIMITATION, UNRERUN_NOTE]},
            'instruction': 'Return the same report with only verification changed. Preserve every other field exactly. Set every verification result to not_run and include both required check statements. Do not run commands, edit files, or claim tests passed. Supplemental material is caller-supplied and unverified; it is not independent authentication.'}
        return {'prompt': [{'type': 'text', 'text': canonical_bytes(body).decode('utf-8')}]}

    def _report_schema(self, context, method_ref, *, method_guarded=False):
        def read():
            schema_ref = self.methods.resource_ref(context, method_ref, 'implementation-report-schema')
            return decode_json(self.methods.read_resource(context, schema_ref))
        if method_guarded:
            # The original port rejects this read unless this exact context
            # already holds its Method guard on this thread.
            schema = read()
        else:
            with self.methods.guard(context, method_ref):
                schema = read()
        try:
            Draft202012Validator.check_schema(schema)
        except Exception:
            raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH') from None
        return schema

    def _check_report(self, plan, raw_report):
        try:
            value = decode_json(raw_report)
        except Exception:
            raise ApplicationError('REPORT_CONTENT_REWORK_REPORT_INVALID') from None
        origin = plan['origin']
        # Source's original correction report is available from the registered
        # Submission; callers pass that record to the common validation path.
        if type(value) is not dict or 'verification' not in value:
            raise ApplicationError('REPORT_CONTENT_REWORK_REPORT_INVALID')
        verification = value['verification']
        if type(verification) is not list or not verification:
            raise ApplicationError('REPORT_CONTENT_REWORK_REPORT_INVALID')
        for item in verification:
            if (type(item) is not dict or set(item) != {'check', 'result'}
                    or item.get('result') != 'not_run' or type(item.get('check')) is not str
                    or CORRECTION_LIMITATION not in item['check']
                    or UNRERUN_NOTE not in item['check']):
                raise ApplicationError('REPORT_CONTENT_REWORK_REPORT_INVALID')
        return value

    def validate_checkpoint(self, context, *, checkpoint_ref, fresh=True,
                            _review=False, _recording=False, _method_guarded=False):
        if _review:
            self._authorize_review(context)
        elif _recording:
            self._authorize_record(context)
        else:
            self._authorize(context)
        checkpoint_ref = _blob(checkpoint_ref)
        raw = self.blobs.read_verified(checkpoint_ref)
        checkpoint = decode_json(raw)
        if (type(checkpoint) is not dict or set(checkpoint) != CHECKPOINT_FIELDS
                or checkpoint.get('contract') != CONTENT_REWORK_CONTRACT
                or type(checkpoint.get('report')) is not dict
                or set(checkpoint['report']) != REPORT_FIELDS):
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        plan_ref, plan = self._plan(checkpoint['plan_ref'])
        if (checkpoint_ref.digest != _digest_of(raw)
                or checkpoint_ref.byte_length != len(raw)
                or plan['origin']['parent_key']['realm_id'] != context.scope.realm_id
                or type(checkpoint['approval_ref']) is not dict):
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        approval_ref = _blob(checkpoint['approval_ref'])
        self._verify_approval_and_claim(context, plan_ref, approval_ref, plan)
        origin = plan['origin']
        source_facts = self._verify_plan_origin(context, plan)
        submission, package, binding, source, _controlled = source_facts
        if source['checkpoint_ref'] != submission.checkpoint_ref:
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        report = checkpoint['report']
        operation_ref = REPORT_OPERATION_PREFIX + plan_ref.digest.hex
        unit_ref = report['unit_ref']
        prompt_digest = _decode_digest(report['prompt_input_digest'])
        output_ref = _blob(report['output_ref'])
        observation_ref = _blob(report['observation_ref'])
        if (output_ref.byte_length > 2 * 1024 * 1024
                or observation_ref.byte_length > MAX_EXECUTION_RECEIPT_BYTES):
            raise ApplicationError('REPORT_CONTENT_REWORK_CAPTURE_INVALID')
        output_raw = self.blobs.read_verified(output_ref)
        receipt_raw = self.blobs.read_verified(observation_ref)
        receipt = canonical_value(receipt_raw, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        if (type(unit_ref) is not dict
                or set(unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
                or type(unit_ref.get('ownerProviderRef')) is not dict
                or report['operation_ref'] != operation_ref
                or type(report['observation_revision']) is not int
                or type(report['observation_revision']) is bool
                or report['observation_revision'] < 1
                or len(output_raw) != output_ref.byte_length
                or _digest_of(output_raw) != output_ref.digest
                or receipt.get('contractVersion') != 'unit-acp-turn/1'
                or receipt.get('unitRef') != unit_ref
                or receipt.get('operationRef') != operation_ref
                or receipt.get('inputDigest') != 'sha256:' + prompt_digest.hex
                or receipt.get('revision') != report['observation_revision']
                or receipt.get('state') != 'completed'
                or type(receipt.get('summary')) is not dict
                or receipt['summary'].get('successfulRpcResponse') is not True
                or receipt['summary'].get('stopReason') != 'end_turn'
                or type(receipt['summary'].get('text')) is not str
                or canonical_bytes(decode_json(receipt['summary']['text'].encode())) != output_raw):
            raise ApplicationError('REPORT_CONTENT_REWORK_CAPTURE_INVALID')
        schema = self._report_schema(context, package.payload.method_ref,
                                     method_guarded=_method_guarded)
        expected_params = self._prompt_params(context, plan_ref, plan, approval_ref,
            source_facts=source_facts, schema_document=schema)
        input_frame = receipt.get('input')
        actual = input_frame.get('params') if type(input_frame) is dict else None
        if type(actual) is not dict:
            raise ApplicationError('REPORT_CONTENT_REWORK_PROMPT_MISMATCH')
        actual_without_session = dict(actual)
        session_id = actual_without_session.pop('sessionId', None)
        native = receipt.get('nativeBinding')
        if (not session_id or type(native) is not dict or native.get('sessionId') != session_id
                or input_frame.get('unitRef') != unit_ref
                or actual_without_session != expected_params):
            raise ApplicationError('REPORT_CONTENT_REWORK_PROMPT_MISMATCH')
        request, response, events = receipt.get('request'), receipt.get('response'), receipt.get('events')
        if (type(request) is not dict or type(request.get('raw')) is not dict
                or request['raw'].get('jsonrpc') != '2.0'
                or request['raw'].get('method') != 'session/prompt'
                or request['raw'].get('params') != actual
                or type(request['raw'].get('id')) not in (str, int)
                or type(request['raw'].get('id')) is bool
                or type(response) is not dict or response.get('jsonrpc') != '2.0'
                or 'result' not in response or 'error' in response
                or type(response.get('id')) is bool
                or canonical_bytes(response.get('id')) != canonical_bytes(request['raw'].get('id'))
                or type(events) is not list
                or type(receipt['summary'].get('eventCount')) is not int
                or receipt['summary']['eventCount'] != len(events)
                or response not in [event.get('raw') for event in events if type(event) is dict]):
            raise ApplicationError('REPORT_CONTENT_REWORK_CAPTURE_INVALID')
        try:
            _check_readonly_capture(receipt,
                [item['path'] for item in plan['materials']['files']])
        except ApplicationError:
            raise ApplicationError('REPORT_CONTENT_REWORK_READ_ONLY_VIOLATION') from None
        value = self._check_report(plan, output_raw)
        old_value = source['submission'].method_content.value
        if {k: v for k, v in value.items() if k != 'verification'} != {
                k: v for k, v in old_value.items() if k != 'verification'}:
            raise ApplicationError('REPORT_CONTENT_REWORK_CONTENT_DRIFT')
        if not Draft202012Validator(schema).is_valid(value):
            raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
        stop_digest = _decode_digest(report['stop_record_digest'])
        release_digest = _decode_digest(report['release_record_digest'])
        if fresh:
            profile = self.ports.read_unit(context, unit_ref)
            if (type(profile) is not dict or set(profile) != {'unit_ref', 'profile_ref', 'stop_record', 'release_record'}
                    or profile['unit_ref'] != unit_ref
                    or _profile(profile['profile_ref']) != origin['profile_ref']):
                raise ApplicationError('REPORT_CONTENT_REWORK_PROFILE_MISMATCH')
            for name, expected in (('stop_record', stop_digest), ('release_record', release_digest)):
                record = profile[name]
                if (type(record) is not dict or record.get('state') != 'confirmed'
                        or record.get('identity', {}).get('unitRef') != unit_ref
                        or _digest_of(canonical_bytes(record)) != expected):
                    raise ApplicationError('REPORT_CONTENT_REWORK_UNIT_OPEN')
        if (unit_ref == origin['author_unit_ref']
                or (unit_ref.get('environmentNamespace'), unit_ref.get('unitId')) ==
                   (origin['author_unit_ref'].get('environmentNamespace'),
                    origin['author_unit_ref'].get('unitId'))
                or unit_ref.get('environmentNamespace') != origin['author_unit_ref'].get('environmentNamespace')):
            raise ApplicationError('REPORT_CONTENT_REWORK_PROFILE_MISMATCH')
        if fresh:
            invocation = self.ports.query(context, unit_ref, operation_ref,
                                          'sha256:' + prompt_digest.hex)
            captured = capture_execution_observation(self.ports.records, self.blobs,
                authority_id=self.factory.authority_id, unit_ref=unit_ref,
                operation_ref=operation_ref, expected_prompt_digest='sha256:' + prompt_digest.hex,
                query_invocation=invocation, max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES)
            if (captured.blob_ref != observation_ref
                    or captured.revision != report['observation_revision']
                    or captured.query_digest != self.ports.records.acp_turn_query_digest(
                        unit_ref, operation_ref, 'sha256:' + prompt_digest.hex)
                    or captured.state != 'completed'):
                raise ApplicationError('REPORT_CONTENT_REWORK_CAPTURE_INVALID')
            original_unit = origin['author_unit_ref']
            original_query = self.ports.query(context, original_unit,
                binding.execution_operation_ref, 'sha256:' + binding.prompt_input_digest.hex)
            original_capture = capture_execution_observation(self.ports.records, self.blobs,
                authority_id=self.factory.authority_id, unit_ref=original_unit,
                operation_ref=binding.execution_operation_ref,
                expected_prompt_digest='sha256:' + binding.prompt_input_digest.hex,
                query_invocation=original_query, max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES)
            if (original_capture.blob_ref != submission.execution_ref.captured_observation_ref
                    or original_capture.revision != origin['observation_revision']
                    or original_capture.query_digest != binding.expected_query_digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        return plan, binding, submission.execution_ref.captured_observation_ref

    def record(self, context, *, checkpoint_ref):
        from ....domain.changes.submission_codec import submission_projection
        from ....domain.changes.submission import Submission
        plan, binding, _original_observation = self.validate_checkpoint(
            context, checkpoint_ref=checkpoint_ref, fresh=False, _recording=True)
        checkpoint = decode_json(self.blobs.read_verified(_blob(checkpoint_ref)))
        output_ref = _blob(checkpoint['report']['output_ref'])
        output_raw = self.blobs.read_verified(output_ref)
        value = decode_json(output_raw)
        origin = plan['origin']
        source_ref = decode_subject_ref(origin['source_submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            source = uow.submissions.resolve(source_ref)
            package = uow.implementation.resolve_package(source.package_ref)
        with self.methods.guard(context, package.payload.method_ref):
            exact = self.methods.resource_ref(context, package.payload.method_ref,
                'implementation-report-schema')
        content = MethodContent.from_value(exact, value, rendered_body_ref=output_ref)
        change_refs = source.change_set.proposal_refs
        coverage = tuple(SubmissionCoverage(change_ref, (output_ref,), (), (), 'implemented')
                         for change_ref in change_refs)
        new_id = 'content-rework-' + _blob(checkpoint['plan_ref']).digest.hex[:40]
        record = replace(source, submission_id=new_id, created_at=context.received_at,
            created_by=context.authenticated_actor, output_refs=(output_ref,),
            coverage=coverage, method_content=content, checkpoint_ref=_blob(checkpoint_ref))
        return decode_json(canonical_bytes(submission_projection(record)))

    @contextmanager
    def guard_report(self, context, package, submission, captured):
        self._authorize_record(context)
        checkpoint = decode_json(self.blobs.read_verified(submission.checkpoint_ref))
        if (type(checkpoint) is not dict or set(checkpoint) != CHECKPOINT_FIELDS
                or checkpoint.get('contract') != CONTENT_REWORK_CONTRACT):
            raise ApplicationError('REPORT_CONTENT_REWORK_CHECKPOINT_INVALID')
        plan_ref, expected = _blob(checkpoint['plan_ref']), _blob(checkpoint['approval_ref'])
        approval = getattr(self.owner, 'content_rework_approval', None)
        if (approval is None or getattr(approval, 'factory', None) is not self.factory
                or getattr(approval, 'access', None) is not self.ports.access
                or getattr(approval, 'blobs', None) is not self.blobs
                or not callable(getattr(approval, 'guard', None))):
            raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_REQUIRED')
        with approval.guard(context, plan_ref=plan_ref) as selected:
            if type(selected) is not BlobRef or selected != expected:
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
            with self._guard_report_checked(context, package, submission, captured) as report:
                yield report

    @contextmanager
    def _guard_report_checked(self, context, package, submission, captured):
        plan, binding, original_ref = self.validate_checkpoint(
            context, checkpoint_ref=submission.checkpoint_ref, fresh=True, _recording=True)
        checkpoint = decode_json(self.blobs.read_verified(submission.checkpoint_ref))
        report = checkpoint['report']
        output_ref = _blob(report['output_ref'])
        source_ref = _subject(plan['origin']['source_submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            original = uow.submissions.resolve(source_ref)
        if (submission.execution_ref.captured_observation_ref != original_ref
                or submission.execution_ref != original.execution_ref
                or submission.execution_ref.operation_ref != binding.execution_operation_ref
                or submission.submission_id != 'content-rework-' + _blob(checkpoint['plan_ref']).digest.hex[:40]
                or submission.package_ref != binding.package_ref
                or submission.authorization_refs != original.authorization_refs
                or submission.change_set != original.change_set
                or submission.source_refs != original.source_refs
                or captured.blob_ref != original_ref
                or output_ref not in submission.output_refs or len(submission.output_refs) != 1
                or self.blobs.read_verified(output_ref) != submission.method_content.value_bytes):
            raise ApplicationError('REPORT_CONTENT_REWORK_BINDING_MISMATCH')
        with self.methods.guard(context, package.payload.method_ref):
            exact_schema = self.methods.resource_ref(
                context, package.payload.method_ref, 'implementation-report-schema')
        if (package.scope != context.scope or package.ref != binding.package_ref
                or package.payload.method_ref != _method_ref(plan['origin']['method_ref'])
                or submission.method_content.schema_ref != exact_schema):
            raise ApplicationError('REPORT_CONTENT_REWORK_BINDING_MISMATCH')
        yield __import__(
            'ordessa_engineering.application.usecases.changes.report_source',
            fromlist=['VerifiedUnitReport']).VerifiedUnitReport(
                package.payload.method_ref, submission.method_content.schema_ref,
                submission.output_refs, _digest_of(submission.method_content.value_bytes),
                binding.execution_operation_ref, binding.prompt_input_digest,
                captured.query_digest, captured.blob_ref)

    def review_evidence(self, context, submission):
        if submission.checkpoint_ref is None or not self._is_checkpoint(submission.checkpoint_ref):
            return None
        plan, _binding, _observation = self.validate_checkpoint(
            context, checkpoint_ref=submission.checkpoint_ref, fresh=False, _review=True)
        return plan['materials']['original_check_observation']

    @contextmanager
    def guard_review(self, context, review_plan, submission, *, prompt_context=None,
                     request=None):
        """Keep generic review writes inside the one approved rework tail."""
        self._authorize_review(context)
        checkpoint = decode_json(self.blobs.read_verified(submission.checkpoint_ref))
        plan_ref, plan = self._plan(checkpoint['plan_ref'])
        approval_ref = _blob(checkpoint['approval_ref'])
        claim = self._verify_approval_and_claim(context, plan_ref, approval_ref, plan)
        suffix = hashlib.sha256(canonical_bytes({'plan_ref': asdict(plan_ref),
            'approval_ref': asdict(approval_ref)})).hexdigest()
        from ...contracts.commands import CommandKey
        key = claim_key(plan)
        tail_key = CommandKey(key.realm_id, key.principal_id, 'report-content-rework-tail-' + suffix[:48])
        expected = record_digest('report-content-rework-tail', {
            'claim_key': asdict(key), 'claim_digest': asdict(claim_digest(plan_ref, approval_ref)),
            'checkpoint_ref': asdict(submission.checkpoint_ref), 'submission_ref': asdict(submission.ref)})
        with self.factory.begin(context.scope, 'read') as uow:
            tail = uow.commands.get(tail_key)
        if (review_plan.review_id != 'report-content-rework-review-' + suffix
                or tail is None or tail.operation != 'engineering.report_content_rework.tail'
                or tail.operation_id != 'report-content-rework-tail/' + suffix
                or tail.request_digest != expected or tail.project_id != context.scope.project_id
                or tail.state not in {'pending', 'completed'}):
            raise ApplicationError('REPORT_CONTENT_REWORK_TAIL_CONFLICT')
        approval = self.owner.content_rework_approval
        with approval.guard(context, plan_ref=plan_ref) as selected:
            if type(selected) is not BlobRef or selected != approval_ref:
                raise ApplicationError('REPORT_CONTENT_REWORK_APPROVAL_INVALID')
            permit = None
            if prompt_context is not None or request is not None:
                from ....application.contracts.commands import CommandContext
                if (type(prompt_context) is not CommandContext or request is None
                        or prompt_context.scope != context.scope
                        or prompt_context.principal_id != context.principal_id
                        or request.state != 'requested'
                        or review_plan.review_id != 'report-content-rework-review-' + suffix):
                    raise ApplicationError('REPORT_CONTENT_REWORK_REVIEW_PERMIT_INVALID')
                permit = _ReportContentReviewCutPermit(
                    source=self, approval=approval, context=prompt_context,
                    scope=prompt_context.scope, principal_id=prompt_context.principal_id,
                    plan_ref=plan_ref, approval_ref=approval_ref,
                    checkpoint_ref=_blob(submission.checkpoint_ref),
                    submission_ref=submission.ref, review_id=review_plan.review_id,
                    plan_digest=review_plan.plan_digest,
                    request_version=request.version, request_fence=request.fence,
                    claim_key=key, claim_operation_id=claim_operation_id(plan),
                    claim_digest=claim_digest(plan_ref, approval_ref),
                    claim_version=claim.version, tail_key=tail_key,
                    tail_operation_id='report-content-rework-tail/' + suffix,
                    tail_digest=expected, tail_version=tail.version)
            yield permit

    def review_materials(self, context, submission, *, method_guarded=False):
        if submission.checkpoint_ref is None or not self._is_checkpoint(submission.checkpoint_ref):
            return None
        plan, _binding, _observation = self.validate_checkpoint(
            context, checkpoint_ref=submission.checkpoint_ref, fresh=False, _review=True,
            _method_guarded=method_guarded)
        origin = plan['origin']
        review_ref = decode_review_ref(origin['review_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            controlled = uow.reviews.get_review(review_ref)
        if (controlled.record.ref != review_ref or controlled.control.state != 'active'
                or controlled.record.verdict != 'fail' or not controlled.record.complete):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        source_ref = _subject(origin['source_submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            original_submission = uow.submissions.resolve(source_ref)
        raw = original_submission.method_content.value_bytes
        failed_review = {'record': controlled.record.projection(),
                         'control': asdict(controlled.control)}
        if controlled.record.raw_response_ref is not None:
            response_ref = controlled.record.raw_response_ref
            response_raw = self.blobs.read_verified(response_ref)
            if (type(response_raw) is not bytes
                    or len(response_raw) != response_ref.byte_length
                    or _digest_of(response_raw) != response_ref.digest):
                raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
            failed_review['raw_response_utf8'] = response_raw.decode('utf-8', errors='strict')
        if (type(raw) is not bytes
                or raw != canonical_bytes(original_submission.method_content.value)):
            raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
        supplements = []
        for value in plan['materials']['supplement_refs']:
            ref = _blob(value)
            text = self.blobs.read_verified(ref)
            if len(text) != ref.byte_length or _digest_of(text) != ref.digest:
                raise ApplicationError('REPORT_CONTENT_REWORK_MATERIALS_INVALID')
            supplements.append({'ref': asdict(ref), 'text': text.decode('utf-8', errors='strict'),
                'limitation': 'caller-supplied, unverified material; not independent authentication'})
        return {'contract': 'ordessa.report-content-rework-materials/1',
            'original_check_observation': plan['materials']['original_check_observation'],
            'failed_review': failed_review,
            'rejected_report_utf8': raw.decode('utf-8', errors='strict'),
            'supplements': supplements,
            'limitation': 'caller-supplied, unverified material; not independent authentication'}

    def _is_checkpoint(self, checkpoint_ref):
        try:
            value = decode_json(self.blobs.read_verified(_blob(checkpoint_ref)))
            return type(value) is dict and value.get('contract') == CONTENT_REWORK_CONTRACT
        except Exception:
            return False


def _subject(value):
    ref = value if type(value) is SubmissionRef else decode_subject_ref(value)
    if type(ref) is not SubmissionRef:
        raise ApplicationError('REPORT_CONTENT_REWORK_ORIGIN_INVALID')
    return ref
