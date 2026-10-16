"""Read-only metadata for a ResourceProvider admitted by the CoreRegistry.

This view intentionally carries no provider object or effectful callable. It
does not imply that any resource reference has been routed or acquired.
"""
from __future__ import annotations

from dataclasses import dataclass
import inspect

from ordessa_execution_api.environment.identity import ActivationRef

from ordessa_units.definitions.materials import ResourceProviderDescriptor

AGENT_MATERIAL_CONTRACT_VERSION = "agent-material/1"


class MaterialContractError(ValueError):
    """A material DTO or optional-provider declaration violates its contract."""

    code = "MATERIAL_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__("material contract is invalid")


_MISSING = object()


def snapshot_material_capability(provider: object) -> "MaterialCapability | None":
    """Copy and validate an explicitly declared capability without effects.

    Static absence is the legacy C1 case. A declared property that cannot be
    read, or any malformed claim, is an invalid material contract.
    """
    try:
        declaration = inspect.getattr_static(provider, "material_capability", _MISSING)
    except Exception:
        raise MaterialContractError() from None
    if declaration is _MISSING:
        return None
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
        return MaterialCapability(
            capability.contract_version,
            capability.lifetimes,
            capability.query_acquire,
            capability.release_recovery,
        )
    except Exception:
        raise MaterialContractError() from None


@dataclass(frozen=True)
class MaterialCapability:
    """Pure versioned declaration owned by Units; same-registry reuse."""

    contract_version: str
    lifetimes: tuple[str, ...]
    query_acquire: bool
    release_recovery: str

    def __post_init__(self) -> None:
        if (type(self.contract_version) is not str
                or self.contract_version != AGENT_MATERIAL_CONTRACT_VERSION
                or type(self.lifetimes) is not tuple
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
    """Read-only admission metadata for one registered ResourceProvider.

    ``owner_activation`` semantics also anchor the consumer-pin trust source
    (material-authorized-handoff-freeze §1): a ``MaterialConsumerPin`` must be
    copied from admission-side trusted host evidence of this shape (or from
    the configuration-admission side's ``owner_activation``), never from a
    requestor's self-report. Field-wise comparison is the enforcement;
    different generation is refused (cold recovery gap: same generation only).
    """

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


@dataclass(frozen=True)
class AdmittedMaterialProviderMetadata:
    resource_provider: AdmittedResourceProviderMetadata
    capability: MaterialCapability

    def __post_init__(self) -> None:
        if type(self.resource_provider) is not AdmittedResourceProviderMetadata:
            raise ValueError("admitted ResourceProvider metadata is required")
        if type(self.capability) is not MaterialCapability:
            raise MaterialContractError()
        resource_provider = AdmittedResourceProviderMetadata(
            self.resource_provider.owner_activation,
            self.resource_provider.descriptor,
            self.resource_provider.supported_contract_ids,
        )
        capability = MaterialCapability(
            self.capability.contract_version,
            self.capability.lifetimes,
            self.capability.query_acquire,
            self.capability.release_recovery,
        )
        object.__setattr__(self, "resource_provider", resource_provider)
        object.__setattr__(self, "capability", capability)
