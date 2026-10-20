"""Frozen F1 capability contracts (DESIGN §3.1).

Standard library only. Descriptors, requests, results and envelopes contain
finite, bounded JSON values: no callables, handles, secrets or arbitrary
objects. Contracts describe capability shape; they grant nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

CONTRACT_REVISION = 'f1/3.1'
CAPABILITY_ENTRY_POINT_GROUP = 'ordessa.capabilities'
CAPABILITY_FACTORY_ATTR = 'factory'

MAX_JSON_BYTES = 1 << 20
MAX_JSON_DEPTH = 64
MAX_ID_LENGTH = 200
MAX_VERSION_LENGTH = 100
MAX_SCOPES = 64
MAX_MESSAGE_LENGTH = 2048
MAX_EVIDENCE_REFS = 256

STATUSES = ('accepted', 'completed', 'refused', 'unknown')
ERROR_CODES = (
    'INVALID_INPUT',
    'AUTHORITY_UNAVAILABLE',
    'PERMISSION_DENIED',
    'ENDPOINT_UNAVAILABLE',
    'CAPABILITY_UNSUPPORTED',
    'CONFLICT',
    'PROTOCOL_INVALID',
    'PROVIDER_UNAVAILABLE',
    'EFFECT_UNKNOWN',
    'OBSERVATION_TIMEOUT',
    'CLEANUP_PENDING',
)
CLI_TYPES = ('string', 'integer', 'number', 'boolean', 'json-file')
CLI_NARGS = ('?', '*', '+', 'REMAINDER')
RENDER_KINDS = ('json', 'table', 'fields', 'process')


class ContractError(ValueError):
    """A descriptor/envelope/result violates the frozen F1 contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def ensure_json_value(value: Any, *, depth: int = 0, max_depth: int = MAX_JSON_DEPTH) -> Any:
    """Return ``value`` if it is finite bounded JSON; refuse everything else."""
    if depth > max_depth:
        raise _fail('INVALID_INPUT', 'JSON value exceeds the contract depth limit')
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _fail('INVALID_INPUT', 'JSON value must be finite')
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [ensure_json_value(item, depth=depth + 1, max_depth=max_depth) for item in value]
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise _fail('INVALID_INPUT', 'JSON object keys must be strings')
            out[key] = ensure_json_value(item, depth=depth + 1, max_depth=max_depth)
        return out
    raise _fail('INVALID_INPUT', 'value is not finite JSON')


