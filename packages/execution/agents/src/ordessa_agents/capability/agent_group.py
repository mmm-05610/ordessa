"""The single ``agents`` capability group.

The registry refuses duplicate capability ids, so the Agent domain must publish
ONE capability whose operations cover profiles, instances, native operations and
the Harness catalog. Each part keeps its own builder and version; this module only
composes the parts that are actually assembled — a part that is not built is not
advertised, never stubbed.
"""
from __future__ import annotations

from ordessa_interfaces_contracts import (
    Capability,
    CapabilityDescriptor,
    compute_descriptor_digest,
    validate_capability,
)

CAPABILITY_ID = "agents"
_GROUP_VERSION = "agent-group/1"


def build_agent_group(*parts) -> Capability:
    """Compose built Agent-domain capabilities into the one published group."""
    operations = []
    handlers = {}
    for part in parts:
        if part is None:
            continue
        if type(part) is not Capability:
            raise TypeError('built Agent-domain capability required')
        if part.handlers and set(part.handlers) != {op.id for op in part.descriptor.operations}:
            raise TypeError('capability handlers must match its declared operations')
        operations.extend(part.descriptor.operations)
        for operation_id, handler in part.handlers.items():
            if operation_id in handlers:
                raise ValueError('duplicate operation in Agent group: ' + operation_id)
            handlers[operation_id] = handler
    if not operations:
        raise ValueError('the agents capability needs at least one assembled part')
    base = CapabilityDescriptor(CAPABILITY_ID, _GROUP_VERSION, tuple(operations), '')
    group = Capability(CapabilityDescriptor(base.id, base.version, base.operations,
                                            compute_descriptor_digest(base)), handlers)
    validate_capability(group)
    return group


__all__ = ["CAPABILITY_ID", "build_agent_group"]
