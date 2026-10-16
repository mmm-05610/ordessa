"""Canonical review DTO byte codec acceptance; domain constructors remain authoritative."""
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.reviews.codec import (
    decode_control,
    decode_key,
    decode_plan,
    decode_record,
    decode_requirement,
    encode_control,
    encode_key,
    encode_plan,
    encode_record,
    encode_requirement,
)
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
    observations_digest,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)


CREATED_AT = "2026-10-09T12:00:00.000000Z"


def _digest(character="a"):
    return Digest("sha256", character * 64)


def _sample():
    scope = Scope("realm-review", "project-review")
    subject = ArtifactRevisionRef(scope.realm_id, scope.project_id, "artifact-1", "revision-1", _digest())
    target = Target("primary", subject)
    targets = TargetSet((target,))
    check = CheckKey(target, "criterion-1")
    requirement = ReviewRequirement(
        scope=scope,
        requirement_id="requirement-1",
        requirement_version=1,
        purpose="quality",
        expected_targets=targets,
        method_ref=MethodRef("method-1", "1.0", 1, _digest("b")),
        criterion_set_ref=CriterionSetRef("criteria-1", 1, _digest("c")),
        required_check_keys=(check,),
        eligible_reviewer_roles=("reviewer",),
        phase_key="phase-1",
    )
    plan = ReviewPlan(
        review_id="review-1",
        requirement=requirement,
        check_policies=(CheckPolicy(check, required=True, blocking=True),),
        aggregation_policy=AggregationPolicy(),
        reviewer_requirements=("reviewer",),
    )
    observation = Observation(check, "pass", (), "Evidence reviewed.")
    reviewer = ActorRef("reviewer-1", "human", "synthetic-review-test")
    reviewer_evidence = VerifiedReviewerEvidence(
        scope=scope,
        reviewer=reviewer,
        roles=("reviewer",),
        verifier_id="verifier-1",
        verifier_version="1",
        trust_version=1,
        request_digest=plan.request_digest,
        raw_response_digest=_digest("d"),
        observations_digest=observations_digest((observation,)),
        capability_digest=_digest("e"),
    )
    record = ReviewRecord(
        identity=RecordIdentity(scope, plan.review_id, CREATED_AT,
                                ActorRef("author-1", "service", "synthetic-review-test")),
        plan=plan,
        reviewer_evidence=reviewer_evidence,
        observations=(observation,),
    )
    return scope, subject, requirement, plan, record


def _invalid(error):
    assert error.value.code == "INVALID_REVIEW_BYTES"


def test_requirement_plan_key_and_control_roundtrip_with_immutable_tuple_views():
    scope, _subject, requirement, plan, _record = _sample()
    key = ReviewSetKey.for_requirement(requirement)
    active = ReviewControl(scope, plan.review_id)
    replacement = ReviewControl(
        scope, "review-old", state="replaced",
        replacement_ref=ReviewRef(scope.realm_id, scope.project_id, "review-new", _digest("f")),
        reason="Superseded by a newer review.", control_evidence=(_digest("1"),), version=1,
    )

    requirement_bytes = encode_requirement(requirement)
    plan_bytes = encode_plan(plan)
    key_bytes = encode_key(key)
    active_bytes = encode_control(active)
    replacement_bytes = encode_control(replacement)

    decoded_requirement = decode_requirement(requirement_bytes)
    decoded_plan = decode_plan(plan_bytes)
    decoded_key = decode_key(key_bytes)
    assert decoded_requirement == requirement
    assert decoded_requirement.required_check_keys == (requirement.required_check_keys[0],)
    assert decoded_requirement.eligible_reviewer_roles == ("reviewer",)
    assert decoded_plan == plan
    assert decoded_plan.check_policies == plan.check_policies
    assert decoded_plan.reviewer_requirements == ("reviewer",)
    assert decoded_key == key
    assert decoded_key.digest == key.digest
    with pytest.raises(FrozenInstanceError):
        decoded_requirement.phase_key = "mutated"
    assert decode_control(active_bytes) == active
    assert decode_control(replacement_bytes) == replacement

    # Returned objects contain detached immutable tuples. Mutating a decoded
    # JSON-shaped copy cannot alter the original canonical bytes or identities.
    mutable_copy = decode_json(requirement_bytes)
    mutable_copy["required_check_keys"].clear()
    assert decode_requirement(requirement_bytes).required_check_keys == requirement.required_check_keys
    assert decoded_requirement.digest == requirement.digest
    assert decoded_plan.plan_digest == plan.plan_digest
    assert decoded_key.digest == key.digest


def test_review_record_roundtrip_recomputes_seal_and_derived_result():
    _scope_value, _subject, _requirement_value, _plan_value, record = _sample()
    raw = encode_record(record)
    restored = decode_record(raw)

    assert restored == record
    assert restored.complete is record.complete
    assert restored.verdict == record.verdict
    assert restored.completed_check_keys == record.completed_check_keys
    assert restored.digest == record.digest
    assert restored.observations == record.observations
    assert restored.observations[0].evidence_refs == ()


