from __future__ import annotations

from dataclasses import replace

import pytest

from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.mechanisms.hashing import (record_digest)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy,
    CheckKey,
    CheckPolicy,
    ControlledReview,
    CriterionSetRef,
    CurrentReviewTrust,
    Observation,
    ReviewControl,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    ReviewControlExpectation,
    ReviewSetKey,
    ReviewSetExpectation,
    ReviewSetSnapshot,
    VerifiedApplicability,
    observations_digest,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)
from ordessa_engineering.domain.reviews.rules import (evaluate_gate)
from ordessa_engineering.domain.reviews.models import (reduce_review)


SCOPE = Scope("realm-1", "project-1")
CREATED_AT = "2026-10-09T12:00:00.000000Z"
REVIEWER = ActorRef("reviewer-1", "human", "test-issuer")
TARGET_REF = ArtifactRevisionRef(
    SCOPE.realm_id, SCOPE.project_id, "artifact-1", "revision-1", Digest("sha256", "a" * 64),
)
TARGET = Target("proposed", TARGET_REF)


def _digest(seed: str) -> Digest:
    return record_digest("test-evidence", {"seed": seed})


def _case(
    policies: tuple[tuple[str, bool, bool, int, Digest | None], ...] = (
        ("criterion-1", True, True, 1, None),
    ),
    aggregation: AggregationPolicy | None = None,
    *,
    requirement_roles: tuple[str, ...] = ("reviewer",),
    reviewer_requirements: tuple[str, ...] = ("reviewer",),
    phase_key: str = "source",
    requirement_id: str = "req-1",
    requirement_version: int = 1,
    review_id: str = "review-1",
) -> tuple[ReviewRequirement, ReviewPlan, tuple[CheckKey, ...]]:
    keys = tuple(CheckKey(TARGET, criterion_id) for criterion_id, *_ in policies)
    required = tuple(
        key for key, (_, is_required, *_rest) in zip(keys, policies) if is_required
    )
    requirement = ReviewRequirement(
        scope=SCOPE,
        requirement_id=requirement_id,
        requirement_version=requirement_version,
        purpose="quality",
        expected_targets=TargetSet((TARGET,)),
        method_ref=MethodRef("method-1", "1.0.0", 1, _digest("method")),
        criterion_set_ref=CriterionSetRef("criteria-1", 1, _digest("criteria")),
        required_check_keys=required,
        eligible_reviewer_roles=requirement_roles,
        phase_key=phase_key,
    )
    check_policies = tuple(
        CheckPolicy(key, is_required, blocking, weight, rule_ref)
        for key, (_, is_required, blocking, weight, rule_ref) in zip(keys, policies)
    )
    plan = ReviewPlan(
        review_id=review_id,
        requirement=requirement,
        check_policies=check_policies,
        aggregation_policy=aggregation or AggregationPolicy(),
        reviewer_requirements=reviewer_requirements,
    )
    return requirement, plan, keys


def _observation(key: CheckKey, result: str, *, evidence=(), rule=None) -> Observation:
    return Observation(key, result, tuple(evidence), f"observed {result}", rule)


def _reviewer(
    plan: ReviewPlan,
    observations: tuple[Observation, ...],
    *,
    scope: Scope | None = None,
    roles: tuple[str, ...] = ("reviewer",),
    request_digest: Digest | None = None,
    obs_digest: Digest | None = None,
    verifier_id: str = "review-verifier",
    trust_version: int = 3,
) -> VerifiedReviewerEvidence:
    return VerifiedReviewerEvidence(
        scope=scope or plan.scope,
        reviewer=REVIEWER,
        roles=roles,
        verifier_id=verifier_id,
        verifier_version="1",
        trust_version=trust_version,
        request_digest=request_digest or plan.request_digest,
        raw_response_digest=_digest("raw-response"),
        observations_digest=obs_digest or observations_digest(observations),
        capability_digest=_digest("capability"),
    )


