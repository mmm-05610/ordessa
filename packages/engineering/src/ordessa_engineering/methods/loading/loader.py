"""Bounded, strict loader for immutable method source bundles."""
from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path
from typing import Any

from ..definitions.errors import MethodError, MethodFailure, MethodResult
from ..definitions.models import (
    LoadLimits, LoadedMethod, MethodSource, ResourceBytes,
    CapturedResource, SourceBundle, VerificationInputs, ParsedContent, ParsedResource, ParsedSourceBundle,
)
from ..validation.structure import (
    validate_entry_structure, validate_manifest_structure,
    validate_requirement_structure, validate_requires_structure,
    validate_resource_fields, validate_resource_values,
)
from .parsing import parse_document
from ..validation.references import validate_logical_path
from ..definitions.models.identity import method_digest
from ..definitions.contracts.sources import ResourceReader


def _valid_json_object(value: Any, code: str, message: str, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MethodFailure(MethodError(code, message, path=path))
    return value


def _read(reader: ResourceReader, source: MethodSource, path: str, max_bytes: int) -> bytes:
    logical = validate_logical_path(path)
    try:
        raw = reader.read(source, logical, max_bytes)
        if not isinstance(raw, bytes):
            raise MethodFailure(MethodError("RESOURCE_READER_INVALID", "resource reader must return immutable bytes", path=logical))
        if len(raw) > max_bytes:
            raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "resource exceeds its byte limit", path=logical))
        return raw
    except MethodFailure:
        raise
    except OSError as exc:
        raise MethodFailure(MethodError("RESOURCE_READ_FAILED", "method resource could not be read", path=logical)) from exc


class _ReadBudget:
    """Account every captured input, including manifest and build evidence."""

    def __init__(self, maximum: int):
        self.maximum = maximum
        self.used = 0

    def account(self, raw: bytes, path: str) -> None:
        self.used += len(raw)
        if self.used > self.maximum:
            raise MethodFailure(MethodError("RESOURCE_TOTAL_TOO_LARGE", "method bundle exceeds its byte limit", path=path))


def _load_optional_lock(reader: ResourceReader, source: MethodSource, manifest_bytes: bytes,
                        manifest: dict[str, Any], resources: dict[str, CapturedResource], limits: LoadLimits, budget: _ReadBudget
                        ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bytes | None, bytes | None]:
    try:
        lock_bytes = _read(reader, source, "bundle-lock.json", limits.resource_bytes)
    except MethodFailure as exc:
        if exc.error.code == "RESOURCE_NOT_FOUND":
            return None, None, None, None
        raise
    budget.account(lock_bytes, "bundle-lock.json")
    lock = _valid_json_object(parse_document(lock_bytes, "application/json", "bundle-lock.json", depth_limit=limits.structure_depth),
                              "BUNDLE_LOCK_INVALID", "bundle lock must be an object", "bundle-lock.json")
    actual_manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if lock.get("manifest_sha256") != actual_manifest_digest:
        raise MethodFailure(MethodError("MANIFEST_DIGEST_MISMATCH", "bundle lock does not match method.yaml", path="method.yaml"))
    expected_resources = [{"id": item["id"], "sha256": item["sha256"]} for item in sorted(manifest["resources"], key=lambda row: row["id"])]
    if lock.get("snapshot_payload", {}).get("resource_digests") != expected_resources:
        raise MethodFailure(MethodError("BUNDLE_LOCK_RESOURCE_MISMATCH", "bundle lock resource list differs from manifest", path="bundle-lock.json"))
    if lock.get("snapshot_payload", {}).get("manifest_sha256") != actual_manifest_digest:
        raise MethodFailure(MethodError("BUNDLE_LOCK_MANIFEST_MISMATCH", "bundle lock snapshot does not bind method.yaml", path="bundle-lock.json"))
    if lock.get("snapshot_payload", {}).get("required_capabilities") != manifest["requires"]:
        raise MethodFailure(MethodError("BUNDLE_LOCK_CAPABILITY_MISMATCH", "bundle lock capabilities differ from manifest", path="bundle-lock.json"))
    expected_snapshot = lock.get("method_ref", {}).get("snapshot_digest", {}).get("hex")
    if expected_snapshot != method_digest("method-snapshot", lock.get("snapshot_payload")):
        raise MethodFailure(MethodError("METHOD_SNAPSHOT_MISMATCH", "bundle lock snapshot digest is invalid", path="bundle-lock.json"))

    golden: dict[str, Any] | None = None
    golden_bytes: bytes | None = None
    plan_path = lock.get("compiled_plan_path")
    plan_digest = lock.get("compiled_plan_digest")
    if plan_path is not None:
        logical_plan_path = validate_logical_path(plan_path)
        golden_bytes = _read(reader, source, logical_plan_path, limits.resource_bytes)
        budget.account(golden_bytes, logical_plan_path)
        golden = _valid_json_object(parse_document(golden_bytes, "application/json", logical_plan_path, depth_limit=limits.structure_depth),
                                    "COMPILED_GOLDEN_INVALID", "compiled plan golden must be an object", logical_plan_path)
        if not isinstance(plan_digest, dict) or plan_digest.get("hex") != method_digest("compiled-method-program", golden):
            raise MethodFailure(MethodError("COMPILED_GOLDEN_DIGEST_MISMATCH", "compiled plan golden digest is invalid", path=logical_plan_path))
    return lock, golden, lock_bytes, golden_bytes


