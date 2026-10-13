"""Reconstruct parsed projections from immutable captured source bytes."""
from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

from ..definitions.models.identity import method_digest
from ..definitions.errors import MethodError, MethodFailure
from ..definitions.models import (
    LoadedMethod, LoadLimits, MethodIdentity, ResourceBytes, SourceResourceView,
    SourceBundle, ParsedContent, ParsedResource, ParsedSourceBundle,
)
from ..validation.structure import (
    validate_manifest_structure,
    validate_resource_fields, validate_resource_values,
)
from .parsing import parse_document
from ..validation.references import validate_logical_path


def captured_manifest(manifest_capture: ResourceBytes, limits: LoadLimits = LoadLimits()) -> dict[str, Any]:
    """Pure bounded manifest reconstruction, shared by source and stored-blob loading."""
    if any(type(getattr(limits, name)) is not int or getattr(limits, name) <= 0
           for name in limits.__dataclass_fields__):
        raise MethodFailure(MethodError("LOAD_LIMITS_INVALID", "all load limits must be positive integers"))
    manifest_bytes = manifest_capture.data
    if not isinstance(manifest_bytes, bytes) or len(manifest_bytes) > limits.manifest_bytes:
        raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "captured manifest is invalid or exceeds its byte limit", path="method.yaml"))
    manifest = validate_manifest_structure(parse_document(
        manifest_bytes, "application/yaml", "method.yaml", depth_limit=limits.structure_depth,
    ))
    if len(manifest["resources"]) > limits.total_resources:
        raise MethodFailure(MethodError("RESOURCE_COUNT_INVALID", "captured resource count exceeds its limit", path="method.yaml"))
    return manifest


def parse_captured_resource(capture: ResourceBytes, limits: LoadLimits = LoadLimits()) -> Any:
    """Pure strict syntax checking at each captured-resource read boundary.

    The caller owns byte budgets and declaration checks at their existing stage;
    this helper preserves parser error order without reading another resource.
    """
    return parse_document(capture.data, capture.media_type, capture.logical_path,
                          depth_limit=limits.structure_depth)


def rebuild_source_bundle(bundle: SourceBundle) -> ParsedSourceBundle:
    """Parse the bundle's captured bytes and reject mutable projection drift."""
    limits = bundle.limits
    manifest_bytes = bundle.manifest_bytes
    manifest = captured_manifest(bundle.manifest_capture, limits)
    total = len(manifest_bytes)
    identity = MethodIdentity(manifest["method_id"], manifest["release_version"], manifest["schema_version"])

    captured_by_path: dict[str, ResourceBytes] = {}
    for original in bundle.resources:
        captured = original.captured
        if not isinstance(captured.data, bytes) or len(captured.data) > limits.resource_bytes:
            raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "captured resource is invalid or exceeds its byte limit", path=captured.logical_path))
        total += len(captured.data)
        if captured.logical_path in captured_by_path:
            raise MethodFailure(MethodError("CAPTURED_RESOURCE_PATH_DUPLICATE", "captured source contains duplicate resource paths", path=captured.logical_path))
        if hashlib.sha256(captured.data).hexdigest() != captured.digest:
            raise MethodFailure(MethodError("CAPTURED_RESOURCE_DIGEST_MISMATCH", "captured resource bytes do not match their digest", path=captured.logical_path))
        captured_by_path[captured.logical_path] = captured

    if total > limits.total_bytes:
        raise MethodFailure(MethodError("RESOURCE_TOTAL_TOO_LARGE", "captured bundle exceeds its byte limit"))
    resources: dict[str, ParsedResource] = {}
    seen_paths: dict[str, str] = {}
    for index, declaration in enumerate(manifest["resources"]):
        pointer = f"/resources/{index}"
        validate_resource_fields(declaration, manifest_path="method.yaml", pointer=pointer)
        resource_id = declaration.get("id")
        path = validate_logical_path(declaration.get("path"))
        media_type = declaration.get("media_type")
        expected_digest = declaration.get("sha256")
        validate_resource_values(declaration, manifest_path="method.yaml", pointer=pointer)
        if resource_id in resources:
            raise MethodFailure(MethodError("DUPLICATE_RESOURCE_ID", "resource ID is duplicated", path="method.yaml", pointer=f"{pointer}/id"))
        path_key = unicodedata.normalize("NFC", path).casefold()
        if path_key in seen_paths:
            raise MethodFailure(MethodError("RESOURCE_PATH_COLLISION", "resource paths collide", resource_id=resource_id, path=path))
        seen_paths[path_key] = resource_id
        captured = captured_by_path.get(path)
        if captured is None:
            raise MethodFailure(MethodError("CAPTURED_RESOURCE_MISSING", "manifest resource has no captured bytes", resource_id=resource_id, path=path))
        if captured.media_type != media_type or captured.digest != expected_digest:
            raise MethodFailure(MethodError("CAPTURED_RESOURCE_DECLARATION_MISMATCH", "captured bytes differ from manifest media type or digest", resource_id=resource_id, path=path))
        value = parse_captured_resource(captured, limits)
        resources[resource_id] = ParsedResource(resource_id, ParsedContent(captured, value))
    if set(captured_by_path) != {item["path"] for item in manifest["resources"]}:
        raise MethodFailure(MethodError("CAPTURED_RESOURCE_SET_MISMATCH", "captured resources do not exactly match the manifest"))
    if set(resources) != {item.resource_id for item in bundle.resources}:
        raise MethodFailure(MethodError("CAPTURED_RESOURCE_SET_MISMATCH", "captured resource ids do not match the manifest"))
    return ParsedSourceBundle(bundle, ParsedContent(bundle.manifest_capture, manifest),
                              tuple(resources[key] for key in sorted(resources)))


