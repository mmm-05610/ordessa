"""Profile catalog DTOs for the Agent assembly module (028 V2.1).

No native or leaf configuration schema lives here. Opaque leaf references
are retained and remain unresolved until the trusted contribution path
validates them. This module does not imply node preparation is available.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ordessa_environment_api import EnvironmentId, IdentityMismatchError, SecretRef

AGENT_CONTRACT_VERSION = "agent-assembly/1"
_LOCAL_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_MANIFEST_BYTES = 262144
MAX_MANIFEST_DEPTH = 32


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
    if depth > MAX_MANIFEST_DEPTH:
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


def _secret_ref(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "ref", "revision", "owner_namespace", "access_purpose"
    }:
        raise ProfileValidationError("SecretRef must use the existing public contract")
    try:
        SecretRef(**value)
    except (ValueError, TypeError):
        raise ProfileValidationError("invalid SecretRef") from None


def _ref(value: Any, environment: str) -> None:
    if not isinstance(value, dict) or len(value) < 2:
        raise ProfileValidationError("leaf references require a scoped structured reference")
    if value.get("environmentNamespace") != environment:
        raise ProfileValidationError("leaf reference environment does not match")
    # No leaf identity schema is invented here. The provider must later
    # validate exact revisions and identity before preview/prepare is usable.


def manifest_content(value: Mapping[str, Any], environment: str) -> str:
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
        if not isinstance(declaration, dict):
            raise ProfileValidationError("declaration must be an object")
        fields = {"declarationId", "configurationKind", "schemaVersion", "action", "requirement"}
        if not fields <= declaration.keys() or declaration.keys() - fields - {"payload", "resourceRefs"}:
            raise ProfileValidationError("declaration fields do not match the core schema")
        for name in ("declarationId", "configurationKind", "schemaVersion"):
            if not isinstance(declaration[name], str) or not declaration[name]:
                raise ProfileValidationError("declaration identifiers are required")
        identifier = declaration["declarationId"]
        if identifier in ids:
            raise ProfileValidationError("duplicate declaration id")
        ids.add(identifier)
        if declaration["action"] not in ("value", "reset", "disabled"):
            raise ProfileValidationError("invalid declaration action")
        if declaration["requirement"] not in ("required", "optional"):
            raise ProfileValidationError("invalid declaration requirement")
        refs = declaration.get("resourceRefs", [])
        if not isinstance(refs, list):
            raise ProfileValidationError("resourceRefs must be an array")
        for ref in refs:
            _ref(ref, environment)
        if declaration["action"] != "value" and ("payload" in declaration or refs):
            raise ProfileValidationError("reset/disabled cannot carry values or resources")
        if declaration["action"] == "value" and "payload" not in declaration and not refs:
            raise ProfileValidationError("value requires payload or resourceRefs")
    if "metadata" in value and not isinstance(value["metadata"], dict):
        raise ProfileValidationError("metadata must be an object")
    _safe_tree(value)
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ProfileValidationError("manifest size exceeds limit")
    return encoded


@dataclass(frozen=True)
class ProfileRef:
    environment_namespace: str
    profile_id: str
    manifest_revision: int
    content_digest: str

    def __post_init__(self):
        EnvironmentId(self.environment_namespace)
        if not isinstance(self.profile_id, str) or not _LOCAL_ID.fullmatch(self.profile_id):
            raise ProfileValidationError("profileId must be a stable local id")
        if type(self.manifest_revision) is not int or self.manifest_revision < 1:
            raise ProfileValidationError("manifestRevision must be a positive integer")
        if not isinstance(self.content_digest, str) or not _DIGEST.fullmatch(self.content_digest):
            raise ProfileValidationError("contentDigest must be sha256")

    def to_dict(self) -> dict[str, Any]:
        return {"environmentNamespace": self.environment_namespace,
                "profileId": self.profile_id, "manifestRevision": self.manifest_revision,
                "contentDigest": self.content_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProfileRef:
        if not isinstance(value, dict) or set(value) != {
            "environmentNamespace", "profileId", "manifestRevision", "contentDigest"
        }:
            raise ProfileValidationError("invalid ProfileRef fields")
        return cls(value["environmentNamespace"], value["profileId"],
                   value["manifestRevision"], value["contentDigest"])


@dataclass(frozen=True)
class ProfileManifest:
    ref: ProfileRef
    content_json: str

    @property
    def content(self) -> dict[str, Any]:
        return json.loads(self.content_json)


@dataclass(frozen=True)
class ProfileCatalogEntry:
    profile_id: str
    catalog_revision: int
    display_name: str
    archived_at: str | None
    current_manifest_ref: ProfileRef

    def to_dict(self) -> dict[str, Any]:
        return {"profileId": self.profile_id, "catalogRevision": self.catalog_revision,
                "displayName": self.display_name, "archivedAt": self.archived_at,
                "currentManifestRef": self.current_manifest_ref.to_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProfileCatalogEntry:
        return cls(value["profileId"], value["catalogRevision"], value["displayName"],
                   value["archivedAt"], ProfileRef.from_dict(value["currentManifestRef"]))


def content_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
