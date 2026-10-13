"""Deterministic review sealing and gate rules; no trust lookup or I/O."""
from __future__ import annotations

from ..common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.reviews.refs import (ReviewRef)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)
from .models import (
    CheckKey,
    CurrentReviewTrust,
    GateDecision,
    Observation,
    ReviewControlExpectation,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    ReviewSetExpectation,
    ReviewSetKey,
    ReviewSetSnapshot,
    VerifiedApplicability,
    observations_digest,
)


def _review_ref_sort(ref: ReviewRef) -> tuple[str, str, str, str]:
    return ref.realm_id, ref.project_id, ref.review_id, ref.digest.hex


def _fail(code: str) -> None:
    raise ReferenceError(code)


def evaluate_gate(
    requirement: ReviewRequirement,
    snapshot: ReviewSetSnapshot,
    current_trust: tuple[CurrentReviewTrust, ...],
) -> GateDecision:
    """Evaluate the complete current review set without resolving or mutating it."""
    if type(requirement) is not ReviewRequirement or type(snapshot) is not ReviewSetSnapshot:
        _fail("INVALID_SCHEMA")
    if type(current_trust) is not tuple or any(type(item) is not CurrentReviewTrust for item in current_trust):
        _fail("INVALID_SCHEMA")
    expected_key = ReviewSetKey.for_requirement(requirement)
    if snapshot.key != expected_key:
        _fail("REVIEW_STALE")

    trust_by_ref: dict[ReviewRef, CurrentReviewTrust] = {}
    for trusted in current_trust:
        if trusted.review_ref in trust_by_ref:
            _fail("DUPLICATE_REVIEW")
        trust_by_ref[trusted.review_ref] = trusted

    active = tuple(item for item in snapshot.reviews if item.control.state == "active")
    active_refs = {item.record.ref for item in active}
    if any(ref not in active_refs for ref in trust_by_ref):
        _fail("UNTRUSTED_REVIEWER")

    controls = tuple(sorted((
        ReviewControlExpectation(item.record.ref, item.control.version)
        for item in snapshot.reviews
    ), key=lambda item: _review_ref_sort(item.review_ref)))
    used_refs = tuple(sorted((item.record.ref for item in active), key=_review_ref_sort))
    set_expectation = (ReviewSetExpectation(snapshot.key, snapshot.set_version),)

    def decision(satisfied: bool, code: str) -> GateDecision:
        return GateDecision(
            satisfied=satisfied,
            code=code,
            used_review_refs=used_refs,
            review_set_expectations=set_expectation,
            control_expectations=controls,
            evaluated_targets_digest=requirement.expected_targets.digest,
        )

    if any(item.record.plan.requirement.digest != requirement.digest for item in active):
        return decision(False, "REVIEW_STALE")
    if not active:
        return decision(False, "REVIEW_INCOMPLETE")

    trust_mismatch = False
    for item in active:
        trusted = trust_by_ref.get(item.record.ref)
        evidence = item.record.reviewer_evidence
        if (trusted is None or trusted.verifier_id != evidence.verifier_id
                or trusted.trust_version != evidence.trust_version):
            trust_mismatch = True
            break
    if trust_mismatch:
        return decision(False, "UNTRUSTED_REVIEWER")

    if any(not item.record.complete for item in active):
        return decision(False, "REVIEW_INCOMPLETE")

    verdicts = {item.record.verdict for item in active}
    has_pass = "pass" in verdicts
    has_negative = bool(verdicts & {"fail", "conflict"})
    if has_pass and has_negative:
        return decision(False, "REVIEW_CONFLICT")
    if "conflict" in verdicts:
        return decision(False, "REVIEW_CONFLICT")
    if "fail" in verdicts:
        return decision(False, "REVIEW_FAILED")
    if "indeterminate" in verdicts:
        return decision(False, "REVIEW_INDETERMINATE")
    if verdicts != {"pass"}:
        return decision(False, "REVIEW_INCOMPLETE")
    return decision(True, "SATISFIED")
