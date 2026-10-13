"""Exact human review reply capture; not consent for a change or a Grant."""
from dataclasses import dataclass
from typing import Protocol
from ...domain.approvals.consent import ConversationSource
from ...domain.reviews.models import ReviewPlan
from ...domain.reviews.evidence import VerifiedReviewerEvidence
from ...domain.common.models.values import Digest
from .reviewer_admission import CriterionAnswer


@dataclass(frozen=True)
class ManualReviewReply:
    question: str
    necessary_context: str
    user_answer: str
    source: ConversationSource
    check_answers: tuple[CriterionAnswer,...]


class ManualReviewAuthorityPort(Protocol):
    def guard_reply(self,context,plan,request,reply):
        """Yield actual human/source verification facts and hold until COMMIT.

        Verify configured product manual-review policy, real question/context/
        explicit answer and available locator+limitations, exact full plan/object
        version/scope/CheckKeys. v1 agent-attested source may be admitted when
        product selects it. Machine bearer/ActorRef alone never proves a human;
        structured answers must faithfully reflect the actual reply. No extra
        click or strong signature is required by this library. No Grant or
        evaluation is created. Missing authority refuses.
        """
        ...

    def guard_disposition(self,context,plan,frozen_request,raw_response_ref,reply,*,
                          standard,mechanical_answers,expected=None):
        """Verify actual human Q&A and selected external policy; hold to COMMIT.

        Yield VerifiedHumanDisposition. policy_bytes are the actual currently
        selected Product policy, never selected by the method/caller. Verify
        registered attestor capability/epoch and reviewer role, exact displayed
        Plan/keys/versions/limitations, explicit reply and faithful per-key
        expansion. agent-attested is sufficient under the selected policy; do
        not claim independent human authentication. expected rechecks the exact
        captured source/current trust. The frozen request is historical source
        correlation; current requested/version/fence CAS belongs to Review.

        To bind observations_digest use the public human_review_observations
        with actual policy_bytes and supplied exact mechanical_answers. The
        Engineering admission repeats it. No response means no formal record;
        review does not authorize implementation or produce a Grant.
        """
        ...


@dataclass(frozen=True)
class VerifiedHumanDisposition:
    policy_bytes: bytes
    reviewer_evidence: VerifiedReviewerEvidence
    explicit_answer: bool
    presentation_digest: Digest
