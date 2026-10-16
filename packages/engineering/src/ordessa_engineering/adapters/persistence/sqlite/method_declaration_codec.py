"""Versioned source-only method declaration envelope for the original snapshot table."""
from __future__ import annotations

from dataclasses import asdict
import re

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.definitions.models import (
    BlobRef, MethodIdentity, MethodRef, ResourceSnapshot, StoredSourceBundle,
)
from ordessa_engineering.methods.validation.references import validate_logical_path

_VERSION = "engineering-method-declaration/1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _invalid():
    return MethodFailure(MethodError(
        "METHOD_DECLARATION_CODEC_INVALID",
        "stored declaration envelope is invalid",
    ))


def _text(value):
    if type(value) is not str or not value:
        raise _invalid()
    return value


def _sha(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise _invalid()
    return value


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise _invalid()
    return value


def _object(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise _invalid()
    return value


def _decode(raw: bytes):
    envelope = _object(decode_json(raw), {"codec_version", "method_ref", "source_bundle"})
    if envelope["codec_version"] != _VERSION:
        raise _invalid()
    ref_value = _object(envelope["method_ref"], {
        "method_id", "release_version", "schema_version", "snapshot_digest",
    })
    ref = MethodRef(
        _text(ref_value["method_id"]), _text(ref_value["release_version"]),
        _integer(ref_value["schema_version"], 1), _sha(ref_value["snapshot_digest"]),
    )
    if ref.schema_version != 2:
        raise _invalid()
    source = _object(envelope["source_bundle"], {
        "identity", "manifest_path", "manifest_ref", "resources",
    })
    manifest_path = validate_logical_path(_text(source["manifest_path"]))
    identity_value = _object(source["identity"], {"method_id", "release_version", "schema_version"})
    identity = MethodIdentity(
        _text(identity_value["method_id"]), _text(identity_value["release_version"]),
        _integer(identity_value["schema_version"], 1),
    )
    if (identity.method_id, identity.release_version, identity.schema_version) != (
            ref.method_id, ref.release_version, ref.schema_version):
        raise _invalid()
    manifest_value = _object(source["manifest_ref"], {
        "digest", "byte_length", "media_type", "storage_object_id",
    })
    manifest_ref = BlobRef(
        _sha(manifest_value["digest"]), _integer(manifest_value["byte_length"]),
        _text(manifest_value["media_type"]), _text(manifest_value["storage_object_id"]),
    )
    if (manifest_ref.media_type not in {"application/yaml", "application/json"}
            or len(manifest_ref.media_type) > 256):
        raise _invalid()
    if type(source["resources"]) is not list or len(source["resources"]) > 128:
        raise _invalid()
    resources = []
    ids, paths = set(), set()
    for item in source["resources"]:
        item = _object(item, {"resource_id", "logical_path", "blob_ref"})
        resource_id = _text(item["resource_id"])
        path = validate_logical_path(_text(item["logical_path"]))
        blob_value = _object(item["blob_ref"], {
            "digest", "byte_length", "media_type", "storage_object_id",
        })
        blob = BlobRef(
            _sha(blob_value["digest"]), _integer(blob_value["byte_length"]),
            _text(blob_value["media_type"]), _text(blob_value["storage_object_id"]),
        )
        if (resource_id in ids or path.casefold() in paths
                or len(blob.media_type) > 256
                or blob.byte_length > 2 * 1024 * 1024):
            raise _invalid()
        ids.add(resource_id)
        paths.add(path.casefold())
        resources.append(ResourceSnapshot(resource_id, path, blob))
    if len(resources) == 0 or manifest_ref.byte_length > 256 * 1024:
        raise _invalid()
    if sum(item.byte_length for item in resources) + manifest_ref.byte_length > 16 * 1024 * 1024:
        raise _invalid()
    bundle = StoredSourceBundle(identity, manifest_ref, tuple(resources))
    return ref, manifest_path, bundle


def encode_declaration(ref: MethodRef, manifest_path: str,
                       source_bundle: StoredSourceBundle) -> bytes:
    try:
        if (type(ref) is not MethodRef or ref.schema_version != 2
                or type(source_bundle) is not StoredSourceBundle
                or validate_logical_path(manifest_path) != manifest_path
                or (source_bundle.identity.method_id, source_bundle.identity.release_version,
                    source_bundle.identity.schema_version) != (
                    ref.method_id, ref.release_version, ref.schema_version)):
            raise _invalid()
        raw = canonical_bytes({
            "codec_version": _VERSION,
            "method_ref": asdict(ref),
            "source_bundle": {
                "identity": asdict(source_bundle.identity),
                "manifest_path": manifest_path,
                "manifest_ref": asdict(source_bundle.manifest_ref),
                "resources": [{
                    "resource_id": item.resource_id,
                    "logical_path": item.logical_path,
                    "blob_ref": asdict(item.blob_ref),
                } for item in source_bundle.resources],
            },
        })
        if _decode(raw) != (ref, manifest_path, source_bundle):
            raise _invalid()
        return raw
    except (MethodFailure, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise _invalid() from None


def decode_declaration(raw: bytes) -> tuple[MethodRef, str, StoredSourceBundle]:
    try:
        if type(raw) is not bytes or len(raw) > 16 * 1024 * 1024:
            raise _invalid()
        envelope = decode_json(raw)
        if canonical_bytes(envelope) != raw:
            raise _invalid()
        return _decode(raw)
    except (MethodFailure, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise _invalid() from None


__all__ = ["encode_declaration", "decode_declaration"]
