"""Read-only registry queries used by discovery and channels."""
from __future__ import annotations

from collections.abc import Mapping


def _operation_projection(operation, *, schemas: bool) -> dict:
    value = {'id': operation.id, 'scopes': list(operation.scopes),
             'cli': operation.cli, 'mcp': operation.mcp}
    if schemas:
        value['inputSchema'] = operation.input_schema
        value['outputSchema'] = operation.output_schema
    return value


def list_capabilities(registry) -> dict:
    """Every published capability with its operation ids."""
    return {'capabilities': [
        {'id': descriptor.id, 'version': descriptor.version,
         'digest': descriptor.descriptor_digest,
         'operations': [operation.id for operation in descriptor.operations]}
        for descriptor in registry.capabilities.values()
    ]}


def list_operations(registry) -> dict:
    """Every published operation with its declarative metadata."""
    return {'operations': [
        _operation_projection(registered.descriptor, schemas=False)
        for registered in registry.operations.values()
    ]}


def describe(registry, operation_id: str) -> dict:
    """One operation's full descriptor projection, or an explicit refusal."""
    registered = registry.resolve(operation_id)
    return {'capability': registered.capability_id,
            'operation': _operation_projection(registered.descriptor, schemas=True)}


__all__ = ['list_capabilities', 'list_operations', 'describe']