def _sealed(
    plan: ReviewPlan,
    observations: tuple[Observation, ...],
    proofs: tuple[VerifiedApplicability, ...] = (),
    *,
    reviewer: VerifiedReviewerEvidence | None = None,
) -> ReviewRecord:
    evidence = reviewer or _reviewer(plan, observations)
    return ReviewRecord(
        identity=RecordIdentity(SCOPE, plan.review_id, CREATED_AT, REVIEWER),
        plan=plan,
        reviewer_evidence=evidence,
        observations=observations,
        applicability_proofs=proofs,
    )


def _controlled(record: ReviewRecord, *, state: str = "active") -> ControlledReview:
    if state == "active":
        control = ReviewControl(SCOPE, record.plan.review_id)
    else:
        control = ReviewControl(
            SCOPE,
            record.plan.review_id,
            state=state,
            reason="controlled test transition",
            control_evidence=(_digest("control"),),
            version=1,
        )
    return ControlledReview(record, control)


def _current_trust(record: ReviewRecord) -> CurrentReviewTrust:
    evidence = record.reviewer_evidence
    return CurrentReviewTrust(record.ref, evidence.verifier_id, evidence.trust_version)


def test_seal_reduces_all_required_checks_and_hashes_the_derived_record() -> None:
    requirement, plan, keys = _case(
        policies=(
            ("required-a", True, True, 1, None),
            ("required-b", True, False, 1, None),
        ),
    )
    observations = (_observation(keys[1], "pass"), _observation(keys[0], "pass"))
    completed, complete, verdict = reduce_review(plan, observations, _reviewer(plan, observations), ())
    assert completed == tuple(sorted(keys, key=lambda item: item.sort_key))
    assert complete is True and verdict == "pass"

    record = _sealed(plan, observations)
    assert record.complete is True and record.verdict == "pass"
    assert record.ref == ReviewRef(SCOPE.realm_id, SCOPE.project_id, plan.review_id, record.digest)
    changed_evidence = replace(record.reviewer_evidence, raw_response_digest=_digest("other-response"))
    changed = _sealed(plan, observations, reviewer=changed_evidence)
    assert changed.digest != record.digest
    assert requirement.digest == plan.requirement.digest


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("scope", Scope("realm-2", "project-1"), "REALM_MISMATCH"),
        ("request_digest", _digest("wrong-request"), "REVIEW_STALE"),
        ("obs_digest", _digest("wrong-observations"), "REVIEW_STALE"),
        ("roles", ("unrecognized-role",), "UNTRUSTED_REVIEWER"),
        ("roles", ("reviewer", "unknown-role"), "UNTRUSTED_REVIEWER"),
    ],
)
def test_review_evidence_must_match_scope_request_observations_and_roles(field, value, code) -> None:
    _, plan, (key,) = _case()
    observations = (_observation(key, "pass"),)
    args = {field: value}
    reviewer = _reviewer(plan, observations, **args)
    with pytest.raises(ReferenceError) as error:
        reduce_review(plan, observations, reviewer, ())
    assert error.value.code == code


def test_review_rejects_duplicate_out_of_plan_and_wrongly_typed_observations() -> None:
    _, plan, (key,) = _case()
    observation = _observation(key, "pass")
    duplicate = (observation, observation)
    # The digest is supplied explicitly because duplicate keys are rejected
    # before any reviewer evidence is accepted.
    reviewer = _reviewer(plan, (observation,))
    with pytest.raises(ReferenceError) as repeated:
        reduce_review(plan, duplicate, reviewer, ())
    assert repeated.value.code == "DUPLICATE_CHECK"

    outside = _observation(CheckKey(TARGET, "not-in-plan"), "pass")
    with pytest.raises(ReferenceError) as extra:
        reduce_review(plan, (outside,), _reviewer(plan, (outside,)), ())
    assert extra.value.code == "CHECK_OUT_OF_PLAN"

    with pytest.raises(ReferenceError) as wrong_type:
        reduce_review(plan, [observation], reviewer, ())  # type: ignore[arg-type]
    assert wrong_type.value.code == "INVALID_SCHEMA"


@pytest.mark.parametrize(
    ("result", "expected_complete", "expected_verdict"),
    [
        ("pass", True, "pass"),
        ("fail", True, "fail"),
        ("indeterminate", True, "indeterminate"),
        ("conflict", True, "conflict"),
    ],
)
def test_fail_unknown_and_conflict_are_complete_observations_but_never_pass(
    result, expected_complete, expected_verdict,
) -> None:
    _, plan, (key,) = _case()
    observations = (_observation(key, result),)
    record = _sealed(plan, observations)
    assert record.complete is expected_complete
    assert record.verdict == expected_verdict


