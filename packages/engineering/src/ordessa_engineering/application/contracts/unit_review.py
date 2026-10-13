"""Original Unit review request/result demand-side contracts; no execution or trust owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .reviewer_admission import CriterionAnswer
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.common.models.values import Digest
from ...domain.reviews.models import ReviewPlan
from ...methods.definitions.models.identity import ResourceRef


@dataclass(frozen=True)
class UnitReviewBinding:
    """Trusted method/business resolution for one exact review Unit invocation."""
    plan_digest: Digest
    request_version: int
    request_fence: int
    unit_ref: dict
    operation_ref: str
    expected_prompt_digest: str
    query_invocation: object
    delivery_refs: tuple[ArtifactRevisionRef, ...]
    response_schema_ref: ResourceRef
    response_document_type: str
    response_schema: bytes
    response_schema_digest: Digest
    reviewer_identity_constraints: object
    required_check_keys: tuple
    decision_question_refs: tuple[ResourceRef, ...] = ()
    decision_input_slots: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeReviewInvocation:
    """Captured original Execution values; no identity or role authority."""
    unit_ref: dict
    operation_ref: str
    params: dict
    query_invocation: object


class UnitReviewBindingResolver(Protocol):
    """Trusted method/composition resolver, never supplied by review caller.

    `expected_prompt_digest` must be computed from the exact fixed-version Unit
    prompt, including every delivery ref, schema ref/digest, full plan/check-key
    selection and identity constraints. The original query digest then binds
    that prompt to the Unit operation. An absent or partial declaration refuses.
    Decision/JEV bindings additionally freeze the exact question resources and
    every method-owned required input slot/value in that prompt. Input contract
    and mapping version come from those definitions, not host name guesses.
    """
    def resolve_unit_review(self, context, plan: ReviewPlan, request, *, standard) -> UnitReviewBinding: ...

    def decode_response(self, binding: UnitReviewBinding, response_value, *, plan: ReviewPlan,
                        standard) -> tuple[CriterionAnswer, ...]:
        """Map schema-validated JSON to exact answer keys; no verdict authority."""
        ...

    def resolve_record_request(self, context, plan: ReviewPlan, record):
        """Recover the request version/fence frozen into this historical record.

        Must bind back to the exact Unit/query/raw response, without requiring
        that the historical request still be in `requested` state.
        """
        ...


class UnitReviewerAuthority(Protocol):
    def guard_unit_reviewer(self, context, plan, request, binding, raw_response_ref,
                            observation_digest, *, expected=None):
        """Yield VerifiedReviewerEvidence from the real current authority.

        The returned owner-held guard must bind identity constraints, roles,
        capability and current trust epoch and remain live through COMMIT.
        Missing authority or a non-context-manager guard refuses.
        """
        ...

__all__ = ["UnitReviewBinding", "UnitReviewBindingResolver", "UnitReviewerAuthority", "NativeReviewInvocation"]