def canonical_json(value: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators, UTF-8."""
    plain = ensure_json_value(value)
    try:
        raw = json.dumps(plain, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as error:
        raise _fail('INVALID_INPUT', 'value is not canonical JSON') from error
    if len(raw) > MAX_JSON_BYTES:
        raise _fail('INVALID_INPUT', 'JSON value exceeds the contract size limit')
    return raw


def _require_str(name: str, value: Any, *, limit: int = MAX_ID_LENGTH) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise _fail('INVALID_INPUT', f'{name} must be a non-empty bounded string')
    return value


def _require_mapping(name: str, value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail('INVALID_INPUT', f'{name} must be a JSON object')
    return value


def _require_str_tuple(name: str, value: Any, *, limit: int) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > limit:
        raise _fail('INVALID_INPUT', f'{name} must be a bounded tuple')
    for item in value:
        _require_str(f'{name}[]', item)
    return value


@dataclass(frozen=True)
class OperationDescriptor:
    id: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    scopes: tuple[str, ...] = ()
    cli: Mapping[str, Any] | None = None
    mcp: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    version: str
    operations: tuple[OperationDescriptor, ...]
    descriptor_digest: str


@dataclass(frozen=True)
class CapabilityError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class OperationResult:
    status: str
    data: Mapping[str, Any] | None = None
    error: CapabilityError | None = None
    operation_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()


@runtime_checkable
class OperationContext(Protocol):
    principal: Mapping[str, Any]
    request_id: str
    deadline: float | None


@runtime_checkable
class OperationHandler(Protocol):
    async def __call__(self, request: Mapping[str, Any],
                       context: OperationContext) -> OperationResult: ...


@dataclass(frozen=True)
class Capability:
    descriptor: CapabilityDescriptor
    handlers: Mapping[str, OperationHandler]


@runtime_checkable
class CapabilityFactory(Protocol):
    def build(self, bindings: Mapping[str, Any]) -> Capability: ...


def _schema(name: str, value: Any) -> Mapping[str, Any]:
    schema = _require_mapping(name, value)
    if schema.get('type') != 'object':
        raise _fail('INVALID_INPUT', f'{name} must describe an object')
    canonical_json(schema)
    return schema


def _cli_metadata(operation_id: str, value: Any) -> None:
    if value is None:
        return
    cli = _require_mapping(f'{operation_id}.cli', value)
    if set(cli) - {'command', 'operation', 'args', 'render'}:
        raise _fail('INVALID_INPUT', f'{operation_id}.cli has unknown keys')
    _require_str(f'{operation_id}.cli.command', cli.get('command'))
    _require_str(f'{operation_id}.cli.operation', cli.get('operation'))
    args = cli.get('args', ())
    if not isinstance(args, (list, tuple)):
        raise _fail('INVALID_INPUT', f'{operation_id}.cli.args must be a list')
    names: set[str] = set()
    for arg in args:
        arg = _require_mapping(f'{operation_id}.cli.args[]', arg)
        if set(arg) - {'name', 'flags', 'nargs', 'type', 'required', 'default', 'jsonPath'}:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.args[] has unknown keys')
        name = _require_str('arg.name', arg.get('name'))
        if name in names:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.args names repeat')
        names.add(name)
        if arg.get('type') not in CLI_TYPES:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.args type is unsupported')
        if 'nargs' in arg and arg['nargs'] not in CLI_NARGS:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.args nargs is unsupported')
        if 'default' in arg:
            canonical_json(arg['default'])
        if 'jsonPath' in arg:
            path = _require_str('arg.jsonPath', arg['jsonPath'])
            if any(not segment for segment in path.split('.')):
                raise _fail('INVALID_INPUT', f'{operation_id}.cli.args jsonPath is invalid')
    render = cli.get('render')
    if render is not None:
        render = _require_mapping(f'{operation_id}.cli.render', render)
        if set(render) - {'kind', 'fields', 'paths'}:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.render has unknown keys')
        if render.get('kind') not in RENDER_KINDS:
            raise _fail('INVALID_INPUT', f'{operation_id}.cli.render kind is unsupported')
        for key in ('fields', 'paths'):
            values = render.get(key, ())
            if not isinstance(values, (list, tuple)) or any(
                    type(item) is not str or not item for item in values):
                raise _fail('INVALID_INPUT', f'{operation_id}.cli.render {key} must be strings')


def _mcp_metadata(operation_id: str, value: Any) -> None:
    if value is None:
        return
    mcp = _require_mapping(f'{operation_id}.mcp', value)
    if set(mcp) - {'tool'}:
        raise _fail('INVALID_INPUT', f'{operation_id}.mcp has unknown keys')
    _require_str(f'{operation_id}.mcp.tool', mcp.get('tool'))


def descriptor_projection(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    """Canonical projection of a capability descriptor without its digest."""
    return {
        'id': descriptor.id,
        'version': descriptor.version,
        'operations': [
            {
                'id': operation.id,
                'inputSchema': operation.input_schema,
                'outputSchema': operation.output_schema,
                'scopes': list(operation.scopes),
                'cli': operation.cli,
                'mcp': operation.mcp,
            }
            for operation in descriptor.operations
        ],
    }


def compute_descriptor_digest(descriptor: CapabilityDescriptor) -> str:
    """``sha256:`` digest of the canonical descriptor, digest field excluded."""
    raw = canonical_json(descriptor_projection(descriptor))
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _validate_descriptor(descriptor: CapabilityDescriptor) -> None:
    if type(descriptor) is not CapabilityDescriptor:
        raise _fail('INVALID_INPUT', 'capability descriptor must be a CapabilityDescriptor')
    _require_str('capability.id', descriptor.id)
    _require_str('capability.version', descriptor.version, limit=MAX_VERSION_LENGTH)
    if type(descriptor.operations) is not tuple or not descriptor.operations:
        raise _fail('INVALID_INPUT', 'capability must declare at least one operation')
    operation_ids: set[str] = set()
    for operation in descriptor.operations:
        if type(operation) is not OperationDescriptor:
            raise _fail('INVALID_INPUT', 'operation must be an OperationDescriptor')
        _require_str('operation.id', operation.id)
        if operation.id in operation_ids:
            raise _fail('INVALID_INPUT', f'operation id repeats: {operation.id}')
        operation_ids.add(operation.id)
        if operation.id != descriptor.id and not operation.id.startswith(descriptor.id + '.'):
            raise _fail('INVALID_INPUT', f'operation id is not owned by capability {descriptor.id}')
        _schema(f'{operation.id}.inputSchema', operation.input_schema)
        _schema(f'{operation.id}.outputSchema', operation.output_schema)
        _require_str_tuple(f'{operation.id}.scopes', operation.scopes, limit=MAX_SCOPES)
        _cli_metadata(operation.id, operation.cli)
        _mcp_metadata(operation.id, operation.mcp)
    if type(descriptor.descriptor_digest) is not str:
        raise _fail('INVALID_INPUT', 'descriptor digest is missing')
    expected = compute_descriptor_digest(descriptor)
    if descriptor.descriptor_digest != expected:
        raise _fail('INVALID_INPUT', 'descriptor digest differs from its canonical content')


def validate_capability(capability: Capability) -> CapabilityDescriptor:
    """Validate one built capability before publication; returns its descriptor."""
    if type(capability) is not Capability:
        raise _fail('INVALID_INPUT', 'capability must be a Capability')
    descriptor = capability.descriptor
    _validate_descriptor(descriptor)
    handlers = capability.handlers
    if not isinstance(handlers, Mapping):
        raise _fail('INVALID_INPUT', 'capability handlers must be a mapping')
    expected = {operation.id for operation in descriptor.operations}
    if set(handlers) != expected:
        raise _fail('INVALID_INPUT', 'handlers must cover exactly the descriptor operation ids')
    for operation_id, handler in handlers.items():
        if not callable(handler):
            raise _fail('INVALID_INPUT', f'handler is not callable: {operation_id}')
    return descriptor


def validate_error(error: CapabilityError) -> CapabilityError:
    if type(error) is not CapabilityError:
        raise _fail('INVALID_INPUT', 'error must be a CapabilityError')
    if error.code not in ERROR_CODES:
        raise _fail('INVALID_INPUT', f'error code is not contract-defined: {error.code}')
    _require_str('error.message', error.message, limit=MAX_MESSAGE_LENGTH)
    if type(error.retryable) is not bool:
        raise _fail('INVALID_INPUT', 'error.retryable must be a boolean')
    return error


def validate_result(result: OperationResult) -> OperationResult:
    if type(result) is not OperationResult:
        raise _fail('INVALID_INPUT', 'result must be an OperationResult')
    if result.status not in STATUSES:
        raise _fail('INVALID_INPUT', f'result status is not contract-defined: {result.status}')
    if result.data is not None:
        canonical_json(result.data)
    if result.error is not None:
        validate_error(result.error)
    if result.operation_ref is not None:
        _require_str('result.operation_ref', result.operation_ref)
    _require_str_tuple('result.evidence_refs', result.evidence_refs, limit=MAX_EVIDENCE_REFS)
    return result


__all__ = [
    'CONTRACT_REVISION', 'CAPABILITY_ENTRY_POINT_GROUP', 'CAPABILITY_FACTORY_ATTR',
    'MAX_JSON_BYTES', 'MAX_JSON_DEPTH', 'MAX_MESSAGE_LENGTH',
    'STATUSES', 'ERROR_CODES', 'CLI_TYPES', 'CLI_NARGS', 'RENDER_KINDS',
    'ContractError', 'ensure_json_value', 'canonical_json',
    'OperationDescriptor', 'CapabilityDescriptor', 'CapabilityError',
    'OperationResult', 'OperationContext', 'OperationHandler',
    'Capability', 'CapabilityFactory',
    'descriptor_projection', 'compute_descriptor_digest', 'validate_capability',
    'validate_error', 'validate_result',
]
