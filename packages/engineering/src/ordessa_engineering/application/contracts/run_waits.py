"""Trusted Work selection over original persisted run rows; never caller truth."""
from dataclasses import asdict, dataclass, field
from typing import Protocol
from ordessa_infrastructure.encoding import canonical_bytes
from ...domain.common.models.identity import Scope
from ...domain.common.models.values import Digest, validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.common.models.refs import BlobRef
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.changes.refs import ProposalRef
from ...domain.packages.refs import ImplementationPackageRef
from ...domain.reviews.models import ReviewPlan
from ...domain.reviews.refs import SubmissionRef
from .commands import ReadSet


@dataclass(frozen=True)
class ReviewReadiness:
    """Owner-bound inputs for a pre-request or pre-record wait.

    This value is a source proof container, not authorization, reviewer trust,
    or a review verdict. Its original owner guard must remain held to COMMIT.
    """
    plan: ReviewPlan
    input_ref: ArtifactRevisionRef
    subject_ref: ProposalRef | ArtifactRevisionRef | ImplementationPackageRef | SubmissionRef
    read_set: ReadSet
    raw_response_ref: BlobRef | None = None

    def __post_init__(self):
        if (type(self.plan) is not ReviewPlan or type(self.input_ref) is not ArtifactRevisionRef
                or type(self.subject_ref) not in
                    (ProposalRef, ArtifactRevisionRef, ImplementationPackageRef, SubmissionRef)
                or type(self.read_set) is not ReadSet
                or (self.raw_response_ref is not None and type(self.raw_response_ref) is not BlobRef)):
            raise ReferenceError('INVALID_REVIEW_READINESS')
        scope = self.plan.scope
        if (self.input_ref.realm_id, self.input_ref.project_id) != (scope.realm_id, scope.project_id):
            raise ReferenceError('REALM_MISMATCH')
        if ((self.subject_ref.realm_id, self.subject_ref.project_id) !=
                (scope.realm_id, scope.project_id) or self.read_set.scope != scope):
            raise ReferenceError('REALM_MISMATCH')
        if not any(version.kind == 'artifact' and version.identifier == self.input_ref.artifact_id
                   for version in self.read_set.versions):
            raise ReferenceError('INVALID_REVIEW_READINESS')
        if self.read_set.review_sets or self.read_set.review_controls:
            raise ReferenceError('INVALID_REVIEW_READINESS')
        if self.raw_response_ref is None:
            if self.read_set.review_requests:
                raise ReferenceError('INVALID_REVIEW_READINESS')
        else:
            if len(self.read_set.review_requests) != 1:
                raise ReferenceError('INVALID_REVIEW_READINESS')
            expectation = self.read_set.review_requests[0]
            if (expectation.scope != scope or expectation.review_id != self.plan.review_id
                    or expectation.expected_plan_digest != self.plan.plan_digest
                    or expectation.expected_state != 'requested'):
                raise ReferenceError('INVALID_REVIEW_READINESS')


@dataclass(frozen=True)
class BoundRunWait:
    scope: Scope
    run_id: str
    row_digest: Digest
    next_step_ordinal: int
    family: str
    refs: tuple = ()
    intent: object = None
    approval_ref: object = None
    action: str | None = None
    expected_control_version: int | None = None
    readiness: ReviewReadiness | None = field(default=None, kw_only=True)

    def __post_init__(self):
        validate_id(self.run_id)
        if (type(self.scope) is not Scope or type(self.row_digest) is not Digest
                or type(self.next_step_ordinal) is not int or self.next_step_ordinal < 0
                or self.family not in {'object_exists','review_gate','action_authorization','result_exists',
                                       'review_plan_ready','review_response_ready'}
                or type(self.refs) is not tuple or len(self.refs) > 4096):
            raise ReferenceError('INVALID_RUN_WAIT')
        exists = self.family in {'object_exists','result_exists'}
        if exists:
            if (not self.refs or any(value is not None for value in
                    (self.intent,self.approval_ref,self.action,self.expected_control_version))):
                raise ReferenceError('INVALID_RUN_WAIT')
        elif self.family in {'review_plan_ready','review_response_ready'}:
            if (type(self.readiness) is not ReviewReadiness or self.refs or self.intent is not None
                    or self.approval_ref is not None or self.action is not None
                    or self.expected_control_version is not None
                    or self.readiness.plan.scope != self.scope
                    or (self.family == 'review_plan_ready') != (self.readiness.raw_response_ref is None)):
                raise ReferenceError('INVALID_RUN_WAIT')
        elif (self.refs or self.intent is None or getattr(self.intent,'scope',None) != self.scope
                or not getattr(self.intent,'required_review_requirements',())):
            raise ReferenceError('INVALID_RUN_WAIT')
        if self.family not in {'review_plan_ready','review_response_ready'} and self.readiness is not None:
            raise ReferenceError('INVALID_RUN_WAIT')
        if self.family == 'review_gate' and any(value is not None for value in
                (self.approval_ref,self.action,self.expected_control_version)):
            raise ReferenceError('INVALID_RUN_WAIT')
        if self.family == 'action_authorization' and (self.approval_ref is None
                or type(self.action) is not str or self.action not in self.intent.actions
                or type(self.expected_control_version) is not int or self.expected_control_version < 0):
            raise ReferenceError('INVALID_RUN_WAIT')

    @property
    def digest(self):
        value = asdict(self)
        # Preserve the wire identity of every pre-readiness family.
        if self.readiness is None:
            value.pop('readiness')
        return record_digest('bound-run-wait', value)


def run_wait_row_digest(row):
    """Identity includes the original method/registry/inputs/cursor/timestamps."""
    return record_digest('run-wait-row', {
        **row, 'method_ref': asdict(row['method_ref'])})


class CurrentRunWaitBindings(Protocol):
    def guard_wait(self, context, run_id, row):
        """Hold current trusted method/Work selection and yield BoundRunWait.

        Owner must establish exact row belongs to context.scope and its actual
        selected workflow condition. For either review readiness family it
        also enters the matching ReviewReadinessBindings guard and holds it
        through this context. Missing production Work owner refuses; wire
        refs/condition booleans and C09 material casts cannot select it.
        """
        ...


class ReviewReadinessBindings(Protocol):
    """Same-owner source proof for review inputs before request/record.

    Implementations expose the selected original factory/method owner by
    identity and hold the source guard while yielding. Response readiness must
    verify the exact original BlobRef/bytes and declared response encoding;
    yielded ReviewReadiness values do not themselves authenticate.
    """
    factory: object
    methods: object

    def guard_plan_ready(self, context, snapshot, plan, *, phase_key, input_ref,
                         subject_ref, view): ...

    def guard_response_ready(self, context, snapshot, plan, request, raw_response_ref, *,
                             phase_key, input_ref, subject_ref, view): ...
