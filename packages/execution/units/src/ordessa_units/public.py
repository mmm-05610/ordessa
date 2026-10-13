"""Unit public composition, sharing the caller's sole governance Environment."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ordessa_execution_api.environment import GuaranteeUnavailableError, IdentityMismatchError

from ordessa_execution_agents.profiles import (
    ProfileService, Profile, ProfileRevision, ProfileRevisionRef, ProfileContent,
    ConfigurationDeclaration, ProfileNotFound, ProfileRevisionConflict, ProfileValidationError,
)
from ordessa_execution_agents.profiles.definitions.validation import AGENT_CONTRACT_VERSION
from ordessa_execution_agents.profiles.definitions.schemas.profile_wire import profile_wire_sections
from ordessa_execution_agents.harness.contracts.schemas.wire_access import access_wire_sections
from ordessa_units.bindings.wire import bindings_wire_sections
from ordessa_units.configuration.wire import configuration_wire_sections
from ordessa_units.lifecycle.wire import lifecycle_wire_sections
from ordessa_units.admission.wire import admission_wire_sections
from ordessa_units.channels.wire import channels_wire_sections
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.bindings.publication import NodePublication, encode_node_ref, decode_node_ref
from ordessa_units.admission.operations import AgentOperations, AgentUnresolvedSnapshot, OperationNotFound
from ordessa_units.configuration.service import AgentConfiguration
from ordessa_execution_agents.harness.providers.registry.catalog import AgentProviders
from ordessa_units.configuration.offers import AgentConfigurationOffers


# --- Agent wire contract aggregation: version selection + owner-fragment composition ---
AGENT_MANAGEMENT_CONTRACT_VERSION = "agent-assembly/3"


def wire_contract(version=AGENT_CONTRACT_VERSION) -> dict:
    """Return an isolated JSON view; callers cannot mutate core authority.

    Composes each owner's wire fragment (Profile format, framework-access formats,
    unit instance-management formats) plus the shared wire envelope. Holds no
    instance-operation logic and no business dependency.
    """
    if version not in (AGENT_CONTRACT_VERSION, AGENT_MANAGEMENT_CONTRACT_VERSION):
        raise ValueError("unsupported Agent wire contract version")
    profile = profile_wire_sections()
    access = access_wire_sections()
    value = {"contractVersion": version, "transport": "wire/1",
             "requestKeyScope": ["environmentNamespace", "principalScope", "requestId"],
             "profileRef": profile["profileRef"],
             "results": dict(profile["results"]),
             "methods": dict(profile["methods"])}
    value["methods"].update(access["legacy_methods"])
    if version == AGENT_MANAGEMENT_CONTRACT_VERSION:
        bindings = bindings_wire_sections()
        configuration = configuration_wire_sections()
        lifecycle = lifecycle_wire_sections()
        admission = admission_wire_sections()
        channels = channels_wire_sections()
        for fragment in (bindings, lifecycle, admission):
            value["results"].update(fragment["results"])
        for fragment in (bindings, configuration, lifecycle, admission, channels):
            value["methods"].update(fragment["methods"])
        value["methods"].update(access["management_methods"])
        value["configurationChange"] = configuration["configurationChange"]
        value["nodeRef"] = bindings["nodeRef"]
        value["configurationSnapshot"] = configuration["configurationSnapshot"]
        value["profileSource"] = bindings["profileSource"]
        value["omissionError"] = configuration["omissionError"]
    return value


def wire_schema_digest(version=AGENT_CONTRACT_VERSION) -> str:
    value = json.dumps(wire_contract(version), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
from ordessa_units.admission.material_contracts import (
    AdmittedResourceProviderMetadata, AdmittedMaterialProviderMetadata,
)
from ordessa_execution_agents.harness.definitions.configuration_providers import (
    CONFIGURATION_PROVIDER_VERSION, CONFIGURATION_METHODS, ConfigurationRoute,
    ConfigurationProviderDescriptor, ConfigurationProviderPin,
    AdmittedConfigurationProviderMetadata,
    ConfigurationContractError as ConfigurationProviderContractError,
)
from ordessa_units.bindings.assembly import AgentAssembly, PreparationContext, PreparationObservation, PreparationContextPort, PreparationObservationPort
from ordessa_units.lifecycle.service import AgentLifecycle, LifecycleObservation, LifecycleObservationPort
from ordessa_units.channels.reservations import (
    CapturedInputRef, CapturedInputEvidence, ControlledInputCapturePort,
    NativeInputState, SessionlessNativeInputState, NativeInputStatePort,
    FirstInputObservation, FirstInputObservationPort, ManagedInputReservations,
)
from ordessa_units.admission.invocation import (
    InvocationContext, InvocationVerifier, InvocationAuthorityRefused,
    InvocationIssuer, InvocationGrant, InvocationAuthorityPort,
    InvocationCurrentState, InvocationCurrentStatePort,
)
from ordessa_units.bindings.material_operations import (
    AGENT_MATERIAL_OPERATION_CONTRACT_VERSION, MaterialOperations,
    material_provider_ref, material_invocation_target,
    material_operation_facts, material_reservation_usages,
)
from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_execution_agents.harness.transport import EffectWriteGuard, EffectWriteRefused
from ordessa_units.channels.contracts import (
    ManagedInputOutcome, WorkspaceExecutionEvidence, WorkspaceExecutionPort,
    plain_json_mapping,
)


@dataclass(frozen=True)
class UnitServices:
    profiles: ProfileService
    nodes: NodePublication
    configuration: AgentConfiguration
    providers: AgentProviders
    configuration_offers: AgentConfigurationOffers
    assembly: AgentAssembly
    lifecycle: AgentLifecycle
    managed_inputs: ManagedInputReservations
    operations: AgentOperations
    material_operations: MaterialOperations
    unit_manager: object | None = None

    def guard_unit_selection(self, unit_ref, *, expected_profile_revision,
                             query_invocation, query_input_digest, require_live):
        """Guard a fixed Profile/query against original Unit lifecycle replacement.

        ``require_live=False`` remains a historical read-time receipt. The live
        context retains a process-local Unit fence through the caller's scope.
        """
        from .bindings.dispatch_selection import guard_unit_selection
        return guard_unit_selection(self, unit_ref, expected_profile_revision=expected_profile_revision,
            query_invocation=query_invocation, query_input_digest=query_input_digest, require_live=require_live)

    def snapshot_live_unit_selection(self, unit_ref, *, expected_profile_revision,
                                     expected_directory_binding_ref, query_invocation,
                                     query_input_digest):
        """Authorized actual live-source snapshot; no dispatch or COMMIT guard."""
        from .bindings.dispatch_selection import snapshot_live_unit_selection
        return snapshot_live_unit_selection(self, unit_ref,
            expected_profile_revision=expected_profile_revision,
            expected_directory_binding_ref=expected_directory_binding_ref,
            query_invocation=query_invocation, query_input_digest=query_input_digest)

    def authorize_acp_turn_query(self, request, unit_ref, operation_ref, *, expected_prompt_input_digest):
        """Reserve an original read recipe and issue through this owner's issuer."""
        from .bindings.dispatch_selection import authorize_acp_turn_query
        return authorize_acp_turn_query(self, request, unit_ref, operation_ref,
            expected_prompt_input_digest=expected_prompt_input_digest)


