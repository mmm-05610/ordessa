"""Versioned lifecycle-provider descriptors consumed by the sole registry.

Dedicated Agent APIs re-export these contracts; the general public facade
never imports the Agent services. No vendor or native protocol lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol, runtime_checkable

from ordessa_environment_api import EnvironmentId
from ordessa_environment_api.identity import ActivationRef
from ordessa_environment_api.operations import sealed_mapping, safe_json

RUNTIME_PROVIDER_VERSION = "agent-runtime/1"
RUNTIME_METHODS = (
    "describe_definition", "inspect_installation", "assess_configuration",
    "plan_preparation", "prepare", "start", "query_step", "describe_access",
    "connect", "inspect_configuration", "stop", "release", "recover",
)


@dataclass(frozen=True)
class RuntimeProviderDescriptor:
    provider_id: str
    contract_version: str
    definition_ref: Mapping
    implementation_digest: str

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
        object.__setattr__(self, "definition_ref", sealed_mapping(self.definition_ref))

    def snapshot(self):
        return RuntimeProviderDescriptor(self.provider_id, self.contract_version,
                                         self.definition_ref, self.implementation_digest)

    def to_dict(self):
        import json
        return {"providerId": self.provider_id, "contractVersion": self.contract_version,
                "definitionRef": json.loads(safe_json(self.definition_ref)),
                "implementationDigest": self.implementation_digest}


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
    def inspect_configuration(self, unit_ref): ...
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
