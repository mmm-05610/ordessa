"""Artifact commands bind interface-2 provenance without legacy fallback."""
from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from ordessa_engineering.adapters.persistence.sqlite import artifact_repository
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases, input_schema
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)


LIBRARY_ID = "test.material-usecases"
RECEIVED_AT = "2026-10-09T12:00:00.000000Z"
SCOPE = Scope("realm-material-usecases", "project-material-usecases")
ACTOR = ActorRef("test-human", "human", "synthetic-usecase-access")


class SyntheticAccess:
    """A test-only access adapter; actor identity is not production authority."""

    def require(self, context, operation):
        assert type(context) is CommandContext


def _context(request_id: str) -> CommandContext:
    return CommandContext(
        SCOPE, "synthetic-principal", ACTOR, request_id, RECEIVED_AT, "trace-material",
    )


def _payload(value="captured"):
    return {"media_type": "application/json", "schema_id": "urn:test:material",
            "inline_value": {"statement": value}}


def _interface2_fields(**values):
    return {"sources": [], "claims": [], "evidence_links": [], "method_refs": [],
            "generation_origin": None, **values}


def _count(library: EngineeringLibrary, table: str) -> int:
    assert table in {"eng_artifacts", "eng_artifact_revisions", "eng_commands"}
    return library._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _digest(raw: bytes) -> dict:
    return {"algorithm": "sha256", "hex": hashlib.sha256(raw).hexdigest()}


def _selector(kind: str, *, pointer=None):
    return {"kind": kind, "start": None, "end": None, "pointer": pointer, "schema_version": 1}


@pytest.fixture
def environment(tmp_path: Path):
    path = tmp_path / "material-usecases.sqlite"
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    factory = SQLiteUoWFactory(library)
    try:
        yield library, factory, ArtifactUseCases(factory, SyntheticAccess())
    finally:
        if not library._closed:
            library.close()


def test_create_and_append_use_interface2_and_persist_every_provenance_field(environment):
    library, factory, usecases = environment
    create_context = _context("create-interface2")
    create_contract = input_schema("engineering.artifacts.create")
    append_contract = input_schema("engineering.artifacts.append_revision")
    assert create_contract["$id"].endswith(":input:2")
    assert append_contract["$id"].endswith(":input:2")
    for contract in (create_contract, append_contract):
        assert {"sources", "claims", "evidence_links", "method_refs", "generation_origin"} <= set(contract["properties"])
        assert "additionalProperties" in contract and contract["additionalProperties"] is False

    created = usecases.create(
        {"kind": "evidence", "initial": _payload(), **_interface2_fields()}, create_context,
    )
    assert created.status == "completed"
    artifact_id = created.result["artifact"]["artifact_id"]
    first_ref = created.result["revision_ref"]
    with factory.begin(SCOPE, "read") as uow:
        first = uow.engineering.resolve_revision(_revision_ref(first_ref))
        assert first.schema_version == 2
        assert first.sources == first.claims == first.evidence_links == first.method_refs == ()
        assert first.generation_origin is None
        uow.commit()

    appended = usecases.append_revision(
        {"artifact_id": artifact_id, "expected_version": 1, "parents": [first_ref],
         "payload": _payload("second"), **_interface2_fields()},
        _context("append-interface2"),
    )
    assert appended.status == "completed"
    with factory.begin(SCOPE, "read") as uow:
        second = uow.engineering.resolve_revision(_revision_ref(appended.result["revision_ref"]))
        assert second.schema_version == 2
        assert second.parent_revision_refs == (_revision_ref(first_ref),)
        assert second.payload.value == {"statement": "second"}
        uow.commit()
    assert _count(library, "eng_artifact_revisions") == 2


