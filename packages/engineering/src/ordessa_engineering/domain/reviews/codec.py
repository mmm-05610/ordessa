"""Strict canonical-byte codec for immutable review domain records."""
from __future__ import annotations

from dataclasses import asdict, fields

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.changes.baselines import (RepositorySnapshotRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef, SubmissionRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.domain.common.mechanisms.codec import (canonical_value)
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy,
    CheckKey,
    CheckPolicy,
    CriterionSetRef,
    Observation,
    ReviewControl,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    ReviewSetKey,
    VerifiedApplicability,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)

_MAX_BYTES = 2 * 1024 * 1024


from ordessa_engineering.domain.common.mechanisms.codec import (require_object, decode_digest, decode_blob_ref, decode_scope, decode_actor)
from ordessa_engineering.domain.reviews.target_codec import (decode_subject_ref, decode_target, decode_target_set)
from ordessa_engineering.domain.reviews.ref_codec import (decode_review_ref)
from ordessa_engineering.domain.artifacts.method_codec import (decode_method_ref)


def _common_decode(parser, value):
    try:
        return parser(value)
    except ReferenceError:
        _invalid()


def _invalid():
    raise ReferenceError("INVALID_REVIEW_BYTES")


def _object(value, expected=None):
    if expected is None:
        if type(value) is not dict:
            _invalid()
        return value
    return require_object(value, expected, 'INVALID_REVIEW_BYTES')

def _fields(value, cls):
    return _object(value, {item.name for item in fields(cls)})


def _list(value):
    if type(value) is not list:
        _invalid()
    return value


def _digest(value):
    return _common_decode(decode_digest, value)


def _blob_ref(value):
    return _common_decode(decode_blob_ref, value)


def _scope(value):
    return _common_decode(decode_scope, value)


def _subject(value):
    return _common_decode(decode_subject_ref, value)


def _target(value):
    return _common_decode(decode_target, value)


def _target_set(value):
    return _common_decode(decode_target_set, value)


def _review_ref(value):
    return _common_decode(decode_review_ref, value)


def _method_ref(value):
    return _common_decode(decode_method_ref, value)


def _criterion_set_ref(value):
    value = _object(value, {"criterion_set_id", "version", "digest"})
    return CriterionSetRef(value["criterion_set_id"], value["version"], _digest(value["digest"]))


def _check_key(value):
    value = _object(value, {"target", "criterion_id", "claim_id"})
    return CheckKey(_target(value["target"]), value["criterion_id"], value["claim_id"])


def _requirement(value):
    value = _fields(value, ReviewRequirement)
    return ReviewRequirement(
        _scope(value["scope"]), value["requirement_id"], value["requirement_version"],
        value["purpose"], _target_set(value["expected_targets"]), _method_ref(value["method_ref"]),
        _criterion_set_ref(value["criterion_set_ref"]),
        tuple(_check_key(item) for item in _list(value["required_check_keys"])),
        tuple(_list(value["eligible_reviewer_roles"])), value["phase_key"],
    )


def _check_policy(value):
    value = _fields(value, CheckPolicy)
    rule = value["applicability_rule_ref"]
    return CheckPolicy(_check_key(value["key"]), value["required"], value["blocking"],
                       value["weight"], _digest(rule) if rule is not None else None)


def _aggregation_policy(value):
    value = _fields(value, AggregationPolicy)
    return AggregationPolicy(value["mode"], value["threshold"], value["soft_failures_block"],
                             value["unknown_handling"])


def _plan(value):
    value = _fields(value, ReviewPlan)
    return ReviewPlan(
        value["review_id"], _requirement(value["requirement"]),
        tuple(_check_policy(item) for item in _list(value["check_policies"])),
        _aggregation_policy(value["aggregation_policy"]), tuple(_list(value["reviewer_requirements"])),
    )


def _record_identity(value):
    value = _fields(value, RecordIdentity)
    return RecordIdentity(_scope(value["scope"]), value["record_id"], value["created_at"],
                          _common_decode(decode_actor, value["created_by"]), value["schema_version"])


def _reviewer_evidence(value):
    value = _fields(value, VerifiedReviewerEvidence)
    reviewer = _common_decode(decode_actor, value["reviewer"])
    return VerifiedReviewerEvidence(
        _scope(value["scope"]), reviewer, tuple(_list(value["roles"])), value["verifier_id"],
        value["verifier_version"], value["trust_version"], _digest(value["request_digest"]),
        _digest(value["raw_response_digest"]), _digest(value["observations_digest"]),
        _digest(value["capability_digest"]),
    )


