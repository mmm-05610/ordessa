"""Generic operation dispatch over a capability registry.

Input is validated against the frozen contract schema before the handler runs;
a handler exception or an invalid handler result after a mutating call is
classified as ``unknown`` (never a pre-effect ``refused``). The dispatcher
performs no retries and no domain branching.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jsonschema

from ordessa_interfaces_contracts import (
    CapabilityError, ContractError, OperationContext, OperationResult,
    canonical_json, validate_result,
)

_MAX_MESSAGE = 2048


class DispatchError(ContractError):
    """A request cannot be dispatched under the frozen contract."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    """One dispatched operation's identity, deadline and trusted local binding.

    ``principal`` stays a JSON object: it is data a handler may inspect or log.
    ``invocation`` is the opposite on purpose — a process-local object minted by
    trusted composition (for the Server: the ``VerifiedPrincipal`` the instance
    authority authenticated for THIS request). It is never serialized, never
    crosses the wire and must not be persisted, so a handler can re-check the
    original authority without a global "last caller" slot. A handler that does
    not receive one must refuse rather than treat absence as permission.
    """

    principal: Mapping[str, Any]
    request_id: str
    deadline: float | None = None
    invocation: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, Mapping):
            raise DispatchError('INVALID_INPUT', 'principal must be a JSON object')
        canonical_json(dict(self.principal))
        if type(self.request_id) is not str or not self.request_id:
            raise DispatchError('INVALID_INPUT', 'request_id must be a non-empty string')
        if self.deadline is not None and type(self.deadline) not in (int, float):
            raise DispatchError('INVALID_INPUT', 'deadline must be a monotonic number or None')


def _plain(value: Any) -> Any:
    """Validate JSON-ness and return a detached plain copy."""
    import json
    return json.loads(canonical_json(value))


def validate_against(schema: Mapping[str, Any], value: Any) -> None:
    """Validate one JSON value against a declared contract schema."""
    try:
        validator_class = jsonschema.validators.validator_for(schema)
        validator_class.check_schema(schema)
        validator_class(schema).validate(value)
    except jsonschema.exceptions.SchemaError as error:
        raise DispatchError('INVALID_INPUT', 'declared schema is invalid') from error
    except jsonschema.exceptions.ValidationError:
        raise DispatchError('INVALID_INPUT', 'request does not match the declared input schema') from None


def _refused(code: str, message: str) -> OperationResult:
    return OperationResult(status='refused',
                           error=CapabilityError(code=code, message=message[:_MAX_MESSAGE]))


def _unknown(message: str) -> OperationResult:
    return OperationResult(status='unknown',
                           error=CapabilityError(code='EFFECT_UNKNOWN',
                                                 message=message[:_MAX_MESSAGE]))


async def invoke(registry, operation_id: str, request: Mapping[str, Any],
                 context: OperationContext) -> OperationResult:
    """Dispatch one operation; input refusals happen before the handler runs."""
    if not isinstance(request, Mapping):
        raise DispatchError('INVALID_INPUT', 'request must be a JSON object')
    plain = _plain(dict(request))
    if type(operation_id) is not str or not operation_id:
        raise DispatchError('INVALID_INPUT', 'operation id must be a non-empty string')
    try:
        registered = registry.resolve(operation_id)
    except ContractError as error:
        return _refused('CAPABILITY_UNSUPPORTED', error.message)
    try:
        validate_against(registered.descriptor.input_schema, plain)
    except DispatchError as error:
        return _refused('INVALID_INPUT', error.message)
    try:
        result = await registered.handler(plain, context)
    except Exception:
        # The handler may have performed an effect; never reclassify as refused.
        return _unknown('handler failed before returning a contract result')
    try:
        validate_result(result)
    except ContractError:
        return _unknown('handler returned an invalid contract result')
    if result.status in ('completed', 'accepted'):
        if result.error is not None:
            return _unknown('handler returned an error with a successful status')
        if result.status == 'completed' and result.data is not None:
            try:
                validate_against(registered.descriptor.output_schema, result.data)
            except DispatchError:
                return _unknown('handler result does not match the declared output schema')
    elif result.error is None:
        return _unknown('handler returned a non-success status without an error')
    return result


__all__ = ['DispatchError', 'RequestContext', 'validate_against', 'invoke']
