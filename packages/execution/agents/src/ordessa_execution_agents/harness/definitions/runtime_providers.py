"""Versioned lifecycle-provider descriptors consumed by the sole registry.

Dedicated Agent APIs re-export these contracts; the general public facade
never imports the Agent services. No vendor or native protocol lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol, runtime_checkable

from ordessa_execution_api.environment import EnvironmentId
from ordessa_execution_api.environment.identity import ActivationRef
from ordessa_execution_api.environment.operations import sealed_mapping, safe_json

RUNTIME_PROVIDER_VERSION = "agent-runtime/2"
RUNTIME_METHODS = (
    "describe_definition", "inspect_installation", "assess_configuration",
    "plan_preparation", "prepare", "start", "query_step", "describe_access",
    "connect", "inspect_unit", "describe_configuration", "inspect_configuration",
    "apply_configuration", "query_change", "stop", "release", "recover",
)

PURE_READ_METHODS = ("describe_configuration_offers", "assess_configuration_proposal")
PURE_READ_VERSION = "agent-configuration-read/1"

@dataclass(frozen=True)
class RuntimeProviderDescriptor:
    provider_id: str
    contract_version: str
    definition_ref: Mapping
    implementation_digest: str
    supported_methods: tuple[str, ...] = ()
    pure_read_contract_version: str | None = None

    def __post_init__(self):
        if (not isinstance(self.provider_id, str)
                or not re.fullmatch(r"[a-z][a-z0-9._-]{0,127}", self.provider_id)):
            raise ValueError("invalid RuntimeProvider id")
        if self.contract_version != RUNTIME_PROVIDER_VERSION:
            raise ValueError("unsupported RuntimeProvider contract")
        if (not isinstance(self.definition_ref, Mapping)
                or set(self.definition_ref) != {"environmentNamespace", "definitionId", "revision"}):
            raise ValueError("complete definition reference required")
        EnvironmentId(self.definition_ref["environmentNamespace"])
        for name in ("definitionId", "revision"):
            value = self.definition_ref[name]
            if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
                raise ValueError("invalid definition identity")
        if (not isinstance(self.implementation_digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.implementation_digest)):
            raise ValueError("implementation digest required")
        if (not isinstance(self.supported_methods, tuple)
                or len(set(self.supported_methods)) != len(self.supported_methods)
                or any(name not in RUNTIME_METHODS + PURE_READ_METHODS for name in self.supported_methods)):
            raise ValueError("explicit supported lifecycle methods required")
        if self.pure_read_contract_version not in (None, PURE_READ_VERSION):
            raise ValueError("unsupported pure-read contract")
        if any(v in PURE_READ_METHODS for v in self.supported_methods) and self.pure_read_contract_version != PURE_READ_VERSION:
            raise ValueError("pure-read methods require explicit version guarantee")
        object.__setattr__(self, "definition_ref", sealed_mapping(self.definition_ref))

    def snapshot(self):
        return RuntimeProviderDescriptor(self.provider_id, self.contract_version,
                                         self.definition_ref, self.implementation_digest, self.supported_methods, self.pure_read_contract_version)

    def to_dict(self):
        import json
        return {"providerId": self.provider_id, "contractVersion": self.contract_version,
                "definitionRef": json.loads(safe_json(self.definition_ref)),
                "implementationDigest": self.implementation_digest,
                "supportedMethods": list(self.supported_methods),
                **({"pureReadContractVersion": self.pure_read_contract_version} if self.pure_read_contract_version is not None else {})}


@runtime_checkable
class RuntimeProvider(Protocol):
    """Versioned lifecycle contract, not proof that a native unit is ready."""
    descriptor: RuntimeProviderDescriptor

    def describe_definition(self, definition_ref): ...
    def inspect_installation(self, binding): ...
    def assess_configuration(self, manifest, installation, context): ...
    def plan_preparation(self, snapshot, context, correlation): ...
    def prepare(self, plan, invocation_context): ...
    def start(self, prepared_unit, invocation_context): ...
    def query_step(self, correlation, authorized_read_context): ...
    def describe_access(self, unit_ref): ...
    def connect(self, unit_ref, authorized_lease): ...
    def inspect_unit(self, unit_ref): ...
    def describe_configuration(self, unit_ref): ...
    def inspect_configuration(self, unit_ref): ...
    def apply_configuration(self, unit_ref, change_request, invocation_context): ...
    def query_change(self, unit_ref, operation_ref, authorized_read_context): ...
    def stop(self, unit_ref, invocation_context): ...
    def release(self, unit_ref, invocation_context): ...
    def recover(self, native_binding, invocation_context): ...


@dataclass(frozen=True)
class AdmittedRuntimeProvider:
    owner_activation: ActivationRef
    descriptor: RuntimeProviderDescriptor
    provider: RuntimeProvider

    @property
    def provider_ref(self):
        owner = self.owner_activation
        return sealed_mapping({"environmentNamespace": owner.environment,
                "providerId": self.descriptor.provider_id,
                "ownerActivationRef": {"environmentNamespace": owner.environment,
                                       "pluginId": owner.plugin_id, "generation": owner.generation},
                "generation": owner.generation,
                "contractVersion": self.descriptor.contract_version,
                "implementationDigest": self.descriptor.implementation_digest})
