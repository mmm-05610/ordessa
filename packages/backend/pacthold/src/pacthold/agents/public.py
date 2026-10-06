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
from .operations_read import AgentOperations, OperationNotFound
from .management import AgentConfiguration
from .providers import AgentProviders
from .assembly import AgentAssembly, PreparationContext, PreparationObservation, PreparationContextPort, PreparationObservationPort
from .lifecycle import AgentLifecycle, LifecycleObservation, LifecycleObservationPort
from .inputs import (
    CapturedInputRef, CapturedInputEvidence, ControlledInputCapturePort,
    NativeInputState, SessionlessNativeInputState, NativeInputStatePort,
    FirstInputObservation, FirstInputObservationPort, ManagedInputReservations,
)
from .invocation import (
    InvocationContext, InvocationVerifier, InvocationAuthorityRefused,
    InvocationIssuer, InvocationGrant, InvocationAuthorityPort,
    InvocationCurrentState, InvocationCurrentStatePort,
)


@dataclass(frozen=True)
class AgentServices:
    profiles: ProfileCatalog
    nodes: NodePublication
    configuration: AgentConfiguration
    providers: AgentProviders
    assembly: AgentAssembly
    lifecycle: AgentLifecycle
    managed_inputs: ManagedInputReservations
    operations: AgentOperations


def agent_services(environment, *, invocation_issuer=None, node_evidence_port=None,
                   preparation_context_port=None, preparation_observation_port=None,
                   lifecycle_observation_port=None, input_capture_port=None,
                   native_input_state_port=None, first_input_observation_port=None) -> AgentServices:
    """Bootstrap one core-owned catalog on the existing Environment.

    No plugin activation, native process or second Environment is created.
    Optional storage/policy availability is checked at each operation.
    """
    with environment._admission_lock:
        environment._check_open()
        services = getattr(environment, "_agent_services", None)
        if services is None:
            nodes = NodePublication(environment, evidence_port=node_evidence_port)
            profiles = ProfileCatalog(environment)
            services = AgentServices(profiles, nodes,
                AgentConfiguration(environment, nodes, invocation_issuer=invocation_issuer),
                AgentProviders(environment), AgentAssembly(environment, profiles, nodes,
                    invocation_issuer=invocation_issuer, context_port=preparation_context_port,
                    observation_port=preparation_observation_port),
                AgentLifecycle(environment, nodes, invocation_issuer=invocation_issuer,
                    observation_port=lifecycle_observation_port),
                ManagedInputReservations(environment, nodes, capture_port=input_capture_port,
                    native_state_port=native_input_state_port,
                    first_input_observation_port=first_input_observation_port,
                    invocation_issuer=invocation_issuer),
                AgentOperations(environment, nodes))
            environment._agent_services = services
        elif ((invocation_issuer is not None and services.configuration._issuer is not invocation_issuer)
                or (node_evidence_port is not None and services.nodes._evidence_port is not node_evidence_port)
                or (preparation_context_port is not None and services.assembly._context_port is not preparation_context_port)
                or (preparation_observation_port is not None and services.assembly._observation_port is not preparation_observation_port)
                or (lifecycle_observation_port is not None
                    and services.lifecycle._observation_port is not lifecycle_observation_port)
                or (input_capture_port is not None
                    and services.managed_inputs._capture is not input_capture_port)
                or (native_input_state_port is not None
                    and services.managed_inputs._native is not native_input_state_port)
                or (first_input_observation_port is not None
                    and services.managed_inputs._first_observation is not first_input_observation_port)
                or (invocation_issuer is not None
                    and services.managed_inputs._issuer is not invocation_issuer)):
            raise ValueError("Agent service authorities must be composed once before use")
        return services


__all__ = ["AGENT_CONTRACT_VERSION", "AgentServices", "agent_services",
           "AgentOperations", "OperationNotFound",
           "ProfileCatalog", "ProfileCatalogEntry", "ProfileManifest", "ProfileRef",
           "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError"]
__all__ += ["wire_contract", "wire_schema_digest"]
__all__ += ["AGENT_MANAGEMENT_CONTRACT_VERSION"]
__all__ += ["DirectoryBindingRef"]
__all__ += ["AgentConfiguration", "InvocationContext", "InvocationVerifier"]
__all__ += ["NodePublication", "encode_node_ref", "decode_node_ref"]
__all__ += ["InvocationAuthorityRefused"]
__all__ += ["InvocationIssuer", "InvocationGrant", "InvocationAuthorityPort",
            "InvocationCurrentState", "InvocationCurrentStatePort"]
__all__ += ["AgentProviders"]
__all__ += ["AgentAssembly", "PreparationContext", "PreparationObservation", "PreparationContextPort", "PreparationObservationPort"]
__all__ += ["AgentLifecycle", "LifecycleObservation", "LifecycleObservationPort"]
__all__ += ["ManagedInputReservations", "CapturedInputRef", "CapturedInputEvidence",
            "ControlledInputCapturePort", "NativeInputState", "SessionlessNativeInputState",
            "NativeInputStatePort", "FirstInputObservation", "FirstInputObservationPort"]
from .runtime import AgentContributionSet, RuntimeProvider, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
__all__ += ["AgentContributionSet", "RuntimeProvider", "RuntimeProviderDescriptor", "RUNTIME_PROVIDER_VERSION"]
from .configuration import (
    CONFIGURATION_CONTRACT_VERSION, ApplicationPolicy, ConfigurationChangeRequest,
    ConfigurationDescription, ConfigurationSnapshot, ConfigurationItemResult,
    ConfigurationChangeResult, ConfigurationContractError, ConfigurationUnsupported, ConfigurationRevisionConflict, UnitInspection,
    ConfigurationOmissionRefused, ConfigurationConversionRefused,
)
__all__ += ["CONFIGURATION_CONTRACT_VERSION", "ApplicationPolicy", "ConfigurationChangeRequest",
            "ConfigurationDescription", "ConfigurationSnapshot", "ConfigurationItemResult",
            "ConfigurationChangeResult", "ConfigurationContractError", "ConfigurationUnsupported", "UnitInspection",
            "ConfigurationOmissionRefused", "ConfigurationConversionRefused"]
__all__ += ["ConfigurationRevisionConflict"]
