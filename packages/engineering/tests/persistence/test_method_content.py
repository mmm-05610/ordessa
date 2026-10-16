"""Real offline method-resource resolution for schema-2 MethodPayload values."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader

import hashlib
import json
import socket
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import (
    Artifact,
    ArtifactRevision,
    MethodContent,
    MethodPayload,
)
from ordessa_engineering.domain.artifacts.method_binding import (ExactMethodResourceRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.methods import compile_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.methods import validate_method


LIBRARY_ID = "test.method-content"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
SCOPE = Scope("realm-method-content", "project-method-content")
ACTOR = ActorRef("test-human", "human", "synthetic-method-content")
METHOD_BASE = "https://ordessa.invalid/method/schemas/"


class _SyntheticEmptyCatalog:
    """Explicit fixture authority for a synthetic method with no capabilities."""

    __test__ = False

    def read_current(self) -> CompilationCapabilities:
        return CompilationCapabilities((), "synthetic-empty-catalog", "host")


def _digest(raw: bytes) -> Digest:
    return Digest("sha256", hashlib.sha256(raw).hexdigest())


def _publish_document_method(library: EngineeringLibrary, source_root: Path):
    source_root.mkdir(parents=True)
    workflow = {
        "schema_version": 1, "entry": "done",
        "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode()
    (source_root / "workflow.yaml").write_bytes(workflow_bytes)

    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": METHOD_BASE + "output.json",
        "type": "object", "properties": {"answer": {"$dynamicRef": "sibling.json#answer"}},
        "required": ["answer"], "additionalProperties": False,
    }
    sibling_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": METHOD_BASE + "sibling.json",
        "$defs": {"answer": {"$dynamicAnchor": "answer", "type": "string", "minLength": 1}},
    }
    output_bytes = json.dumps(output_schema, separators=(",", ":")).encode()
    sibling_bytes = json.dumps(sibling_schema, separators=(",", ":")).encode()
    (source_root / "output.schema.json").write_bytes(output_bytes)
    (source_root / "sibling.schema.json").write_bytes(sibling_bytes)
    resources = [
        {"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
         "media_type": "application/yaml", "sha256": hashlib.sha256(workflow_bytes).hexdigest()},
        {"id": "document.output", "kind": "document_schema", "path": "output.schema.json",
         "media_type": "application/schema+json", "sha256": hashlib.sha256(output_bytes).hexdigest()},
        {"id": "document.sibling", "kind": "document_schema", "path": "sibling.schema.json",
         "media_type": "application/schema+json", "sha256": hashlib.sha256(sibling_bytes).hexdigest()},
    ]
    manifest = {
        "schema_version": 1, "method_id": "test.method-content", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": resources, "requires": [],
        "documents": [
            {"document_type": "output", "schema": {"resource": "document.output"}},
            {"document_type": "sibling", "schema": {"resource": "document.sibling"}},
        ],
    }
    (source_root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")))
    loaded = load_method(MethodSource(source_root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, CompilationCapabilities(()), "test.compiler/1")
    assert compiled.ok and compiled.value is not None, compiled.error
    store = SQLiteSnapshotStore(library)
    result = freeze_method(compiled.value, store, store, capability_catalog=_SyntheticEmptyCatalog())
    assert result.ok and result.value is not None, result.error
    frozen = result.value
    method_ref = MethodRef(frozen.ref.method_id, frozen.ref.release_version,
                           frozen.ref.schema_version, Digest("sha256", frozen.ref.snapshot_digest))
    snapshot = store.get(frozen.ref)
    return method_ref, snapshot


def _artifact(library: EngineeringLibrary, artifact_id: str) -> None:
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, artifact_id, "evidence", CREATED_AT))
        uow.commit()


def _revision(artifact_id: str, revision_id: str, method_ref: MethodRef,
              resource_id: str, path: str, digest: Digest, value) -> ArtifactRevision:
    exact = ExactMethodResourceRef(method_ref, path, digest, resource_id)
    payload = MethodPayload(
        "application/json", METHOD_BASE + "output.json",
        MethodContent.from_value(exact, value),
    )
    return ArtifactRevision(
        SCOPE, artifact_id, revision_id, CREATED_AT, ACTOR, payload,
        schema_version=2, method_refs=(method_ref,),
    )


def _append(library: EngineeringLibrary, revision: ArtifactRevision):
    with SQLiteUoWFactory(library).begin(SCOPE) as uow:
        verify_material(revision, uow.engineering.validated_budget())
        ref = uow.engineering.append_revision(revision, expected_version=0)
        uow.commit()
    return ref


def _resources(snapshot):
    return {item.resource_id: item for item in snapshot.resources}


def test_document_label_comes_from_exact_snapshot_schema_not_artifact_kind(tmp_path):
    from dataclasses import replace
    from ordessa_engineering.application.orchestration.method_content import document_type_for_payload
    library=EngineeringLibrary.create(tmp_path/'label.sqlite',library_id=LIBRARY_ID,schema_version=6)
    try:
        method,snapshot=_publish_document_method(library,tmp_path/'label-method')
        output=_resources(snapshot)['document.output']
        revision=_revision('label-artifact','label-revision',method,output.resource_id,
            output.logical_path,Digest('sha256',output.digest),{'answer':'real captured schema'})
        assert document_type_for_payload(snapshot,revision.payload)=='output'
        with pytest.raises(ApplicationError,match='METHOD_RESOURCE_MISMATCH'):
            content=replace(revision.payload.content,schema_ref=replace(revision.payload.content.schema_ref,logical_path='wrong.json'))
            document_type_for_payload(snapshot,replace(revision.payload,content=content))
        with pytest.raises(ApplicationError,match='METHOD_SCHEMA_ID_MISMATCH'):
            document_type_for_payload(snapshot,replace(revision.payload,schema_id='wrong-schema'))
        with pytest.raises(ApplicationError,match='METHOD_CONTENT_INVALID'):
            content=MethodContent.from_value(revision.payload.content.schema_ref,{'answer':3})
            document_type_for_payload(snapshot,replace(revision.payload,content=content))
    finally:library.close()


def test_published_document_schema_method_content_resolves_sibling_offline(tmp_path: Path, monkeypatch):
    library = EngineeringLibrary.create(
        tmp_path / "method-content.sqlite", library_id=LIBRARY_ID, schema_version=6,
    )
    try:
        method_ref, snapshot = _publish_document_method(library, tmp_path / "document-method")
        output = _resources(snapshot)["document.output"]
        revision = _revision("valid-method-content", "valid-revision", method_ref,
                             output.resource_id, output.logical_path, Digest("sha256", output.digest),
                             {"answer": "sibling schema resolved"})
        # Refusing any socket connection proves the JSON Schema sibling lookup
        # is backed by the published local bundle and never retrieves remotely.
        def deny_network(*_args, **_kwargs):
            raise AssertionError("method schema resolution attempted network access")

        monkeypatch.setattr(socket, "create_connection", deny_network)
        _artifact(library, "valid-method-content")
        ref = _append(library, revision)
        with SQLiteUoWFactory(library).begin(SCOPE, "read") as uow:
            assert uow.engineering.resolve_revision(ref) == revision
            uow.commit()
    finally:
        library.close()


@pytest.mark.parametrize("wrong", ("resource_id", "path", "digest", "kind", "value"))
def test_method_content_rejects_unbound_or_invalid_resource(tmp_path: Path, wrong: str):
    library = EngineeringLibrary.create(
        tmp_path / f"method-content-{wrong}.sqlite", library_id=LIBRARY_ID, schema_version=6,
    )
    try:
        method_ref, snapshot = _publish_document_method(library, tmp_path / f"source-{wrong}")
        resources = _resources(snapshot)
        output = resources["document.output"]
        resource_id, path, digest = output.resource_id, output.logical_path, Digest("sha256", output.digest)
        value = {"answer": "valid"}
        if wrong == "resource_id":
            resource_id = "not-in-published-method"
        elif wrong == "path":
            path = "schemas/renamed.json"
        elif wrong == "digest":
            digest = _digest(b"wrong schema digest")
        elif wrong == "kind":
            workflow = resources["workflow.main"]
            resource_id, path, digest = workflow.resource_id, workflow.logical_path, Digest("sha256", workflow.digest)
        elif wrong == "value":
            value = {"answer": 42}
        artifact_id = f"artifact-{wrong}"
        _artifact(library, artifact_id)
        revision = _revision(artifact_id, f"revision-{wrong}", method_ref,
                             resource_id, path, digest, value)
        expected = "METHOD_CONTENT_INVALID" if wrong == "value" else "METHOD_RESOURCE_MISMATCH"
        with pytest.raises(ApplicationError) as rejected:
            _append(library, revision)
        assert rejected.value.code == expected
        assert library._connection.execute(
            "SELECT COUNT(*) FROM eng_artifact_revisions WHERE artifact_id=?", (artifact_id,),
        ).fetchone() == (0,)
    finally:
        library.close()


def test_method_content_rejects_tampered_published_source_bytes(tmp_path: Path):
    library = EngineeringLibrary.create(
        tmp_path / "method-content-tampered.sqlite", library_id=LIBRARY_ID, schema_version=6,
    )
    try:
        method_ref, snapshot = _publish_document_method(library, tmp_path / "tampered-method")
        sibling = _resources(snapshot)["document.sibling"]
        original = (tmp_path / "tampered-method" / sibling.logical_path).read_bytes()
        modified = original.replace(b'"type":"string"', b'"type":"number"')
        assert len(modified) == len(original) and modified != original
        library._connection.execute(
            "UPDATE eng_method_blobs SET body=? WHERE digest=?",
            (modified, sibling.digest),
        )
        library._connection.commit()
        _artifact(library, "tampered-method-artifact")
        output = _resources(snapshot)["document.output"]
        revision = _revision("tampered-method-artifact", "tampered-method-revision", method_ref,
                             output.resource_id, output.logical_path, Digest("sha256", output.digest),
                             {"answer": "still superficially valid"})
        with pytest.raises(ApplicationError) as rejected:
            _append(library, revision)
        assert rejected.value.code == "MATERIAL_METHOD_SNAPSHOT_BLOB_CORRUPT"
        assert library._connection.execute(
            "SELECT COUNT(*) FROM eng_artifact_revisions WHERE artifact_id=?",
            ("tampered-method-artifact",),
        ).fetchone() == (0,)
    finally:
        library.close()


def test_missing_remote_document_schema_reference_is_rejected_without_network(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "remote-reference-method"
    source_root.mkdir()
    workflow = {
        "schema_version": 1, "entry": "done",
        "steps": [{"id": "done", "kind": "stop", "outcome": "finished"}],
        "stop_outcomes": ["finished"], "wait_kinds": [],
    }
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode()
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$id": "https://ordessa.invalid/method/schemas/remote.json",
              "$ref": "https://missing.invalid/schema.json", "type": "object"}
    schema_bytes = json.dumps(schema, separators=(",", ":")).encode()
    (source_root / "workflow.yaml").write_bytes(workflow_bytes)
    (source_root / "output.schema.json").write_bytes(schema_bytes)
    manifest = {
        "schema_version": 1, "method_id": "test.remote-schema", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [
            {"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
             "media_type": "application/yaml", "sha256": hashlib.sha256(workflow_bytes).hexdigest()},
            {"id": "document.remote", "kind": "document_schema", "path": "output.schema.json",
             "media_type": "application/schema+json", "sha256": hashlib.sha256(schema_bytes).hexdigest()},
        ], "requires": [],
        "documents": [{"document_type": "remote", "schema": {"resource": "document.remote"}}],
    }
    (source_root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")))

    def deny_network(*_args, **_kwargs):
        raise AssertionError("schema validation attempted network access")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    loaded = load_method(MethodSource(source_root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    report = validate_method(loaded.value, CompilationCapabilities(()))
    assert "REMOTE_SCHEMA_REF" in {item.code for item in report.diagnostics}