def test_interface2_parses_and_persists_source_claim_and_link_projection(environment):
    library, factory, usecases = environment
    captured = b'{"statement":"captured"}'
    blob_ref = SQLiteBlobStore(library).put_verified(
        captured, Digest("sha256", hashlib.sha256(captured).hexdigest()), "application/json",
    )
    source = {
        "source_id": "source-1", "kind": "document",
        "locator": {"kind": "document", "provider": "fixture", "conversation_id": None,
                    "message_id": None, "repository_id": None, "path": None,
                    "document_id": "doc-1", "artifact_ref": None, "observation_id": None},
        "capture": {"kind": "immutable_excerpt", "blob_ref": {
            "digest": _digest(captured), "byte_length": len(captured),
            "media_type": "application/json", "storage_object_id": blob_ref.storage_object_id,
        }, "excerpt_digest": _digest(captured), "selector": _selector("whole_capture"),
                    "upstream_version": "captured-version-1"},
        "captured_at": RECEIVED_AT,
        "captured_by": {"actor_id": ACTOR.actor_id, "actor_kind": ACTOR.actor_kind,
                        "issuer": ACTOR.issuer},
        "media_type": "application/json", "byte_length": len(captured), "original_url": None,
    }
    claim_bytes = b'"captured"'
    claim = {"claim_id": "claim-1", "selector": _selector("json_pointer", pointer="/statement"),
             "statement_digest": _digest(claim_bytes)}
    link = {"claim_id": "claim-1", "source_ref": source,
            "source_selector": _selector("whole_capture"), "relation": "supports",
            "rationale": "synthetic relation"}
    result = usecases.create(
        {"kind": "evidence", "initial": _payload(),
         **_interface2_fields(sources=[source], claims=[claim], evidence_links=[link])},
        _context("interface2-provenance"),
    )
    assert result.status == "completed"
    with factory.begin(SCOPE, "read") as uow:
        revision = uow.engineering.resolve_revision(_revision_ref(result.result["revision_ref"]))
        assert revision.schema_version == 2
        assert len(revision.sources) == len(revision.claims) == len(revision.evidence_links) == 1
        assert revision.sources[0].source_id == "source-1"
        assert revision.claims[0].statement_digest.hex == claim["statement_digest"]["hex"]
        assert revision.evidence_links[0].claim_id == "claim-1"
        assert revision.payload.value == {"statement": "captured"}
        uow.commit()


def test_interface2_rejects_v1_shape_and_missing_published_method(environment):
    library, _factory, usecases = environment
    with pytest.raises(ApplicationError) as old_shape:
        usecases.create({"kind": "evidence", "initial": _payload(), "schema_version": 1},
                        _context("old-interface-shape"))
    assert old_shape.value.code == "INVALID_INPUT"

    method_ref = {"method_id": "method-1", "release_version": "1.0.0", "schema_version": 1,
                  "snapshot_digest": {"algorithm": "sha256", "hex": "a" * 64}}
    missing_method_payload = {
        "media_type": "application/json", "schema_id": "urn:test:method-output",
        "content_kind": "method_content",
        "inline_value": {
            "schema_ref": {"method_ref": method_ref,
                            "logical_path": "schemas/output.json", "resource_digest": {"algorithm": "sha256", "hex": "b" * 64},
                            "resource_id": "missing-document-schema"},
            "value": {"answer": "x"}, "rendered_body_ref": None,
        },
    }
    missing = usecases.create(
        {"kind": "evidence", "initial": missing_method_payload,
         **_interface2_fields(method_refs=[method_ref])},
        _context("method-without-resource"),
    )
    assert missing.status == "rejected"
    assert missing.result == {"code": "MATERIAL_METHOD_SNAPSHOT_NOT_FOUND"}
    assert _count(library, "eng_artifacts") == 0
    assert _count(library, "eng_artifact_revisions") == 0
    assert _count(library, "eng_commands") == 1


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (("generation_origin", {"provider": "generator", "trace_id": "trace-1",
                             "execution_id": None, "generator_version": "v1"},
      "GENERATION_ORIGIN_UNAVAILABLE"),
     ("sources", [{"source_id": "source-1", "kind": "document",
                    "locator": {"kind": "document", "provider": "external", "conversation_id": None,
                                "message_id": None, "repository_id": None, "path": None,
                                "document_id": "doc-1", "artifact_ref": None, "observation_id": None},
                    "capture": {"kind": "immutable_version", "upstream_version": "version-1",
                                "content_digest": {"algorithm": "sha256", "hex": "c" * 64}},
                    "captured_at": RECEIVED_AT,
                    "captured_by": {"actor_id": ACTOR.actor_id, "actor_kind": ACTOR.actor_kind,
                                    "issuer": ACTOR.issuer},
                    "media_type": "application/json", "byte_length": 12, "original_url": None}],
      "SOURCE_VERSION_UNAVAILABLE")),
)
def test_unavailable_authorities_fail_closed_and_do_not_create_material_facts(
    environment, field, value, expected,
):
    library, _factory, usecases = environment
    unavailable = usecases.create(
        {"kind": "evidence", "initial": _payload(), **_interface2_fields(**{field: value})},
        _context(f"unavailable-{field}"),
    )
    assert unavailable.status == "rejected"
    assert unavailable.result == {"code": expected}
    assert _count(library, "eng_artifacts") == 0
    assert _count(library, "eng_artifact_revisions") == 0
    assert _count(library, "eng_commands") == 1


