"""Review identities and records. Evidence DTOs are not authentication grants."""
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)
from ..common.mechanisms.codec import (projection)
from ..common.models.values import (validate_version, validate_text, validate_items, ordered_unique, MAX_VERSION)
from dataclasses import asdict, dataclass, field, fields
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ..common.models.values import (Digest, validate_id)
from ..common.models.identity import (Scope)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.mechanisms.hashing import (record_digest)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)

PURPOSES = frozenset({"provenance_support", "quality", "acceptance"})
RESULTS = frozenset({"pass", "fail", "indeterminate", "conflict", "not_applicable"})


def payload_fields(value, exclude):
    return {f.name: projection(getattr(value, f.name), identity=True)
            for f in fields(value) if f.name not in exclude}


@dataclass(frozen=True)
class CriterionSetRef:
    criterion_set_id: str
    version: int
    digest: Digest

    def __post_init__(self):
        validate_id(self.criterion_set_id)
        validate_version(self.version, positive=True)
        if type(self.digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class CheckKey:
    target: Target
    criterion_id: str
    claim_id: str | None = None

    def __post_init__(self):
        if type(self.target) is not Target:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.criterion_id)
        if self.claim_id is not None:
            validate_id(self.claim_id)

    @property
    def sort_key(self):
        return canonical_bytes(asdict(self))


@dataclass(frozen=True)
class ReviewRequirement:
    scope: Scope
    requirement_id: str
    requirement_version: int
    purpose: str
    expected_targets: TargetSet
    method_ref: MethodRef
    criterion_set_ref: CriterionSetRef
    required_check_keys: tuple[CheckKey, ...]
    eligible_reviewer_roles: tuple[str, ...]
    phase_key: str
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.expected_targets) is not TargetSet
                or type(self.method_ref) is not MethodRef or type(self.criterion_set_ref) is not CriterionSetRef):
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.requirement_id)
        validate_id(self.phase_key)
        validate_version(self.requirement_version, positive=True)
        if type(self.purpose) is not str or self.purpose not in PURPOSES:
            raise ReferenceError("INVALID_SCHEMA")
        if any((t.ref.realm_id, t.ref.project_id) != (self.scope.realm_id, self.scope.project_id)
               for t in self.expected_targets.targets):
            raise ReferenceError("REALM_MISMATCH")
        validate_items(self.required_check_keys, CheckKey, nonempty=True)
        if any(k.target not in self.expected_targets.targets for k in self.required_check_keys):
            raise ReferenceError("CHECK_OUT_OF_PLAN")
        if set(k.target for k in self.required_check_keys) != set(self.expected_targets.targets):
            raise ReferenceError("REVIEW_INCOMPLETE")
        object.__setattr__(self, "required_check_keys", ordered_unique(self.required_check_keys, lambda k: k.sort_key, code='DUPLICATE_CHECK'))
        validate_items(self.eligible_reviewer_roles, str, nonempty=True)
        for role in self.eligible_reviewer_roles:
            validate_id(role)
        object.__setattr__(self, "eligible_reviewer_roles", ordered_unique(self.eligible_reviewer_roles, lambda r: r,
                                                                         code="DUPLICATE_ROLE"))
        object.__setattr__(self, "digest", record_digest("review-requirement", self.hash_payload()))

    def hash_payload(self):
        return payload_fields(self, {"digest"})


@dataclass(frozen=True)
class CheckPolicy:
    key: CheckKey
    required: bool
    blocking: bool
    weight: int = 1
    applicability_rule_ref: Digest | None = None

    def __post_init__(self):
        if type(self.key) is not CheckKey or type(self.required) is not bool or type(self.blocking) is not bool:
            raise ReferenceError("INVALID_SCHEMA")
        if self.blocking and not self.required:
            raise ReferenceError("INVALID_POLICY")
        validate_version(self.weight, positive=True)
        if self.applicability_rule_ref is not None and type(self.applicability_rule_ref) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class AggregationPolicy:
    mode: str = "all_applicable"
    threshold: int | None = None
    soft_failures_block: bool = True
    unknown_handling: str = "no_credit"

    def __post_init__(self):
        if (self.mode not in {"all_applicable", "threshold"} or type(self.soft_failures_block) is not bool
                or self.unknown_handling != "no_credit"):
            raise ReferenceError("INVALID_POLICY")
        if self.mode == "threshold":
            validate_version(self.threshold, positive=True)
        elif self.threshold is not None:
            raise ReferenceError("INVALID_POLICY")


