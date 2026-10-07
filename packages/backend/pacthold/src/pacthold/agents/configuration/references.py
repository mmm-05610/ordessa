"""Closed reference declarations for the Agent configuration contract.

This module composes core configuration metadata with the existing material
reference DTO. It does not inspect configuration payloads or acquire resources.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

from ordessa_environment_api.identity import EnvironmentId
from ordessa_environment_api.operations import sealed_mapping

from pacthold.core.configuration_admission import (
    ConfigurationContractError,
    ConfigurationProviderDescriptor,
    ConfigurationProviderPin,
    ConfigurationRoute,
)
from pacthold.agents.assembly.materials import ResourceRef


_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DEFINITION_KEYS = {"environmentNamespace", "definitionId", "revision"}
_MAX_TEXT = 256
_MAX_REFERENCES = 256


def _invalid() -> None:
    raise ConfigurationContractError()


def _label(value: object, *, maximum: int = _MAX_TEXT) -> str:
    if (type(value) is not str or not value or value.strip() != value
            or len(value) > maximum or any(ord(char) < 32 for char in value)):
        _invalid()
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid()
    return value


def _opaque(value: object) -> str:
    if type(value) is not str or not _OPAQUE.fullmatch(value):
        _invalid()
    return value


def _definition_ref(value: object) -> Mapping[str, str]:
    if type(value) is dict:
        if set(value) != _DEFINITION_KEYS:
            _invalid()
        environment = value["environmentNamespace"]
        definition_id = value["definitionId"]
        revision = value["revision"]
    elif type(value) is MappingProxyType:
        if set(value) != _DEFINITION_KEYS:
            _invalid()
        environment = value["environmentNamespace"]
        definition_id = value["definitionId"]
        revision = value["revision"]
    else:
        _invalid()
    environment = _label(environment, maximum=64)
    try:
        EnvironmentId(environment)
    except (TypeError, ValueError):
        _invalid()
    definition_id = _label(definition_id, maximum=128)
    revision = _label(revision, maximum=128)
    if ("*" in definition_id or "*" in revision
            or definition_id.lower() == "latest" or revision.lower() == "latest"):
        _invalid()
    return sealed_mapping({"environmentNamespace": environment,
                           "definitionId": definition_id, "revision": revision})


def _definition_dict(value: Mapping[str, str]) -> dict[str, str]:
    return {"environmentNamespace": value["environmentNamespace"],
            "definitionId": value["definitionId"], "revision": value["revision"]}


def _resource_ref(value: object) -> ResourceRef:
    if type(value) is not ResourceRef:
        _invalid()
    try:
        # Copy only stable fields. Do not call an instance method which a caller
        # could have replaced on this frozen-but-nonslotted dataclass.
        return ResourceRef(value.environment_namespace, value.provider_id,
                           value.contract_id, value.resource_id, value.revision)
    except (TypeError, ValueError):
        _invalid()


def _resource_ref_dict(value: ResourceRef) -> dict[str, str]:
    return {
        "environmentNamespace": value.environment_namespace,
        "providerId": value.provider_id,
        "contractId": value.contract_id,
        "resourceId": value.resource_id,
        "revision": value.revision,
    }


def _resource_ref_from_dict(value: object) -> ResourceRef:
    if type(value) is not dict or set(value) != {
        "environmentNamespace", "providerId", "contractId", "resourceId", "revision"
    }:
        _invalid()
    try:
        return ResourceRef(value["environmentNamespace"], value["providerId"],
                           value["contractId"], value["resourceId"], value["revision"])
    except (TypeError, ValueError):
        _invalid()


def _copy_pin(value: object) -> ConfigurationProviderPin:
    if type(value) is not ConfigurationProviderPin:
        _invalid()
    try:
        return ConfigurationProviderPin(value.provider_id, value.contract_version,
                                        value.implementation_digest, value.owner_activation)
    except (TypeError, ValueError):
        _invalid()


def _pin_equal(left: ConfigurationProviderPin, right: ConfigurationProviderPin) -> bool:
    return (left.provider_id == right.provider_id
            and left.contract_version == right.contract_version
            and left.implementation_digest == right.implementation_digest
            and left.owner_activation.environment == right.owner_activation.environment
            and left.owner_activation.plugin_id == right.owner_activation.plugin_id
            and left.owner_activation.generation == right.owner_activation.generation)


def _closed_dict(value: object, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        _invalid()
    return value


@dataclass(frozen=True)
class ConfigurationReference:
    reference_id: str
    resource_ref: ResourceRef
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_id", _opaque(self.reference_id))
        object.__setattr__(self, "resource_ref", _resource_ref(self.resource_ref))
        object.__setattr__(self, "purpose", _label(self.purpose))

    def to_dict(self) -> dict:
        return {"referenceId": self.reference_id,
                "resourceRef": _resource_ref_dict(self.resource_ref),
                "purpose": self.purpose}

    @classmethod
    def from_dict(cls, value: object) -> "ConfigurationReference":
        value = _closed_dict(value, {"referenceId", "resourceRef", "purpose"})
        try:
            return cls(value["referenceId"], _resource_ref_from_dict(value["resourceRef"]),
                       value["purpose"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class ConfigurationReferenceExtraction:
    declaration_id: str
    configuration_kind: str
    schema_version: str
    action: str
    declaration_digest: str
    definition_ref: Mapping[str, str]
    provider_pin: ConfigurationProviderPin
    coverage: str
    references: tuple[ConfigurationReference, ...]
    error_code: str | None

    def __post_init__(self) -> None:
        declaration_id = _label(self.declaration_id, maximum=128)
        if type(self.configuration_kind) is not str or not re.fullmatch(
                r"^[a-z][a-z0-9._-]{0,127}$", self.configuration_kind):
            _invalid()
        # Delegate the shared, bounded schema grammar to a one-route value only
        # indirectly would add unrelated fields, so validate its exact pattern.
        if type(self.schema_version) is not str or not re.fullmatch(
                r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._:+-]{0,63})?$",
                self.schema_version):
            _invalid()
        if (any(part.lower() == "latest" for part in self.schema_version.split("/"))
                or any(part in {".", ".."} for part in self.schema_version.split("/"))
                or "*" in self.schema_version):
            _invalid()
        if type(self.action) is not str or self.action not in {"value", "reset", "disabled"}:
            _invalid()
        if type(self.declaration_digest) is not str or not _DIGEST.fullmatch(self.declaration_digest):
            _invalid()
        definition_ref = _definition_ref(self.definition_ref)
        provider_pin = _copy_pin(self.provider_pin)
        if definition_ref["environmentNamespace"] != provider_pin.environment_namespace:
            _invalid()
        if type(self.coverage) is not str or self.coverage not in {"complete", "unknown"}:
            _invalid()
        if (type(self.references) is not tuple or len(self.references) > _MAX_REFERENCES
                or any(type(item) is not ConfigurationReference for item in self.references)):
            _invalid()
        references = tuple(ConfigurationReference(item.reference_id, item.resource_ref, item.purpose)
                           for item in self.references)
        if len({item.reference_id for item in references}) != len(references):
            _invalid()
        for item in references:
            if item.resource_ref.environment_namespace != provider_pin.environment_namespace:
                _invalid()
        if self.coverage == "complete":
            if self.error_code is not None:
                _invalid()
        elif (type(self.error_code) is not str or not _ERROR_CODE.fullmatch(self.error_code)):
            _invalid()
        object.__setattr__(self, "declaration_id", declaration_id)
        object.__setattr__(self, "definition_ref", definition_ref)
        object.__setattr__(self, "provider_pin", provider_pin)
        object.__setattr__(self, "references", references)

    def to_dict(self) -> dict:
        return {
            "declarationId": self.declaration_id,
            "configurationKind": self.configuration_kind,
            "schemaVersion": self.schema_version,
            "action": self.action,
            "declarationDigest": self.declaration_digest,
            "definitionRef": _definition_dict(self.definition_ref),
            "providerPin": ConfigurationProviderPin.to_dict(self.provider_pin),
            "coverage": self.coverage,
            "references": [ConfigurationReference.to_dict(item) for item in self.references],
            "errorCode": self.error_code,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigurationReferenceExtraction":
        value = _closed_dict(value, {"declarationId", "configurationKind", "schemaVersion", "action",
                                     "declarationDigest", "definitionRef", "providerPin", "coverage",
                                     "references", "errorCode"})
        if type(value["references"]) is not list:
            _invalid()
        try:
            return cls(value["declarationId"], value["configurationKind"], value["schemaVersion"],
                       value["action"], value["declarationDigest"], value["definitionRef"],
                       ConfigurationProviderPin.from_dict(value["providerPin"]), value["coverage"],
                       tuple(ConfigurationReference.from_dict(item) for item in value["references"]),
                       value["errorCode"])
        except (TypeError, ValueError):
            _invalid()


def _expected_declaration(value: object) -> dict:
    keys = {"declarationId", "configurationKind", "schemaVersion", "action",
            "declarationDigest", "definitionRef"}
    if type(value) is dict:
        if set(value) != keys:
            _invalid()
        source = value
    elif type(value) is MappingProxyType:
        if set(value) != keys:
            _invalid()
        source = value
    else:
        _invalid()
    declaration_id = _label(source["declarationId"], maximum=128)
    kind = source["configurationKind"]
    if type(kind) is not str or not re.fullmatch(r"^[a-z][a-z0-9._-]{0,127}$", kind):
        _invalid()
    schema = source["schemaVersion"]
    if type(schema) is not str or not re.fullmatch(
            r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._:+-]{0,63})?$", schema):
        _invalid()
    if (any(part.lower() == "latest" for part in schema.split("/"))
            or any(part in {".", ".."} for part in schema.split("/")) or "*" in schema):
        _invalid()
    action = source["action"]
    if type(action) is not str or action not in {"value", "reset", "disabled"}:
        _invalid()
    digest = source["declarationDigest"]
    if type(digest) is not str or not _DIGEST.fullmatch(digest):
        _invalid()
    definition = _definition_ref(source["definitionRef"])
    return {"declarationId": declaration_id, "configurationKind": kind,
            "schemaVersion": schema, "action": action,
            "declarationDigest": digest, "definitionRef": definition}


def _definition_equal(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    return (left["environmentNamespace"] == right["environmentNamespace"]
            and left["definitionId"] == right["definitionId"]
            and left["revision"] == right["revision"])


def validate_reference_extraction(
    descriptor: ConfigurationProviderDescriptor,
    extraction: ConfigurationReferenceExtraction,
    *,
    expected_pin: ConfigurationProviderPin,
    expected_declaration: Mapping,
) -> ConfigurationReferenceExtraction:
    """Validate one explicit provider result against caller-fixed identities.

    This validates declarations only. It does not prove extraction completeness,
    route a resource, authorize access, or invoke a provider.
    """
    if type(descriptor) is not ConfigurationProviderDescriptor:
        _invalid()
    if type(extraction) is not ConfigurationReferenceExtraction:
        _invalid()
    expected_pin = _copy_pin(expected_pin)
    expected = _expected_declaration(expected_declaration)
    snapshot_descriptor = ConfigurationProviderDescriptor(
        descriptor.provider_id, descriptor.contract_version, descriptor.implementation_digest,
        descriptor.routes, descriptor.supported_methods)
    if "extract_references" not in snapshot_descriptor.supported_methods:
        _invalid()
    snapshot = ConfigurationReferenceExtraction(
        extraction.declaration_id, extraction.configuration_kind, extraction.schema_version,
        extraction.action, extraction.declaration_digest, extraction.definition_ref,
        extraction.provider_pin, extraction.coverage, extraction.references, extraction.error_code)

    if (not _pin_equal(snapshot.provider_pin, expected_pin)
            or snapshot.provider_pin.provider_id != snapshot_descriptor.provider_id
            or snapshot.provider_pin.contract_version != snapshot_descriptor.contract_version
            or snapshot.provider_pin.implementation_digest != snapshot_descriptor.implementation_digest
            or snapshot.provider_pin.environment_namespace != snapshot_descriptor.environment_namespace):
        _invalid()
    if (snapshot.declaration_id != expected["declarationId"]
            or snapshot.configuration_kind != expected["configurationKind"]
            or snapshot.schema_version != expected["schemaVersion"]
            or snapshot.action != expected["action"]
            or snapshot.declaration_digest != expected["declarationDigest"]
            or not _definition_equal(snapshot.definition_ref, expected["definitionRef"])):
        _invalid()
    if snapshot.definition_ref["environmentNamespace"] != expected_pin.environment_namespace:
        _invalid()

    route = None
    for candidate in snapshot_descriptor.routes:
        if (candidate.configuration_kind == snapshot.configuration_kind
                and candidate.schema_version == snapshot.schema_version):
            route = candidate
            break
    if route is None or snapshot.action not in route.actions:
        _invalid()
    if not any(_definition_equal(item, snapshot.definition_ref) for item in route.definition_refs):
        _invalid()

    # Reconstruct once more from fields so callers receive a detached DTO graph.
    return ConfigurationReferenceExtraction(
        snapshot.declaration_id, snapshot.configuration_kind, snapshot.schema_version,
        snapshot.action, snapshot.declaration_digest, snapshot.definition_ref,
        snapshot.provider_pin, snapshot.coverage, snapshot.references, snapshot.error_code)


__all__ = ["ConfigurationReference", "ConfigurationReferenceExtraction",
           "validate_reference_extraction"]
