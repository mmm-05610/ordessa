"""Pure Profile value validation; opaque provider references stay unresolved."""
from __future__ import annotations

import json
from typing import Any, Mapping

from ordessa_execution_api.environment import EnvironmentId, IdentityMismatchError, SecretRef

from .schemas.profile_wire import LOCAL_ID, DIGEST

AGENT_CONTRACT_VERSION = "agent-assembly/1"
MAX_CONTENT_BYTES = 262144
MAX_CONTENT_DEPTH = 32


class ProfileValidationError(ValueError):
    code = "PROFILE_INVALID"


class ProfileRevisionConflict(IdentityMismatchError):
    code = "PROFILE_REVISION_CONFLICT"


class ProfileNotFound(LookupError):
    code = "PROFILE_NOT_FOUND"


def canonical(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProfileValidationError("manifest must contain finite JSON values") from None


def _safe_tree(value: Any, depth: int = 0) -> None:
    if depth > MAX_CONTENT_DEPTH:
        raise ProfileValidationError("manifest nesting exceeds limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProfileValidationError("JSON object keys must be strings")
            # Explicit credentials never belong in a Profile. Unknown leaf
            # schemas still need provider validation before any material use.
            if key == "secretRef":
                _secret_ref(item)
            if key.lower().replace('_', '').replace('-', '') in {
                'token', 'accesstoken', 'apikey', 'password', 'secret',
                'privatekey', 'authorization', 'credential', 'credentials',
            } and item is not None:
                if not isinstance(item, dict) or set(item) != {"secretRef"}:
                    raise ProfileValidationError("plaintext credentials are forbidden; use SecretRef")
                _secret_ref(item["secretRef"])
            _safe_tree(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _safe_tree(item, depth + 1)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ProfileValidationError("manifest must contain JSON values")


def _safe_typed_tree(value: Any, depth: int = 0) -> None:
    """Validate frozen model values without projecting them back to JSON dicts."""
    if depth > MAX_CONTENT_DEPTH:
        raise ProfileValidationError("manifest nesting exceeds limit")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProfileValidationError("JSON object keys must be strings")
            normalized = key.lower().replace('_', '').replace('-', '')
            if key == "secretRef":
                _secret_ref(item)
            if normalized in {
                'token', 'accesstoken', 'apikey', 'password', 'secret',
                'privatekey', 'authorization', 'credential', 'credentials',
            } and item is not None:
                if not isinstance(item, Mapping) or set(item) != {"secretRef"}:
                    raise ProfileValidationError("plaintext credentials are forbidden; use SecretRef")
                _secret_ref(item["secretRef"])
            _safe_typed_tree(item, depth + 1)
    elif isinstance(value, tuple):
        for item in value:
            _safe_typed_tree(item, depth + 1)
    elif value is None or type(value) in (str, bool, int):
        return
    elif type(value) is float:
        import math
        if math.isfinite(value):
            return
        raise ProfileValidationError("manifest must contain finite JSON values")
    else:
        raise ProfileValidationError("manifest must contain finite JSON values")


def _secret_ref(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "ref", "revision", "owner_namespace", "access_purpose"
    }:
        raise ProfileValidationError("SecretRef must use the existing public contract")
    try:
        SecretRef(**value)
    except (ValueError, TypeError):
        raise ProfileValidationError("invalid SecretRef") from None


def _ref(value: Any, environment: str) -> None:
    if not isinstance(value, Mapping) or len(value) < 2:
        raise ProfileValidationError("leaf references require a scoped structured reference")
    if value.get("environmentNamespace") != environment:
        raise ProfileValidationError("leaf reference environment does not match")
    # No leaf identity schema is invented here. The provider must later
    # validate exact revisions and identity before preview/prepare is usable.


def validate_declaration(declaration: dict[str, object], environment: str | None = None) -> None:
    if not isinstance(declaration, dict):
        raise ProfileValidationError("declaration must be an object")
    fields = {"declarationId", "configurationKind", "schemaVersion", "action", "requirement"}
    if not fields <= declaration.keys() or declaration.keys() - fields - {"payload", "resourceRefs"}:
        raise ProfileValidationError("declaration fields do not match the core schema")
    refs = declaration.get("resourceRefs", [])
    validate_declaration_fields(
        declaration["declarationId"], declaration["configurationKind"],
        declaration["schemaVersion"], declaration["action"], declaration["requirement"],
        has_payload="payload" in declaration, payload=declaration.get("payload"),
        resource_refs=refs, environment=environment, parsed=True)
    _safe_tree(declaration)
    canonical(declaration)


def validate_declaration_fields(declaration_id: object, configuration_kind: object,
                                schema_version: object, action: object, requirement: object,
                                *, has_payload: bool, payload: object,
                                resource_refs: object, environment: str | None = None,
                                parsed: bool = False) -> None:
    """Check a typed declaration's fields without encoding a model as a dict."""
    for value in (declaration_id, configuration_kind, schema_version):
        if not isinstance(value, str) or not value:
            raise ProfileValidationError("declaration identifiers are required")
    if action not in ("value", "reset", "disabled"):
        raise ProfileValidationError("invalid declaration action")
    if requirement not in ("required", "optional"):
        raise ProfileValidationError("invalid declaration requirement")
    expected_refs = (list, Mapping) if parsed else (tuple, Mapping)
    if not isinstance(resource_refs, expected_refs):
        raise ProfileValidationError("resourceRefs must be an array")
    if isinstance(resource_refs, Mapping):
        raise ProfileValidationError("resourceRefs must be an array")
    for ref in resource_refs:
        reference_environment = environment
        if reference_environment is None:
            reference_environment = ref.get("environmentNamespace") if isinstance(ref, Mapping) else None
        if not isinstance(reference_environment, str) or not reference_environment:
            raise ProfileValidationError("resource reference environment is required")
        _ref(ref, reference_environment)
        (_safe_tree if parsed else _safe_typed_tree)(ref)
    if has_payload:
        (_safe_tree if parsed else _safe_typed_tree)(payload)
    if action != "value" and (has_payload or resource_refs):
        raise ProfileValidationError("reset/disabled cannot carry values or resources")
    if action == "value" and not has_payload and not resource_refs:
        raise ProfileValidationError("value requires payload or resourceRefs")
def validate_content_fields(schema_version: object, harness_definition_ref: Mapping[str, Any],
                            declarations: tuple[Any, ...], metadata: Mapping[str, Any] | None,
                            *, omitted_value: object, environment: str | None = None) -> None:
    """Check typed ProfileContent fields; canonical size is a codec boundary rule."""
    if not isinstance(schema_version, str) or not schema_version:
        raise ProfileValidationError("schemaVersion is required")
    content_environment = harness_definition_ref.get("environmentNamespace")
    if not isinstance(content_environment, str) or not content_environment:
        raise ProfileValidationError("manifest environment is required")
    if environment is not None and environment != content_environment:
        raise ProfileValidationError("content environment does not match revision reference")
    _ref(harness_definition_ref, content_environment)
    if not isinstance(declarations, tuple) or len(declarations) > 256:
        raise ProfileValidationError("declarations must be a bounded array")
    identifiers: set[str] = set()
    for item in declarations:
        identifier = item.declaration_id
        if identifier in identifiers:
            raise ProfileValidationError("duplicate declaration id")
        identifiers.add(identifier)
        validate_declaration_fields(
            item.declaration_id, item.configuration_kind, item.schema_version,
            item.action, item.requirement, has_payload=item.payload is not omitted_value,
            payload=item.payload, resource_refs=item.resource_refs or (), environment=content_environment)
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise ProfileValidationError("metadata must be an object")
        _safe_typed_tree(metadata)
    _safe_typed_tree(harness_definition_ref)


def canonical_content(value: dict[str, object], environment: str) -> str:
    if not isinstance(environment, str) or not environment:
        raise ProfileValidationError("manifest environment is required")
    if not isinstance(value, dict):
        raise ProfileValidationError("manifest must be an object")
    required = {"harnessDefinitionRef", "schemaVersion", "declarations"}
    if not required <= value.keys() or value.keys() - required - {"metadata"}:
        raise ProfileValidationError("manifest fields do not match the core schema")
    if not isinstance(value["schemaVersion"], str) or not value["schemaVersion"]:
        raise ProfileValidationError("schemaVersion is required")
    _ref(value["harnessDefinitionRef"], environment)
    declarations = value["declarations"]
    if not isinstance(declarations, list) or len(declarations) > 256:
        raise ProfileValidationError("declarations must be a bounded array")
    ids = set()
    for declaration in declarations:
        validate_declaration(declaration, environment)
        identifier = declaration["declarationId"]
        if identifier in ids:
            raise ProfileValidationError("duplicate declaration id")
        ids.add(identifier)
    if "metadata" in value and not isinstance(value["metadata"], dict):
        raise ProfileValidationError("metadata must be an object")
    _safe_tree(value)
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ProfileValidationError("manifest size exceeds limit")
    return encoded


def validate_ref(environment_namespace, profile_id, manifest_revision, digest) -> None:
    EnvironmentId(environment_namespace)
    if not isinstance(profile_id, str) or not LOCAL_ID.fullmatch(profile_id):
        raise ProfileValidationError("profileId must be a stable local id")
    if type(manifest_revision) is not int or manifest_revision < 1:
        raise ProfileValidationError("manifestRevision must be a positive integer")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ProfileValidationError("contentDigest must be sha256")


def validate_entry(profile_id, revision, display_name, archived_at, ref) -> None:
    if profile_id != ref.profile_id:
        raise ProfileValidationError("entry and manifest profile identities must match")
    if type(revision) is not int or revision < 1:
        raise ProfileValidationError("catalogRevision must be a positive integer")
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 256:
        raise ProfileValidationError("displayName must be nonempty and bounded")
    if archived_at is not None and not isinstance(archived_at, str):
        raise ProfileValidationError("archivedAt must be a string or null")