@dataclass(frozen=True)
class ReviewPlan:
    review_id: str
    requirement: ReviewRequirement
    check_policies: tuple[CheckPolicy, ...]
    aggregation_policy: AggregationPolicy
    reviewer_requirements: tuple[str, ...]
    plan_digest: Digest = field(init=False)

    def __post_init__(self):
        validate_id(self.review_id)
        if type(self.requirement) is not ReviewRequirement or type(self.aggregation_policy) is not AggregationPolicy:
            raise ReferenceError("INVALID_SCHEMA")
        validate_items(self.check_policies, CheckPolicy, nonempty=True)
        object.__setattr__(self, "check_policies", ordered_unique(self.check_policies, lambda p: p.key.sort_key, code='DUPLICATE_CHECK'))
        policies = {p.key: p for p in self.check_policies}
        if (not any(p.required for p in self.check_policies)
                or any(k not in policies or not policies[k].required for k in self.requirement.required_check_keys)):
            raise ReferenceError("REVIEW_INCOMPLETE")
        if any(p.key.target not in self.requirement.expected_targets.targets for p in self.check_policies):
            raise ReferenceError("CHECK_OUT_OF_PLAN")
        total = sum(p.weight for p in self.check_policies)
        validate_version(total, positive=True)
        if self.aggregation_policy.mode == "threshold" and self.aggregation_policy.threshold > total:
            raise ReferenceError("INVALID_POLICY")
        validate_items(self.reviewer_requirements, str, nonempty=True)
        for role in self.reviewer_requirements:
            validate_id(role)
        object.__setattr__(self, "reviewer_requirements", ordered_unique(self.reviewer_requirements, lambda r: r,
                                                                        code="DUPLICATE_ROLE"))
        if not set(self.reviewer_requirements) <= set(self.requirement.eligible_reviewer_roles):
            raise ReferenceError("UNTRUSTED_REVIEWER")
        object.__setattr__(self, "plan_digest", record_digest("review-plan", self.hash_payload()))

    def hash_payload(self):
        return payload_fields(self, {"plan_digest"})

    @property
    def check_keys(self):
        return tuple(p.key for p in self.check_policies)

    @property
    def scope(self):
        return self.requirement.scope

    @property
    def request_digest(self):
        return record_digest("review-request", {"scope": asdict(self.scope), "review_id": self.review_id,
                                                "plan_digest": asdict(self.plan_digest)})


@dataclass(frozen=True)
class Observation:
    check_key: CheckKey
    result: str
    evidence_refs: tuple[ArtifactRevisionRef, ...]
    rationale: str
    applicability_rule_ref: Digest | None = None

    def __post_init__(self):
        if type(self.check_key) is not CheckKey or type(self.result) is not str or self.result not in RESULTS:
            raise ReferenceError("INVALID_SCHEMA")
        validate_items(self.evidence_refs, ArtifactRevisionRef)
        object.__setattr__(self, "evidence_refs", ordered_unique(self.evidence_refs,
            lambda r: canonical_bytes(asdict(r)), code="DUPLICATE_EVIDENCE"))
        validate_text(self.rationale)
        if self.applicability_rule_ref is not None and type(self.applicability_rule_ref) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")


@dataclass(frozen=True)
class VerifiedApplicability:
    """A trusted verifier's rule/evidence result; no client self-exemption."""
    check_key: CheckKey
    rule_ref: Digest
    evidence_refs: tuple[ArtifactRevisionRef, ...]

    def __post_init__(self):
        if type(self.check_key) is not CheckKey or type(self.rule_ref) is not Digest:
            raise ReferenceError("INVALID_NA")
        try:
            validate_items(self.evidence_refs, ArtifactRevisionRef, nonempty=True)
        except ReferenceError:
            raise ReferenceError("INVALID_NA") from None
        object.__setattr__(self, "evidence_refs", ordered_unique(self.evidence_refs,
            lambda r: canonical_bytes(asdict(r)), code="DUPLICATE_EVIDENCE"))


