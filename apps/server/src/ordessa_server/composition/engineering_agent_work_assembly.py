"""Explicit root Agent Work composition; no Unit runtime or default authority.

The default product supplies the original root owner to a trusted method
factory. This module binds only existing Agent/Profile/source and original
Engineering business/permission inputs, without acquiring or launching agents.
"""
from __future__ import annotations
from dataclasses import replace
from ordessa_engineering.application.api import ApplicationError
from ordessa_agents.profiles import ProfileRevisionRef, decode_revision_ref
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts


from dataclasses import dataclass


@dataclass(frozen=True)
class RootAgentWorkDispatchInputs:
    """Trusted existing Agent bindings; not wire data or execution authority."""
    command_authority: object
    expected_profile_revision: ProfileRevisionRef
    send_invocation_resolver: object
    read_invocation_resolver: object
    query_invocation_resolver: object
    agent_ref_resolver: object
    workspace_scope_guard: object
    implementation_timeout: float = 60


def _validate_root_agent_work_inputs(owner, inputs):
    from .agent_owner import AssembledAgentOwner
    from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
    from ordessa_agents.public import InteractionService
    if (type(owner) is not AssembledAgentOwner or owner._revoked
            or type(owner.interactions) is not InteractionService
            or owner.manager.records is not owner.records or owner.interactions.records is not owner.records
            or owner.manager.profile_service is not owner.profile_service):
        raise ApplicationError('AGENT_WORK_ROOT_OWNER_UNAVAILABLE')
    if type(inputs) is not RootAgentWorkDispatchInputs:
        raise ApplicationError('AGENT_WORK_TRUSTED_INPUTS_UNBOUND')
    if (type(inputs.command_authority) is not InstanceAccessAuthority
            or getattr(owner.interactions.authority, 'authority', None) is not inputs.command_authority):
        raise ApplicationError('AGENT_WORK_INSTANCE_AUTHORITY_UNBOUND')
    if type(inputs.expected_profile_revision) is not ProfileRevisionRef:
        raise ApplicationError('AGENT_WORK_PROFILE_PIN_UNBOUND')
    names = {'send_invocation_resolver':'AGENT_WORK_SEND_INVOCATION_UNBOUND',
        'read_invocation_resolver':'AGENT_WORK_READ_INVOCATION_UNBOUND',
        'query_invocation_resolver':'AGENT_WORK_QUERY_INVOCATION_UNBOUND',
        'agent_ref_resolver':'AGENT_WORK_EXISTING_INSTANCE_UNBOUND',
        'workspace_scope_guard':'AGENT_WORK_WORKSPACE_AUTHORITY_UNBOUND'}
    for name, code in names.items():
        if not callable(getattr(inputs, name)):
            raise ApplicationError(code)
    import math
    if (type(inputs.implementation_timeout) not in (int,float)
            or not math.isfinite(inputs.implementation_timeout)
            or not 0 < inputs.implementation_timeout <= 60):
        raise ApplicationError('DISPATCH_TIMEOUT_INVALID')
    try:
        owner.profile_service.get_revision(inputs.expected_profile_revision)
    except Exception as error:
        raise ApplicationError('AGENT_WORK_PROFILE_PIN_UNAVAILABLE') from error


