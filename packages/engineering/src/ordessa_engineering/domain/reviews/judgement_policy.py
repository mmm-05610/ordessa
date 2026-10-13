from __future__ import annotations
from typing import Any
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.reviews.library_judgements import ReviewVerdict
from dataclasses import dataclass

@dataclass(frozen=True)
class ReviewFacts:
    source_status: str
    standard_status: str
    summary_status: str
    unavailable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {'source_status': self.source_status, 'standard_status': self.standard_status, 'summary_status': self.summary_status, 'unavailable': self.unavailable}

class ReviewPolicy:

    def __init__(self, precedence: tuple[str, ...], rules: dict[str, str]):
        if set(precedence) != set(ReviewVerdict.ALL) or len(precedence) != 4:
            raise EngineeringError('review_policy_precedence')
        if set(rules) != {'conflict', 'unknown', 'gap', 'all_checks_pass'} or any((value not in ReviewVerdict.ALL for value in rules.values())):
            raise EngineeringError('review_policy_rules')
        self.precedence = precedence
        self.rules = rules

    def _select(self, state: dict[str, Any]) -> str:
        source = state['source_status']
        standard = state['standard_status']
        summary = state['summary_status']
        signals = set()
        known = ({'SUPPORTED', 'NEEDS_EVIDENCE', 'CONFLICT', 'INDETERMINATE'}, {'SATISFIED', 'NEEDS_EVIDENCE', 'CONFLICT', 'INDETERMINATE'}, {'FAITHFUL', 'CONFLICT', 'INDETERMINATE'})
        if state['unavailable'] or 'INDETERMINATE' in (source, standard, summary) or any((value not in allowed for value, allowed in zip((source, standard, summary), known, strict=True))):
            signals.add(self.rules['unknown'])
        if 'CONFLICT' in (source, standard, summary):
            signals.add(self.rules['conflict'])
        if source == 'NEEDS_EVIDENCE' or standard in {'NEEDS_EVIDENCE', 'GAP'}:
            signals.add(self.rules['gap'])
        if source == 'SUPPORTED' and standard == 'SATISFIED' and (summary == 'FAITHFUL'):
            signals.add(self.rules['all_checks_pass'])
        for verdict in self.precedence:
            if verdict in signals:
                return verdict
        raise EngineeringError('review_policy_no_verdict')
