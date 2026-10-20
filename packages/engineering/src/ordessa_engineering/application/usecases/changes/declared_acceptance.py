"""Resolve exact declared-Work report and independent review facts.

This module only closes persisted references on the caller's original UoW. Its
DTO checks are not native Unit or reviewer authentication. Callers must hold the
original ReviewAdmission ``guard_plan`` and ``guard_trust`` plus the original
Unit authority guard through COMMIT. This code never records acceptance,
creates an AcceptanceReceipt, or changes Artifact heads.
"""
from dataclasses import asdict, dataclass

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ...contracts.errors import ApplicationError
from ...contracts.work_context import (
    WORK_CONTEXT_KIND,
    WorkBinding,
    decode_work_binding,
)
from ....domain.changes.dispatch import DispatchBinding
from ....domain.changes.submission import Submission
from ....domain.packages.models import ImplementationPackage
from ....domain.reviews.refs import ReviewRef, SubmissionRef
from ....domain.reviews.targets import Target
from ....domain.reviews.models import (
    ControlledReview,
    ReviewControl,
    ReviewRecord,
    ReviewRequestState,
)
from ....domain.reviews.assignments import ReviewerAssignment, ReviewerAssignmentControl
from ....domain.common.models.identity import ActorRef
from ....domain.common.mechanisms.hashing import record_digest
from .declared_report import resolve_declared_report_binding


@dataclass(frozen=True)
class DeclaredReviewClosure:
    """Exact persisted facts for one declared Work report review."""

    work: WorkBinding
    binding: DispatchBinding
    submission: Submission
    package: ImplementationPackage
    review: ReviewRecord
    review_control: ReviewControl
    request: ReviewRequestState
    assignment: ReviewerAssignment
    assignment_control: ReviewerAssignmentControl


def _current_work(uow, work):
    if type(work) is not WorkBinding or work.scope != uow.scope:
        raise ApplicationError("WORK_BINDING_INVALID")
    head = uow.workflow.head_ref(WORK_CONTEXT_KIND, work.stable_id)
    if head is None:
        raise ApplicationError("WORK_NOT_FOUND")
    current = decode_work_binding(uow.workflow.read(head))
    if (current != work or current.work_id != work.work_id
            or current.stable_id != work.stable_id or current.revision != head.revision):
        raise ApplicationError("WORK_REVISION_STALE")
    return current


def _require(condition, code):
    if not condition:
        raise ApplicationError(code)


