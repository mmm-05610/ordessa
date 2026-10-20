"""Actual source verification inputs; values alone never attest reviewer trust."""
from dataclasses import dataclass
from typing import Protocol
from ...domain.reviews.models import CheckKey
from ...domain.reviews.evidence import VerifiedReviewerEvidence
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.reviews.refs import SubmissionRef
from ...domain.reviews.models import ReviewPlan
from ...methods.definitions.models import MethodDefinition, StandardDefinition


@dataclass(frozen=True)
class SourceReviewBinding:
    """Method-owner selection, never evidence of reviewer authorization."""
    plan: ReviewPlan
    standard: StandardDefinition


class SourceReviewBindingsPort(Protocol):
    def resolve_source_plan(self, context, plan: ReviewPlan,
                            definition: MethodDefinition) -> SourceReviewBinding:
        """Independently bind the exact explicit source-review action and checks.

        Do not echo a client plan as approval. Actual source/trust admission is
        still performed by ReviewerSourcePort and held through original COMMIT.
        No global workflow phase or fabricated ArtifactRevision participates.
        """
        ...


class DeclaredSubmissionReviewBindingsPort(Protocol):
    """Selected original-library owner for a declared report's exact plan.

    This optional capability does not reinterpret a historical compiled plan.
    The owner must derive the complete checks from the pinned method resources;
    echoing a supplied plan does not constitute production admission.
    """
    factory: object

    def resolve_declared_submission_plan(self, context, plan: ReviewPlan,
                                        definition: MethodDefinition) -> SourceReviewBinding: ...


class DeclaredImplementationReviewPlanFactory(Protocol):
    """Optional capability of the composition-selected review plan producer.

    The returned schema-2 plan targets the exact persisted report. Native
    reviewer selection, assignment, execution and trust remain with their
    original owners; producing this value supplies none of those authorities.
    """
    factory: object

    def implementation_plan(self, context, work, *, review_id, submission,
                            package, reviewer_profile_ref, requirement_id,
                            resources) -> ReviewPlan: ...


@dataclass(frozen=True)
class CriterionAnswer:
    check_key: CheckKey
    status: str
    evidence_refs: tuple[ArtifactRevisionRef, ...]
    rationale: str


@dataclass(frozen=True)
class NominalCriterionResolution:
    """Public classification and quality facts; never reviewer authentication."""
    answer: CriterionAnswer
    classification_reason: str
    quality_disposition: str
    quality_reason: str


@dataclass(frozen=True)
class VerifiedReviewResponse:
    reviewer_evidence: VerifiedReviewerEvidence
    answers: tuple[CriterionAnswer, ...]


class ReviewerSourcePort(Protocol):
    """Original durable execution/source owner, not a wire-supplied response DTO.

    Verify actual run/terminal/digest/request/plan, roles and capability identity.
    guard_trust must recheck those original facts and hold through COMMIT.
    Engineering translates admitted semantic statuses using the frozen method;
    Decision remains independent of approval/domain code.

    To bind observations_digest without copying disposition rules, call the
    public application.usecases.reviews.admission.review_observations with the
    supplied exact standard and complete answers, then the original domain
    observations_digest. Admission independently repeats the same projection.
    """
    def verify_response(self, context, plan, request, raw_response_ref, *, standard) -> VerifiedReviewResponse: ...
    def guard_trust(self, context, records): ...


class ReviewBindingsPort(Protocol):
    """Configured original business-input owner; never resolved from client plan."""
    def resolve_bindings(self, context, method_ref, phase_key): ...

    def resolve_review_proposal(self, context, method_ref, phase_key):
        """Exact original ProposalRef for document-target review, or None.

        Selected by the configured business owner, not guessed from requirement
        IDs, material labels, caller targets or latest Proposal state.
        """
        ...

    def resolve_intent_bindings(self, context, method_ref, proposal_ref):
        """All applicable phase bindings for this exact original Proposal.

        The configured business owner determines the complete phase/target/slot
        set, independently of caller requirements or stored template omissions.
        Return a nonempty tuple of EngineeringTargetBindings. This is not a
        wire command and captured bindings alone do not authenticate their source.
        """
        ...

    def resolve_review_submission(self, context, method_ref, phase_key) -> SubmissionRef | None:
        """Select the exact persisted Submission for this configured phase."""
        ...

    def resolve_submission_bindings(self, context, method_ref, submission_ref):
        """Return every applicable acceptance phase for this exact Submission.

        Bindings and phase completeness are chosen by the configured business
        owner, never by a client ReviewPlan or a latest-record query.
        """
        ...

    def resolve_acceptance_submission(self, context, intent):
        """Select the exact Submission governed by this frozen acceptance intent."""
        ...
