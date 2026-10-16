"""Material validation context: per-operation budget, no bypass, UoW/content binding.

The application validates one operation against a short-lived budget on the live
UoW; the save requires that same validation and still performs integrity/CAS checks.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, BlobPayload, InlinePayload
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest

LIBRARY_ID = "test.material-validation-context"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
ACTOR = ActorRef("test-human", "human", "synthetic-validation-context")
SCOPE = Scope("realm-validation", "project-validation")


def _library(path: Path) -> EngineeringLibrary:
    return EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)


def _artifact(library: EngineeringLibrary, artifact_id: str) -> None:
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, artifact_id, "evidence", CREATED_AT))
        uow.commit()


def _revision(artifact_id: str, revision_id: str, payload=None) -> ArtifactRevision:
    return ArtifactRevision(
        SCOPE, artifact_id, revision_id, CREATED_AT, ACTOR,
        payload or InlinePayload.from_value("application/json", "urn:test:material", {"statement": "stored"}),
        schema_version=2,
    )


def test_append_without_validation_is_refused(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        with pytest.raises(ApplicationError, match="MATERIAL_VALIDATION_REQUIRED"):
            uow.engineering.append_revision(_revision("artifact-1", "revision-1"), expected_version=0)


def test_validation_is_bound_to_content_and_operation(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        verify_material(_revision("artifact-1", "revision-1"), uow.engineering.validated_budget())
        # A different content/operation (different revision id) is not covered.
        with pytest.raises(ApplicationError, match="MATERIAL_VALIDATION_REQUIRED"):
            uow.engineering.append_revision(_revision("artifact-1", "revision-2"), expected_version=0)


def test_validation_is_bound_to_the_uow(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    revision = _revision("artifact-1", "revision-1")
    with SQLiteUoWFactory(library).begin(SCOPE) as first:
        verify_material(revision, first.engineering.validated_budget())
        first.commit()
    with SQLiteUoWFactory(library).begin(SCOPE) as second:
        with pytest.raises(ApplicationError, match="MATERIAL_VALIDATION_REQUIRED"):
            second.engineering.append_revision(revision, expected_version=0)


def test_same_uow_two_operations_have_independent_budgets(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    _artifact(library, "artifact-2")
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        verify_material(_revision("artifact-1", "revision-1"), uow.engineering.validated_budget())
        uow.engineering.append_revision(_revision("artifact-1", "revision-1"), expected_version=0)
        verify_material(_revision("artifact-2", "revision-2"), uow.engineering.validated_budget())
        uow.engineering.append_revision(_revision("artifact-2", "revision-2"), expected_version=0)
        uow.commit()
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        assert uow.engineering.get_artifact("artifact-1").version == 1
        assert uow.engineering.get_artifact("artifact-2").version == 1


def test_failed_validation_rolls_back_without_rows(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    missing = BlobRef(Digest("sha256", "a" * 64), 16, "application/json", "missing-object")
    bad = _revision("artifact-1", "revision-1",
                    payload=BlobPayload("application/json", "urn:test:material", missing))
    with pytest.raises(ApplicationError):
        with SQLiteUoWFactory(library).begin(SCOPE) as uow:
            verify_material(bad, uow.engineering.validated_budget())
            uow.engineering.append_revision(bad, expected_version=0)
            uow.commit()
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        assert uow.engineering.get_artifact("artifact-1").version == 0


def _payload(value: str) -> InlinePayload:
    return InlinePayload.from_value("application/json", "urn:test:material", {"statement": value})


def test_validation_is_bound_to_canonical_content_not_only_the_id(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        verify_material(_revision("artifact-1", "revision-1", payload=_payload("a")),
                        uow.engineering.validated_budget())
        # Same revision id, replaced content -> different canonical key -> refused.
        with pytest.raises(ApplicationError, match="MATERIAL_VALIDATION_REQUIRED"):
            uow.engineering.append_revision(_revision("artifact-1", "revision-1", payload=_payload("b")),
                                            expected_version=0)


def test_validation_is_bound_to_scope(tmp_path):
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    other = Scope("realm-other", "project-other")
    revision = _revision("artifact-1", "revision-1")
    with SQLiteUoWFactory(library).begin(other) as uow:
        # The same content under a different scope is a different key and is refused.
        with pytest.raises(ApplicationError):
            verify_material(revision, uow.engineering.validated_budget())
            uow.engineering.append_revision(revision, expected_version=0)


def test_marker_is_not_a_self_issuable_permit(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.material_validation import MaterialBudget
    library = _library(tmp_path / "library.sqlite")
    _artifact(library, "artifact-1")
    revision = _revision("artifact-1", "revision-1")
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        # A foreign/self-made budget is not the repository's current per-operation
        # budget, so its marker is not accepted as a permit.
        foreign = MaterialBudget(uow.engineering.access)
        verify_material(revision, foreign)
        with pytest.raises(ApplicationError, match="MATERIAL_VALIDATION_REQUIRED"):
            uow.engineering.append_revision(revision, expected_version=0)