def _observation(value):
    value = _fields(value, Observation)
    rule = value["applicability_rule_ref"]
    return Observation(
        _check_key(value["check_key"]), value["result"],
        tuple(_subject(item) for item in _list(value["evidence_refs"])), value["rationale"],
        _digest(rule) if rule is not None else None,
    )


def _verified_applicability(value):
    value = _fields(value, VerifiedApplicability)
    return VerifiedApplicability(
        _check_key(value["check_key"]), _digest(value["rule_ref"]),
        tuple(_subject(item) for item in _list(value["evidence_refs"])),
    )


def _record(value):
    if type(value) is not dict or "identity" not in value:
        _invalid()
    identity = _record_identity(value["identity"])
    expected = {item.name for item in fields(ReviewRecord)}
    if identity.schema_version == 1:
        expected.remove("raw_response_ref")
    value = _object(value, expected)
    body_ref = value["body_ref"]
    raw_response_ref = (_blob_ref(value["raw_response_ref"])
                        if identity.schema_version == 2 else None)
    return ReviewRecord(
        identity, _plan(value["plan"]),
        _reviewer_evidence(value["reviewer_evidence"]),
        tuple(_observation(item) for item in _list(value["observations"])),
        _subject(body_ref) if body_ref is not None else None,
        tuple(_list(value["limitations"])),
        tuple(_verified_applicability(item) for item in _list(value["applicability_proofs"])),
        raw_response_ref,
    )


def _review_set_key(value):
    value = _fields(value, ReviewSetKey)
    return ReviewSetKey(
        _scope(value["scope"]), value["requirement_id"], value["requirement_version"],
        value["purpose"], _digest(value["targets_digest"]),
        _digest(value["method_snapshot_digest"]), _digest(value["criterion_set_digest"]),
    )


def _control(value):
    value = _fields(value, ReviewControl)
    replacement = value["replacement_ref"]
    return ReviewControl(
        _scope(value["scope"]), value["review_id"], value["state"],
        _review_ref(replacement) if replacement is not None else None, value["reason"],
        tuple(_digest(item) for item in _list(value["control_evidence"])), value["version"],
    )


def _decode(raw, cls, parse):
    try:
        if type(raw) is not bytes or len(raw) > _MAX_BYTES:
            _invalid()
        value = canonical_value(raw, maximum=_MAX_BYTES)
        if canonical_bytes(value) != raw:
            _invalid()
        result = parse(value)
        projection = result.projection() if type(result) is ReviewRecord else asdict(result)
        if type(result) is not cls or canonical_bytes(projection) != raw:
            _invalid()
        return result
    except (ReferenceError, TypeError, ValueError, KeyError, AttributeError,
            RecursionError, OverflowError):
        _invalid()


def _encode(value, cls, decode):
    try:
        if type(value) is not cls:
            _invalid()
        projection = value.projection() if type(value) is ReviewRecord else asdict(value)
        raw = canonical_bytes(projection)
        if len(raw) > _MAX_BYTES:
            _invalid()
        # Decoding recomputes all init=False identities and the ReviewRecord
        # seal through its real constructor, then verifies byte equality.
        decode(raw)
        return raw
    except (ReferenceError, TypeError, ValueError, KeyError, AttributeError,
            RecursionError, OverflowError):
        _invalid()


def encode_requirement(value: ReviewRequirement) -> bytes:
    return _encode(value, ReviewRequirement, decode_requirement)


def decode_requirement(raw: bytes) -> ReviewRequirement:
    return _decode(raw, ReviewRequirement, _requirement)


def encode_plan(value: ReviewPlan) -> bytes:
    return _encode(value, ReviewPlan, decode_plan)


def decode_plan(raw: bytes) -> ReviewPlan:
    return _decode(raw, ReviewPlan, _plan)


def encode_record(value: ReviewRecord) -> bytes:
    return _encode(value, ReviewRecord, decode_record)


def decode_record(raw: bytes) -> ReviewRecord:
    return _decode(raw, ReviewRecord, _record)


def encode_key(value: ReviewSetKey) -> bytes:
    return _encode(value, ReviewSetKey, decode_key)


def decode_key(raw: bytes) -> ReviewSetKey:
    return _decode(raw, ReviewSetKey, _review_set_key)


def encode_control(value: ReviewControl) -> bytes:
    return _encode(value, ReviewControl, decode_control)


def decode_control(raw: bytes) -> ReviewControl:
    return _decode(raw, ReviewControl, _control)


__all__ = [
    "encode_requirement", "decode_requirement", "encode_plan", "decode_plan",
    "encode_record", "decode_record", "encode_key", "decode_key",
    "encode_control", "decode_control",
]