def unit_services(environment, *, invocation_issuer=None, node_evidence_port=None,
                   preparation_context_port=None, preparation_observation_port=None,
                   lifecycle_observation_port=None, input_capture_port=None,
                   native_input_state_port=None, first_input_observation_port=None,
                   owner_ports: AgentOwnerPorts | None = None) -> UnitServices:
    """Bootstrap the sole execution-owned catalog on the existing Environment.

    No plugin activation, native process or second Environment is created.
    Optional storage/policy availability is checked at each operation.
    """
    unit_manager = None
    explicit_ports = (invocation_issuer, node_evidence_port, preparation_context_port,
                      preparation_observation_port, lifecycle_observation_port,
                      input_capture_port, native_input_state_port,
                      first_input_observation_port)
    if owner_ports is not None:
        if any(port is not None for port in explicit_ports):
            raise ValueError("owner_ports cannot be combined with individual Agent ports")
        if not isinstance(owner_ports, AgentOwnerPorts):
            raise TypeError("owner_ports must be AgentOwnerPorts")
        owner_ports.validate_for(environment)
        unit_manager = owner_ports.unit_manager
        invocation_issuer = owner_ports.issuer
        node_evidence_port = owner_ports.node_evidence_port
        if unit_manager is not None:
            from ordessa_units.bindings.manager_evidence import UnitOwnerEvidence
            existing = getattr(environment, "_agent_services", None)
            adapter = (existing.lifecycle._observation_port
                       if type(existing) is UnitServices and existing.unit_manager is unit_manager
                       else UnitOwnerEvidence(unit_manager))
            for port in (owner_ports.node_evidence_port, owner_ports.preparation_observation_port,
                         owner_ports.lifecycle_observation_port):
                if port is not None and (type(port) is not UnitOwnerEvidence
                                         or port.manager is not unit_manager):
                    raise ValueError("Manager evidence ports must read the same original Unit owner")
            node_evidence_port = node_evidence_port or adapter
        preparation_context_port = owner_ports.preparation_context_port
        preparation_observation_port = owner_ports.preparation_observation_port
        if unit_manager is not None:
            preparation_observation_port = preparation_observation_port or adapter
        lifecycle_observation_port = owner_ports.lifecycle_observation_port
        if unit_manager is not None:
            lifecycle_observation_port = lifecycle_observation_port or adapter
        input_capture_port = owner_ports.input_capture_port
        native_input_state_port = owner_ports.native_input_state_port
        first_input_observation_port = owner_ports.first_input_observation_port
    with environment._admission_lock:
        environment._check_open()
        services = getattr(environment, "_agent_services", None)
        if services is None:
            nodes = NodePublication(environment, evidence_port=node_evidence_port)
            profiles = ProfileService(environment)
            services = UnitServices(profiles, nodes,
                AgentConfiguration(environment, nodes, invocation_issuer=invocation_issuer),
                AgentProviders(environment), AgentConfigurationOffers(environment),
                AgentAssembly(environment, profiles, nodes,
                    invocation_issuer=invocation_issuer, context_port=preparation_context_port,
                    observation_port=preparation_observation_port, unit_manager=unit_manager),
                AgentLifecycle(environment, nodes, invocation_issuer=invocation_issuer,
                    observation_port=lifecycle_observation_port, unit_manager=unit_manager),
                ManagedInputReservations(environment, nodes, capture_port=input_capture_port,
                    native_state_port=native_input_state_port,
                    first_input_observation_port=first_input_observation_port,
                    invocation_issuer=invocation_issuer),
                AgentOperations(environment, nodes),
                MaterialOperations(environment, invocation_issuer=invocation_issuer), unit_manager)
            environment._agent_services = services
            environment._agent_owner_ports = owner_ports
        elif getattr(environment, "_agent_owner_ports", None) is not None and owner_ports is None and any(
                port is not None for port in explicit_ports):
            raise ValueError("an assembled owner bundle cannot be overridden by individual Agent ports")
        elif owner_ports is not None and getattr(environment, "_agent_owner_ports", None) is not owner_ports:
            raise ValueError("Agent owner bundle must be composed once before use")
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
                    and services.managed_inputs._issuer is not invocation_issuer)
                or (invocation_issuer is not None
                    and services.material_operations._issuer is not invocation_issuer)):
            raise ValueError("Agent service authorities must be composed once before use")
        return services