def observations_digest(observations):
    validate_items(observations, Observation)
    ordered = ordered_unique(observations, lambda o: o.check_key.sort_key, code='DUPLICATE_CHECK')
    return record_digest("review-observations", {"observations": [asdict(o) for o in ordered]})


def _fail(code: str) -> None:
    raise ReferenceError(code)


def _key_sort(key: CheckKey) -> bytes:
    return key.sort_key


def _validate_reviewer(
    plan: ReviewPlan,
    observations: tuple,
    reviewer: VerifiedReviewerEvidence,
) -> None:
    if type(reviewer) is not VerifiedReviewerEvidence:
        _fail("UNTRUSTED_REVIEWER")
    if reviewer.scope != plan.scope:
        _fail("REALM_MISMATCH")
    if reviewer.request_digest != plan.request_digest:
        _fail("REVIEW_STALE")
    if reviewer.observations_digest != observations_digest(observations):
        _fail("REVIEW_STALE")
    eligible = set(plan.requirement.eligible_reviewer_roles)
    if (not set(plan.reviewer_requirements) <= set(reviewer.roles)
            or not set(reviewer.roles) <= eligible):
        _fail("UNTRUSTED_REVIEWER")


def _validate_observations(
    plan: ReviewPlan,
    observations: tuple,
    applicability_proofs: tuple,
) -> tuple[dict[CheckKey, object], dict[CheckKey, object]]:
    policy_by_key = {policy.key: policy for policy in plan.check_policies}
    observed: dict[CheckKey, object] = {}
    for observation in observations:
        if observation.check_key not in policy_by_key:
            _fail("CHECK_OUT_OF_PLAN")
        if observation.check_key in observed:
            _fail("DUPLICATE_CHECK")
        observed[observation.check_key] = observation

    proof_by_key: dict[CheckKey, VerifiedApplicability] = {}
    for proof in applicability_proofs:
        if proof.check_key in proof_by_key:
            _fail("INVALID_NA")
        if proof.check_key not in observed:
            _fail("INVALID_NA")
        if observed[proof.check_key].result != "not_applicable":
            _fail("INVALID_NA")
        proof_by_key[proof.check_key] = proof

    for key, observation in observed.items():
        policy = policy_by_key[key]
        proof = proof_by_key.get(key)
        if observation.result == "not_applicable":
            rule_ref = policy.applicability_rule_ref
            if (rule_ref is None or observation.applicability_rule_ref != rule_ref
                    or proof is None or proof.rule_ref != rule_ref
                    or not observation.evidence_refs
                    or proof.evidence_refs != observation.evidence_refs):
                _fail("INVALID_NA")
        elif observation.applicability_rule_ref is not None or proof is not None:
            _fail("INVALID_NA")

    return policy_by_key, observed


