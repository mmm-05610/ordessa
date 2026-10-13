"""Common invariants, closed parsing and byte preservation across the refactor."""
from dataclasses import asdict, FrozenInstanceError

import pytest

from ordessa_engineering.domain.common.mechanisms.codec import (canonical_value)
from ordessa_engineering.domain.approvals.ref_codec import (decode_approval_ref)
from ordessa_engineering.domain.reviews.target_codec import (decode_subject_ref, decode_target_set)
from ordessa_engineering.domain.changes.errors import (DomainError, from_reference_error)
from ordessa_engineering.domain.changes.errors import (DomainErrorCode)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.mechanisms.hashing import (record_digest)
from ordessa_engineering.application.contracts.preconditions import VersionExpectation
from ordessa_engineering.domain.artifacts.provenance import (EvidenceLink)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.artifacts.provenance import (SourceLocator, SourceRef, VersionCapture)
from ordessa_engineering.domain.approvals.refs import (ApprovalRef)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.changes.baselines import (RepositorySnapshotRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.identity import (ActorRef, Scope)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.domain.common.models.values import (Digest, UtcInstant, normalized_path, validate_id, utc_instant)
from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
from ordessa_infrastructure.encoding import canonical_bytes

DIGEST = Digest("sha256", "a" * 64)
REVISION = ArtifactRevisionRef("realm", "project", "artifact", "revision", DIGEST)
SOURCE = SourceRef("source", "document", SourceLocator("document", provider="provider", document_id="document"),
    VersionCapture("version", DIGEST), "2026-10-09T00:00:00.000000Z",
    ActorRef("actor", "human", "issuer"), "text/plain", 1)


@pytest.mark.parametrize("construct,code", [
    (lambda: ActorRef("actor", [], "issuer"), "INVALID_ACTOR"),
    (lambda: RepositorySnapshotRef("realm", "project", "repo", [], None, DIGEST, None), "INVALID_SCHEMA"),
    (lambda: RepositorySnapshotRef("realm", "project", "repo", "git", [], DIGEST, None), "INVALID_SCHEMA"),
    (lambda: Target([], REVISION), "INVALID_SCHEMA"),
    (lambda: EvidenceLink("claim", SOURCE, ContentSelector("whole_capture"), [], "reason"), "INVALID_EVIDENCE_LINK"),
    (lambda: record_digest([], {}), "INVALID_SCHEMA"),
    (lambda: record_digest("artifact", {"value": float("nan")}), "INVALID_SCHEMA"),
    (lambda: record_digest("artifact", {"value": "\ud800"}), "INVALID_SCHEMA"),
])
def test_invalid_types_raise_stable_domain_errors(construct, code):
    with pytest.raises(ReferenceError) as caught:
        construct()
    assert caught.value.code == code
    assert caught.value.args == (code,)
    assert from_reference_error(caught.value).code.value == code
    assert not hasattr(caught.value, "error")


def test_ids_reject_unpaired_surrogates_without_normalizing_unicode():
    with pytest.raises(ReferenceError, match="INVALID_SCHEMA"):
        validate_id("\ud800")
    for value in ("é", "e\u0301", "设计"):
        validate_id(value)
        assert Scope(value, "project").realm_id == value
    assert record_digest("artifact", {"id": "é"}) != record_digest("artifact", {"id": "e\u0301"})


def test_utc_value_keeps_exact_microseconds_and_constructor_validation():
    instant = UtcInstant("2026-10-09T00:00:00.000001Z")
    utc_instant(instant)
    identity = RecordIdentity(Scope("realm", "project"), "record", instant,
                              ActorRef("actor", "human", "issuer"))
    assert asdict(identity)["created_at"] == "2026-10-09T00:00:00.000001Z"
    for invalid in ("2026-10-09T00:00:00Z", "2026-02-30T00:00:00.000000Z",
                    "2026-10-09T00:00:00.000001+00:00"):
        with pytest.raises(ReferenceError, match="INVALID_TIME"):
            RecordIdentity(identity.scope, "record", invalid, identity.created_by)


@pytest.mark.parametrize("path", ["/root", "a/../b", "a//b", "a\\b", "C:/file"])
def test_relative_paths_are_validated_without_rewriting(path):
    with pytest.raises(ReferenceError, match="INVALID_PATH"):
        normalized_path(path)
    normalized_path("设计/a.md")


def test_approval_ref_has_grant_digest_and_is_not_a_review_subject():
    ref = ApprovalRef("realm", "project", "approval", DIGEST)
    assert decode_approval_ref(asdict(ref)) == ref
    for malformed in (asdict(ref) | {"digest": asdict(DIGEST)},
                      asdict(ref) | {"kind": "review"}):
        with pytest.raises(ReferenceError):
            decode_approval_ref(malformed)
    with pytest.raises(ReferenceError):
        decode_subject_ref(asdict(ref))
    with pytest.raises(ReferenceError):
        Target("primary", ref)


def test_dirty_target_order_and_digest_tampering():
    snapshot = RepositorySnapshotRef("realm", "project", "repo", "git", "b" * 40,
                                     DIGEST, Digest("sha256", "c" * 64))
    targets = (Target("base", snapshot), Target("proposed", REVISION))
    left, right = TargetSet(targets), TargetSet(tuple(reversed(targets)))
    assert left == right
    assert decode_target_set(canonical_value(canonical_bytes(asdict(left)))) == left
    with pytest.raises(ReferenceError, match="DIGEST_MISMATCH"):
        decode_target_set(canonical_value(canonical_bytes(asdict(left))) | {"digest": asdict(Digest("sha256", "d" * 64))})


def test_target_codec_preserves_existing_constructor_capacity():
    refs = tuple(Target("primary", ArtifactRevisionRef("realm", "project", str(i), "r", DIGEST))
                 for i in range(4097))
    target_set = TargetSet(refs)
    assert decode_target_set(canonical_value(canonical_bytes(asdict(target_set)))) == target_set


def test_blob_locator_remains_wire_data_but_not_content_identity():
    first = BlobRef(DIGEST, 4, "text/plain", "location-a")
    second = BlobRef(DIGEST, 4, "text/plain", "location-b")
    assert first.identity_projection() == second.identity_projection()
    assert asdict(first) != asdict(second)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{ "a":1}', b'{"a":1.0}', b'{"a":NaN}', b'{"a":9223372036854775808}'])
def test_canonical_decoder_rejects_noncanonical_or_unsafe_numbers(raw):
    with pytest.raises(ReferenceError, match="INVALID_RECORD_BYTES"):
        canonical_value(raw)


def test_canonical_decoder_preserves_byte_and_size_boundaries():
    raw = canonical_bytes({"value": "设计", "version": 1})
    assert canonical_bytes(canonical_value(raw, maximum=len(raw))) == raw
    for invalid in (bytearray(raw), raw + b"\n", b'"\\ud800"'):
        with pytest.raises(ReferenceError, match="INVALID_RECORD_BYTES"):
            canonical_value(invalid)
    with pytest.raises(ReferenceError, match="INVALID_RECORD_BYTES"):
        canonical_value(raw, maximum=len(raw) - 1)


def test_structured_errors_are_frozen_and_do_not_capture_exception_text():
    error = DomainError(DomainErrorCode.VERSION_CONFLICT, (REVISION,),
                        (("actual_version", 2), ("expected_version", 1)))
    assert error.message_key == "engineering.domain.version_conflict"
    with pytest.raises(FrozenInstanceError):
        error.code = DomainErrorCode.INVALID_SCHEMA
    with pytest.raises(ValueError, match="INVALID_DOMAIN_ERROR"):
        DomainError(DomainErrorCode.INVALID_SCHEMA, details=(("sql", "synthetic query"),))
    extension = ReferenceError("external-extension")
    assert extension.code == "external-extension"
    converted = from_reference_error(extension)
    assert converted.code == DomainErrorCode.INVALID_SCHEMA
    assert "external-extension" not in repr(converted)
    assert not hasattr(extension, "error")


def test_complete_error_requires_actual_refs_not_class_name_or_module_spoofs():
    impostor = type(ArtifactRevisionRef.__name__, (), {"__module__": ArtifactRevisionRef.__module__})()
    with pytest.raises(ValueError, match="INVALID_DOMAIN_ERROR"):
        DomainError(DomainErrorCode.INVALID_SCHEMA, (impostor,))


@pytest.mark.parametrize("failure", [TypeError("synthetic defect"), RuntimeError("synthetic defect"), ValueError("synthetic defect")])
def test_constructor_error_conversion_does_not_accept_programming_exceptions(failure):
    with pytest.raises(TypeError, match="Expected ReferenceError"):
        from_reference_error(failure)


@pytest.mark.parametrize("version", [True, -1, "1", 1 << 63])
def test_version_expectations_reject_invalid_cas_values(version):
    with pytest.raises(ReferenceError, match="INVALID_VERSION"):
        VersionExpectation("artifact", "realm", "project", "artifact", version)


def test_application_read_set_projects_scoped_domain_expectations():
    read_set = ReadSet(Scope("realm", "project"), (ReadVersion("artifact", "artifact", 7),))
    assert read_set.version_expectations == (VersionExpectation("artifact", "realm", "project", "artifact", 7),)
    assert VersionExpectation("artifact", "realm", "project", "artifact", (1 << 63) - 1).expected_version == (1 << 63) - 1


def test_structured_error_can_express_the_actual_cas_upper_bound():
    error = DomainError(DomainErrorCode.VERSION_CONFLICT,
                        details=(("expected_version", (1 << 63) - 1),))
    assert error.details == (("expected_version", (1 << 63) - 1),)


def test_structured_error_tree_limits_count_shared_children_and_depth():
    error = DomainError(DomainErrorCode.INVALID_SCHEMA)
    for _ in range(11):
        error = DomainError(DomainErrorCode.INVALID_SCHEMA, violations=(error, error))
    with pytest.raises(ValueError, match="INVALID_DOMAIN_ERROR"):
        DomainError(DomainErrorCode.INVALID_SCHEMA, violations=(error, error))
    error = DomainError(DomainErrorCode.INVALID_SCHEMA)
    for _ in range(32):
        error = DomainError(DomainErrorCode.INVALID_SCHEMA, violations=(error,))
    with pytest.raises(ValueError, match="INVALID_DOMAIN_ERROR"):
        DomainError(DomainErrorCode.INVALID_SCHEMA, violations=(error,))