def test_schema1_review_bytes_match_pinned_pre_blobref_history():
    _scope_value, _subject, _requirement_value, _plan_value, record = _sample()
    assert record.identity.schema_version == 1
    raw = encode_record(record)
    # Pinned from the pre-BlobRef schema-1 canonical projection at HEAD. The
    # byte hash and record seal both remain stable after schema 2 is added.
    assert len(raw) == 4165
    assert hashlib.sha256(raw).hexdigest() == "03e0235af5842b66169371e7b4c41e2046ad1a95a2efe665ddcc5703bbea23ad"
    assert record.digest.hex == "687521a3a9f413792e667ac9b24f568b04e1772981a09b56dec3b76ce7489c9f"
    assert decode_record(raw) == record


def _schema2_record(record, *, storage_object_id="raw-response-a", media_type="application/json",
                    raw_digest=None, byte_length=123):
    digest = raw_digest or record.reviewer_evidence.raw_response_digest
    reviewer = replace(record.reviewer_evidence, raw_response_digest=digest)
    blob_ref = BlobRef(digest, byte_length, media_type, storage_object_id)
    identity = replace(record.identity, schema_version=2)
    return replace(record, identity=identity, reviewer_evidence=reviewer, raw_response_ref=blob_ref)


def test_schema2_record_roundtrip_and_locator_is_not_content_identity():
    _scope_value, _subject, _requirement_value, _plan_value, schema1 = _sample()
    schema2 = _schema2_record(schema1)
    raw = encode_record(schema2)
    value = decode_json(raw)
    assert value["identity"]["schema_version"] == 2
    assert value["raw_response_ref"]["storage_object_id"] == "raw-response-a"
    assert decode_record(raw) == schema2

    moved = _schema2_record(schema1, storage_object_id="raw-response-b")
    assert moved.raw_response_ref.storage_object_id != schema2.raw_response_ref.storage_object_id
    assert moved.digest == schema2.digest
    assert encode_record(moved) != raw
    assert decode_record(encode_record(moved)) == moved


def test_schema2_blob_content_and_media_type_change_review_identity():
    _scope_value, _subject, _requirement_value, _plan_value, schema1 = _sample()
    original = _schema2_record(schema1)
    changed_content = _schema2_record(schema1, raw_digest=_digest("f"))
    changed_length = _schema2_record(schema1, byte_length=124)
    changed_media = _schema2_record(schema1, media_type="text/plain")
    assert changed_content.digest != original.digest
    assert changed_length.digest != original.digest
    assert changed_media.digest != original.digest


def test_schema1_and_schema2_review_projections_have_closed_versioned_shapes():
    _scope_value, _subject, _requirement_value, _plan_value, schema1 = _sample()
    schema2 = _schema2_record(schema1)

    legacy_with_new_field = decode_json(encode_record(schema1))
    legacy_with_new_field["raw_response_ref"] = asdict(schema2.raw_response_ref)
    with pytest.raises(ReferenceError) as forced_v1_field:
        decode_record(canonical_bytes(legacy_with_new_field))
    _invalid(forced_v1_field)

    missing_v2_ref = decode_json(encode_record(schema2))
    del missing_v2_ref["raw_response_ref"]
    with pytest.raises(ReferenceError) as missing_v2:
        decode_record(canonical_bytes(missing_v2_ref))
    _invalid(missing_v2)

    unknown_v2_field = decode_json(encode_record(schema2))
    unknown_v2_field["future_payload"] = "not part of schema 2"
    with pytest.raises(ReferenceError) as unknown:
        decode_record(canonical_bytes(unknown_v2_field))
    _invalid(unknown)

    future_version = decode_json(encode_record(schema2))
    future_version["identity"]["schema_version"] = 3
    with pytest.raises(ReferenceError) as future:
        decode_record(canonical_bytes(future_version))
    _invalid(future)


def test_schema2_rejects_forged_seal_and_raw_response_digest_mismatch():
    _scope_value, _subject, _requirement_value, _plan_value, schema1 = _sample()
    schema2 = _schema2_record(schema1)

    forged_seal = decode_json(encode_record(schema2))
    forged_seal["digest"]["hex"] = "f" * 64
    with pytest.raises(ReferenceError) as forged:
        decode_record(canonical_bytes(forged_seal))
    _invalid(forged)

    mismatched_ref = decode_json(encode_record(schema2))
    mismatched_ref["raw_response_ref"]["digest"]["hex"] = "f" * 64
    with pytest.raises(ReferenceError) as mismatch:
        decode_record(canonical_bytes(mismatched_ref))
    _invalid(mismatch)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda data: data["digest"].update(hex="f" * 64),
        lambda data: data["expected_targets"]["digest"].update(hex="f" * 64),
    ],
)
def test_requirement_derived_hash_tampering_is_rejected(tamper):
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    value = decode_json(encode_requirement(requirement))
    tamper(value)
    with pytest.raises(ReferenceError) as caught:
        decode_requirement(canonical_bytes(value))
    _invalid(caught)


