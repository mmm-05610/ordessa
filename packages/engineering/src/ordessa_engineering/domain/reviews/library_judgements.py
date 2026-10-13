from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Literal, TypeAlias
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.artifacts.library_materials import MaterialRef, _DIGEST

class ReviewVerdict:
    CLEAR = 'CLEAR'
    REVISION_REQUIRED = 'REVISION_REQUIRED'
    CONFLICT = 'CONFLICT'
    INDETERMINATE = 'INDETERMINATE'
    ALL = (CLEAR, REVISION_REQUIRED, CONFLICT, INDETERMINATE)
ReviewVerdictValue: TypeAlias = Literal['CLEAR', 'REVISION_REQUIRED', 'CONFLICT', 'INDETERMINATE']

@dataclass(frozen=True)
class ReviewJudgement:
    """Engineering-domain verdict linked to (never inferred from) Decision facts."""
    verdict: ReviewVerdictValue
    decision_run_ref: MaterialRef
    answer_digest: str
    policy_ref: MaterialRef
    check_receipt_refs: tuple[MaterialRef, ...]
    registry_ref: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.verdict not in ReviewVerdict.ALL:
            raise EngineeringError('review_verdict')
        if self.decision_run_ref.kind != 'decision-run' or self.policy_ref.kind != 'review-policy':
            raise EngineeringError('review_decision_refs')
        if not _DIGEST.fullmatch(self.answer_digest):
            raise EngineeringError('review_answer_digest')
        if any((not isinstance(ref, MaterialRef) for ref in self.check_receipt_refs)):
            raise EngineeringError('review_check_refs')
        if not isinstance(self.registry_ref, Mapping) or set(self.registry_ref) != {'registry_id', 'revision', 'digest'}:
            raise EngineeringError('review_registry_ref')