def _aggregate(
    plan: ReviewPlan,
    policy_by_key: dict[CheckKey, object],
    observed: dict[CheckKey, object],
    complete: bool,
) -> str:
    # The security reductions are deliberately independent of the configured
    # scoring policy and preserve the first decisive failure class.
    if any(policy.blocking and observed.get(key) is not None
           and observed[key].result == "conflict" for key, policy in policy_by_key.items()):
        return "conflict"
    if any(policy.blocking and observed.get(key) is not None
           and observed[key].result == "fail" for key, policy in policy_by_key.items()):
        return "fail"

    required_missing = any(
        policy.required and key not in observed for key, policy in policy_by_key.items()
    )
    blocking_unknown = any(
        policy.blocking and key in observed
        and observed[key].result == "indeterminate"
        for key, policy in policy_by_key.items()
    )
    if not complete or required_missing or blocking_unknown:
        return "indeterminate"

    soft_failure = any(
        not policy.blocking and key in observed
        and observed[key].result == "fail"
        for key, policy in policy_by_key.items()
    )
    if soft_failure and plan.aggregation_policy.soft_failures_block:
        return "fail"

    applicable = {
        key: observation.result
        for key, observation in observed.items()
        if observation.result != "not_applicable"
    }
    policy = plan.aggregation_policy
    if policy.mode == "all_applicable":
        # Under this policy every predeclared check must be accounted for by
        # an observation (including a verified not-applicable result). This is
        # stricter than record completeness, which intentionally tracks only
        # required checks; threshold mode can therefore score a missing
        # optional check as zero without changing its completeness contract.
        if set(policy_by_key) - set(observed):
            return "indeterminate"
        if any(result == "conflict" for result in applicable.values()):
            return "conflict"
        if any(result == "indeterminate" for result in applicable.values()):
            return "indeterminate"
        if any(result not in {"pass", "fail"} for result in applicable.values()):
            return "indeterminate"
        # Non-blocking failures are ignored only when the frozen plan permits it.
        if any(result == "fail" for result in applicable.values()):
            return "pass" if not policy.soft_failures_block else "fail"
        return "pass"

    score = sum(
        policy_by_key[key].weight
        for key, result in applicable.items()
        if result == "pass"
    )
    if score >= policy.threshold:
        return "pass"
    # Preserve uncertainty if an unresolved check could still change the
    # threshold outcome; it receives no score and can never itself pass.
    unknown_weight = sum(
        policy_by_key[key].weight
        for key, result in applicable.items()
        if result in {"indeterminate", "conflict"}
    )
    if score + unknown_weight >= policy.threshold:
        if any(result == "conflict" for result in applicable.values()):
            return "conflict"
        return "indeterminate"
    return "fail"


def reduce_review(
    plan: ReviewPlan,
    observations: tuple,
    reviewer: VerifiedReviewerEvidence,
    applicability_proofs: tuple,
) -> tuple[tuple[CheckKey, ...], bool, str]:
    """Validate a frozen plan's observations and derive its sealed outcome.

    Trust is only checked against the captured evidence supplied by the caller;
    this pure function neither authenticates the reviewer nor fetches current
    trust. Gate evaluation performs the separate current-trust comparison.
    """
    if type(plan) is not ReviewPlan:
        _fail("INVALID_SCHEMA")
    if type(observations) is not tuple:
        _fail("INVALID_SCHEMA")
    if type(applicability_proofs) is not tuple:
        _fail("INVALID_NA")
    if any(type(item) is not Observation for item in observations):
        _fail("INVALID_SCHEMA")
    if any(type(item) is not VerifiedApplicability for item in applicability_proofs):
        _fail("INVALID_NA")
    if len({item.check_key for item in observations}) != len(observations):
        _fail("DUPLICATE_CHECK")
    if len({item.check_key for item in applicability_proofs}) != len(applicability_proofs):
        _fail("INVALID_NA")

    _validate_reviewer(plan, observations, reviewer)
    policy_by_key, observed = _validate_observations(plan, observations, applicability_proofs)
    required = {item.key for item in plan.check_policies if item.required}
    complete = required <= set(observed)
    completed = tuple(sorted(observed, key=_key_sort))
    return completed, complete, _aggregate(plan, policy_by_key, observed, complete)


