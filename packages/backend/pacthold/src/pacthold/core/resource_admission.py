"""Read-only metadata for a ResourceProvider admitted by the CoreRegistry.

This view intentionally carries no provider object or effectful callable. It
does not imply that any resource reference has been routed or acquired.
"""
from __future__ import annotations

from dataclasses import dataclass

from ordessa_environment_api.identity import ActivationRef

from .descriptors import ResourceProviderDescriptor

AGENT_MATERIAL_CONTRACT_VERSION = "agent-material/1"


class MaterialContractError(ValueError):
    """A material DTO or optional-provider declaration violates its contract."""

    code = "MATERIAL_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__("material contract is invalid")


@dataclass(frozen=True)
class MaterialCapability:
    """Pure versioned declaration, kept in core for same-registry reuse."""

    contract_version: str
    lifetimes: tuple[str, ...]
    query_acquire: bool
    release_recovery: str

    def __post_init__(self) -> None:
        if (type(self.contract_version) is not str
                or self.contract_version != AGENT_MATERIAL_CONTRACT_VERSION
                or not isinstance(self.lifetimes, tuple)
                or not self.lifetimes
                or any(type(item) is not str
                       or item not in {"copyComplete", "runtimeRequired", "dynamic"}
                       for item in self.lifetimes)
                or len(set(self.lifetimes)) != len(self.lifetimes)
                or self.lifetimes != tuple(sorted(self.lifetimes))
                or type(self.query_acquire) is not bool
                or type(self.release_recovery) is not str
                or self.release_recovery not in {"queryable", "idempotent", "both", "unsupported"}):
            raise MaterialContractError()

    def to_dict(self) -> dict[str, object]:
        return {"contractVersion": self.contract_version,
                "lifetimes": list(self.lifetimes),
                "queryAcquire": self.query_acquire,
                "releaseRecovery": self.release_recovery}

    @classmethod
    def from_dict(cls, value: object) -> "MaterialCapability":
        if type(value) is not dict or set(value) != {
            "contractVersion", "lifetimes", "queryAcquire", "releaseRecovery"
        } or type(value.get("lifetimes")) is not list:
            raise MaterialContractError()
        try:
            return cls(value["contractVersion"], tuple(value["lifetimes"]),
                       value["queryAcquire"], value["releaseRecovery"])
        except (TypeError, ValueError):
            raise MaterialContractError() from None


@dataclass(frozen=True)
class AdmittedResourceProviderMetadata:
    owner_activation: ActivationRef
    descriptor: ResourceProviderDescriptor
    supported_contract_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.owner_activation, ActivationRef):
            raise ValueError("host owner activation is required")
        object.__setattr__(self, "owner_activation", ActivationRef(
            self.owner_activation.environment,
            self.owner_activation.plugin_id,
            self.owner_activation.generation,
        ))
        if not isinstance(self.descriptor, ResourceProviderDescriptor):
            raise ValueError("admitted resource descriptor is required")
        object.__setattr__(self, "descriptor", ResourceProviderDescriptor(
            self.descriptor.id, self.descriptor.display_name,
            self.descriptor.version, self.descriptor.reconcile_support))
        if (not isinstance(self.supported_contract_ids, tuple)
                or any(not isinstance(item, str) or not item for item in self.supported_contract_ids)
                or self.supported_contract_ids != tuple(sorted(set(self.supported_contract_ids)))):
            raise ValueError("complete sorted supported contract ids are required")