def composed_profile_service(environment) -> ProfileService:
    """Read the already composed ProfileService of this Environment.

    This is an owner-bound read port: it never calls unit_services, composes a
    default owner, creates a Store, or makes a historical profile admissible.
    """
    with environment._admission_lock:
        environment._check_open()
        services = getattr(environment, "_agent_services", None)
        if type(services) is not UnitServices or type(services.profiles) is not ProfileService:
            raise GuaranteeUnavailableError("original Agent Profile service is not composed")
        profiles = services.profiles
        if profiles._environment is not environment:
            raise GuaranteeUnavailableError("original Agent Profile service is not composed")
        if profiles.environment_namespace != environment.environment_id:
            raise IdentityMismatchError("Profile view owner differs from Environment")
        return profiles


__all__ = ["AGENT_CONTRACT_VERSION", "UnitServices", "unit_services", "composed_profile_service",
           "EffectWriteGuard", "EffectWriteRefused",
           "AgentOperations", "AgentUnresolvedSnapshot", "OperationNotFound",
           "ProfileService", "Profile", "ProfileRevision", "ProfileRevisionRef", "ProfileContent", "ConfigurationDeclaration",
           "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError"]
__all__ += ["AgentOwnerPorts", "AgentProviderView"]
__all__ += ["wire_contract", "wire_schema_digest"]
__all__ += ["AGENT_MANAGEMENT_CONTRACT_VERSION"]
__all__ += ["DirectoryBindingRef"]
__all__ += ["AgentConfiguration", "InvocationContext", "InvocationVerifier"]
__all__ += ["NodePublication", "encode_node_ref", "decode_node_ref"]
__all__ += ["InvocationAuthorityRefused"]
__all__ += ["InvocationIssuer", "InvocationGrant", "InvocationAuthorityPort",
            "InvocationCurrentState", "InvocationCurrentStatePort"]
__all__ += ["AgentProviders"]
__all__ += ["AdmittedResourceProviderMetadata"]
__all__ += ["AdmittedMaterialProviderMetadata"]
__all__ += ["CONFIGURATION_PROVIDER_VERSION", "CONFIGURATION_METHODS",
            "ConfigurationRoute", "ConfigurationProviderDescriptor",
            "ConfigurationProviderPin", "ConfigurationProviderContractError"]