def test_plan_and_review_record_derived_fields_cannot_be_forged():
    _scope_value, _subject, _requirement_value, plan, record = _sample()
    plan_value = decode_json(encode_plan(plan))
    plan_value["plan_digest"]["hex"] = "f" * 64
    with pytest.raises(ReferenceError) as plan_error:
        decode_plan(canonical_bytes(plan_value))
    _invalid(plan_error)

    mutations = (
        lambda value: value.update(complete=not value["complete"]),
        lambda value: value.update(verdict="conflict" if value["verdict"] != "conflict" else "pass"),
        lambda value: value.update(completed_check_keys=[]),
        lambda value: value["digest"].update(hex="f" * 64),
    )
    for mutate in mutations:
        value = decode_json(encode_record(record))
        mutate(value)
        with pytest.raises(ReferenceError) as caught:
            decode_record(canonical_bytes(value))
        _invalid(caught)


def test_review_ref_is_not_accepted_as_a_target_subject():
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    value = decode_json(encode_requirement(requirement))
    value["expected_targets"]["targets"][0]["ref"] = asdict(
        ReviewRef("realm-review", "project-review", "review-elsewhere", _digest("2")))
    with pytest.raises(ReferenceError) as caught:
        decode_requirement(canonical_bytes(value))
    _invalid(caught)


@pytest.mark.parametrize("subject_kind", ["artifact_revision", "proposal", "submission", "repository_snapshot"])
def test_closed_supported_target_subject_union_roundtrips(subject_kind):
    scope, _subject, requirement, _plan_value, _record_value = _sample()
    if subject_kind == "artifact_revision":
        subject = ArtifactRevisionRef(scope.realm_id, scope.project_id, "artifact-other", "revision-other", _digest("3"))
    elif subject_kind == "proposal":
        subject = ProposalRef(scope.realm_id, scope.project_id, "change-1", "proposal-1", _digest("4"))
    elif subject_kind == "submission":
        subject = SubmissionRef(scope.realm_id, scope.project_id, "submission-1", _digest("5"))
    else:
        subject = RepositorySnapshotRef(
            scope.realm_id, scope.project_id, "repository-1", "none", None,
            _digest("6"), _digest("7"),
        )
    target = Target("support", subject)
    changed = replace(
        requirement,
        expected_targets=TargetSet((target,)),
        required_check_keys=(CheckKey(target, "criterion-1"),),
    )
    assert decode_requirement(encode_requirement(changed)) == changed


def test_unknown_fields_duplicate_keys_deep_json_and_oversized_bytes_fail_closed():
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    value = decode_json(encode_requirement(requirement))
    value["unexpected"] = "ignored fields are forbidden"
    with pytest.raises(ReferenceError) as unknown:
        decode_requirement(canonical_bytes(value))
    _invalid(unknown)

    with pytest.raises(ReferenceError) as duplicate:
        decode_requirement(b'{"requirement_id":"a","requirement_id":"b"}')
    _invalid(duplicate)

    deep = b"[" * 70 + b"0" + b"]" * 70
    with pytest.raises(ReferenceError) as too_deep:
        decode_requirement(deep)
    _invalid(too_deep)

    with pytest.raises(ReferenceError) as oversized:
        decode_requirement(b" " * (2 * 1024 * 1024 + 1))
    _invalid(oversized)


@pytest.mark.parametrize("bad_version", [True, 1.0, "1"])
def test_boolean_and_noninteger_versions_are_not_coerced(bad_version):
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    value = decode_json(encode_requirement(requirement))
    value["requirement_version"] = bad_version
    with pytest.raises(ReferenceError) as caught:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
               if type(bad_version) is float else canonical_bytes(value))
        decode_requirement(raw)
    _invalid(caught)

    key = ReviewSetKey.for_requirement(requirement)
    key_value = decode_json(encode_key(key))
    key_value["requirement_version"] = bad_version
    with pytest.raises(ReferenceError) as key_error:
        raw = (json.dumps(key_value, sort_keys=True, separators=(",", ":")).encode()
               if type(bad_version) is float else canonical_bytes(key_value))
        decode_key(raw)
    _invalid(key_error)


def test_noncanonical_raw_json_bytes_are_rejected():
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    raw = encode_requirement(requirement)
    with pytest.raises(ReferenceError) as caught:
        decode_requirement(raw + b" ")
    _invalid(caught)


def test_encoding_over_two_mebibytes_is_rejected():
    _scope_value, _subject, requirement, _plan_value, _record_value = _sample()
    many_roles = tuple(f"role-{index:04d}-" + "x" * 500 for index in range(4096))
    oversized = replace(requirement, eligible_reviewer_roles=many_roles)
    with pytest.raises(ReferenceError) as caught:
        encode_requirement(oversized)
    _invalid(caught)
