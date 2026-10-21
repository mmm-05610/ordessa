"""Trusted composition of original Agent query/effect ports and Engineering."""
from ordessa_server.composition.engineering_bindings.dispatch_routes import EngineeringDispatchRoutes


def dispatch_routes_factory(*,execution,blobs,approvals_factory,selection=None,
        submission_source=None,registry_loader=None,source_snapshots=None,
        history_sources=None,method_runs=None,method_guard=None,source_materials=None):
    from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
    from ordessa_engineering.adapters.native_records.agent_execution import AgentDispatchSources
    if type(execution) is not RecordedDispatchExecution or execution.blobs is not blobs:
        raise ValueError('Same original Agent execution and Blob authority required')
    for source in (source_snapshots,history_sources):
        if source is not None and (type(source) is not AgentDispatchSources or source.source is not execution.source):
            raise ValueError('Same original Agent source authority required')
    def build(factory,access,scope):
        if blobs.authority_id!=factory.authority_id:raise ValueError('Original Engineering Blob authority required')
        approvals=approvals_factory(factory,access) if approvals_factory is not None else None
        return EngineeringDispatchRoutes(factory,access,execution=execution,blobs=blobs,
            approvals=approvals,selection=selection,submission_source=submission_source,
            registry_loader=registry_loader,source_snapshots=source_snapshots,
            history_sources=history_sources,method_runs=method_runs,
            method_guard=method_guard,source_materials=source_materials)
    return build


def native_dispatch_sources(source,*,read_invocation_resolver):
    from ordessa_engineering.adapters.native_records.agent_execution import AgentDispatchSources
    return AgentDispatchSources(source,read_invocation_resolver)


class OriginalAgentDispatchQueries:
    """Trusted mapping to an original READ invocation; never query from a digest."""
    def __init__(self,source,*,request_factory):
        from ordessa_agents.public import InteractionService
        if type(source) is not InteractionService or not callable(request_factory):
            raise ValueError('Original Agent query owner required')
        self.source,self.request_factory=source,request_factory

    def __call__(self,binding):
        from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding, AgentWorkDispatchBinding
        if type(binding) not in (AgentDispatchBinding, AgentWorkDispatchBinding):raise ValueError('Original Agent dispatch binding required')
        binding.require_turn_binding()
        invocation=self.request_factory(binding)
        if invocation is None:raise ValueError('Original Agent read authority required')
        # Original Agent independently verifies principal and exact TurnRef/query
        # at capture_dispatch. This object neither issues nor caches authority.
        return invocation


def bind_original_agent_work_dispatch(service, *, execution, selection, agent_ref_resolver,
                                      implementation_timeout=60):
    """Actual SDK source and Profile/workspace selection, with no default grant."""
    from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
    from ordessa_engineering.adapters.native_records.agent_selection import OriginalAgentDispatchSelection
    from ordessa_engineering.application.assembly import bind_agent_execution_dispatch
    if (type(execution) is not RecordedDispatchExecution
            or type(selection) is not OriginalAgentDispatchSelection
            or selection.source is not execution.source):
        raise ValueError('Same original Agent and explicit Profile/workspace owners required')
    return bind_agent_execution_dispatch(service,execution=execution,selection=selection,
        agent_ref_resolver=agent_ref_resolver,implementation_timeout=implementation_timeout)