def test_material_write_failure_rolls_back_reserved_command_and_reopens_empty(tmp_path: Path, monkeypatch):
    path = tmp_path / "material-command-rollback.sqlite"
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    context = _context("material-rollback")
    usecases = ArtifactUseCases(SQLiteUoWFactory(library), SyntheticAccess())

    def fail_append(self, revision, *, expected_version):
        self.access.require_write()
        raise ApplicationError("MATERIAL_STORAGE_FAILURE", retry="reconcile")

    monkeypatch.setattr(artifact_repository.SQLiteArtifactRepository, "append_revision", fail_append)
    try:
        with pytest.raises(ApplicationError) as failed:
            usecases.create(
                {"kind": "evidence", "initial": _payload(), **_interface2_fields()}, context,
            )
        assert failed.value.code == "MATERIAL_STORAGE_FAILURE"
        assert _count(library, "eng_artifacts") == 0
        assert _count(library, "eng_artifact_revisions") == 0
        assert _count(library, "eng_commands") == 0
    finally:
        library.close()

    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        with SQLiteUoWFactory(reopened).begin(SCOPE, "read") as uow:
            assert uow.commands.get(context.key) is None
            assert uow._access.execute("SELECT COUNT(*) FROM eng_artifacts").fetchone() == (0,)
            assert uow._access.execute("SELECT COUNT(*) FROM eng_artifact_revisions").fetchone() == (0,)
            uow.commit()
    finally:
        reopened.close()


def test_interface2_usecases_refuse_old_schema_without_falling_back(tmp_path: Path):
    path = tmp_path / "material-old-schema.sqlite"
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=5)
    try:
        usecases = ArtifactUseCases(SQLiteUoWFactory(library), SyntheticAccess())
        with pytest.raises(ApplicationError) as unavailable:
            usecases.create(
                {"kind": "evidence", "initial": _payload(), **_interface2_fields()},
                _context("interface2-old-schema"),
            )
        assert unavailable.value.code == "MATERIAL_SCHEMA_REQUIRED"
        assert _count(library, "eng_artifacts") == 0
        assert _count(library, "eng_artifact_revisions") == 0
        assert _count(library, "eng_commands") == 0
    finally:
        library.close()


def _revision_ref(value: dict):
    from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
    from ordessa_engineering.domain.common.models.values import (Digest)
    return ArtifactRevisionRef(value["realm_id"], value["project_id"], value["artifact_id"],
                               value["revision_id"], Digest(**value["digest"]))
