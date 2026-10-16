"""Synthetic DTO seam tests, without a database or a claimed host catalog."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

from ordessa_engineering.methods.definitions.models import StoredProgram, CompiledProgram, ProgramBindings, StoredSourceBundle, StoredSnapshot, CapturedResource, SourceBundle, ResourceBytes

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.persistence.sqlite.snapshot_codec import (
    decode_snapshot, encode_snapshot,
)
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.methods.definitions.models import (
    BlobRef, MethodIdentity, MethodSnapshot, ResourceSnapshot,
)
from ordessa_engineering.methods.definitions.models.compiled import StoredProgram
from ordessa_engineering.methods.compilation.encoding import program_to_canonical, stored_program_from_canonical


def _domain_digest(kind, payload):
    # Independent specification formula, without calling production method_digest.
    return hashlib.sha256(
        ("ordessa/" + kind + "/v1\n").encode("utf-8") + canonical_bytes(payload),
    ).hexdigest()


@pytest.fixture
def snapshot():
    raw = "来源: 保留 e\u0301 与 é\n".encode("utf-8")
    resource_digest = hashlib.sha256(raw).hexdigest()
    blob = BlobRef(resource_digest, len(raw), "application/yaml", "fixture:workflow")
    resource = ResourceSnapshot("workflow.main", "workflow.yaml", blob)
    manifest = BlobRef(hashlib.sha256(b"synthetic manifest").hexdigest(), 18,
                       "application/yaml", "fixture:manifest")
    compiler = "ordessa.methods.test-v1"
    workflow = {"schema_version": 1, "entry": "done", "steps": [
        {"id": "done", "kind": "stop", "outcome": "finished"},
    ], "annotation": ["来源", "e\u0301", "é"]}
    program = {
        "schema_version": 1, "compiler_version": compiler, "workflow": deepcopy(workflow),
        "documents": [{"document_type": "proposal", "value_schema": {"type": "object"}}],
        "standards": [{"schema_version": 1, "purpose": "fixture", "criteria": []}],
        "decision_templates": [{"schema_version": 1, "questions": []}],
        "skill_resources": [{"resource_id": "workflow.main", "sha256": resource_digest,
                             "kind": "workflow"}],
        "capability_bindings": [{"capability_id": "fixture.check", "kind": "check",
                                 "interface_version": "1.0.0", "contract_digest": "a" * 64}],
    }
    plan = _domain_digest("compiled-method-program", program)
    digest = _domain_digest("method-snapshot", {
        "schema_version": 1, "method_id": "test.method", "release_version": "1.0.0",
        "manifest_sha256": manifest.digest,
        "resource_digests": [{"id": resource.resource_id, "sha256": resource.digest}],
        "required_capabilities": program["capability_bindings"],
        "compiler_version": compiler, "compiled_plan_digest": {"algorithm": "sha256", "hex": plan},
    })
    return StoredSnapshot(StoredSourceBundle(MethodIdentity("test.method", "1.0.0", 1), manifest, (resource,)),
        stored_program_from_canonical(program), digest)


def _wire(snapshot):
    return decode_json(encode_snapshot(snapshot))


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _set(value, path, replacement):
    _at(value, path[:-1])[path[-1]] = replacement


def _rehash_wire(wire):
    s = wire["snapshot"]
    program = s["compiled_plan"]["program"]
    plan_digest = _domain_digest("compiled-method-program", program)
    s["compiled_plan"]["plan_digest"] = plan_digest
    s["compiled_plan_digest"] = plan_digest
    s["snapshot_digest"] = _domain_digest("method-snapshot", {
        "schema_version": s["identity"]["schema_version"], "method_id": s["identity"]["method_id"],
        "release_version": s["identity"]["release_version"], "manifest_sha256": s["manifest_ref"]["digest"],
        "resource_digests": [{"id": item["resource_id"], "sha256": item["digest"]}
                             for item in sorted(s["resources"], key=lambda item: item["resource_id"])],
        "required_capabilities": program["capability_bindings"], "compiler_version": s["compiler_version"],
        "compiled_plan_digest": {"algorithm": "sha256", "hex": plan_digest},
    })


def _assert_invalid(call):
    with pytest.raises(MethodFailure) as caught:
        call()
    assert caught.value.error.code == "SNAPSHOT_CODEC_INVALID"
    assert caught.value.error.message == "method snapshot encoding or identity is invalid"
    assert caught.value.error.path is None
    assert caught.value.error.resource_id is None


def test_roundtrip_canonical_snake_case_and_independent_hashes(snapshot):
    raw = encode_snapshot(snapshot)
    wire = decode_json(raw)
    assert set(wire) == {"codec_version", "snapshot"}
    assert wire["codec_version"] == "engineering-method-snapshot/1"
    assert raw == canonical_bytes(wire)
    assert decode_snapshot(raw) == snapshot
    assert encode_snapshot(decode_snapshot(raw)) == raw
    assert b"\\u6765" not in raw
    assert "e\u0301".encode() in raw and "é".encode() in raw
    assert program_to_canonical(decode_snapshot(raw).program)["workflow"]["annotation"] == ["来源", "e\u0301", "é"]


def test_decodes_and_nested_projections_are_detached(snapshot):
    raw = encode_snapshot(snapshot)
    first, second = decode_snapshot(raw), decode_snapshot(raw)
    first_workflow = program_to_canonical(first.program)["workflow"]
    first_documents = program_to_canonical(first.program)["documents"]
    first_workflow["steps"][0]["outcome"] = "changed"
    first_documents[0]["value_schema"]["type"] = "changed"
    assert second == snapshot
    assert program_to_canonical(first.program)["workflow"]["steps"][0]["outcome"] == "finished"
    assert program_to_canonical(first.program)["documents"][0]["value_schema"]["type"] == "object"
    program_to_canonical(snapshot.program)["workflow"]["entry"] = "mutated after encode"
    assert encode_snapshot(second) == raw


@pytest.mark.parametrize("path", [
    (), ("snapshot",), ("snapshot", "identity"), ("snapshot", "manifest_ref"),
    ("snapshot", "resources", 0), ("snapshot", "resources", 0, "blob_ref"),
    ("snapshot", "compiled_plan"), ("snapshot", "compiled_plan", "program"),
    ("snapshot", "compiled_plan", "program", "capability_bindings", 0),
])
@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_closed_envelope_and_nested_contracts(snapshot, path, mutation):
    wire = _wire(snapshot)
    target = _at(wire, path)
    if mutation == "unknown":
        target["unregistered_secret_field"] = "sensitive body must not leak"
    else:
        del target[next(iter(target))]
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


@pytest.mark.parametrize(("path", "bad"), [
    (("codec_version",), "engineering-method-snapshot/2"),
    (("snapshot", "engine_contract_version"), "ordessa.methods/v2"),
    (("snapshot", "identity", "schema_version"), True),
    (("snapshot", "identity", "schema_version"), 0),
    (("snapshot", "identity", "method_id"), ""),
    (("snapshot", "identity", "release_version"), "   "),
    (("snapshot", "manifest_ref", "storage_object_id"), ""),
    (("snapshot", "manifest_ref", "byte_length"), False),
    (("snapshot", "manifest_ref", "media_type"), "application/json"),
    (("snapshot", "resources", 0, "byte_length"), -1),
    (("snapshot", "resources", 0, "byte_length"), True),
    (("snapshot", "resources", 0, "digest"), "A" * 64),
    (("snapshot", "manifest_ref", "digest"), "sha256:" + "a" * 64),
    (("snapshot", "snapshot_digest"), "a" * 63),
    (("snapshot", "compiled_plan", "plan_digest"), "a" * 64),
    (("snapshot", "compiled_plan_digest"), "b" * 64),
    (("snapshot", "compiled_plan", "compiler_version"), "other-compiler"),
    (("snapshot", "compiled_plan", "program", "schema_version"), True),
    (("snapshot", "compiled_plan", "program", "compiler_version"), "other-compiler"),
    (("snapshot", "resources", 0, "blob_ref", "digest"), "b" * 64),
    (("snapshot", "resources", 0, "blob_ref", "byte_length"), 0),
    (("snapshot", "resources", 0, "blob_ref", "media_type"), "text/plain"),
    (("snapshot", "compiled_plan", "program", "capability_bindings", 0, "kind"), "provider"),
    (("snapshot", "compiled_plan", "program", "capability_bindings", 0, "interface_version"), ""),
    (("snapshot", "compiled_plan", "program", "capability_bindings", 0, "contract_digest"), "X" * 64),
])
def test_invalid_scalar_metadata_or_identity(snapshot, path, bad):
    wire = _wire(snapshot)
    _set(wire, path, bad)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/escape", "a\\b",
                                  "./workflow", "a//b", "https://example.invalid/a", "e\u0301.yaml"])
def test_unsafe_logical_path(snapshot, path):
    wire = _wire(snapshot)
    wire["snapshot"]["resources"][0]["logical_path"] = path
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


@pytest.mark.parametrize("collision", ["id", "path", "casefold"])
def test_duplicate_resource_identity_or_path(snapshot, collision):
    wire = _wire(snapshot)
    second = deepcopy(wire["snapshot"]["resources"][0])
    if collision == "id":
        second["logical_path"] = "other.yaml"
    else:
        second["resource_id"] = "workflow.other"
        if collision == "casefold":
            second["logical_path"] = "WORKFLOW.YAML"
    wire["snapshot"]["resources"].append(second)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


@pytest.mark.parametrize("projection", ["workflow", "document_specs", "standard_specs",
                                       "decision_specs", "skill_snapshots"])
def test_mutable_projection_drift_rejected_on_encode(snapshot, projection):
    before = encode_snapshot(snapshot)
    fields = {
        "workflow": "workflow", "document_specs": "documents",
        "standard_specs": "standards", "decision_specs": "decision_templates",
        "skill_snapshots": "skill_resources",
    }
    target = program_to_canonical(snapshot.program)[fields[projection]]
    if projection == "workflow":
        target["entry"] = "not the frozen program"
    else:
        target[0]["drift"] = "not the frozen program"
    assert encode_snapshot(snapshot) == before
    assert program_to_canonical(snapshot.program)[fields[projection]] != target
    wire = decode_json(before)
    wire["snapshot"][projection] = target if projection == "workflow" else list(target)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


def test_program_digest_is_recomputed(snapshot):
    projection = program_to_canonical(snapshot.program)
    projection["workflow"]["entry"] = "changed"
    assert program_to_canonical(snapshot.program)["workflow"]["entry"] == "done"
    wire = _wire(snapshot)
    wire["snapshot"]["compiled_plan"]["program"]["workflow"]["entry"] = "changed"
    wire["snapshot"]["workflow"]["entry"] = "changed"
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


def test_snapshot_domain_digest_is_recomputed(snapshot):
    changed = replace(snapshot, source_bundle=replace(snapshot.source_bundle, identity=replace(snapshot.identity, method_id="other.method")))
    _assert_invalid(lambda: encode_snapshot(changed))


@pytest.mark.parametrize("raw", [b"not JSON", b"\xff", b'{"codec_version":1,"codec_version":2}',
                                 b'{"snapshot":NaN}', b'[' * 1100 + b'0' + b']' * 1100])
def test_parser_errors_are_bounded(snapshot, raw):
    _assert_invalid(lambda: decode_snapshot(raw))


def test_noncanonical_encoding_and_json_numeric_values_rejected(snapshot):
    wire = _wire(snapshot)
    _assert_invalid(lambda: decode_snapshot(json.dumps(wire, ensure_ascii=False).encode()))
    for bad in (1.5, 2**63):
        wire = _wire(snapshot)
        wire["snapshot"]["workflow"]["annotation"] = bad
        raw = json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode()
        _assert_invalid(lambda: decode_snapshot(raw))


def test_encode_rejects_shape_compatible_foreign_dto_and_wrong_containers(snapshot):
    _assert_invalid(lambda: encode_snapshot(replace(snapshot, source_bundle=replace(snapshot.source_bundle, manifest_ref={
        "digest": "a" * 64, "byte_length": 0, "media_type": "application/yaml",
        "storage_object_id": "fixture:foreign",
    }))))
    with pytest.raises(TypeError):
        replace(snapshot.source_bundle, resources=list(snapshot.resources))
    _assert_invalid(lambda: decode_snapshot(encode_snapshot(snapshot).decode()))


def test_caller_cannot_forge_snapshot_digest_to_cover_projection_drift(snapshot):
    # Rehashing the frozen program and snapshot still cannot validate a stale
    # separately stored projection. This exercises consistency beyond hashes.
    wire = _wire(snapshot)
    program = wire["snapshot"]["compiled_plan"]["program"]
    program["documents"][0]["document_type"] = "changed"
    _rehash_wire(wire)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


@pytest.mark.parametrize(("field", "bad"), [("kind", "provider"), ("interface_version", ""),
                                           ("contract_digest", "A" * 64)])
def test_capability_shape_rejected_even_with_balanced_digests(snapshot, field, bad):
    wire = _wire(snapshot)
    wire["snapshot"]["compiled_plan"]["program"]["capability_bindings"][0][field] = bad
    _rehash_wire(wire)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


def test_duplicate_capability_rejected_even_with_balanced_digests(snapshot):
    wire = _wire(snapshot)
    bindings = wire["snapshot"]["compiled_plan"]["program"]["capability_bindings"]
    bindings.append(deepcopy(bindings[0]))
    _rehash_wire(wire)
    _assert_invalid(lambda: decode_snapshot(canonical_bytes(wire)))


def test_historical_original_fixture_bytes_stay_exact(snapshot):
    # SHA captured independently from the pre-authority-change dataclasses/asdict
    # and this unchanged original fixture; not generated from the new model.
    raw = encode_snapshot(snapshot)
    assert len(raw) == 2367
    assert hashlib.sha256(raw).hexdigest() == "4493b290d42b298be1e16b53a14a3225cee40bef084d4a414499ad524fd24e98"
    assert encode_snapshot(decode_snapshot(raw)) == raw