@dataclass(frozen=True)
class ReviewRecord:
    identity: RecordIdentity
    plan: ReviewPlan
    reviewer_evidence: VerifiedReviewerEvidence
    observations: tuple[Observation, ...]
    body_ref: ArtifactRevisionRef | None = None
    limitations: tuple[str, ...] = ()
    applicability_proofs: tuple[VerifiedApplicability, ...] = ()
    raw_response_ref: BlobRef | None = None
    completed_check_keys: tuple[CheckKey, ...] = field(init=False)
    complete: bool = field(init=False)
    verdict: str = field(init=False)
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.identity) is not RecordIdentity or type(self.plan) is not ReviewPlan
                or type(self.reviewer_evidence) is not VerifiedReviewerEvidence
                or self.identity.scope != self.plan.scope or self.identity.record_id != self.plan.review_id):
            raise ReferenceError("INVALID_SCHEMA")
        if self.identity.schema_version == 1:
            if self.raw_response_ref is not None:
                raise ReferenceError("INVALID_SCHEMA")
        elif (type(self.raw_response_ref) is not BlobRef
                or self.raw_response_ref.digest != self.reviewer_evidence.raw_response_digest
                or self.raw_response_ref.byte_length > 2097152):
            raise ReferenceError("INVALID_RAW_RESPONSE_REF")
        validate_items(self.observations, Observation)
        object.__setattr__(self, "observations", ordered_unique(self.observations, lambda o: o.check_key.sort_key, code='DUPLICATE_CHECK'))
        validate_items(self.limitations, str)
        for limitation in self.limitations:
            validate_text(limitation)
        validate_items(self.applicability_proofs, VerifiedApplicability)
        object.__setattr__(self, "applicability_proofs", ordered_unique(self.applicability_proofs,
                                                                        lambda p: p.check_key.sort_key, code='DUPLICATE_CHECK'))
        refs = [ref for o in self.observations for ref in o.evidence_refs]
        refs.extend(ref for proof in self.applicability_proofs for ref in proof.evidence_refs)
        if self.body_ref is not None:
            if type(self.body_ref) is not ArtifactRevisionRef:
                raise ReferenceError("INVALID_SCHEMA")
            refs.append(self.body_ref)
        if any((r.realm_id, r.project_id) != (self.plan.scope.realm_id, self.plan.scope.project_id) for r in refs):
            raise ReferenceError("REALM_MISMATCH")
        keys, complete, verdict = reduce_review(self.plan, self.observations,
                                                self.reviewer_evidence, self.applicability_proofs)
        object.__setattr__(self, "completed_check_keys", keys)
        object.__setattr__(self, "complete", complete)
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "digest", record_digest("review-record", self.hash_payload()))
        if len(canonical_bytes(self.projection())) > 2097152:
            raise ReferenceError("RECORD_TOO_LARGE")

    def hash_payload(self):
        excluded = {"digest"}
        if self.identity.schema_version == 1:
            excluded.add("raw_response_ref")
        return payload_fields(self, excluded)

    def projection(self):
        result = asdict(self)
        if self.identity.schema_version == 1:
            del result["raw_response_ref"]
        return result

    @property
    def ref(self):
        scope = self.plan.scope
        return ReviewRef(scope.realm_id, scope.project_id, self.plan.review_id, self.digest)


@dataclass(frozen=True)
class ReviewSetKey:
    scope: Scope
    requirement_id: str
    requirement_version: int
    purpose: str
    targets_digest: Digest
    method_snapshot_digest: Digest
    criterion_set_digest: Digest
    digest: Digest = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.purpose) is not str or self.purpose not in PURPOSES:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.requirement_id)
        validate_version(self.requirement_version, positive=True)
        for value in (self.targets_digest, self.method_snapshot_digest, self.criterion_set_digest):
            if type(value) is not Digest:
                raise ReferenceError("INVALID_SCHEMA")
        object.__setattr__(self, "digest", record_digest("review-set-key", self.hash_payload()))

    def hash_payload(self):
        return payload_fields(self, {"digest"})

    @classmethod
    def for_requirement(cls, requirement):
        if type(requirement) is not ReviewRequirement:
            raise ReferenceError("INVALID_SCHEMA")
        return cls(requirement.scope, requirement.requirement_id, requirement.requirement_version,
                   requirement.purpose, requirement.expected_targets.digest,
                   requirement.method_ref.snapshot_digest, requirement.criterion_set_ref.digest)


@dataclass(frozen=True)
class ReviewControl:
    scope: Scope
    review_id: str
    state: str = "active"
    replacement_ref: ReviewRef | None = None
    reason: str | None = None
    control_evidence: tuple[Digest, ...] = ()
    version: int = 0

    def __post_init__(self):
        if type(self.scope) is not Scope or type(self.state) is not str or self.state not in {"active", "voided", "replaced"}:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.review_id)
        validate_version(self.version)
        validate_items(self.control_evidence, Digest)
        if self.state == "active":
            if self.replacement_ref is not None or self.reason is not None or self.control_evidence or self.version != 0:
                raise ReferenceError("INVALID_CONTROL")
        else:
            if self.version == 0 or not self.control_evidence:
                raise ReferenceError("INVALID_CONTROL")
            validate_text(self.reason)
            if self.state == "replaced":
                if (type(self.replacement_ref) is not ReviewRef or self.replacement_ref.review_id == self.review_id
                        or (self.replacement_ref.realm_id, self.replacement_ref.project_id) !=
                           (self.scope.realm_id, self.scope.project_id)):
                    raise ReferenceError("INVALID_CONTROL")
            elif self.replacement_ref is not None:
                raise ReferenceError("INVALID_CONTROL")


