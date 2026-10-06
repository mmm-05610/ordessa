"""Closed, non-secret material contracts for the Agent unit model.

These frozen DTOs describe stable resource identities and operation-bound
material receipts. They do not resolve resources, issue invocation contexts,
create Usage records, or prove that a consumer used a material.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import inspect
import re
from typing import Protocol, runtime_checkable

from ordessa_environment_api.errors import GuaranteeUnavailableError
from ordessa_environment_api.identity import ActivationRef, EnvironmentId, ParticipantInstanceRef
from ordessa_environment_api.operations import safe_json

from ..core.descriptors import validate_component_id, validate_contract_id
from ..core.resource_admission import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialCapability,
    MaterialContractError,
)
from .directory import DirectoryBindingRef
from .invocation import InvocationContext


class MaterialUnavailable(GuaranteeUnavailableError):
    """The optional material capability was not declared by this provider."""

    code = "MATERIAL_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("authorized material capability is unavailable")


class MaterialLifetime(str, Enum):
    COPY_COMPLETE = "copyComplete"
    DYNAMIC = "dynamic"
    RUNTIME_REQUIRED = "runtimeRequired"


class MaterialAccessMode(str, Enum):
    READ_ONLY = "readOnly"
    EFFECTFUL = "effectful"


class MaterialReleaseRecovery(str, Enum):
    QUERYABLE = "queryable"
    IDEMPOTENT = "idempotent"
    BOTH = "both"
    UNSUPPORTED = "unsupported"


class MaterialOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$")
_SCHEMA_VERSION = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._:+-]{0,63})?$")
_MATERIAL_TYPE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z0-9_]{1,64}$")
_MAX_TEXT = 256
_MISSING = object()


def _invalid() -> None:
    raise MaterialContractError()


def _closed_dict(value: object, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        _invalid()
    return value


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
    if type(value) is not str or not _OPAQUE_ID.fullmatch(value):
        _invalid()
    return value


def _version(value: object) -> str:
    if (type(value) is not str or not _VERSION.fullmatch(value)
            or value.lower() == "latest" or "*" in value):
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


def _environment(value: object) -> str:
    if type(value) is not str:
        _invalid()
    try:
        EnvironmentId(value)
    except (TypeError, ValueError):
        _invalid()
    return value


def _provider_id(value: object) -> str:
    try:
        return validate_component_id(value, kind="provider")
    except (TypeError, ValueError):
        _invalid()


def _contract_id(value: object) -> str:
    try:
        return validate_contract_id(value)
    except (TypeError, ValueError):
        _invalid()


def _digest(value: object) -> str:
    if type(value) is not str or not _HEX_64.fullmatch(value):
        _invalid()
    return value


def _content_digest(value: object) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        _invalid()
    return value


def _error_code(value: object) -> str:
    if type(value) is not str or not _ERROR_CODE.fullmatch(value):
        _invalid()
    return value


def _environment_equal(environment: str, *values: str) -> None:
    if any(value != environment for value in values):
        _invalid()


def _copy_activation(value: object) -> ActivationRef:
    if type(value) is not ActivationRef:
        _invalid()
    try:
        return ActivationRef(value.environment, value.plugin_id, value.generation)
    except (TypeError, ValueError):
        _invalid()


def _copy_directory(value: object) -> DirectoryBindingRef:
    if type(value) is not DirectoryBindingRef:
        _invalid()
    try:
        return DirectoryBindingRef(value.environment_namespace, value.binding_id,
                                   value.binding_revision, value.content_digest)
    except (TypeError, ValueError):
        _invalid()


def _enum_value(enum_type, value):
    try:
        return value if type(value) is enum_type else enum_type(value)
    except (TypeError, ValueError):
        _invalid()


def _hash_facts(value: dict) -> str:
    try:
        return hashlib.sha256(safe_json(value).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError):
        _invalid()


@dataclass(frozen=True)
class ResourceRef:
    environment_namespace: str
    provider_id: str
    contract_id: str
    resource_id: str
    revision: str

    def __post_init__(self) -> None:
        _environment(self.environment_namespace)
        _provider_id(self.provider_id)
        _contract_id(self.contract_id)
        _opaque(self.resource_id)
        _version(self.revision)

    def to_dict(self) -> dict[str, str]:
        return {"environmentNamespace": self.environment_namespace,
                "providerId": self.provider_id, "contractId": self.contract_id,
                "resourceId": self.resource_id, "revision": self.revision}

    @classmethod
    def from_dict(cls, value: object) -> ResourceRef:
        value = _closed_dict(value, {"environmentNamespace", "providerId", "contractId", "resourceId", "revision"})
        try:
            return cls(value["environmentNamespace"], value["providerId"], value["contractId"],
                       value["resourceId"], value["revision"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialProviderPin:
    provider_id: str
    provider_version: str
    owner_activation: ActivationRef

    def __post_init__(self) -> None:
        _provider_id(self.provider_id)
        _version(self.provider_version)
        object.__setattr__(self, "owner_activation", _copy_activation(self.owner_activation))

    def to_dict(self) -> dict:
        return {"providerId": self.provider_id, "providerVersion": self.provider_version,
                "ownerActivation": {"environmentNamespace": self.owner_activation.environment,
                                    "pluginId": self.owner_activation.plugin_id,
                                    "generation": self.owner_activation.generation}}

    @classmethod
    def from_dict(cls, value: object) -> MaterialProviderPin:
        value = _closed_dict(value, {"providerId", "providerVersion", "ownerActivation"})
        owner = _closed_dict(value["ownerActivation"], {"environmentNamespace", "pluginId", "generation"})
        try:
            return cls(value["providerId"], value["providerVersion"],
                       ActivationRef(owner["environmentNamespace"], owner["pluginId"], owner["generation"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialUseTarget:
    node_ref: ParticipantInstanceRef
    directory_binding_ref: DirectoryBindingRef
    management_epoch: int
    purpose: str

    def __post_init__(self) -> None:
        if type(self.node_ref) is not ParticipantInstanceRef:
            _invalid()
        try:
            object.__setattr__(self, "node_ref", ParticipantInstanceRef(
                self.node_ref.environment, self.node_ref.instance_id, self.node_ref.generation))
        except (TypeError, ValueError):
            _invalid()
        object.__setattr__(self, "directory_binding_ref", _copy_directory(self.directory_binding_ref))
        if type(self.management_epoch) is not int or self.management_epoch < 0:
            _invalid()
        _label(self.purpose)
        _environment_equal(self.node_ref.environment, self.directory_binding_ref.environment_namespace)

    def to_dict(self) -> dict:
        return {"nodeRef": {"environmentNamespace": self.node_ref.environment,
                            "instanceId": self.node_ref.instance_id,
                            "generation": self.node_ref.generation},
                "directoryBindingRef": self.directory_binding_ref.to_dict(),
                "managementEpoch": self.management_epoch, "purpose": self.purpose}

    @classmethod
    def from_dict(cls, value: object) -> MaterialUseTarget:
        value = _closed_dict(value, {"nodeRef", "directoryBindingRef", "managementEpoch", "purpose"})
        node = _closed_dict(value["nodeRef"], {"environmentNamespace", "instanceId", "generation"})
        try:
            node_ref = ParticipantInstanceRef(node["environmentNamespace"], node["instanceId"], node["generation"])
            directory = DirectoryBindingRef.from_dict(value["directoryBindingRef"])
            return cls(node_ref, directory, value["managementEpoch"], value["purpose"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialCorrelation:
    operation_ref: str
    step_id: str
    recovery_correlation: str
    input_digest: str

    def __post_init__(self) -> None:
        for name in ("operation_ref", "step_id", "recovery_correlation"):
            _label(getattr(self, name))
        _digest(self.input_digest)

    def to_dict(self) -> dict[str, str]:
        return {"operationRef": self.operation_ref, "stepId": self.step_id,
                "recoveryCorrelation": self.recovery_correlation, "inputDigest": self.input_digest}

    @classmethod
    def from_dict(cls, value: object) -> MaterialCorrelation:
        value = _closed_dict(value, {"operationRef", "stepId", "recoveryCorrelation", "inputDigest"})
        try:
            return cls(value["operationRef"], value["stepId"], value["recoveryCorrelation"], value["inputDigest"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialObjectRef:
    environment_namespace: str
    material_id: str
    revision: str

    def __post_init__(self) -> None:
        _environment(self.environment_namespace)
        _opaque(self.material_id)
        _version(self.revision)

    def to_dict(self) -> dict[str, str]:
        return {"environmentNamespace": self.environment_namespace,
                "materialId": self.material_id, "revision": self.revision}

    @classmethod
    def from_dict(cls, value: object) -> MaterialObjectRef:
        value = _closed_dict(value, {"environmentNamespace", "materialId", "revision"})
        try:
            return cls(value["environmentNamespace"], value["materialId"], value["revision"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialEvidenceRef:
    environment_namespace: str
    reference_id: str
    revision: str

    def __post_init__(self) -> None:
        _environment(self.environment_namespace)
        _opaque(self.reference_id)
        _version(self.revision)

    def to_dict(self) -> dict[str, str]:
        return {"environmentNamespace": self.environment_namespace,
                "referenceId": self.reference_id, "revision": self.revision}

    @classmethod
    def from_dict(cls, value: object) -> MaterialEvidenceRef:
        value = _closed_dict(value, {"environmentNamespace", "referenceId", "revision"})
        try:
            return cls(value["environmentNamespace"], value["referenceId"], value["revision"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class ResourceMaterialDescriptor:
    resource_ref: ResourceRef
    material_type: str
    schema_version: str
    content_digest: str
    lifetime: MaterialLifetime
    access_mode: MaterialAccessMode
    provenance_ref: MaterialEvidenceRef
    evidence_ref: MaterialEvidenceRef

    def __post_init__(self) -> None:
        if type(self.resource_ref) is not ResourceRef:
            _invalid()
        object.__setattr__(self, "resource_ref", ResourceRef.from_dict(self.resource_ref.to_dict()))
        if type(self.material_type) is not str or not _MATERIAL_TYPE.fullmatch(self.material_type):
            _invalid()
        _schema_version(self.schema_version)
        _content_digest(self.content_digest)
        object.__setattr__(self, "lifetime", _enum_value(MaterialLifetime, self.lifetime))
        object.__setattr__(self, "access_mode", _enum_value(MaterialAccessMode, self.access_mode))
        for name in ("provenance_ref", "evidence_ref"):
            ref = getattr(self, name)
            if type(ref) is not MaterialEvidenceRef:
                _invalid()
            object.__setattr__(self, name, MaterialEvidenceRef.from_dict(ref.to_dict()))
        _environment_equal(self.resource_ref.environment_namespace,
                           self.provenance_ref.environment_namespace, self.evidence_ref.environment_namespace)

    def to_dict(self) -> dict:
        return {"resourceRef": self.resource_ref.to_dict(), "materialType": self.material_type,
                "schemaVersion": self.schema_version, "contentDigest": self.content_digest,
                "lifetime": self.lifetime.value, "accessMode": self.access_mode.value,
                "provenanceRef": self.provenance_ref.to_dict(), "evidenceRef": self.evidence_ref.to_dict()}

    @property
    def descriptor_digest(self) -> str:
        return _hash_facts(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> ResourceMaterialDescriptor:
        value = _closed_dict(value, {"resourceRef", "materialType", "schemaVersion", "contentDigest",
                                     "lifetime", "accessMode", "provenanceRef", "evidenceRef"})
        try:
            return cls(ResourceRef.from_dict(value["resourceRef"]), value["materialType"],
                       value["schemaVersion"], value["contentDigest"], value["lifetime"],
                       value["accessMode"], MaterialEvidenceRef.from_dict(value["provenanceRef"]),
                       MaterialEvidenceRef.from_dict(value["evidenceRef"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialRequest:
    resource_ref: ResourceRef
    provider_pin: MaterialProviderPin
    target: MaterialUseTarget
    descriptor_digest: str
    correlation: MaterialCorrelation

    def __post_init__(self) -> None:
        if (type(self.resource_ref) is not ResourceRef or type(self.provider_pin) is not MaterialProviderPin
                or type(self.target) is not MaterialUseTarget or type(self.correlation) is not MaterialCorrelation):
            _invalid()
        object.__setattr__(self, "resource_ref", ResourceRef.from_dict(self.resource_ref.to_dict()))
        object.__setattr__(self, "provider_pin", MaterialProviderPin.from_dict(self.provider_pin.to_dict()))
        object.__setattr__(self, "target", MaterialUseTarget.from_dict(self.target.to_dict()))
        object.__setattr__(self, "correlation", MaterialCorrelation.from_dict(self.correlation.to_dict()))
        _digest(self.descriptor_digest)
        _environment_equal(self.resource_ref.environment_namespace,
                           self.provider_pin.owner_activation.environment,
                           self.target.node_ref.environment,
                           self.target.directory_binding_ref.environment_namespace)
        if self.provider_pin.provider_id != self.resource_ref.provider_id:
            _invalid()
        if self.correlation.input_digest != self.input_digest:
            _invalid()

    def input_facts(self) -> dict:
        return {"resourceRef": self.resource_ref.to_dict(), "providerPin": self.provider_pin.to_dict(),
                "target": self.target.to_dict(), "descriptorDigest": self.descriptor_digest}

    @property
    def input_digest(self) -> str:
        return _hash_facts(self.input_facts())

    def to_dict(self) -> dict:
        return {**self.input_facts(), "correlation": self.correlation.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> MaterialRequest:
        value = _closed_dict(value, {"resourceRef", "providerPin", "target", "descriptorDigest", "correlation"})
        try:
            return cls(ResourceRef.from_dict(value["resourceRef"]),
                       MaterialProviderPin.from_dict(value["providerPin"]),
                       MaterialUseTarget.from_dict(value["target"]), value["descriptorDigest"],
                       MaterialCorrelation.from_dict(value["correlation"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialLeaseRef:
    lease_id: str
    resource_ref: ResourceRef
    provider_pin: MaterialProviderPin
    target: MaterialUseTarget
    acquisition_correlation: MaterialCorrelation

    def __post_init__(self) -> None:
        _opaque(self.lease_id)
        if (type(self.resource_ref) is not ResourceRef or type(self.provider_pin) is not MaterialProviderPin
                or type(self.target) is not MaterialUseTarget
                or type(self.acquisition_correlation) is not MaterialCorrelation):
            _invalid()
        object.__setattr__(self, "resource_ref", ResourceRef.from_dict(self.resource_ref.to_dict()))
        object.__setattr__(self, "provider_pin", MaterialProviderPin.from_dict(self.provider_pin.to_dict()))
        object.__setattr__(self, "target", MaterialUseTarget.from_dict(self.target.to_dict()))
        object.__setattr__(self, "acquisition_correlation",
                           MaterialCorrelation.from_dict(self.acquisition_correlation.to_dict()))
        _environment_equal(self.resource_ref.environment_namespace,
                           self.provider_pin.owner_activation.environment,
                           self.target.node_ref.environment,
                           self.target.directory_binding_ref.environment_namespace)
        if self.provider_pin.provider_id != self.resource_ref.provider_id:
            _invalid()

    def to_dict(self) -> dict:
        return {"leaseId": self.lease_id, "resourceRef": self.resource_ref.to_dict(),
                "providerPin": self.provider_pin.to_dict(), "target": self.target.to_dict(),
                "acquisitionCorrelation": self.acquisition_correlation.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> MaterialLeaseRef:
        value = _closed_dict(value, {"leaseId", "resourceRef", "providerPin", "target", "acquisitionCorrelation"})
        try:
            return cls(value["leaseId"], ResourceRef.from_dict(value["resourceRef"]),
                       MaterialProviderPin.from_dict(value["providerPin"]),
                       MaterialUseTarget.from_dict(value["target"]),
                       MaterialCorrelation.from_dict(value["acquisitionCorrelation"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialReceipt:
    resource_ref: ResourceRef
    provider_pin: MaterialProviderPin
    target: MaterialUseTarget
    correlation: MaterialCorrelation
    descriptor_digest: str
    immutable_material_ref: MaterialObjectRef
    content_digest: str
    material_type: str
    schema_version: str
    lease_ref: MaterialLeaseRef
    provenance_ref: MaterialEvidenceRef
    evidence_ref: MaterialEvidenceRef

    def __post_init__(self) -> None:
        if (type(self.resource_ref) is not ResourceRef or type(self.provider_pin) is not MaterialProviderPin
                or type(self.target) is not MaterialUseTarget or type(self.correlation) is not MaterialCorrelation
                or type(self.immutable_material_ref) is not MaterialObjectRef
                or type(self.lease_ref) is not MaterialLeaseRef
                or type(self.provenance_ref) is not MaterialEvidenceRef
                or type(self.evidence_ref) is not MaterialEvidenceRef):
            _invalid()
        for name, value, decoder in (
            ("resource_ref", self.resource_ref, ResourceRef.from_dict),
            ("provider_pin", self.provider_pin, MaterialProviderPin.from_dict),
            ("target", self.target, MaterialUseTarget.from_dict),
            ("correlation", self.correlation, MaterialCorrelation.from_dict),
            ("immutable_material_ref", self.immutable_material_ref, MaterialObjectRef.from_dict),
            ("lease_ref", self.lease_ref, MaterialLeaseRef.from_dict),
            ("provenance_ref", self.provenance_ref, MaterialEvidenceRef.from_dict),
            ("evidence_ref", self.evidence_ref, MaterialEvidenceRef.from_dict),
        ):
            object.__setattr__(self, name, decoder(value.to_dict()))
        _digest(self.descriptor_digest)
        _content_digest(self.content_digest)
        if type(self.material_type) is not str or not _MATERIAL_TYPE.fullmatch(self.material_type):
            _invalid()
        _schema_version(self.schema_version)
        lease = self.lease_ref
        if (self.resource_ref != lease.resource_ref or self.provider_pin != lease.provider_pin
                or self.target != lease.target or self.correlation != lease.acquisition_correlation):
            _invalid()
        # Recompute the original acquire input identity from the receipt facts;
        # a provider report cannot substitute a different step digest.
        MaterialRequest(self.resource_ref, self.provider_pin, self.target,
                        self.descriptor_digest, self.correlation)
        _environment_equal(self.resource_ref.environment_namespace,
                           self.immutable_material_ref.environment_namespace,
                           self.provenance_ref.environment_namespace, self.evidence_ref.environment_namespace)

    def to_dict(self) -> dict:
        return {"resourceRef": self.resource_ref.to_dict(), "providerPin": self.provider_pin.to_dict(),
                "target": self.target.to_dict(), "correlation": self.correlation.to_dict(),
                "descriptorDigest": self.descriptor_digest,
                "immutableMaterialRef": self.immutable_material_ref.to_dict(),
                "contentDigest": self.content_digest, "materialType": self.material_type,
                "schemaVersion": self.schema_version, "leaseRef": self.lease_ref.to_dict(),
                "provenanceRef": self.provenance_ref.to_dict(), "evidenceRef": self.evidence_ref.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> MaterialReceipt:
        value = _closed_dict(value, {"resourceRef", "providerPin", "target", "correlation", "descriptorDigest",
                                     "immutableMaterialRef", "contentDigest", "materialType", "schemaVersion",
                                     "leaseRef", "provenanceRef", "evidenceRef"})
        try:
            return cls(ResourceRef.from_dict(value["resourceRef"]),
                       MaterialProviderPin.from_dict(value["providerPin"]),
                       MaterialUseTarget.from_dict(value["target"]),
                       MaterialCorrelation.from_dict(value["correlation"]), value["descriptorDigest"],
                       MaterialObjectRef.from_dict(value["immutableMaterialRef"]), value["contentDigest"],
                       value["materialType"], value["schemaVersion"],
                       MaterialLeaseRef.from_dict(value["leaseRef"]),
                       MaterialEvidenceRef.from_dict(value["provenanceRef"]),
                       MaterialEvidenceRef.from_dict(value["evidenceRef"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialResult:
    outcome: MaterialOutcome
    correlation: MaterialCorrelation
    receipt: MaterialReceipt | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", _enum_value(MaterialOutcome, self.outcome))
        if type(self.correlation) is not MaterialCorrelation:
            _invalid()
        object.__setattr__(self, "correlation", MaterialCorrelation.from_dict(self.correlation.to_dict()))
        if self.outcome is MaterialOutcome.SUCCESS:
            if type(self.receipt) is not MaterialReceipt or self.error_code is not None:
                _invalid()
            object.__setattr__(self, "receipt", MaterialReceipt.from_dict(self.receipt.to_dict()))
            if self.receipt.correlation != self.correlation:
                _invalid()
        elif self.outcome is MaterialOutcome.REFUSED:
            if self.receipt is not None:
                _invalid()
            _error_code(self.error_code)
        elif self.receipt is not None or self.error_code is not None:
            _invalid()

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "correlation": self.correlation.to_dict(),
                "receipt": None if self.receipt is None else self.receipt.to_dict(),
                "errorCode": self.error_code}

    @classmethod
    def from_dict(cls, value: object) -> MaterialResult:
        value = _closed_dict(value, {"outcome", "correlation", "receipt", "errorCode"})
        try:
            return cls(value["outcome"], MaterialCorrelation.from_dict(value["correlation"]),
                       None if value["receipt"] is None else MaterialReceipt.from_dict(value["receipt"]),
                       value["errorCode"])
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialReleaseRequest:
    lease_ref: MaterialLeaseRef
    correlation: MaterialCorrelation

    def __post_init__(self) -> None:
        if type(self.lease_ref) is not MaterialLeaseRef or type(self.correlation) is not MaterialCorrelation:
            _invalid()
        object.__setattr__(self, "lease_ref", MaterialLeaseRef.from_dict(self.lease_ref.to_dict()))
        object.__setattr__(self, "correlation", MaterialCorrelation.from_dict(self.correlation.to_dict()))
        acquisition = self.lease_ref.acquisition_correlation
        if ((self.correlation.operation_ref, self.correlation.step_id,
             self.correlation.recovery_correlation)
                == (acquisition.operation_ref, acquisition.step_id,
                    acquisition.recovery_correlation)):
            _invalid()
        if self.correlation.input_digest != self.input_digest:
            _invalid()

    def input_facts(self) -> dict:
        return {"leaseRef": self.lease_ref.to_dict()}

    @property
    def input_digest(self) -> str:
        return _hash_facts(self.input_facts())

    def to_dict(self) -> dict:
        return {"leaseRef": self.lease_ref.to_dict(), "correlation": self.correlation.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> MaterialReleaseRequest:
        value = _closed_dict(value, {"leaseRef", "correlation"})
        try:
            return cls(MaterialLeaseRef.from_dict(value["leaseRef"]),
                       MaterialCorrelation.from_dict(value["correlation"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialReleaseReceipt:
    lease_ref: MaterialLeaseRef
    correlation: MaterialCorrelation
    evidence_ref: MaterialEvidenceRef

    def __post_init__(self) -> None:
        if (type(self.lease_ref) is not MaterialLeaseRef
                or type(self.correlation) is not MaterialCorrelation
                or type(self.evidence_ref) is not MaterialEvidenceRef):
            _invalid()
        object.__setattr__(self, "lease_ref", MaterialLeaseRef.from_dict(self.lease_ref.to_dict()))
        object.__setattr__(self, "correlation", MaterialCorrelation.from_dict(self.correlation.to_dict()))
        object.__setattr__(self, "evidence_ref", MaterialEvidenceRef.from_dict(self.evidence_ref.to_dict()))
        if self.evidence_ref.environment_namespace != self.lease_ref.resource_ref.environment_namespace:
            _invalid()
        # A release receipt must bind the exact new release step and full
        # lease identity, without replacing the lease's acquisition correlation.
        MaterialReleaseRequest(self.lease_ref, self.correlation)

    def to_dict(self) -> dict:
        return {"leaseRef": self.lease_ref.to_dict(), "correlation": self.correlation.to_dict(),
                "evidenceRef": self.evidence_ref.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> MaterialReleaseReceipt:
        value = _closed_dict(value, {"leaseRef", "correlation", "evidenceRef"})
        try:
            return cls(MaterialLeaseRef.from_dict(value["leaseRef"]),
                       MaterialCorrelation.from_dict(value["correlation"]),
                       MaterialEvidenceRef.from_dict(value["evidenceRef"]))
        except (TypeError, ValueError):
            _invalid()


@dataclass(frozen=True)
class MaterialReleaseResult:
    outcome: MaterialOutcome
    correlation: MaterialCorrelation
    receipt: MaterialReleaseReceipt | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", _enum_value(MaterialOutcome, self.outcome))
        if type(self.correlation) is not MaterialCorrelation:
            _invalid()
        object.__setattr__(self, "correlation", MaterialCorrelation.from_dict(self.correlation.to_dict()))
        if self.outcome is MaterialOutcome.SUCCESS:
            if type(self.receipt) is not MaterialReleaseReceipt or self.error_code is not None:
                _invalid()
            object.__setattr__(self, "receipt", MaterialReleaseReceipt.from_dict(self.receipt.to_dict()))
            if self.receipt.correlation != self.correlation:
                _invalid()
        elif self.outcome is MaterialOutcome.REFUSED:
            if self.receipt is not None:
                _invalid()
            _error_code(self.error_code)
        elif self.receipt is not None or self.error_code is not None:
            _invalid()

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "correlation": self.correlation.to_dict(),
                "receipt": None if self.receipt is None else self.receipt.to_dict(),
                "errorCode": self.error_code}

    @classmethod
    def from_dict(cls, value: object) -> MaterialReleaseResult:
        value = _closed_dict(value, {"outcome", "correlation", "receipt", "errorCode"})
        try:
            return cls(value["outcome"], MaterialCorrelation.from_dict(value["correlation"]),
                       None if value["receipt"] is None else MaterialReleaseReceipt.from_dict(value["receipt"]),
                       value["errorCode"])
        except (TypeError, ValueError):
            _invalid()


@runtime_checkable
class AuthorizedMaterialProvider(Protocol):
    @property
    def material_capability(self) -> MaterialCapability: ...

    def describe_material(self, resource_ref: ResourceRef, principal: str) -> ResourceMaterialDescriptor: ...

    def resolve_material(self, request: MaterialRequest,
                         invocation: InvocationContext) -> MaterialResult: ...

    def query_material(self, request: MaterialRequest | MaterialReleaseRequest,
                       invocation: InvocationContext) -> MaterialResult | MaterialReleaseResult: ...

    def release_material(self, request: MaterialReleaseRequest,
                         invocation: InvocationContext) -> MaterialReleaseResult: ...


def read_material_capability(provider: object) -> MaterialCapability:
    """Return a detached declaration after structural checks only.

    This function never calls a material operation and never returns the
    provider object. Absence of the optional property remains distinguishable
    from a malformed claimed capability.
    """
    try:
        declared = inspect.getattr_static(provider, "material_capability", _MISSING)
    except Exception:
        raise MaterialContractError() from None
    if declared is _MISSING:
        raise MaterialUnavailable()
    try:
        capability = getattr(provider, "material_capability")
    except Exception:
        raise MaterialContractError() from None
    if type(capability) is not MaterialCapability:
        raise MaterialContractError()
    for name in ("describe", "acquire", "release", "reconcile",
                 "describe_material", "resolve_material", "query_material", "release_material"):
        try:
            method = getattr(provider, name, None)
        except Exception:
            raise MaterialContractError() from None
        if not callable(method):
            raise MaterialContractError()
    try:
        return MaterialCapability.from_dict(capability.to_dict())
    except Exception:
        raise MaterialContractError() from None


__all__ = [
    "AGENT_MATERIAL_CONTRACT_VERSION", "MaterialContractError", "MaterialUnavailable",
    "MaterialCapability", "MaterialLifetime", "MaterialAccessMode", "MaterialReleaseRecovery",
    "MaterialOutcome", "ResourceRef", "MaterialProviderPin", "MaterialUseTarget",
    "MaterialCorrelation", "MaterialObjectRef", "MaterialEvidenceRef", "ResourceMaterialDescriptor",
    "MaterialRequest", "MaterialLeaseRef", "MaterialReceipt", "MaterialResult",
    "MaterialReleaseRequest", "MaterialReleaseResult", "AuthorizedMaterialProvider",
    "MaterialReleaseReceipt", "read_material_capability",
]
