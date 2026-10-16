"""Strict snapshot DTO codec; source bytes and host trust belong to the store."""
from __future__ import annotations

from dataclasses import asdict, fields
import re

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ....methods.definitions.models.identity import method_digest
from ....methods.compilation.encoding import (
    stored_program_from_canonical, program_to_canonical, program_plan_digest, program_encoding,
)
from ....methods.definitions.errors import MethodError, MethodFailure
from ....methods.definitions.models import (
    BlobRef, MethodIdentity, MethodSnapshot, ResourceSnapshot, StoredSourceBundle, StoredSnapshot,
)
from ....methods.definitions.models.compiled import StoredProgram
from ....methods.validation.references import validate_logical_path


_VERSION = "engineering-method-snapshot/1"
_SNAPSHOT_FIELDS = {"identity", "engine_contract_version", "manifest_ref", "resources", "workflow", "document_specs", "standard_specs", "decision_specs", "skill_snapshots", "compiler_version", "compiled_plan_digest", "compiled_plan", "snapshot_digest"}
_RESOURCE_FIELDS = {"resource_id", "logical_path", "media_type", "byte_length", "digest", "blob_ref"}
_COMPILED_FIELDS = {"compiler_version", "plan_digest", "program"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROGRAM_FIELDS = {
    "schema_version", "compiler_version", "workflow", "documents", "standards",
    "decision_templates", "skill_resources", "capability_bindings",
}
_PROJECTIONS = {
    "document_specs": "documents", "standard_specs": "standards",
    "decision_specs": "decision_templates", "skill_snapshots": "skill_resources",
}


def _invalid() -> MethodFailure:
    return MethodFailure(MethodError(
        "SNAPSHOT_CODEC_INVALID", "method snapshot encoding or identity is invalid",
    ))


def _object(value, expected=None):
    if type(value) is not dict or (expected is not None and set(value) != expected):
        raise _invalid()
    return value


def _dto_object(value, cls):
    return _object(value, {field.name for field in fields(cls)})


def _text(value):
    # Method/resource IDs have no additional regex in the current loader.
    if type(value) is not str or not value.strip():
        raise _invalid()
    return value


def _digest(value):
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _invalid()
    return value


def _integer(value, minimum):
    if type(value) is not int or value < minimum:
        raise _invalid()
    return value


def _objects(value):
    if type(value) is not list:
        raise _invalid()
    for item in value:
        _object(item)
    return value


def _blob(value):
    value = _dto_object(value, BlobRef)
    return BlobRef(
        _digest(value["digest"]), _integer(value["byte_length"], 0),
        _text(value["media_type"]), _text(value["storage_object_id"]),
    )


def _decode(envelope):
    envelope = _object(envelope, {"codec_version", "snapshot"})
    if envelope["codec_version"] != _VERSION:
        raise _invalid()
    value = _object(envelope["snapshot"], _SNAPSHOT_FIELDS)
    identity = _dto_object(value["identity"], MethodIdentity)
    identity = MethodIdentity(
        _text(identity["method_id"]), _text(identity["release_version"]),
        _integer(identity["schema_version"], 1),
    )
    if value["engine_contract_version"] != "ordessa.methods/v1":
        raise _invalid()
    manifest = _blob(value["manifest_ref"])
    if manifest.media_type != "application/yaml":
        raise _invalid()
    resources = []
    ids, paths = set(), set()
    for resource in _objects(value["resources"]):
        resource = _object(resource, _RESOURCE_FIELDS)
        resource_id = _text(resource["resource_id"])
        path = validate_logical_path(_text(resource["logical_path"]))
        # The loader rejects case-insensitive path collisions too.
        if resource_id in ids or path.casefold() in paths:
            raise _invalid()
        ids.add(resource_id)
        paths.add(path.casefold())
        blob = _blob(resource["blob_ref"])
        digest = _digest(resource["digest"])
        size = _integer(resource["byte_length"], 0)
        media_type = _text(resource["media_type"])
        if (blob.digest, blob.byte_length, blob.media_type) != (digest, size, media_type):
            raise _invalid()
        resources.append(ResourceSnapshot(resource_id, path, blob))

    compiled = _object(value["compiled_plan"], _COMPILED_FIELDS)
    compiler = _text(value["compiler_version"])
    plan_digest = _digest(value["compiled_plan_digest"])
    program = _object(compiled["program"])
    fields = _PROGRAM_FIELDS | ({"schema_resources"} if program.get("schema_version") == 2 else set())
    program = _object(program, fields)
    if (_integer(program["schema_version"], 1) not in (1, 2)
            or compiled["compiler_version"] != compiler
            or program["compiler_version"] != compiler
            or _digest(compiled["plan_digest"]) != plan_digest
            or method_digest("compiled-method-program", program) != plan_digest):
        raise _invalid()
    workflow = _object(value["workflow"])
    if workflow != _object(program["workflow"]):
        raise _invalid()
    projections = {}
    for snapshot_key, program_key in _PROJECTIONS.items():
        items = _objects(value[snapshot_key])
        if items != _objects(program[program_key]):
            raise _invalid()
        projections[snapshot_key] = tuple(items)
    capabilities = _objects(program["capability_bindings"])
    capability_ids = set()
    for capability in capabilities:
        _object(capability, {"capability_id", "kind", "interface_version", "contract_digest"})
        capability_id = _text(capability["capability_id"])
        if capability_id in capability_ids or capability["kind"] not in {"operation", "check"}:
            raise _invalid()
        capability_ids.add(capability_id)
        _text(capability["interface_version"])
        _digest(capability["contract_digest"])
    if [item["capability_id"] for item in capabilities] != sorted(capability_ids):
        raise _invalid()
    snapshot_digest = _digest(value["snapshot_digest"])
    expected_digest = method_digest("method-snapshot", {
        "schema_version": identity.schema_version,
        "method_id": identity.method_id,
        "release_version": identity.release_version,
        "manifest_sha256": manifest.digest,
        "resource_digests": [
            {"id": item.resource_id, "sha256": item.digest}
            for item in sorted(resources, key=lambda item: item.resource_id)
        ],
        "required_capabilities": capabilities,
        "compiler_version": compiler,
        "compiled_plan_digest": {"algorithm": "sha256", "hex": plan_digest},
    })
    if expected_digest != snapshot_digest:
        raise _invalid()
    return StoredSnapshot(StoredSourceBundle(identity, manifest, tuple(resources)), stored_program_from_canonical(program), snapshot_digest)


def encode_snapshot(snapshot: MethodSnapshot) -> bytes:
    """Encode a detached, internally consistent snapshot as canonical JSON."""
    try:
        if type(snapshot) not in (MethodSnapshot, StoredSnapshot):
            raise _invalid()
        if type(snapshot.source_bundle) is not StoredSourceBundle or type(snapshot.manifest_ref) is not BlobRef:
            raise _invalid()
        program = program_encoding(snapshot.program)
        canonical_program = program_to_canonical(program)
        value = {
            "identity": asdict(snapshot.identity), "engine_contract_version": snapshot.engine_contract_version,
            "manifest_ref": asdict(snapshot.manifest_ref),
            "resources": [{"resource_id": r.resource_id, "logical_path": r.logical_path, "media_type": r.media_type,
                "byte_length": r.byte_length, "digest": r.digest, "blob_ref": asdict(r.blob_ref)} for r in snapshot.resources],
            "workflow": canonical_program["workflow"],
            **{key: list(canonical_program[field]) for key, field in _PROJECTIONS.items()},
            "compiler_version": snapshot.compiler_version, "compiled_plan_digest": program_plan_digest(snapshot.program),
            "compiled_plan": {"compiler_version": program.compiler_version, "plan_digest": program_plan_digest(program), "program": canonical_program},
            "snapshot_digest": snapshot.snapshot_digest,
        }
        raw = canonical_bytes({"codec_version": _VERSION, "snapshot": value})
        _decode(decode_json(raw))
        return raw
    except (MethodFailure, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise _invalid() from None


def decode_snapshot(raw: bytes) -> StoredSnapshot:
    """Decode a lossless immutable stored representation; no source materialization or IO."""
    try:
        if type(raw) is not bytes:
            raise _invalid()
        envelope = decode_json(raw)
        if canonical_bytes(envelope) != raw:
            raise _invalid()
        return _decode(envelope)
    except (MethodFailure, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise _invalid() from None


__all__ = ["encode_snapshot", "decode_snapshot"]
