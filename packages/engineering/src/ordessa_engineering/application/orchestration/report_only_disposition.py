"""Internal, one-path permit for a report-only disposition closeout.

This is constructed only by the report-content-rework consumer after its
original approval guard, report claim, and unique tail reservation exist. It
does not grant execution or change the historical implementation Grant.
"""
from dataclasses import asdict, dataclass
from contextlib import contextmanager

from ordessa_infrastructure.encoding import decode_json
from ..contracts.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class ReportOnlyDispositionPermit:
    approval_port: object
    factory: object
    access: object
    blobs: object
    context: object
    plan_ref: object
    approval_ref: object
    parent_operation_id: str
    parent_key: object
    parent_request_digest: object
    parent_version: int
    work_id: str
    work_revision: int
    binding: object
    origin_review_ref: object
    source_submission_ref: object
    submission_ref: object
    review_ref: object
    claim_key: object
    claim_operation_id: str
    claim_digest: object
    tail_key: object
    tail_operation_id: str
    tail_digest: object

    @contextmanager
    def guard_commit(self):
        """Last live authorization cut, held across the original UoW COMMIT."""
        if self.access.current_context() is not self.context:
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        with self.approval_port.guard(self.context, plan_ref=self.plan_ref) as ref:
            if ref != self.approval_ref:
                raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
            yield

    def validate(self, uow, *, context, work, binding, submission_ref,
                 review_ref, now):
        """Revalidate the captured approval and exact pending closeout in-UoW."""
        approval = self.approval_port
        if (context is not self.context
                or self.claim_key.realm_id != context.scope.realm_id
                or self.claim_key.principal_id != context.principal_id
                or self.tail_key.realm_id != context.scope.realm_id
                or self.tail_key.principal_id != context.principal_id
                or self.parent_key.realm_id != context.scope.realm_id
                or self.parent_key.principal_id != context.principal_id
                or work.work_id != self.work_id
                or work.revision != self.work_revision
                or binding != self.binding
                or submission_ref != self.submission_ref
                or review_ref != self.review_ref
                or getattr(approval, 'factory', None) is not self.factory
                or getattr(approval, 'access', None) is not self.access
                or getattr(approval, 'blobs', None) is not self.blobs
                or getattr(self.access, 'current_context', lambda: None)() is not context):
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        self.access.require(context, 'engineering.work.invoke')
        # The trusted host port checks the canonical proof and its live 90-minute
        # window. Reentrant guarding is part of that port's contract.
        with approval.guard(context, plan_ref=self.plan_ref) as selected:
            if selected != self.approval_ref:
                raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        parent = uow.commands.find_operation(context.scope, self.parent_operation_id,
                                             operation='engineering.work.invoke')
        if (parent is None or parent.key != self.parent_key
                or parent.request_digest != self.parent_request_digest
                or parent.version != self.parent_version
                or parent.state not in {'completed', 'rejected'}
                or parent.project_id != context.scope.project_id):
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        try:
            parent_result = decode_json(parent.result_bytes)
            parent_method = parent_result['method_result']
        except Exception:
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID') from None
        if (type(parent_method) is not dict
                or parent_method.get('disposition') != 'rejected'
                or parent_method.get('review_ref') != asdict(self.origin_review_ref)
                or parent_method.get('submission_ref') != asdict(self.source_submission_ref)
                or parent_method.get('implementation_operation_ref')
                    != self.binding.execution_operation_ref):
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        origin_review = uow.reviews.get_review(self.origin_review_ref)
        if (origin_review.record.ref != self.origin_review_ref
                or not origin_review.record.complete
                or origin_review.record.verdict != 'fail'
                or origin_review.control.state != 'active'):
            raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
        for key, operation, operation_id, digest, state in (
                (self.claim_key, 'engineering.report_content_rework.claim',
                 self.claim_operation_id, self.claim_digest, 'pending'),
                (self.tail_key, 'engineering.report_content_rework.tail',
                 self.tail_operation_id, self.tail_digest, 'pending')):
            entry = uow.commands.get(key)
            if (entry is None or entry.key != key
                    or entry.project_id != context.scope.project_id
                    or entry.operation != operation
                    or entry.operation_id != operation_id
                    or entry.request_digest != digest
                    or entry.state != state):
                raise ApplicationError('REPORT_CONTENT_REWORK_DISPOSITION_PERMIT_INVALID')
