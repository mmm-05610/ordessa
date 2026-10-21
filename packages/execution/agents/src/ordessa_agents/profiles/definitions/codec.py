"""Typed Profile values ↔ existing parsed JSON schema; no file or persistence IO."""
from __future__ import annotations

import hashlib

from .models import (ProfileRevisionRef, ProfileRevision, Profile, ProfileContent,
                     ConfigurationDeclaration)
from .json_values import OMITTED, json_data
from .validation import (ProfileValidationError, canonical, canonical_content,
                         validate_declaration, validate_ref, validate_entry)


def content_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _fields(value, fields, kind, optional=frozenset()):
    if not isinstance(value, dict) or not fields <= value.keys() or value.keys() - fields - optional:
        raise ProfileValidationError(f"invalid {kind} fields")


def decode_revision_ref(value: dict[str, object]) -> ProfileRevisionRef:
    _fields(value, {"environmentNamespace", "profileId", "manifestRevision", "contentDigest"}, "ProfileRef")
    return ProfileRevisionRef(value["environmentNamespace"], value["profileId"],
                              value["manifestRevision"], value["contentDigest"])


def encode_revision_ref(value: ProfileRevisionRef) -> dict[str, object]:
    if type(value) is not ProfileRevisionRef:
        raise ProfileValidationError("typed Profile revision reference required")
    validate_ref(value.environment_namespace, value.profile_id, value.revision, value.digest)
    return {"environmentNamespace": value.environment_namespace,
            "profileId": value.profile_id, "manifestRevision": value.revision,
            "contentDigest": value.digest}


def decode_profile(value: dict[str, object]) -> Profile:
    _fields(value, {"profileId", "catalogRevision", "displayName", "archivedAt", "currentManifestRef"}, "Profile entry")
    return Profile(value["profileId"], value["catalogRevision"], value["displayName"],
                   value["archivedAt"], decode_revision_ref(value["currentManifestRef"]))


def encode_profile(value: Profile) -> dict[str, object]:
    if type(value) is not Profile:
        raise ProfileValidationError("typed Profile required")
    if type(value.current_revision) is not ProfileRevisionRef:
        raise ProfileValidationError("fixed Profile revision reference required")
    validate_entry(value.profile_id, value.version, value.name,
                   value.archived_at, value.current_revision)
    return {"profileId": value.profile_id, "catalogRevision": value.version,
            "displayName": value.name, "archivedAt": value.archived_at,
            "currentManifestRef": encode_revision_ref(value.current_revision)}


def decode_declaration(value: dict[str, object]) -> ConfigurationDeclaration:
    validate_declaration(value)
    return ConfigurationDeclaration(value["declarationId"], value["configurationKind"],
        value["schemaVersion"], value["action"], value["requirement"],
        value.get("payload", OMITTED),
        tuple(value["resourceRefs"]) if "resourceRefs" in value else None)


def encode_declaration(value: ConfigurationDeclaration) -> dict[str, object]:
    if type(value) is not ConfigurationDeclaration:
        raise ProfileValidationError("typed configuration declaration required")
    result = {"declarationId": value.declaration_id, "configurationKind": value.configuration_kind,
              "schemaVersion": value.schema_version, "action": value.action, "requirement": value.requirement}
    if value.payload is not OMITTED:
        result["payload"] = json_data(value.payload)
    if value.resource_refs is not None:
        result["resourceRefs"] = [json_data(ref) for ref in value.resource_refs]
    validate_declaration(result)
    return result


def decode_content(value: dict[str, object], environment: str) -> ProfileContent:
    canonical_content(value, environment)
    return ProfileContent(value["schemaVersion"], value["harnessDefinitionRef"],
                          tuple(decode_declaration(item) for item in value["declarations"]),
                          value.get("metadata"))


def encode_content(value: ProfileContent) -> dict[str, object]:
    if type(value) is not ProfileContent:
        raise ProfileValidationError("typed Profile content required")
    result = {"schemaVersion": value.schema_version,
              "harnessDefinitionRef": json_data(value.harness_definition_ref),
              "declarations": [encode_declaration(item) for item in value.declarations]}
    if value.metadata is not None:
        result["metadata"] = json_data(value.metadata)
    environment = result["harnessDefinitionRef"].get("environmentNamespace")
    canonical_content(result, environment)
    return result


def decode_revision(value: dict[str, object]) -> ProfileRevision:
    _fields(value, {"ref", "content"}, "Profile manifest")
    ref = decode_revision_ref(value["ref"])
    content = decode_content(value["content"], ref.environment_namespace)
    encoded = canonical_content(value["content"], ref.environment_namespace)
    if content_digest(encoded) != ref.digest:
        raise ProfileValidationError("Profile revision digest does not match content")
    return ProfileRevision(ref, content)


def encode_revision(value: ProfileRevision) -> dict[str, object]:
    if type(value) is not ProfileRevision:
        raise ProfileValidationError("typed Profile revision required")
    content = encode_content(value.content)
    encoded = canonical_content(content, value.ref.environment_namespace)
    if content_digest(encoded) != value.ref.digest:
        raise ProfileValidationError("Profile revision digest does not match content")
    return {"ref": encode_revision_ref(value.ref), "content": content}