def verify_loaded_method(loaded: LoadedMethod) -> LoadedMethod:
    limits = loaded.source_bundle.limits
    all_bytes = [loaded.manifest_bytes, *(item.captured.data for item in loaded.source_bundle.resources)]
    for raw in (loaded.bundle_lock_bytes, loaded.compiled_golden_bytes):
        if raw is not None:
            if not isinstance(raw, bytes) or len(raw) > limits.resource_bytes:
                raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "captured build evidence exceeds its byte limit"))
            all_bytes.append(raw)
    if sum(len(raw) for raw in all_bytes) > limits.total_bytes:
        raise MethodFailure(MethodError("RESOURCE_TOTAL_TOO_LARGE", "captured bundle including build evidence exceeds its byte limit"))
    expected = rebuild_source_bundle(loaded.source_bundle)
    if loaded.parsed_source != expected:
        raise MethodFailure(MethodError("LOADED_PROJECTION_INVALID", "parsed source view differs from captured bytes"))
    manifest = expected.manifest
    digest = loaded.manifest_digest
    lock = None
    golden = None
    if loaded.bundle_lock_bytes is None:
        if loaded.bundle_lock is not None or loaded.compiled_golden is not None or loaded.compiled_golden_bytes is not None:
            raise MethodFailure(MethodError("LOADED_LOCK_PROJECTION_MUTATED", "lock projection has no captured source bytes"))
    else:
        lock = parse_document(loaded.bundle_lock_bytes, "application/json", "bundle-lock.json", depth_limit=limits.structure_depth)
        if not isinstance(lock, dict) or loaded.bundle_lock != lock:
            raise MethodFailure(MethodError("LOADED_LOCK_PROJECTION_MUTATED", "bundle lock projection differs from captured bytes", path="bundle-lock.json"))
        if lock.get("manifest_sha256") != digest:
            raise MethodFailure(MethodError("BUNDLE_LOCK_MANIFEST_MISMATCH", "captured bundle lock does not bind the manifest", path="bundle-lock.json"))
        expected_resources = [{"id": item["id"], "sha256": item["sha256"]}
                              for item in sorted(manifest["resources"], key=lambda row: row["id"])]
        payload = lock.get("snapshot_payload")
        if (not isinstance(payload, dict)
                or payload.get("resource_digests") != expected_resources
                or payload.get("manifest_sha256") != digest
                or payload.get("required_capabilities") != manifest["requires"]
                or lock.get("method_ref", {}).get("snapshot_digest", {}).get("hex") != method_digest("method-snapshot", payload)):
            raise MethodFailure(MethodError("BUNDLE_LOCK_INVALID", "captured bundle lock does not match the captured method", path="bundle-lock.json"))
        if loaded.compiled_golden_bytes is None:
            if loaded.compiled_golden is not None:
                raise MethodFailure(MethodError("LOADED_GOLDEN_PROJECTION_MUTATED", "golden projection has no captured bytes"))
        else:
            golden = parse_document(loaded.compiled_golden_bytes, "application/json", lock["compiled_plan_path"], depth_limit=limits.structure_depth)
            if not isinstance(golden, dict) or loaded.compiled_golden != golden:
                raise MethodFailure(MethodError("LOADED_GOLDEN_PROJECTION_MUTATED", "compiled golden projection differs from captured bytes", path=lock["compiled_plan_path"]))
            expected_golden = lock.get("compiled_plan_digest", {}).get("hex")
            if expected_golden != method_digest("compiled-method-program", golden):
                raise MethodFailure(MethodError("COMPILED_GOLDEN_DIGEST_MISMATCH", "captured compiled golden digest is invalid", path=lock["compiled_plan_path"]))

    return LoadedMethod(loaded.source, loaded.source_bundle, expected, loaded.verification)
