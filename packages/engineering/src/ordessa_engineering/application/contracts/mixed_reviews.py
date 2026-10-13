"""Original mixed check-source contracts; DTOs never authenticate their owners."""
from dataclasses import dataclass
from typing import Protocol
from ...domain.common.models.values import Digest
from ...domain.reviews.models import ReviewPlan
from .reviewer_admission import CriterionAnswer


@dataclass(frozen=True)
class FrozenCheckRequest:
    """Historical source correlation, never proof of current requested state."""
    plan_digest: Digest
    request_version: int
    fence: int


@dataclass(frozen=True)
class VerifiedCheckResponse:
    answers: tuple[CriterionAnswer, ...]
    provenance_digest: Digest


@dataclass(frozen=True)
class CheckSourceAdmission:
    plan: ReviewPlan
    request: FrozenCheckRequest
    raw_response_ref: object
    check_keys: tuple
    response: VerifiedCheckResponse


class ReviewCheckSourcePort(Protocol):
    def verify_checks(self,context,plan,request,raw_response_ref,*,standard,check_keys): ...
    def guard_checks(self,context,admissions):
        """Reverify actual source bytes/roles/capabilities/epochs; hold until COMMIT.

        Full original plan stays unchanged when checking a subset. Request is
        frozen source correlation. Current ReviewRequest CAS is the original
        write owner, not inferred from this DTO. Missing current source refuses.
        """
        ...


class MixedReviewerAuthorityPort(Protocol):
    def guard_verification(self,context,plan,raw_response_ref,observations_digest,provenance_digest,*,expected=None):
        """Original actual composite reviewer principal/role/capability authority.

        Yield VerifiedReviewerEvidence bound to exact full raw/observations and
        all-source provenance digest. Never union source actors into a human or
        infer roles from configured source IDs. expected rechecks the exact
        captured principal/role/verifier/capability/trust epoch, held to COMMIT.
        Default missing refuses; no new principal or trust database is created.
        The evidence capability_digest must bind both the actual admitted
        capability and this provenance digest; provenance alone is not a
        capability or proof of an authenticated principal.
        """
        ...