@dataclass(frozen=True)
class ControlledReview:
    record: ReviewRecord
    control: ReviewControl

    def __post_init__(self):
        if (type(self.record) is not ReviewRecord or type(self.control) is not ReviewControl
                or self.record.plan.scope != self.control.scope or self.record.plan.review_id != self.control.review_id):
            raise ReferenceError("INVALID_CONTROL")


@dataclass(frozen=True)
class ReviewSetSnapshot:
    key: ReviewSetKey
    set_version: int
    reviews: tuple[ControlledReview, ...]

    def __post_init__(self):
        if type(self.key) is not ReviewSetKey:
            raise ReferenceError("INVALID_SCHEMA")
        validate_version(self.set_version)
        validate_items(self.reviews, ControlledReview)
        object.__setattr__(self, "reviews", ordered_unique(self.reviews,
            lambda r: r.record.plan.review_id, code="DUPLICATE_REVIEW"))
        if any(ReviewSetKey.for_requirement(r.record.plan.requirement) != self.key for r in self.reviews):
            raise ReferenceError("REVIEW_STALE")
        if self.reviews and self.set_version == 0:
            raise ReferenceError("INVALID_VERSION")


@dataclass(frozen=True)
class CurrentReviewTrust:
    """Current original-owner facts, supplied by trusted application composition."""
    review_ref: ReviewRef
    verifier_id: str
    trust_version: int

    def __post_init__(self):
        if type(self.review_ref) is not ReviewRef:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.verifier_id)
        validate_version(self.trust_version)


@dataclass(frozen=True)
class ReviewSetExpectation:
    key: ReviewSetKey
    set_version: int

    def __post_init__(self):
        if type(self.key) is not ReviewSetKey:
            raise ReferenceError("INVALID_SCHEMA")
        validate_version(self.set_version)


@dataclass(frozen=True)
class ReviewControlExpectation:
    review_ref: ReviewRef
    version: int

    def __post_init__(self):
        if type(self.review_ref) is not ReviewRef:
            raise ReferenceError("INVALID_SCHEMA")
        validate_version(self.version)


@dataclass(frozen=True)
class GateDecision:
    satisfied: bool
    code: str
    used_review_refs: tuple[ReviewRef, ...]
    review_set_expectations: tuple[ReviewSetExpectation, ...]
    control_expectations: tuple[ReviewControlExpectation, ...]
    evaluated_targets_digest: Digest

    def __post_init__(self):
        if type(self.satisfied) is not bool or type(self.evaluated_targets_digest) is not Digest:
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.code)
        validate_items(self.used_review_refs, ReviewRef)
        validate_items(self.review_set_expectations, ReviewSetExpectation)
        validate_items(self.control_expectations, ReviewControlExpectation)


@dataclass(frozen=True)
class ReviewRequestState:
    scope: Scope
    review_id: str
    state: str
    fence: int
    version: int

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.state) is not str
                or self.state not in {"requested", "recorded", "withdrawn"}):
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.review_id)
        validate_version(self.fence, positive=True)
        validate_version(self.version)


@dataclass(frozen=True)
class ReviewRequestExpectation:
    """Exact pending request predicate; neither reviewer trust nor permission."""
    scope: Scope
    review_id: str
    expected_plan_digest: Digest
    expected_request_version: int
    expected_fence: int
    expected_state: str = "requested"

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.expected_plan_digest) is not Digest
                or self.expected_state != "requested" or type(self.expected_state) is not str):
            raise ReferenceError("INVALID_SCHEMA")
        validate_id(self.review_id)
        validate_version(self.expected_request_version)
        validate_version(self.expected_fence, positive=True)