def resolve_declared_review(
    uow,
    work,
    submission_ref,
    review_ref,
    *,
    review_step_id="review",
):
    """Resolve exact report, Work, review and active Unit assignment facts.

    Authentication is intentionally left to the original review admission and
    Unit authority guards, which callers must retain through COMMIT.
    """
    current = _current_work(uow, work)
    _require(type(submission_ref) is SubmissionRef
             and (submission_ref.realm_id, submission_ref.project_id)
             == (uow.scope.realm_id, uow.scope.project_id), "SCOPE_MISMATCH")
    _require(type(review_ref) is ReviewRef
             and (review_ref.realm_id, review_ref.project_id)
             == (uow.scope.realm_id, uow.scope.project_id), "SCOPE_MISMATCH")
    _require(type(review_step_id) is str and bool(review_step_id), "INVALID_INPUT")

    submission = uow.submissions.resolve(submission_ref)
    _require(type(submission) is Submission and submission.ref == submission_ref
             and submission.schema_version == 2 and submission.scope == current.scope,
             "SUBMISSION_DECLARED_REVIEW_UNAVAILABLE")
    binding = resolve_declared_report_binding(uow, submission)
    _require(binding.work["work_id"] == current.work_id
             and binding.scope == current.scope
             and binding.work["step_id"] == binding.step_id
             and binding.work["dispatch_key"] == binding.run_id
             and binding.package_ref == submission.package_ref,
             "SUBMISSION_WORK_BINDING_MISMATCH")
    package = uow.implementation.resolve_package(binding.package_ref)
    payload = package.payload
    _require(package.scope == current.scope and package.ref == submission.package_ref
             and payload.method_ref == current.method_ref,
             "SUBMISSION_WORK_BINDING_MISMATCH")

    controlled = uow.reviews.get_review(review_ref)
    _require(type(controlled) is ControlledReview, "REVIEW_RECORD_UNAVAILABLE")
    review, review_control = controlled.record, controlled.control
    request = uow.reviews.get_request(review_ref.review_id)
    plan = review.plan
    requirement = plan.requirement
    primary = tuple(target for target in requirement.expected_targets.targets
                    if target.role == "primary")
    _require(type(review) is ReviewRecord and review.ref == review_ref
             and review.identity.scope == current.scope
             and review.identity.schema_version == 2
             and review.identity.record_id == review_ref.review_id
             and review_control.scope == current.scope
             and review_control.review_id == review_ref.review_id
             and review_control.state == "active"
             and request.scope == current.scope
             and request.review_id == review_ref.review_id
             and request.state == "recorded"
             and requirement.schema_version == 2
             and requirement.purpose == "acceptance"
             and requirement.phase_key == review_step_id
             and requirement.scope == current.scope
             and requirement.method_ref == current.method_ref
             and len(requirement.expected_targets.targets) == 1
             and len(primary) == 1 and type(primary[0]) is Target
             and primary[0].ref == submission_ref,
             "SUBMISSION_REVIEW_BINDING_MISMATCH")

    assignment, assignment_control = uow.reviewer_assignments.active_for_review(
        review_ref.review_id)
    _require(type(assignment) is ReviewerAssignment
             and type(assignment_control) is ReviewerAssignmentControl
             and assignment.scope == current.scope
             and assignment.review_id == review_ref.review_id
             and assignment.plan_digest == plan.plan_digest
             and assignment.method_ref == current.method_ref
             and assignment.roles == tuple(sorted(plan.reviewer_requirements))
             and request.version == assignment.request_version + 1
             and request.fence == assignment.fence
             and assignment_control.ref == assignment.ref
             and assignment_control.state == "active"
             and assignment.author_unit_ref_bytes == binding.unit_ref_bytes,
             "SUBMISSION_REVIEW_ASSIGNMENT_MISMATCH")
    expected_reviewer = ActorRef(record_digest("unit-reviewer-actor", {
        "unit_ref": assignment.reviewer_unit_ref,
        "assignment": asdict(assignment.ref),
    }).hex, "agent", "ordessa-unit-records")
    evidence = review.reviewer_evidence
    _require(evidence.reviewer == expected_reviewer
             and evidence.roles == assignment.roles
             and evidence.trust_version == assignment_control.version
             and evidence.request_digest == plan.request_digest,
             "SUBMISSION_REVIEW_ASSIGNMENT_MISMATCH")
    author = decode_json(assignment.author_unit_ref_bytes)
    reviewer = decode_json(assignment.reviewer_unit_ref_bytes)
    # Compare stable native Unit identity; sourceRevision changes must not turn
    # the report author into an apparently independent reviewer.
    _require((author["environmentNamespace"], author["unitId"])
             != (reviewer["environmentNamespace"], reviewer["unitId"]),
             "UNTRUSTED_REVIEWER")

    return DeclaredReviewClosure(current, binding, submission, package, review,
                                 review_control, request, assignment,
                                 assignment_control)


def resolve_declared_acceptance(
    uow,
    work,
    submission_ref,
    review_ref,
    *,
    review_step_id="review",
):
    """Resolve a passing complete review; never persist an acceptance effect."""
    closure = resolve_declared_review(
        uow, work, submission_ref, review_ref, review_step_id=review_step_id)
    if not closure.review.complete:
        raise ApplicationError("SUBMISSION_REVIEW_INCOMPLETE")
    if closure.review.verdict != "pass":
        raise ApplicationError("SUBMISSION_REVIEW_NOT_PASS")
    return closure

