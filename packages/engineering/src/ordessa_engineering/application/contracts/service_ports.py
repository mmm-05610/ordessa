"""Dependencies selected by trusted composition, never by request parameters.

Optional ports retain the original owners' explicit unavailable behavior. This
bundle creates no authority, registry, workflow or replacement state.
"""
from dataclasses import dataclass
from .execution_dispatch import ExecutionDispatchPort
from typing import Callable, Protocol

from .access import BlobStorePort
from .acceptance import AcceptanceAdmissionPort
from .confirmation import ConversationAdmissionPort
from .execution_observations import AuthorizedAcpTurnReader
from .implementation_routes import ImplementationRoutesPort
from .repositories import CommandAccessPort, ProposalControlAdmission
from .run_waits import CurrentRunWaitBindings
from .submissions import SubmissionReportSourcePort, SubmissionSourcePort
from .source_materials import SourceMaterialPort, MethodDeclarationGuard
from .reviewer_admission import SourceReviewBindingsPort
from ...domain.changes.dispatch import DispatchBinding


class ReviewAdmissionPort(Protocol):
    def guard_plan(self, context, plan): ...
    def verify_response(self, context, plan, request, raw_response_ref): ...
    def guard_trust(self, context, records): ...


class ReviewControlAdmissionPort(Protocol):
    def guard_control(self, context, expectations, *, state, reason, evidence,
                      replacement_ref=None): ...


class ReviewerAssignmentsPort(Protocol):
    """Selected original-library assignment owner; request data grants no role."""
    factory: object
    access: CommandAccessPort
    expected_scope: object
    def assign_reviewer(self, context, *, review_id, expected_plan_digest,
                        request_version, fence, reviewer_unit_ref,
                        author_unit_ref=None): ...
    def revoke_reviewer(self, context, *, assignment_ref,
                        expected_control_version, reason): ...


@dataclass(frozen=True)
class EngineeringPorts:
    access: CommandAccessPort | None
    proposal_control_admission: ProposalControlAdmission | None = None
    review_admission: ReviewAdmissionPort | None = None
    review_control: ReviewControlAdmissionPort | None = None
    blobs: BlobStorePort | None = None
    conversation_admission: ConversationAdmissionPort | None = None
    acceptance_admission: AcceptanceAdmissionPort | None = None
    submission_source: SubmissionSourcePort | None = None
    current_wait_bindings: CurrentRunWaitBindings | None = None
    submission_report_source: SubmissionReportSourcePort | None = None
    execution_records: AuthorizedAcpTurnReader | None = None
    execution_query_factory: Callable[[DispatchBinding], object] | None = None
    implementation_routes: ImplementationRoutesPort | None = None
    execution_dispatch: ExecutionDispatchPort | None = None
    reviewer_assignments: ReviewerAssignmentsPort | None = None
    source_materials: SourceMaterialPort | None = None
    method_guard: MethodDeclarationGuard | None = None
    source_review_bindings: SourceReviewBindingsPort | None = None
    # Optional source-review execution remains composition-owned.  The Work
    # action is unavailable unless both halves are supplied.
    review_run: Callable | None = None
    review_plan_factory: Callable | None = None


__all__ = ["EngineeringPorts", "ReviewAdmissionPort", "ReviewControlAdmissionPort",
           "ReviewerAssignmentsPort"]