def test_required_missing_is_incomplete_and_security_reductions_have_priority() -> None:
    _, one_check_plan, _ = _case()
    empty: tuple[Observation, ...] = ()
    record = _sealed(one_check_plan, empty)
    assert record.complete is False
    assert record.verdict == "indeterminate"

    _, plan, keys = _case(policies=(
        ("conflict", True, True, 1, None),
        ("failure", True, True, 1, None),
        ("missing", True, False, 1, None),
    ))
    conflict_and_failure = (
        _observation(keys[0], "conflict"),
        _observation(keys[1], "fail"),
    )
    reviewer = _reviewer(plan, conflict_and_failure)
    _, complete, verdict = reduce_review(plan, conflict_and_failure, reviewer, ())
    assert complete is False and verdict == "conflict"

    failure_only = (_observation(keys[1], "fail"),)
    _, complete, verdict = reduce_review(plan, failure_only, _reviewer(plan, failure_only), ())
    assert complete is False and verdict == "fail"


def test_all_applicable_honors_frozen_soft_failure_policy_and_unknown_never_clears() -> None:
    _, plan, keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("soft", False, False, 1, None),
        ),
        aggregation=AggregationPolicy(mode="all_applicable", soft_failures_block=False),
    )
    soft_failure = (_observation(keys[0], "pass"), _observation(keys[1], "fail"))
    assert _sealed(plan, soft_failure).verdict == "pass"

    unknown = (_observation(keys[0], "pass"), _observation(keys[1], "indeterminate"))
    assert _sealed(plan, unknown).verdict == "indeterminate"

    _, blocking_soft_plan, blocking_soft_keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("soft", False, False, 1, None),
        ),
        aggregation=AggregationPolicy(mode="all_applicable", soft_failures_block=True),
    )
    blocked_soft_failure = (
        _observation(blocking_soft_keys[0], "pass"),
        _observation(blocking_soft_keys[1], "fail"),
    )
    assert _sealed(blocking_soft_plan, blocked_soft_failure).verdict == "fail"


def test_all_applicable_requires_optional_check_accounting_but_threshold_does_not() -> None:
    _, all_plan, all_keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("optional", False, False, 2, None),
        ),
        aggregation=AggregationPolicy(mode="all_applicable", soft_failures_block=False),
    )
    only_required = (_observation(all_keys[0], "pass"),)
    omitted_optional = _sealed(all_plan, only_required)
    assert omitted_optional.complete is True
    assert omitted_optional.verdict == "indeterminate"

    optional_unknown = (
        _observation(all_keys[0], "pass"),
        _observation(all_keys[1], "indeterminate"),
    )
    unknown_optional = _sealed(all_plan, optional_unknown)
    assert unknown_optional.complete is True
    assert unknown_optional.verdict == "indeterminate"

    _, threshold_plan, threshold_keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("optional", False, False, 2, None),
        ),
        aggregation=AggregationPolicy(mode="threshold", threshold=1),
    )
    threshold_missing_optional = _sealed(
        threshold_plan, (_observation(threshold_keys[0], "pass"),),
    )
    assert threshold_missing_optional.complete is True
    assert threshold_missing_optional.verdict == "pass"