def root_agent_work_execution_ports(owner, inputs, *, access, blobs):
    """Compose the original root Agent source without launch/acquire/default grant."""
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
    from ordessa_engineering.adapters.native_records.agent_selection import OriginalAgentDispatchSelection
    from ordessa_agents.public import AgentInstanceRef
    from ordessa_infrastructure.encoding import canonical_bytes
    from .engineering_dispatch import OriginalAgentDispatchQueries
    _validate_root_agent_work_inputs(owner, inputs)
    if type(access) is not EngineeringCommandAccess or access.authority is not inputs.command_authority:
        raise ApplicationError('AGENT_WORK_INSTANCE_AUTHORITY_UNBOUND')

    def current():
        _validate_root_agent_work_inputs(owner, inputs)

    def invocation(resolver, context, agent):
        current()
        access.require(context, 'engineering.executions.dispatch')
        value = resolver(context, agent)
        if value is None:
            raise ApplicationError('AGENT_WORK_INVOCATION_UNBOUND')
        return value

    def selected(context, work, profile, authorization):
        current()
        access.require(context, 'engineering.executions.dispatch')
        try:
            selected_profile = profile if type(profile) is ProfileRevisionRef else decode_revision_ref(profile)
        except Exception as error:
            raise ApplicationError('AGENT_WORK_PROFILE_BINDING_MISMATCH') from error
        if selected_profile != inputs.expected_profile_revision:
            raise ApplicationError('AGENT_WORK_PROFILE_BINDING_MISMATCH')
        value = inputs.agent_ref_resolver(context, work, profile, authorization)
        if type(value) is not dict or set(value) != {'agent_ref','session_id'}:
            raise ApplicationError('AGENT_WORK_EXISTING_INSTANCE_UNBOUND')
        try:
            agent = AgentInstanceRef.decode(value['agent_ref'])
            observed = owner.interactions.read_binding(agent,
                invocation=invocation(inputs.read_invocation_resolver, context, value['agent_ref']))
            if observed.profile_ref != inputs.expected_profile_revision:
                raise ApplicationError('AGENT_WORK_PROFILE_BINDING_MISMATCH')
            # The original service checks its real fixed session. Freezing is a
            # metadata-only check: it allocates no turn and sends no frame.
            owner.interactions.freeze_prompt(agent, canonical_bytes({
                'sessionId':value['session_id'],'prompt':[]}))
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError('AGENT_WORK_EXISTING_INSTANCE_UNAVAILABLE') from error
        return {'agent_ref':agent.projection(),'session_id':value['session_id']}

    def query(binding):
        current()
        return inputs.query_invocation_resolver(binding)

    execution = RecordedDispatchExecution(owner.interactions, blobs,
        send_invocation_resolver=lambda ctx,agent:invocation(inputs.send_invocation_resolver,ctx,agent),
        read_invocation_resolver=lambda ctx,agent:invocation(inputs.read_invocation_resolver,ctx,agent),
        query_factory=OriginalAgentDispatchQueries(owner.interactions,request_factory=query),
        endpoint_resolver=owner.interactions.endpoint_resolver)
    selection = OriginalAgentDispatchSelection(owner.interactions,inputs.expected_profile_revision,
        read_invocation_resolver=lambda ctx,agent:invocation(inputs.read_invocation_resolver,ctx,agent),
        workspace_scope_guard=inputs.workspace_scope_guard)
    return execution, selection, selected


def root_agent_application_ports_factory(*, owner, inputs, base_ports_factory):
    """Current root Agent Work assembly, independent of Unit/report selection.

    The original base factory supplies consent/review/source business ports.
    Missing bindings refuse; this adapter cannot create them from an Agent DTO.
    """
    _validate_root_agent_work_inputs(owner, inputs)
    if not callable(base_ports_factory):
        raise ApplicationError('AGENT_WORK_BUSINESS_PORTS_UNBOUND')

    def construct(factory, access, scope):
        if type(access) is not EngineeringCommandAccess or type(scope) is not WireScope:
            raise ApplicationError('AGENT_WORK_INSTANCE_AUTHORITY_UNBOUND')
        library = getattr(factory, 'library', None)
        if library is None:
            raise ApplicationError('AGENT_WORK_BUSINESS_PORTS_UNBOUND')
        # The existing business assembly supplies its exact original objects;
        # constructing lookalike wrappers would break the Service's original
        # review/source/Blob identity guard even on the same library.
        base = base_ports_factory(factory, access, scope)
        if type(base) is not EngineeringApplicationPorts:
            raise ApplicationError('AGENT_WORK_BUSINESS_PORTS_MISMATCH')
        methods, blobs = base.method_guard, base.blobs
        if (getattr(methods, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != factory.authority_id
                or not callable(getattr(blobs, 'read_verified', None))
                or not callable(getattr(blobs, 'put_verified', None))
                or getattr(base.source_materials, 'factory', None) is not factory
                or base.execution_dispatch_binder is not None
                or base.declared_generation_binder is not None
                or any(value is not None for value in (base.execution_records,
                    base.execution_query_factory, base.agent_execution_records,
                    base.agent_execution_query_factory))):
            raise ApplicationError('AGENT_WORK_BUSINESS_PORTS_MISMATCH')
        execution, selection, resolve = root_agent_work_execution_ports(owner, inputs,
            access=access, blobs=blobs)
        from .engineering_dispatch import bind_original_agent_work_dispatch
        def bind(service):
            if (getattr(service, '_factory', None) is not factory
                    or getattr(service, '_access', None) is not access
                    or getattr(service, '_blobs', None) is not blobs
                    or getattr(service, '_method_guard', None) is not methods
                    or getattr(service, '_source_materials', None) is not base.source_materials):
                raise ApplicationError('AGENT_WORK_BUSINESS_PORTS_MISMATCH')
            return bind_original_agent_work_dispatch(service, execution=execution,
                selection=selection, agent_ref_resolver=resolve,
                implementation_timeout=inputs.implementation_timeout)
        return replace(base, agent_execution_records=execution.records,
            agent_execution_query_factory=execution.query_factory,
            execution_dispatch_binder=bind)
    return construct


__all__ = ['RootAgentWorkDispatchInputs', 'root_agent_work_execution_ports',
           'root_agent_application_ports_factory']
