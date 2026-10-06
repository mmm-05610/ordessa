"""Pure, closed metadata contracts for Agent configuration providers.

These DTOs do not admit a provider, authorize a configuration change, or call
native controls. The Environment's existing CoreRegistry remains the future
source of trusted provider ownership.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

from ordessa_environment_api.identity import ActivationRef, EnvironmentId
from ordessa_environment_api.operations import sealed_mapping


CONFIGURATION_PROVIDER_VERSION = "agent-configuration-provider/1"
CONFIGURATION_METHODS = (
    "describe", "validate", "extract_references", "assess", "compile", "verify",
)

_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SCHEMA_VERSION = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._:+-]{0,63})?$")
_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_DEFINITION_KEYS = {"environmentNamespace", "definitionId", "revision"}
_PROVIDER_REF_KEYS = {
    "environmentNamespace", "providerId", "ownerActivationRef", "generation",
    "contractVersion", "implementationDigest",
}
_MAX_ROUTES = 64
_MAX_DEFINITIONS = 64
_MAX_CLAIMS = 256
_MAX_TEXT = 256


class ConfigurationContractError(ValueError):
    """A closed configuration metadata DTO is malformed or inconsistent."""

    code = "CONFIGURATION_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__("configuration provider contract is invalid")


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


def _provider_id(value: object) -> str:
    if type(value) is not str or not _PROVIDER_ID.fullmatch(value):
        _invalid()
    return value


def _schema_version(value: object) -> str:
    if type(value) is not str or not _SCHEMA_VERSION.fullmatch(value):
        _invalid()
    parts = value.split("/")
    if (any(part.lower() == "latest" for part in parts)
            or any(part in {".", ".."} for part in parts)
            or "*" in value):
        _invalid()
    return value


def _opaque(value: object) -> str:
    if type(value) is not str or not _OPAQUE.fullmatch(value):
        _invalid()
    return value


def _definition_label(value: object) -> str:
    return _label(value, maximum=128)


def _definition_ref(value: object) -> Mapping[str, str]:
    # Accept only ordinary DTO dictionaries or our sealed mapping type. This
    # avoids invoking arbitrary Mapping implementations while taking a snapshot.
    if type(value) is dict:
        if set(value) != _DEFINITION_KEYS:
            _invalid()
        raw_environment = value["environmentNamespace"]
        raw_id = value["definitionId"]
        raw_revision = value["revision"]
    elif type(value) is MappingProxyType:
        if set(value) != _DEFINITION_KEYS:
            _invalid()
        raw_environment = value["environmentNamespace"]
        raw_id = value["definitionId"]
        raw_revision = value["revision"]
    else:
        _invalid()
    environment = _label(raw_environment, maximum=64)
    try:
        EnvironmentId(environment)
    except (TypeError, ValueError):
        _invalid()
    definition_id = _definition_label(raw_id)
    revision = _definition_label(raw_revision)
    if (definition_id.lower() == "latest" or revision.lower() == "latest"
            or "*" in definition_id or "*" in revision):
        _invalid()
    return sealed_mapping({"environmentNamespace": environment,
                           "definitionId": definition_id,
                           "revision": revision})


def _definition_dict(value: Mapping[str, str]) -> dict[str, str]:
    # Do not call an instance serialization method while projecting DTO data.
    return {"environmentNamespace": value["environmentNamespace"],
            "definitionId": value["definitionId"],
            "revision": value["revision"]}


def _activation(value: object) -> ActivationRef:
    if type(value) is not ActivationRef:
        _invalid()
    try:
        return ActivationRef(value.environment, value.plugin_id, value.generation)
    except (TypeError, ValueError):
        _invalid()


def _closed_dict(value: object, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        _invalid()
    return value


@dataclass(frozen=True)
class ConfigurationRoute:
    configuration_kind: str
    schema_version: str
    definition_refs: tuple[Mapping[str, str], ...]
    actions: tuple[str, ...]
    field_claims: tuple[str, ...]

    def __post_init__(self) -> None:
        kind = _provider_id(self.configuration_kind)
        schema = _schema_version(self.schema_version)
        if type(self.definition_refs) is not tuple or not 1 <= len(self.definition_refs) <= _MAX_DEFINITIONS:
            _invalid()
        definitions = tuple(_definition_ref(item) for item in self.definition_refs)
        definition_keys = tuple((item["environmentNamespace"], item["definitionId"], item["revision"])
                                for item in definitions)
        if len(set(definition_keys)) != len(definition_keys):
            _invalid()
        if len({item["environmentNamespace"] for item in definitions}) != 1:
            _invalid()
        if (type(self.actions) is not tuple or not 1 <= len(self.actions) <= 3
                or any(type(item) is not str or item not in {"value", "reset", "disabled"}
                       for item in self.actions)
                or len(set(self.actions)) != len(self.actions)):
            _invalid()
        if (type(self.field_claims) is not tuple or not 1 <= len(self.field_claims) <= _MAX_CLAIMS):
            _invalid()
        claims = tuple(_opaque(item) for item in self.field_claims)
        if len(set(claims)) != len(claims):
            _invalid()
        object.__setattr__(self, "configuration_kind", kind)
        object.__setattr__(self, "schema_version", schema)
        object.__setattr__(self, "definition_refs", definitions)
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "field_claims", claims)

    @property
    def environment_namespace(self) -> str:
        return self.definition_refs[0]["environmentNamespace"]

    def to_dict(self) -> dict:
        return {
            "configurationKind": self.configuration_kind,
            "schemaVersion": self.schema_version,
            "definitionRefs": [_definition_dict(item) for item in self.definition_refs],
            "actions": list(self.actions),
            "fieldClaims": list(self.field_claims),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigurationRoute":
        value = _closed_dict(value, {"configurationKind", "schemaVersion", "definitionRefs",
                                     "actions", "fieldClaims"})
        if any(type(value[key]) is not list for key in ("definitionRefs", "actions", "fieldClaims")):
            _invalid()
        try:
            return cls(value["configurationKind"], value["schemaVersion"],
                       tuple(value["definitionRefs"]), tuple(value["actions"]),
                       tuple(value["fieldClaims"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class ConfigurationProviderDescriptor:
    provider_id: str
    contract_version: str
    implementation_digest: str
    routes: tuple[ConfigurationRoute, ...]
    supported_methods: tuple[str, ...]

    def __post_init__(self) -> None:
        provider_id = _provider_id(self.provider_id)
        if (type(self.contract_version) is not str
                or self.contract_version != CONFIGURATION_PROVIDER_VERSION):
            _invalid()
        if type(self.implementation_digest) is not str or not _SHA256.fullmatch(self.implementation_digest):
            _invalid()
        if type(self.routes) is not tuple or not 1 <= len(self.routes) <= _MAX_ROUTES:
            _invalid()
        routes = []
        for item in self.routes:
            if type(item) is not ConfigurationRoute:
                _invalid()
            routes.append(ConfigurationRoute(item.configuration_kind, item.schema_version,
                                             item.definition_refs, item.actions, item.field_claims))
        route_keys = tuple((item.configuration_kind, item.schema_version) for item in routes)
        if len(set(route_keys)) != len(route_keys):
            _invalid()
        if len({item.environment_namespace for item in routes}) != 1:
            _invalid()
        if (type(self.supported_methods) is not tuple
                or len(self.supported_methods) > len(CONFIGURATION_METHODS)
                or any(type(item) is not str or item not in CONFIGURATION_METHODS
                       for item in self.supported_methods)
                or len(set(self.supported_methods)) != len(self.supported_methods)):
            _invalid()
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "routes", tuple(routes))
        object.__setattr__(self, "supported_methods", tuple(self.supported_methods))

    @property
    def environment_namespace(self) -> str:
        return self.routes[0].environment_namespace

    def to_dict(self) -> dict:
        return {
            "providerId": self.provider_id,
            "contractVersion": self.contract_version,
            "implementationDigest": self.implementation_digest,
            "routes": [ConfigurationRoute.to_dict(item) for item in self.routes],
            "supportedMethods": list(self.supported_methods),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigurationProviderDescriptor":
        value = _closed_dict(value, {"providerId", "contractVersion", "implementationDigest",
                                     "routes", "supportedMethods"})
        if type(value["routes"]) is not list or type(value["supportedMethods"]) is not list:
            _invalid()
        try:
            routes = tuple(ConfigurationRoute.from_dict(item) for item in value["routes"])
            return cls(value["providerId"], value["contractVersion"], value["implementationDigest"],
                       routes, tuple(value["supportedMethods"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class ConfigurationProviderPin:
    provider_id: str
    contract_version: str
    implementation_digest: str
    owner_activation: ActivationRef

    def __post_init__(self) -> None:
        provider_id = _provider_id(self.provider_id)
        if (type(self.contract_version) is not str
                or self.contract_version != CONFIGURATION_PROVIDER_VERSION):
            _invalid()
        if type(self.implementation_digest) is not str or not _SHA256.fullmatch(self.implementation_digest):
            _invalid()
        activation = _activation(self.owner_activation)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "owner_activation", activation)

    @property
    def environment_namespace(self) -> str:
        return self.owner_activation.environment

    @property
    def provider_ref(self) -> Mapping[str, object]:
        owner = self.owner_activation
        return sealed_mapping({
            "environmentNamespace": owner.environment,
            "providerId": self.provider_id,
            "ownerActivationRef": {
                "environmentNamespace": owner.environment,
                "pluginId": owner.plugin_id,
                "generation": owner.generation,
            },
            "generation": owner.generation,
            "contractVersion": self.contract_version,
            "implementationDigest": self.implementation_digest,
        })

    def to_dict(self) -> dict:
        owner = self.owner_activation
        return {
            "environmentNamespace": owner.environment,
            "providerId": self.provider_id,
            "ownerActivationRef": {
                "environmentNamespace": owner.environment,
                "pluginId": owner.plugin_id,
                "generation": owner.generation,
            },
            "generation": owner.generation,
            "contractVersion": self.contract_version,
            "implementationDigest": self.implementation_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigurationProviderPin":
        value = _closed_dict(value, _PROVIDER_REF_KEYS)
        owner = value["ownerActivationRef"]
        owner = _closed_dict(owner, {"environmentNamespace", "pluginId", "generation"})
        try:
            activation = ActivationRef(owner["environmentNamespace"], owner["pluginId"], owner["generation"])
            pin = cls(value["providerId"], value["contractVersion"],
                      value["implementationDigest"], activation)
        except (TypeError, ValueError):
            _invalid()
        if (type(value["environmentNamespace"]) is not str
                or value["environmentNamespace"] != pin.environment_namespace
                or type(value["generation"]) is not int
                or value["generation"] != pin.owner_activation.generation):
            _invalid()
        return pin
