"""Operation-registry contract: registry-ref shape, results and input typing.

The active registry data is a packaged resource read by a runtime loader; the
application depends on this contract (injected loader), never on a concrete
adapter.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from ...domain.common.outcomes.library_failures import EngineeringError
from ...domain.artifacts.library_materials import MaterialRef

__all__ = ['RegistryLoader', 'registry_ref', 'require_registry_ref', 'operation_results',
           'validate_operation_inputs']


class RegistryLoader(Protocol):
    """Injected active-registry loader; the application depends on this contract."""

    def __call__(self) -> Mapping[str, Any]: ...


def registry_ref(registry: Mapping[str, Any]) -> dict[str, Any]:
    value = registry
    return {'registry_id': value['registry_id'], 'revision': value['revision'], 'digest': value['registry_digest']}


def require_registry_ref(value: Any, registry) -> dict[str, Any]:
    expected = registry_ref(registry)
    if not isinstance(value, Mapping) or set(value) != set(expected) or dict(value) != expected:
        raise EngineeringError('operation_registry_ref_mismatch')
    return expected


def operation_results(registry: Mapping[str, Any]) -> dict[str, set[str]]:
    value = registry
    return {name: set(contract['results']) for name, contract in value['operations'].items()}


def validate_operation_inputs(operation: str, context: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    contract = registry['operations'].get(operation)
    if contract is None:
        raise EngineeringError('method_operation_unknown')
    for path, expected_type in contract['inputs'].items():
        value: Any = context
        for segment in path.split('.'):
            if not isinstance(value, Mapping) or segment not in value:
                raise EngineeringError('operation_input_missing')
            value = value[segment]
        if expected_type == 'MaterialRef' and (not isinstance(value, MaterialRef)):
            raise EngineeringError('operation_input_type')
        if expected_type == 'MaterialRef[]' and (not isinstance(value, (tuple, list)) or any((not isinstance(item, MaterialRef) for item in value))):
            raise EngineeringError('operation_input_type')
        if expected_type == 'Mapping' and (not isinstance(value, Mapping)):
            raise EngineeringError('operation_input_type')
        if expected_type == 'str' and type(value) is not str:
            raise EngineeringError('operation_input_type')
        if expected_type not in {'MaterialRef', 'MaterialRef[]', 'Mapping', 'str'}:
            raise EngineeringError('operation_registry_input_type_unknown')
