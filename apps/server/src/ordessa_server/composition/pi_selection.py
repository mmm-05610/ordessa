"""Select the public Unit owner after the normal product context is ready.

No second context/store, permission implementation, grant issuer or model call.
The runtime's original identity and explicit permission configuration reach
Execution's production builder before core methods are published.
"""
from dataclasses import dataclass
from copy import deepcopy

from ordessa_execution_agents.profiles import ProfileRevisionRef, ProfileService, encode_revision
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.assembly import build_local_unit_owner, UnitRunPermission
from ordessa_units.public import AgentOwnerUnavailable, unit_services, validate_agent_owner_selection
from ordessa_harness_pi import PiAcpHarnessPreparation
from ordessa_harness_pi.configuration.unit_materialization import PiUnitProfileMaterializer

from .agent_owner import _expected_binding, assemble_agent_owner
from ordessa_units.assembly.process_input import UnitProcessInputBinding
from .temporary_process_capability import ExistingOpenCodeInput


@dataclass(frozen=True)
class PiExecutionSelection:
    agent_id: str
    profile_revision: ProfileRevisionRef
    environment_id: str
    environment_provider: str
    environment_isolation: str
    sharing: bool
    model_declaration_id: str
    provider: str
    model: str
    bridge_executable: str
    bridge_sha256: str
    pi_executable: str
    credential_source: str

    def __post_init__(self):
        if (type(self.profile_revision) is not ProfileRevisionRef
                or type(self.sharing) is not bool
                or any(type(value) is not str or not value or value.strip() != value
                       for value in (self.agent_id, self.environment_id,
                                     self.environment_provider, self.environment_isolation,
                                     self.model_declaration_id, self.provider, self.model))):
            raise AgentOwnerUnavailable('Complete fixed Pi selection required')


@dataclass(frozen=True)
class PiExecutionPorts:
    environments: object
    declaration: object
    fingerprint: object
    permission_factory: object
    model_catalogue: tuple
    native_model_definition: object
    acp_turn_opt_in: bool = False
    effect_write_guard_factory: object = None
    defer_effect_write_guard_factory: bool = False
    credential_environment_variable: str = 'OPENCODE_API_KEY'
    callback_approval_factory: object = None
    managed_input_ports: object = None
    agent_journal_reopen: object = None
    restricted_file_tools: bool = False
    approved_check_command: str | None = None
    read_only_file_tools: bool = False
    request_budget: object = None


class SelectedPiExecution:
    def __init__(self, selection, ports):
        self.selection, self.ports = selection, ports
        self._runtime = None
        self._description = None

    def describe(self):
        return deepcopy(self._description)

    def bind_runtime(self, runtime):
        if self._runtime is not None or getattr(runtime, 'units', None) is not None:
            raise AgentOwnerUnavailable('Public Unit service is already bound')
        selection, ports = self.selection, self.ports
        context = runtime.unit_runtime.context
        if context.owner_ports is not None:
            raise AgentOwnerUnavailable('Unit selection requires the original unbound admission context')
        # Normal plugin activation has populated this same Harness catalog.
        profiles = ProfileService(UnitProfileAdmission(context))
        revision = profiles.get_revision(selection.profile_revision)
        if revision.ref != selection.profile_revision:
            raise AgentOwnerUnavailable('Selected immutable Profile differs')
        instance = ports.environments.get(selection.environment_id)
        snapshot = instance.inspect()
        if (instance.identity != selection.environment_id
                or snapshot.provider_id != selection.environment_provider
                or snapshot.phase != 'ready' or snapshot.observation is None
                or snapshot.observation.state != 'running'
                or snapshot.observation.capabilities.isolation != selection.environment_isolation):
            raise AgentOwnerUnavailable('Selected existing Environment or explicit isolation differs')
        materializer = PiUnitProfileMaterializer(
            fixed_revision=revision.ref, harness_definition_ref=ports.declaration.descriptor.definition_ref,
            model_declaration_id=selection.model_declaration_id,
            model_catalogue=ports.model_catalogue,
            credential_environment_variable=ports.credential_environment_variable,
            native_model_definition=ports.native_model_definition)
        encoded = encode_revision(revision)
        route = materializer.selected_launch_configuration(
            {'ref': encoded['ref'], 'manifest': encoded['content']})
        if (route['provider'], route['model']) != (selection.provider, selection.model):
            raise AgentOwnerUnavailable('Fixed Profile differs from the explicit provider/model selection')
        preparation = PiAcpHarnessPreparation(
            bridge_executable=selection.bridge_executable,
            bridge_sha256=selection.bridge_sha256, pi_executable=selection.pi_executable,
            provider=route['provider'], model=route['model'],
            restricted_file_tools=ports.restricted_file_tools,
            approved_check_command=ports.approved_check_command,
            read_only_file_tools=ports.read_only_file_tools,
            request_budget=ports.request_budget)
        permission = ports.permission_factory(runtime=runtime, admission_context=context,
            selection=selection, environment_instance=instance)
        if (type(permission) is not UnitRunPermission
                or permission.agent_id != selection.agent_id
                or permission.profile_revision != revision.ref
                or permission.environment_identity != instance.identity
                or permission.access_authority is not runtime.wire.identity_authority):
            raise AgentOwnerUnavailable('Actual runtime permission differs from fixed Pi selection')

        def process_binding(instance, agent_id, sharing):
            return UnitProcessInputBinding(instance=instance, agent_id=agent_id,
                sharing=sharing, input_source=ExistingOpenCodeInput(selection.credential_source,
                    variable_name=ports.credential_environment_variable),
                variable_name=ports.credential_environment_variable)

        callback_approval = (None if ports.callback_approval_factory is None else
            ports.callback_approval_factory(runtime=runtime, permission=permission,
                                            environment_instance=instance))
        if callback_approval is not None and not callable(getattr(callback_approval, 'authorize', None)):
            raise AgentOwnerUnavailable('Original callback approval port must provide authorize')
        if ports.approved_check_command is not None and (
                callback_approval is None
                or getattr(callback_approval, 'approved_check_command', None) != ports.approved_check_command
                or not callable(getattr(callback_approval, 'scope_guard', None))):
            raise AgentOwnerUnavailable('Exact Pi check command requires matching original callback scope')
        if ports.read_only_file_tools and (
                callback_approval is None
                or getattr(callback_approval, 'approved_check_command', None) is not None
                or not callable(getattr(callback_approval, 'scope_guard', None))):
            raise AgentOwnerUnavailable('Read-only Pi tools require their original callback scope without commands')
        execution = build_local_unit_owner(admission_context=context, permission=permission,
            environment_instance=instance, preparation=preparation, materializer=materializer,
            environment_sharing=selection.sharing, process_binding_factory=process_binding,
            callback_approval=callback_approval,
            managed_input_ports=ports.managed_input_ports,
            acp_turn_opt_in=ports.acp_turn_opt_in,
            effect_write_guard_factory=ports.effect_write_guard_factory,
            defer_effect_write_guard_factory=ports.defer_effect_write_guard_factory)
        validate_agent_owner_selection(ports.fingerprint, execution.owner_inputs)
        # Host retains its original root proof, journal and issuer/records.
        binding = _expected_binding(context.store_path, runtime.owner)
        assembled = assemble_agent_owner(context, execution.owner_inputs, binding,
            root_port=runtime.owner, reopen=ports.agent_journal_reopen)
        context.agent_owner, context.owner_ports = assembled, assembled.ports
        manager = execution.bind(assembled.ports)
        services = unit_services(context, owner_ports=assembled.ports)
        if services.unit_manager is not assembled.ports.unit_manager:
            raise AgentOwnerUnavailable('Original Unit Manager diverged during composition')
        runtime.units, runtime.unit_execution_owner = manager, execution
        runtime.execution_environments = ports.environments
        self._description = {'agentId': selection.agent_id, 'profileRevision': encoded['ref'],
            'environmentId': instance.identity, 'environmentProvider': snapshot.provider_id,
            'isolation': snapshot.observation.capabilities.isolation, 'sharing': selection.sharing,
            'harnessId': preparation.harness_id, 'provider': route['provider'], 'model': route['model']}
        runtime.execution_selection = self.describe()
        self._runtime = runtime


