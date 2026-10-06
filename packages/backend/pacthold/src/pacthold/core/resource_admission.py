"""Read-only metadata for a ResourceProvider admitted by the CoreRegistry.

This view intentionally carries no provider object or effectful callable. It
does not imply that any resource reference has been routed or acquired.
"""
from __future__ import annotations

from dataclasses import dataclass

from ordessa_environment_api.identity import ActivationRef

from .descriptors import ResourceProviderDescriptor


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
