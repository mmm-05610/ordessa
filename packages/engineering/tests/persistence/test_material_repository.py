"""SQLite schema-6 material revision acceptance on the original library UoW."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

import hashlib
import json
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema5
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import object_id
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.codec import encode_revision
from ordessa_engineering.domain.artifacts.models import (
    Artifact, ArtifactRevision, BlobPayload, InlinePayload,
)
from ordessa_engineering.domain.artifacts.provenance import (Claim, EvidenceLink, ExcerptCapture, SourceLocator, SourceRef)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method


LIBRARY_ID = "test.material-repository"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
ACTOR = ActorRef("test-human", "human", "synthetic-material-test")
SCOPE = Scope("realm-material", "project-material")


class _SyntheticEmptyCatalog:
    """An explicit fixture catalog used only to publish a real empty method."""

    __test__ = False

    def read_current(self) -> CompilationCapabilities:
        return CompilationCapabilities((), "synthetic-empty-catalog", "host")


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _library(path: Path, schema_version: int = 6) -> EngineeringLibrary:
    return EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=schema_version)


def _artifact(library: EngineeringLibrary, artifact_id: str = "artifact-1") -> None:
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, artifact_id, "evidence", CREATED_AT))
        uow.commit()


def _source(ref: BlobRef, excerpt_digest: Digest, selector: ContentSelector,
            source_id: str = "source-1") -> SourceRef:
    return SourceRef(
        source_id, "document", SourceLocator("document", provider="fixture", document_id="doc-1"),
        ExcerptCapture(ref, excerpt_digest, selector, "document-version-1"),
        CREATED_AT, ACTOR, ref.media_type, ref.byte_length,
    )


def _revision(*, artifact_id: str = "artifact-1", revision_id: str = "revision-1",
              payload=None, sources=(), claims=(), evidence_links=(), method_refs=(), generation_origin=None,
              schema_version: int = 2) -> ArtifactRevision:
    selected_payload = payload or InlinePayload.from_value(
        "application/json", "urn:test:material", {"statement": "stored"},
    )
    return ArtifactRevision(
        SCOPE, artifact_id, revision_id, CREATED_AT, ACTOR, selected_payload,
        schema_version=schema_version, sources=tuple(sources), claims=tuple(claims),
        evidence_links=tuple(evidence_links), method_refs=tuple(method_refs),
        generation_origin=generation_origin,
    )


def _append(library: EngineeringLibrary, revision: ArtifactRevision, expected_version: int = 0):
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        verify_material(revision, uow.engineering.validated_budget())
        ref = uow.engineering.append_revision(revision, expected_version=expected_version)
        uow.commit()
    return ref


def _publish_method(library: EngineeringLibrary, source_root: Path, method_id: str) -> MethodRef:
    source_root.mkdir(parents=True)
    workflow = {
        "schema_version": 1, "entry": "done",
        "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode()
    (source_root / "workflow.yaml").write_bytes(workflow_bytes)
    manifest = {
        "schema_version": 1, "method_id": method_id, "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                       "media_type": "application/yaml",
                       "sha256": hashlib.sha256(workflow_bytes).hexdigest()}],
        "requires": [],
    }
    (source_root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")))
    loaded = load_method(MethodSource(source_root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, CompilationCapabilities(()), "test.compiler/1")
    assert compiled.ok and compiled.value is not None, compiled.error
    store = SQLiteSnapshotStore(library)
    frozen = freeze_method(compiled.value, store, store, capability_catalog=_SyntheticEmptyCatalog())
    assert frozen.ok and frozen.value is not None, frozen.error
    released = frozen.value.ref
    return MethodRef(released.method_id, released.release_version, released.schema_version,
                     Digest("sha256", released.snapshot_digest))


def _count(library: EngineeringLibrary, table: str) -> int:
    assert table in {"eng_artifacts", "eng_artifact_revisions", "eng_method_blobs"}
    return library._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_schema6_roundtrips_full_material_revision_and_preserves_wire_locators(tmp_path: Path):
    path = tmp_path / "material-roundtrip.sqlite"
    library = _library(path)
    raw = b'{"statement":"captured"}'
    blob_store = SQLiteBlobStore(library)
    blob_ref = blob_store.put_verified(raw, _digest(raw), "application/json")
    _artifact(library)

    selector = ContentSelector("json_pointer", pointer="/statement")
    statement = b'"captured"'
    claim = Claim("claim-1", selector, _digest(statement))
    source_selector = ContentSelector("whole_capture")
    source = _source(blob_ref, _digest(raw), source_selector)
    link = EvidenceLink(claim.claim_id, source, source_selector, "supports", "synthetic capture link")
    method_ref = _publish_method(library, tmp_path / "published-method", "test.material.method")
    record = _revision(
        payload=BlobPayload("application/json", "urn:test:material", blob_ref),
        sources=(source,), claims=(claim,), evidence_links=(link,), method_refs=(method_ref,),
    )
    ref = _append(library, record)
    stored_bytes = encode_revision(record)
    with SQLiteUoWFactory(library).begin(SCOPE, "read") as uow:
        assert uow.engineering.resolve_revision(ref) == record
        row = uow._access.execute(
            "SELECT canonical_bytes, schema_version FROM eng_artifact_revisions WHERE revision_id=?",
            (record.revision_id,),
        ).fetchone()
        assert row == (stored_bytes, 2)
        uow.commit()
    library.close()

    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        with SQLiteUoWFactory(reopened).begin(SCOPE, "read") as uow:
            restored = uow.engineering.resolve_revision(ref)
            assert restored == record
            assert restored.projection()["sources"][0]["capture"]["blob_ref"]["storage_object_id"] == blob_ref.storage_object_id
            assert restored.payload.blob_ref == blob_ref
            assert restored.method_refs == (method_ref,)
            uow.commit()
        assert SQLiteBlobStore(reopened).read_verified(blob_ref) == raw
    finally:
        reopened.close()


def test_schema6_rejects_legacy_material_write_but_keeps_legacy_schema5_bytes(tmp_path: Path):
    legacy_path = tmp_path / "legacy-v5.sqlite"
    legacy = _library(legacy_path, schema_version=5)
    _artifact(legacy)
    legacy_record = _revision(schema_version=1)
    legacy_ref = _append(legacy, legacy_record)
    legacy_bytes = encode_revision(legacy_record)
    backup = tmp_path / "schema5-backup.sqlite"
    migrate_schema5(legacy, backup_path=backup)
    with SQLiteUoWFactory(legacy).begin(SCOPE, "read") as uow:
        restored = uow.engineering.resolve_revision(legacy_ref)
        assert restored == legacy_record
        row = uow._access.execute(
            "SELECT canonical_bytes, schema_version FROM eng_artifact_revisions WHERE revision_id=?",
            (legacy_record.revision_id,),
        ).fetchone()
        assert row == (legacy_bytes, 1)
        uow.commit()
    with pytest.raises(ApplicationError) as rejected:
        _append(legacy, _revision(revision_id="schema6-required", schema_version=1), expected_version=1)
    assert rejected.value.code == "MATERIAL_REVISION_REQUIRED"
    legacy.close()


@pytest.mark.parametrize("failure", ("missing", "wrong_locator", "tampered_body", "claim_digest",
                                     "excerpt_digest", "source_selector"))
def test_schema6_verifies_every_material_locator_and_digest_before_persisting(tmp_path: Path, failure: str):
    path = tmp_path / f"material-{failure}.sqlite"
    library = _library(path)
    raw = b'{"statement":"captured"}'
    store = SQLiteBlobStore(library)
    ref = store.put_verified(raw, _digest(raw), "application/json")
    _artifact(library)
    if failure == "missing":
        library._connection.execute("DELETE FROM eng_method_blobs WHERE digest=?", (ref.digest.hex,))
    elif failure == "tampered_body":
        library._connection.execute(
            "UPDATE eng_method_blobs SET body=? WHERE digest=?",
            (b'{"statement":"tampered"}', ref.digest.hex),
        )
    if failure in {"missing", "tampered_body"}:
        library._connection.commit()
    elif failure == "wrong_locator":
        ref = BlobRef(ref.digest, ref.byte_length, ref.media_type, "engineering-blob:foreign:wrong")

    selector = ContentSelector("json_pointer", pointer="/statement")
    claim_digest = _digest(b'"different"' if failure == "claim_digest" else b'"captured"')
    claim = Claim("claim-1", selector, claim_digest)
    source_selector = ContentSelector("whole_capture")
    capture_selector = (ContentSelector("byte_range", start=0, end=1)
                        if failure == "source_selector" else source_selector)
    source_digest = (_digest(b"different excerpt") if failure == "excerpt_digest" else
                     _digest(raw[:1]) if failure == "source_selector" else _digest(raw))
    source = _source(ref, source_digest, capture_selector)
    link_selector = (ContentSelector("byte_range", start=1, end=2)
                     if failure == "source_selector" else source_selector)
    link = EvidenceLink(claim.claim_id, source, link_selector, "context", "synthetic source")
    record = _revision(payload=BlobPayload("application/json", "urn:test:material", ref),
                       sources=(source,), claims=(claim,), evidence_links=(link,))
    before_blobs = _count(library, "eng_method_blobs")
    expected = {
        "missing": "MATERIAL_BLOB_NOT_FOUND", "wrong_locator": "MATERIAL_BLOB_INVALID",
        "tampered_body": "MATERIAL_BLOB_CORRUPT", "claim_digest": "MATERIAL_CONTENT_INVALID",
        "excerpt_digest": "MATERIAL_CONTENT_INVALID",
        "source_selector": "MATERIAL_CONTENT_INVALID",
    }[failure]
    with pytest.raises(ApplicationError) as rejected:
        _append(library, record)
    assert rejected.value.code == expected
    assert _count(library, "eng_artifact_revisions") == 0
    assert _count(library, "eng_method_blobs") == before_blobs
    library.close()


def test_material_budget_is_rejected_before_any_missing_blob_lookup(tmp_path: Path):
    library = _library(tmp_path / "material-budget.sqlite")
    _artifact(library)
    # Five individually well-shaped 16 MiB declarations exceed the 64 MiB
    # per-revision budget. Their object locators intentionally have no rows:
    # the bounded preflight must reject aggregate size before any byte lookup.
    refs = tuple(BlobRef(Digest("sha256", f"{index:064x}"), 16 * 1024 * 1024,
                         "application/octet-stream", object_id(LIBRARY_ID, f"{index:064x}"))
                 for index in range(1, 6))
    sources = tuple(_source(ref, ref.digest, ContentSelector("whole_capture"), f"source-{index}")
                    for index, ref in enumerate(refs, start=1))
    record = _revision(sources=sources)
    with pytest.raises(ApplicationError) as rejected:
        _append(library, record)
    assert rejected.value.code == "MATERIAL_LIMIT"
    assert _count(library, "eng_artifact_revisions") == 0
    library.close()


def test_evidence_link_selector_uses_verified_excerpt_coordinates(tmp_path: Path):
    library = _library(tmp_path / "excerpt-coordinates.sqlite")
    store = SQLiteBlobStore(library)
    raw = b"AB"
    ref = store.put_verified(raw, _digest(raw), "text/plain")
    payload = InlinePayload.from_value("application/json", "urn:test:excerpt-coordinate",
                                       {"statement": "captured"})
    claim = Claim("claim-1", ContentSelector("whole_capture"), _digest(payload.content_bytes()))
    excerpt = ContentSelector("byte_range", start=0, end=1)
    source = _source(ref, _digest(b"A"), excerpt)
    allowed_link = EvidenceLink(claim.claim_id, source,
                               ContentSelector("byte_range", start=0, end=1),
                               "supports", "within verified excerpt")
    _artifact(library, "excerpt-valid")
    valid = _revision(artifact_id="excerpt-valid", revision_id="excerpt-valid-r1",
                      payload=payload, sources=(source,), claims=(claim,),
                      evidence_links=(allowed_link,))
    _append(library, valid)

    outside_link = EvidenceLink(claim.claim_id, source,
                                ContentSelector("byte_range", start=1, end=2),
                                "supports", "outside verified excerpt")
    _artifact(library, "excerpt-invalid")
    invalid = _revision(artifact_id="excerpt-invalid", revision_id="excerpt-invalid-r1",
                        payload=payload, sources=(source,), claims=(claim,),
                        evidence_links=(outside_link,))
    with pytest.raises(ApplicationError) as rejected:
        _append(library, invalid)
    assert rejected.value.code == "MATERIAL_CONTENT_INVALID"
    assert library._connection.execute(
        "SELECT COUNT(*) FROM eng_artifact_revisions WHERE artifact_id=?", ("excerpt-invalid",),
    ).fetchone() == (0,)
    library.close()


def test_schema6_source_version_is_explicitly_unavailable_without_resolver(tmp_path: Path):
    from ordessa_engineering.domain.artifacts.provenance import (SourceLocator, SourceRef, VersionCapture)

    library = _library(tmp_path / "source-version.sqlite")
    _artifact(library)
    source = SourceRef(
        "upstream-source", "document",
        SourceLocator("document", provider="external", document_id="doc-versioned"),
        VersionCapture("immutable-upstream-version", _digest(b"not locally captured")),
        CREATED_AT, ACTOR, "application/json", 24,
    )
    record = _revision(sources=(source,))
    with pytest.raises(ApplicationError) as unavailable:
        _append(library, record)
    assert unavailable.value.code == "SOURCE_VERSION_UNAVAILABLE"
    assert _count(library, "eng_artifact_revisions") == 0
    library.close()
