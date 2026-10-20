"""Versioned external source records reuse the existing Change/Review/Package owners."""
import pytest

from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.provenance import SourceLocator, SourceRef, VersionCapture
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.codec import decode_proposal, encode_proposal
from ordessa_engineering.domain.changes.models import Proposal, SourceChange
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.mechanisms.codec import canonical_value
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.codec import decode_package, encode_package
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, PackageDocument, PreparedPackagePayload,
)
from ordessa_engineering.domain.reviews.codec import decode_plan, encode_plan, encode_requirement
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan, ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.targets import SourceTargetRef, Target, TargetSet


SCOPE = Scope("realm-external", "project-alpha")
ACTOR = ActorRef("author", "human", "controlled-test")
METHOD = MethodRef("ordessa.incremental-engineering", "2.7.0", 2, Digest("sha256", "a" * 64))
RESOURCE = ExactMethodResourceRef(METHOD, "schemas/review.json", Digest("sha256", "b" * 64), "review-schema")
LOCATOR = SourceLocator("document", provider="project-files", document_id="alpha:design/DID.md")


def _source(source_id: str, version: str, content: bytes) -> SourceRef:
    import hashlib

    return SourceRef(source_id, "document", LOCATOR,
        VersionCapture(version, Digest("sha256", hashlib.sha256(content).hexdigest())),
        "2026-10-14T05:00:00.000000Z", ACTOR, "text/markdown", len(content))


BASELINE = _source("did-baseline-v1", "baseline-v1", b"design: before\n")
CANDIDATE = _source("did-candidate-v2", "candidate-v2", b"design: after\n")
REVIEW_REF = ReviewRef(SCOPE.realm_id, SCOPE.project_id, "review-1", Digest("sha256", "c" * 64))


def _proposal(proposal_id: str, source_change: SourceChange, supersedes=()) -> Proposal:
    return Proposal(SCOPE, proposal_id, "2026-10-14T05:00:00.000000Z", ACTOR,
        "change-did", "Register external DID change", "Explicitly requested review",
        (), (), (), (), METHOD, (), None, tuple(supersedes), 2, source_change)


def test_external_target_and_review_plan_pin_exact_sources_and_method_resources() -> None:
    targets = TargetSet((Target.external("base", SCOPE, BASELINE),
                         Target.external("proposed", SCOPE, CANDIDATE)))
    assert all(type(item.ref) is SourceTargetRef for item in targets.targets)
    keys = tuple(CheckKey(target, "did-consistency") for target in targets.targets)
    requirement = ReviewRequirement(SCOPE, "did-review", 1, "quality", targets, METHOD,
        CriterionSetRef("did-criteria", 1, Digest("sha256", "d" * 64)), keys,
        ("reviewer",), "explicit-did-review", 2, (RESOURCE,))
    plan = ReviewPlan("did-review-1", requirement,
        tuple(CheckPolicy(key, True, True) for key in keys), AggregationPolicy(), ("reviewer",))

    restored = decode_plan(encode_plan(plan))
    assert restored == plan
    assert restored.requirement.method_resource_refs == (RESOURCE,)
    assert {item.ref.source_ref.content_identity for item in restored.requirement.expected_targets.targets} == {
        BASELINE.content_identity, CANDIDATE.content_identity,
    }
    with pytest.raises(ReferenceError, match="INVALID_METHOD_RESOURCE"):
        ReviewRequirement(SCOPE, "bad-review", 1, "quality", targets, METHOD,
            requirement.criterion_set_ref, keys, ("reviewer",), "explicit-did-review", 2,
            (ExactMethodResourceRef(MethodRef("other", "1.0", 1, Digest("sha256", "e" * 64)),
                                    "schemas/review.json", Digest("sha256", "f" * 64), "other-resource"),))


def test_immutable_proposal_revision_associates_review_without_artifact_mirrors() -> None:
    initial = _proposal("proposal-1", SourceChange(BASELINE, CANDIDATE, (RESOURCE,)))
    associated = _proposal("proposal-2", SourceChange(BASELINE, CANDIDATE, (RESOURCE,), (REVIEW_REF,)),
                           (initial.ref,))

    restored = decode_proposal(encode_proposal(associated))
    assert restored == associated
    assert restored.schema_version == 2
    assert restored.mutations == restored.claim_refs == restored.evidence_links == ()
    assert restored.implementation_intent is None
    assert restored.source_change.review_refs == (REVIEW_REF,)
    assert restored.supersedes_refs == (initial.ref,)
    with pytest.raises(ReferenceError, match="INVALID_SUPERSEDES_REF"):
        _proposal("proposal-with-review", SourceChange(BASELINE, CANDIDATE, (RESOURCE,), (REVIEW_REF,)))


