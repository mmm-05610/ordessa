"""Public engineering/agent/decision capability bindings for system-access.

These bind the *published* capabilities of the engineering, agent and decision
owners to the system-access surface. They own no business authority; apps inject
the dependencies (authority, environment resolver, services) and assemble.
"""
def __getattr__(name):
    # Public exports load their actual owner only when selected. An Engineering
    # reader must not import or construct unrelated Unit/Decision services.
    if name == 'agent_core_methods':
        from .agents import agent_core_methods
        return agent_core_methods
    if name in {'OrdessaReadFacade', 'ObservationQuery', 'OwnerProposalValidator'}:
        from . import decision
        return getattr(decision, name)
    if name == 'EngineeringCommandAccess':
        from .engineering import EngineeringCommandAccess
        return EngineeringCommandAccess
    if name == 'EngineeringWireBinding':
        from .engineering_wire import EngineeringWireBinding
        return EngineeringWireBinding
    raise AttributeError(name)

__all__ = [
    "EngineeringCommandAccess", "EngineeringWireBinding", "ObservationQuery", "OrdessaReadFacade",
    "OwnerProposalValidator", "agent_core_methods",
]