__all__ += ["AdmittedConfigurationProviderMetadata"]
__all__ += ["AgentAssembly", "PreparationContext", "PreparationObservation", "PreparationContextPort", "PreparationObservationPort"]
__all__ += ["AgentLifecycle", "LifecycleObservation", "LifecycleObservationPort"]
__all__ += ["ManagedInputReservations", "CapturedInputRef", "CapturedInputEvidence",
            "ControlledInputCapturePort", "NativeInputState", "SessionlessNativeInputState",
            "NativeInputStatePort", "FirstInputObservation", "FirstInputObservationPort"]
__all__ += ["ManagedInputOutcome", "WorkspaceExecutionEvidence", "WorkspaceExecutionPort",
            "plain_json_mapping"]
from ordessa_execution_agents.harness.providers.registry.contributions import RuntimeProvider, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION, PURE_READ_METHODS
__all__ += ["RuntimeProvider", "RuntimeProviderDescriptor", "RUNTIME_PROVIDER_VERSION", "PURE_READ_METHODS"]
from ordessa_units.configuration.contracts import (
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
from ordessa_units.bindings.materials import (
    AGENT_MATERIAL_CONTRACT_VERSION, MaterialContractError, MaterialUnavailable,
    MaterialCapability, MaterialLifetime, MaterialAccessMode, MaterialReleaseRecovery,
    MaterialOutcome, ResourceRef, MaterialProviderPin, MaterialUseTarget, MaterialCorrelation,
    MaterialObjectRef, MaterialEvidenceRef, ResourceMaterialDescriptor, MaterialRequest,
    MaterialLeaseRef, MaterialReceipt, MaterialResult, MaterialReleaseRequest,
    MaterialReleaseReceipt, MaterialReleaseResult, AuthorizedMaterialProvider,
    read_material_capability,
)
__all__ += [
    "AGENT_MATERIAL_CONTRACT_VERSION", "MaterialContractError", "MaterialUnavailable",
    "MaterialCapability", "MaterialLifetime", "MaterialAccessMode", "MaterialReleaseRecovery",
    "MaterialOutcome", "ResourceRef", "MaterialProviderPin", "MaterialUseTarget",
    "MaterialCorrelation", "MaterialObjectRef", "MaterialEvidenceRef", "ResourceMaterialDescriptor",
    "MaterialRequest", "MaterialLeaseRef", "MaterialReceipt", "MaterialResult",
    "MaterialReleaseRequest", "MaterialReleaseReceipt", "MaterialReleaseResult", "AuthorizedMaterialProvider",
    "read_material_capability",
]
from ordessa_units.configuration.references import (
    ConfigurationReference, ConfigurationReferenceExtraction,
    validate_reference_extraction,
)
__all__ += ["ConfigurationReference", "ConfigurationReferenceExtraction",
            "validate_reference_extraction"]
__all__ += ["AGENT_MATERIAL_OPERATION_CONTRACT_VERSION", "MaterialOperations",
            "material_provider_ref", "material_invocation_target",
            "material_operation_facts", "material_reservation_usages"]

from ordessa_units.configuration.offers import (PURE_READ_VERSION, OwnerReadContext, OwnerProposalInput, OwnerConfigurationOfferBatch, OwnerProposalAssessment)
__all__ += ["PURE_READ_VERSION", "OwnerReadContext", "OwnerProposalInput", "OwnerConfigurationOfferBatch", "OwnerProposalAssessment"]

from ordessa_units.admission.owner_selection import (
    AgentOwnerInputs, AgentOwnerUnavailable, FreshUnitFactory, bind_unit_manager, validate_agent_owner_inputs,
    validate_agent_owner_selection,
)
__all__ += ["AgentOwnerInputs", "AgentOwnerUnavailable", "validate_agent_owner_inputs",
            "validate_agent_owner_selection", "FreshUnitFactory", "bind_unit_manager"]

from ordessa_units.management import UnitInstance
from ordessa_units.definitions import UnitDefinition
__all__ += ["UnitInstance", "UnitDefinition"]

from ordessa_units.management import UnitManager, UnitManagementRefused
__all__ += ['UnitManager', 'UnitManagementRefused']

from .admission.context import UnitAdmissionContext
from .admission.fingerprint import ProtectedFingerprintHmac
from .persistence.sqlite import SqliteUnitStore
__all__ += ["UnitAdmissionContext", "SqliteUnitStore", "ProtectedFingerprintHmac"]