def load_method(source: MethodSource, reader: ResourceReader | None = None,
                limits: LoadLimits | None = None) -> MethodResult[LoadedMethod]:
    if reader is None:
        return MethodResult.failure(MethodError("RESOURCE_READER_UNAVAILABLE", "method loading requires an injected resource reader"))
    limits = limits or LoadLimits()
    try:
        if any(type(getattr(limits, name)) is not int or getattr(limits, name) <= 0
               for name in limits.__dataclass_fields__):
            raise MethodFailure(MethodError("LOAD_LIMITS_INVALID", "all load limits must be positive integers"))
        budget = _ReadBudget(limits.total_bytes)
        manifest_path = validate_logical_path(source.manifest_path)
        manifest_bytes = _read(reader, source, manifest_path, limits.manifest_bytes)
        budget.account(manifest_bytes, manifest_path)
        manifest = validate_manifest_structure(parse_document(manifest_bytes, "application/yaml", manifest_path,
                                                     depth_limit=limits.structure_depth))
        declarations = manifest.get("resources")
        if not isinstance(declarations, list) or not declarations or len(declarations) > limits.total_resources:
            raise MethodFailure(MethodError("RESOURCE_COUNT_INVALID", "method resource count is empty or exceeds its limit", path=manifest_path, pointer="/resources"))
        ids: set[str] = set()
        paths: dict[str, str] = {}
        loaded: dict[str, CapturedResource] = {}
        parsed_resources = {}
        for index, declaration in enumerate(declarations):
            pointer = f"/resources/{index}"
            validate_resource_fields(declaration, manifest_path=manifest_path, pointer=pointer)
            resource_id = declaration.get("id")
            path = validate_logical_path(declaration.get("path"))
            media_type = declaration.get("media_type")
            digest = declaration.get("sha256")
            if not isinstance(resource_id, str) or not resource_id or resource_id in ids:
                raise MethodFailure(MethodError("DUPLICATE_RESOURCE_ID", "resource ID is invalid or duplicated", path=manifest_path, pointer=f"{pointer}/id"))
            validate_resource_values(declaration, manifest_path=manifest_path, pointer=pointer)
            path_key = unicodedata.normalize("NFC", path).casefold()
            if path_key in paths:
                raise MethodFailure(MethodError("RESOURCE_PATH_COLLISION", f"path collides with resource {paths[path_key]}", resource_id=resource_id, path=path))
            ids.add(resource_id)
            paths[path_key] = resource_id
            raw = _read(reader, source, path, limits.resource_bytes)
            budget.account(raw, path)
            actual_digest = hashlib.sha256(raw).hexdigest()
            if actual_digest != digest:
                raise MethodFailure(MethodError("RESOURCE_DIGEST_MISMATCH", "resource bytes do not match manifest digest", resource_id=resource_id, path=path))
            captured = ResourceBytes(path, media_type, raw)
            value = parse_document(raw, media_type, path, depth_limit=limits.structure_depth)
            loaded[resource_id] = CapturedResource(resource_id, captured)
            parsed_resources[resource_id] = ParsedResource(resource_id, ParsedContent(captured, value))

        entry = manifest.get("entry")
        validate_entry_structure(entry, manifest_path=manifest_path)
        entry_resource = loaded.get(entry["resource"])
        if entry_resource is None or next(item for item in declarations if item["id"] == entry["resource"]).get("kind") != "workflow":
            raise MethodFailure(MethodError("MANIFEST_ENTRY_INVALID", "manifest entry must reference a declared workflow resource", resource_id=entry.get("resource"), path=manifest_path, pointer="/entry/resource"))

        capability_ids: set[str] = set()
        requires = manifest.get("requires")
        validate_requires_structure(requires, manifest_path=manifest_path)
        for index, requirement in enumerate(requires):
            validate_requirement_structure(requirement, manifest_path=manifest_path, pointer=f"/requires/{index}")
            capability_id = requirement.get("capability_id")
            if not isinstance(capability_id, str) or not capability_id or capability_id in capability_ids:
                raise MethodFailure(MethodError("DUPLICATE_CAPABILITY", "capability ID is invalid or duplicated", path=manifest_path, pointer=f"/requires/{index}/capability_id"))
            capability_ids.add(capability_id)

        bundle_lock, compiled_golden, bundle_lock_bytes, compiled_golden_bytes = _load_optional_lock(
            reader, source, manifest_bytes, manifest, loaded, limits, budget,
        )
        ordered_resources = tuple(loaded[key] for key in sorted(loaded))
        source_bundle = SourceBundle(ResourceBytes(manifest_path, "application/yaml", manifest_bytes), ordered_resources, limits)
        parsed_source = ParsedSourceBundle(source_bundle, ParsedContent(source_bundle.manifest_capture, manifest),
            tuple(parsed_resources[key] for key in sorted(parsed_resources)))
        verification = None if bundle_lock_bytes is None and compiled_golden_bytes is None else VerificationInputs(
            ParsedContent(ResourceBytes("bundle-lock.json", "application/json", bundle_lock_bytes), bundle_lock) if bundle_lock_bytes is not None else None,
            ParsedContent(ResourceBytes(bundle_lock["compiled_plan_path"], "application/json", compiled_golden_bytes), compiled_golden) if compiled_golden_bytes is not None else None,
        )
        return MethodResult.success(LoadedMethod(source, source_bundle, parsed_source, verification))
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, OSError, ValueError, TypeError, KeyError):
        return MethodResult.failure(MethodError("METHOD_LOAD_FAILED", "method bundle could not be loaded safely", path=source.manifest_path))
