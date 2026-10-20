"""Agent review request/result demand-side contracts; no execution or trust owner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .reviewer_admission import CriterionAnswer
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.common.models.values import Digest
from ...domain.reviews.models import ReviewPlan
from ...domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ...methods.definitions.models.identity import ResourceRef


@dataclass(frozen=True)
class AgentReviewBinding:
    """Trusted method/business resolution for one exact review Agent invocation."""
    plan_digest: Digest
    request_version: int
    request_fence: int
    execution_ref: AgentExecutionRecordRef
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
    execution_ref: AgentExecutionRecordRef
    params: dict
    query_invocation: object


class AgentReviewBindingResolver(Protocol):
    """Trusted method/composition resolver, never supplied by review caller.

    `expected_prompt_digest` must be computed from the exact fixed-version Agent
    prompt, including every delivery ref, schema ref/digest, full plan/check-key
    selection and identity constraints. The original query digest then binds
    that prompt to the Agent turn. An absent or partial declaration refuses.
    Decision/JEV bindings additionally freeze the exact question resources and
    every method-owned required input slot/value in that prompt. Input contract
    and mapping version come from those definitions, not host name guesses.
    """
    def resolve_agent_review(self, context, plan: ReviewPlan, request, *, standard) -> AgentReviewBinding: ...

    def decode_response(self, binding: AgentReviewBinding, response_value, *, plan: ReviewPlan,
                        standard) -> tuple[CriterionAnswer, ...]:
        """Map schema-validated JSON to exact answer keys; no verdict authority."""
        ...

    def resolve_record_request(self, context, plan: ReviewPlan, record):
        """Recover the request version/fence frozen into this historical record.

        Must bind back to the exact Agent/turn/query/raw response, without requiring
        that the historical request still be in `requested` state.
        """
        ...


class AgentReviewerAuthority(Protocol):
    def guard_agent_reviewer(self, context, plan, request, binding, raw_response_ref,
                            observation_digest, *, expected=None):
        """Yield VerifiedReviewerEvidence from the real current authority.

        The returned owner-held guard must bind identity constraints, roles,
        capability and current trust epoch and remain live through COMMIT.
        Missing authority or a non-context-manager guard refuses.
        """
        ...

__all__ = ["AgentReviewBinding", "AgentReviewBindingResolver", "AgentReviewerAuthority", "NativeReviewInvocation"]
