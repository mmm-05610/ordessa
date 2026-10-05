"""Dedicated Agent public face, sharing the caller's sole Environment."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AGENT_CONTRACT_VERSION, ProfileCatalogEntry, ProfileManifest, ProfileRef,
    ProfileNotFound, ProfileRevisionConflict, ProfileValidationError,
)
from .profiles import ProfileCatalog
from .schema import wire_contract, wire_schema_digest, AGENT_MANAGEMENT_CONTRACT_VERSION
from .directory import DirectoryBindingRef
from .nodes import NodePublication, encode_node_ref, decode_node_ref
from .management import AgentConfiguration
from .providers import AgentProviders
from .invocation import InvocationContext, InvocationVerifier, InvocationAuthorityRefused


@dataclass(frozen=True)
class AgentServices:
    profiles: ProfileCatalog
    nodes: NodePublication
    configuration: AgentConfiguration
    providers: AgentProviders


def agent_services(environment, *, invocation_issuer=None, node_evidence_port=None) -> AgentServices:
    """Bootstrap one core-owned catalog on the existing Environment.

    No plugin activation, native process or second Environment is created.
    Optional storage/policy availability is checked at each operation.
    """
    with environment._admission_lock:
        environment._check_open()
        services = getattr(environment, "_agent_services", None)
        if services is None:
            nodes = NodePublication(environment, evidence_port=node_evidence_port)
            services = AgentServices(ProfileCatalog(environment), nodes,
                AgentConfiguration(environment, nodes, invocation_issuer=invocation_issuer),
                AgentProviders(environment))
            environment._agent_services = services
        elif ((invocation_issuer is not None and services.configuration._issuer is not invocation_issuer)
                or (node_evidence_port is not None and services.nodes._evidence_port is not node_evidence_port)):
            raise ValueError("Agent service authorities must be composed once before use")
        return services


__all__ = ["AGENT_CONTRACT_VERSION", "AgentServices", "agent_services",
           "ProfileCatalog", "ProfileCatalogEntry", "ProfileManifest", "ProfileRef",
           "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError"]
__all__ += ["wire_contract", "wire_schema_digest"]
__all__ += ["AGENT_MANAGEMENT_CONTRACT_VERSION"]
__all__ += ["DirectoryBindingRef"]
__all__ += ["AgentConfiguration", "InvocationContext", "InvocationVerifier"]
__all__ += ["NodePublication", "encode_node_ref", "decode_node_ref"]
__all__ += ["InvocationAuthorityRefused"]
__all__ += ["AgentProviders"]
from .runtime import AgentContributionSet, RuntimeProvider, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
__all__ += ["AgentContributionSet", "RuntimeProvider", "RuntimeProviderDescriptor", "RUNTIME_PROVIDER_VERSION"]
from .configuration import (
    CONFIGURATION_CONTRACT_VERSION, ApplicationPolicy, ConfigurationChangeRequest,
    ConfigurationDescription, ConfigurationSnapshot, ConfigurationItemResult,
    ConfigurationChangeResult, ConfigurationContractError, ConfigurationUnsupported, ConfigurationRevisionConflict, UnitInspection,
)
__all__ += ["CONFIGURATION_CONTRACT_VERSION", "ApplicationPolicy", "ConfigurationChangeRequest",
            "ConfigurationDescription", "ConfigurationSnapshot", "ConfigurationItemResult",
            "ConfigurationChangeResult", "ConfigurationContractError", "ConfigurationUnsupported", "UnitInspection"]
__all__ += ["ConfigurationRevisionConflict"]