def test_threshold_uses_only_pass_weight_and_preserves_uncertainty() -> None:
    _, plan, keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("weighted-optional", False, False, 2, None),
        ),
        aggregation=AggregationPolicy(mode="threshold", threshold=2),
    )
    unresolved = (_observation(keys[0], "pass"), _observation(keys[1], "indeterminate"))
    assert _sealed(plan, unresolved).complete is True
    assert _sealed(plan, unresolved).verdict == "indeterminate"

    enough_pass_weight = (_observation(keys[0], "pass"), _observation(keys[1], "pass"))
    assert _sealed(plan, enough_pass_weight).verdict == "pass"

    insufficient_known_weight = (_observation(keys[0], "pass"), _observation(keys[1], "fail"))
    assert _sealed(plan, insufficient_known_weight).verdict == "fail"

    _, enough_unknown_plan, enough_unknown_keys = _case(
        policies=(
            ("required", True, True, 2, None),
            ("unknown-optional", False, False, 2, None),
        ),
        aggregation=AggregationPolicy(mode="threshold", threshold=2),
    )
    pass_plus_unknown = (
        _observation(enough_unknown_keys[0], "pass"),
        _observation(enough_unknown_keys[1], "indeterminate"),
    )
    # The unknown receives zero points; the independent passing weight already
    # meets the frozen threshold, so the unknown does not veto the result.
    assert _sealed(enough_unknown_plan, pass_plus_unknown).verdict == "pass"

    _, enough_conflict_plan, enough_conflict_keys = _case(
        policies=(
            ("required", True, True, 2, None),
            ("conflict-optional", False, False, 2, None),
        ),
        aggregation=AggregationPolicy(mode="threshold", threshold=2),
    )
    pass_plus_conflict = (
        _observation(enough_conflict_keys[0], "pass"),
        _observation(enough_conflict_keys[1], "conflict"),
    )
    assert _sealed(enough_conflict_plan, pass_plus_conflict).verdict == "pass"

    _, short_conflict_plan, short_conflict_keys = _case(
        policies=(
            ("required", True, True, 1, None),
            ("conflict-optional", False, False, 1, None),
        ),
        aggregation=AggregationPolicy(mode="threshold", threshold=2),
    )
    pass_short_plus_conflict = (
        _observation(short_conflict_keys[0], "pass"),
        _observation(short_conflict_keys[1], "conflict"),
    )
    assert _sealed(short_conflict_plan, pass_short_plus_conflict).verdict == "conflict"


def test_not_applicable_needs_matching_plan_rule_unique_proof_and_actual_evidence() -> None:
    rule = _digest("applicability-rule")
    _, plan, (key,) = _case(policies=(("conditional", True, True, 1, rule),))
    evidence = (TARGET_REF,)
    observation = _observation(key, "not_applicable", evidence=evidence, rule=rule)
    proof = VerifiedApplicability(key, rule, evidence)
    record = _sealed(plan, (observation,), (proof,))
    assert record.complete is True and record.verdict == "pass"

    cases = (
        ((observation,), ()),
        ((_observation(key, "not_applicable", evidence=evidence, rule=_digest("wrong-rule")),), (proof,)),
        ((_observation(key, "not_applicable", rule=rule),), (VerifiedApplicability(key, rule, evidence),)),
        ((observation,), (proof, proof)),
        ((_observation(key, "pass"),), (proof,)),
        ((observation,), (VerifiedApplicability(key, _digest("wrong-proof-rule"), evidence),)),
    )
    for observations, proofs in cases:
        reviewer = _reviewer(plan, observations)
        with pytest.raises(ReferenceError) as invalid:
            reduce_review(plan, observations, reviewer, proofs)
        assert invalid.value.code == "INVALID_NA"

    with pytest.raises(ReferenceError) as empty_evidence:
        VerifiedApplicability(key, rule, ())
    assert empty_evidence.value.code == "INVALID_NA"

    _, no_rule_plan, (no_rule_key,) = _case(policies=(("conditional", True, True, 1, None),))
    no_rule_na = _observation(no_rule_key, "not_applicable", evidence=evidence, rule=rule)
    with pytest.raises(ReferenceError) as no_policy:
        _sealed(no_rule_plan, (no_rule_na,), (VerifiedApplicability(no_rule_key, rule, evidence),))
    assert no_policy.value.code == "INVALID_NA"