def test_prepared_package_reuses_package_owner_and_pins_exact_change_and_reviews() -> None:
    initial = _proposal("proposal-before-package", SourceChange(BASELINE, CANDIDATE, (RESOURCE,)))
    proposal = _proposal("proposal-final", SourceChange(BASELINE, CANDIDATE, (RESOURCE,), (REVIEW_REF,)),
                         (initial.ref,))
    payload = PreparedPackagePayload(BASELINE, CANDIDATE, proposal.ref, (REVIEW_REF,), METHOD,
        (RESOURCE,), (PackageDocument("spec", CANDIDATE), PackageDocument("plan", CANDIDATE)))
    package = ImplementationPackage(SCOPE, "prepared-did", "2026-10-14T05:00:00.000000Z", ACTOR, payload)

    restored = decode_package(encode_package(package))
    assert restored == package
    assert restored.ref == package.ref
    assert restored.payload.change_ref == proposal.ref
    assert restored.payload.review_refs == (REVIEW_REF,)
    assert all(type(item.source_ref) is SourceRef for item in restored.payload.documents)
    assert not any("ArtifactRevisionRef" in type(item).__name__ for item in restored.payload.documents)


def test_external_source_identity_pins_locator_version_and_bytes_digest() -> None:
    newer_version_same_bytes = _source("did-candidate-v3", "candidate-v3", b"design: after\n")
    other_document = SourceRef("did-other", "document",
        SourceLocator("document", provider="project-files", document_id="alpha:other.md"),
        CANDIDATE.capture, CANDIDATE.captured_at, ACTOR, "text/markdown", CANDIDATE.byte_length)
    same_version_other_bytes = _source("did-candidate-v4", "candidate-v2", b"design: changed\n")
    pins = TargetSet((Target.external("proposed", SCOPE, CANDIDATE),))
    assert TargetSet((Target.external("proposed", SCOPE, newer_version_same_bytes),)).digest != pins.digest
    assert TargetSet((Target.external("proposed", SCOPE, other_document),)).digest != pins.digest
    assert TargetSet((Target.external("proposed", SCOPE, same_version_other_bytes),)).digest != pins.digest
    same_bytes_new_version = _source("same-bytes-new-version", "baseline-v2", b"design: before\n")
    assert SourceChange(BASELINE, same_bytes_new_version, (RESOURCE,)).candidate == same_bytes_new_version
    with pytest.raises(ReferenceError, match="INVALID_SOURCE_CHANGE"):
        SourceChange(BASELINE, _source("same-content", "baseline-v1", b"design: before\n"), (RESOURCE,))


def test_prepared_package_rejects_cross_scope_review_and_empty_review_set() -> None:
    proposal = _proposal("proposal-package-scope", SourceChange(BASELINE, CANDIDATE, (RESOURCE,)))
    foreign_review = ReviewRef("other-realm", SCOPE.project_id, "foreign-review", Digest("sha256", "9" * 64))
    with pytest.raises(ReferenceError, match="REALM_MISMATCH"):
        ImplementationPackage(SCOPE, "prepared-foreign", "2026-10-14T05:00:00.000000Z", ACTOR,
            PreparedPackagePayload(BASELINE, CANDIDATE, proposal.ref, (foreign_review,), METHOD,
                (RESOURCE,), (PackageDocument("spec", CANDIDATE),)))
    with pytest.raises(ReferenceError, match="INVALID_SCHEMA"):
        PreparedPackagePayload(BASELINE, CANDIDATE, proposal.ref, (), METHOD,
            (RESOURCE,), (PackageDocument("spec", CANDIDATE),))


def test_v1_requirement_wire_projection_keeps_legacy_field_set() -> None:
    artifact = ArtifactRevisionRef(SCOPE.realm_id, SCOPE.project_id, "artifact", "rev-1",
                                   Digest("sha256", "3" * 64))
    target = Target("primary", artifact)
    key = CheckKey(target, "criterion")
    requirement = ReviewRequirement(SCOPE, "v1-external-invalid", 1, "quality",
        TargetSet((target,)), METHOD, CriterionSetRef("criteria", 1, Digest("sha256", "2" * 64)),
        (key,), ("reviewer",), "phase")
    wire = canonical_value(encode_requirement(requirement))
    assert "schema_version" not in wire
    assert "method_resource_refs" not in wire
    assert requirement.schema_version == 1