def select_pi_execution(selection, ports):
    """Capture configuration only; normal runtime supplies the real context."""
    if type(selection) is not PiExecutionSelection or type(ports) is not PiExecutionPorts:
        raise AgentOwnerUnavailable('Explicit Pi selection and production owner ports required')
    if type(ports.acp_turn_opt_in) is not bool:
        raise AgentOwnerUnavailable('ACP durable opt-in must be an exact boolean')
    if type(ports.restricted_file_tools) is not bool:
        raise AgentOwnerUnavailable('Restricted Pi file tools selection must be an exact boolean')
    if (type(ports.read_only_file_tools) is not bool
            or ports.read_only_file_tools and (
                not ports.restricted_file_tools or ports.approved_check_command is not None
                or ports.callback_approval_factory is None)):
        raise AgentOwnerUnavailable('Read-only Pi tools require restricted tools and a command-free callback scope')
    if ports.approved_check_command is not None and (
            not ports.restricted_file_tools or ports.callback_approval_factory is None
            or type(ports.approved_check_command) is not str or not ports.approved_check_command):
        raise AgentOwnerUnavailable('Exact Pi check command requires restricted tools and callback scope')
    if type(ports.defer_effect_write_guard_factory) is not bool:
        raise AgentOwnerUnavailable('Deferred effect-write factory selection must be an exact boolean')
    if (ports.defer_effect_write_guard_factory
            and (ports.acp_turn_opt_in is not True
                 or ports.effect_write_guard_factory is not None)):
        raise AgentOwnerUnavailable(
            'Deferred effect-write factory requires explicit ACP opt-in and no initial factory'
        )
    if (ports.effect_write_guard_factory is not None
            and not callable(ports.effect_write_guard_factory)):
        raise AgentOwnerUnavailable('Fixed effect-write guard factory must be callable')
    if ports.effect_write_guard_factory is not None and not ports.acp_turn_opt_in:
        raise AgentOwnerUnavailable('Guarded recorded dispatch requires explicit original ACP schema opt-in')
    if not callable(ports.permission_factory):
        raise AgentOwnerUnavailable('Explicit actual-runtime Unit permission configuration is unavailable')
    if ports.callback_approval_factory is not None and not callable(ports.callback_approval_factory):
        raise AgentOwnerUnavailable('Explicit callback approval factory must be callable')
    if ports.managed_input_ports is not None:
        from ordessa_units.api import ManagedAcpInputPorts
        if type(ports.managed_input_ports) is not ManagedAcpInputPorts or ports.acp_turn_opt_in is not True:
            raise AgentOwnerUnavailable('Managed ACP input requires fixed owner ports and ACP opt-in')
    return SelectedPiExecution(selection, ports)
