"""Agent lifecycle contribution payload on the existing CoreRegistry.

C1 CoreContributionSet keeps its frozen three fields; this dedicated payload
is an additive subtype, exported only through pacthold.agents.public.
"""
from dataclasses import dataclass
from ..core.registration import CoreContributionSet, _validate_provider_shape
from ..core.errors import CoreDTOError
from ..core.lifecycle import (
    RuntimeProviderDescriptor, RuntimeProvider, AdmittedRuntimeProvider,
    RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS, PURE_READ_METHODS,
)


@dataclass(frozen=True)
class AgentContributionSet(CoreContributionSet):
    agent_runtime_providers: tuple[object, ...] = ()

    def __post_init__(self):
        super().__post_init__()
        value = self.agent_runtime_providers
        if not isinstance(value, (tuple, list)):
            raise CoreDTOError("Agent runtime providers must be a sequence")
        object.__setattr__(self, "agent_runtime_providers", tuple(value))
        for provider in self.agent_runtime_providers:
            if any(hasattr(provider, name) for name in ("owner", "owner_activation", "generation")):
                raise CoreDTOError("RuntimeProvider may not declare trusted owner identity")
            if type(getattr(provider, "descriptor", None)) is not RuntimeProviderDescriptor:
                raise CoreDTOError("RuntimeProvider requires its versioned descriptor")
            _validate_provider_shape(provider, RUNTIME_METHODS + tuple(v for v in PURE_READ_METHODS if v in provider.descriptor.supported_methods), "Agent runtime")