def test_gate_requires_current_trust_and_emits_all_set_and_control_expectations() -> None:
    requirement, plan, (key,) = _case()
    record = _sealed(plan, (_observation(key, "pass"),))
    controlled = _controlled(record)
    snapshot = ReviewSetSnapshot(ReviewSetKey.for_requirement(requirement), 7, (controlled,))

    valid = evaluate_gate(requirement, snapshot, (_current_trust(record),))
    assert valid.satisfied is True and valid.code == "SATISFIED"
    assert valid.used_review_refs == (record.ref,)
    assert valid.review_set_expectations == (ReviewSetExpectation(snapshot.key, 7),)
    assert valid.control_expectations == (ReviewControlExpectation(record.ref, 0),)
    assert valid.evaluated_targets_digest == requirement.expected_targets.digest

    missing_trust = evaluate_gate(requirement, snapshot, ())
    assert missing_trust.satisfied is False and missing_trust.code == "UNTRUSTED_REVIEWER"
    changed_trust = CurrentReviewTrust(record.ref, "different-verifier", 3)
    assert evaluate_gate(requirement, snapshot, (changed_trust,)).code == "UNTRUSTED_REVIEWER"


def test_gate_uses_exact_requirement_digest_and_propagates_active_conflicts() -> None:
    requirement, plan, (key,) = _case()
    pass_record = _sealed(plan, (_observation(key, "pass"),))

    # The ReviewSetKey intentionally identifies the predicate dimensions, but
    # an active record must still bind the exact frozen requirement digest.
    alternate_requirement, alternate_plan, (alternate_key,) = _case(
        phase_key="different-phase", review_id="stale-review",
    )
    assert ReviewSetKey.for_requirement(alternate_requirement) == ReviewSetKey.for_requirement(requirement)
    stale = _sealed(alternate_plan, (_observation(alternate_key, "pass"),))
    stale_snapshot = ReviewSetSnapshot(
        ReviewSetKey.for_requirement(requirement), 1, (_controlled(stale),),
    )
    assert evaluate_gate(requirement, stale_snapshot, (_current_trust(stale),)).code == "REVIEW_STALE"

    _, fail_plan, (fail_key,) = _case(review_id="review-fail")
    fail_record = _sealed(fail_plan, (_observation(fail_key, "fail"),))
    snapshot = ReviewSetSnapshot(
        ReviewSetKey.for_requirement(requirement),
        2,
        (_controlled(pass_record), _controlled(fail_record)),
    )
    decision = evaluate_gate(
        requirement, snapshot, (_current_trust(pass_record), _current_trust(fail_record)),
    )
    assert decision.satisfied is False and decision.code == "REVIEW_CONFLICT"
    assert set(decision.used_review_refs) == {pass_record.ref, fail_record.ref}
    assert len(decision.control_expectations) == 2


def test_voided_review_is_preserved_as_control_expectation_but_never_a_pass() -> None:
    requirement, plan, (key,) = _case()
    record = _sealed(plan, (_observation(key, "pass"),))
    controlled = _controlled(record, state="voided")
    snapshot = ReviewSetSnapshot(ReviewSetKey.for_requirement(requirement), 2, (controlled,))
    decision = evaluate_gate(requirement, snapshot, ())
    assert decision.satisfied is False and decision.code == "REVIEW_INCOMPLETE"
    assert decision.used_review_refs == ()
    assert decision.control_expectations == (ReviewControlExpectation(record.ref, 1),)


def test_gate_rejects_wrong_set_key_duplicate_or_unbound_trust() -> None:
    requirement, plan, (key,) = _case()
    record = _sealed(plan, (_observation(key, "pass"),))
    snapshot = ReviewSetSnapshot(ReviewSetKey.for_requirement(requirement), 1, (_controlled(record),))

    wrong_requirement, _, _ = _case(requirement_id="req-other")
    with pytest.raises(ReferenceError) as wrong_set:
        evaluate_gate(wrong_requirement, snapshot, (_current_trust(record),))
    assert wrong_set.value.code == "REVIEW_STALE"

    trust = _current_trust(record)
    with pytest.raises(ReferenceError) as duplicate:
        evaluate_gate(requirement, snapshot, (trust, trust))
    assert duplicate.value.code == "DUPLICATE_REVIEW"

    unrelated = CurrentReviewTrust(
        ReviewRef(SCOPE.realm_id, SCOPE.project_id, "unrelated", _digest("unrelated")),
        "review-verifier", 3,
    )
    with pytest.raises(ReferenceError) as unbound:
        evaluate_gate(requirement, snapshot, (trust, unrelated))
    assert unbound.value.code == "UNTRUSTED_REVIEWER"
