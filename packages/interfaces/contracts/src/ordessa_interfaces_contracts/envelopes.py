"""The single ``agent-tools/1`` JSON envelope shared by every channel.

The envelope is a JSON object with exactly these keys: ``apiVersion``,
``requestId``, ``command``, ``status``, ``data``, ``error``, ``operationRef``,
``evidenceRefs``. ``accepted`` means the owner accepted work; only
``completed`` is a finished result. ``unknown`` is never retried implicitly.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .capability import (
    CapabilityError, ContractError, OperationResult, canonical_json,
    validate_result,
)

ENVELOPE_API_VERSION = 'agent-tools/1'

EXIT_COMPLETED = 0
EXIT_REFUSED = 2
EXIT_ACCEPTED = 3
EXIT_UNSUPPORTED = 4
EXIT_CONFLICT = 5
EXIT_UNKNOWN = 6
EXIT_TIMEOUT = 7

_EXIT_BY_ERROR = {
    'INVALID_INPUT': EXIT_REFUSED,
    'PERMISSION_DENIED': EXIT_REFUSED,
    'AUTHORITY_UNAVAILABLE': EXIT_REFUSED,
    'CAPABILITY_UNSUPPORTED': EXIT_UNSUPPORTED,
    'ENDPOINT_UNAVAILABLE': EXIT_UNSUPPORTED,
    'PROVIDER_UNAVAILABLE': EXIT_UNSUPPORTED,
    'CONFLICT': EXIT_CONFLICT,
    'PROTOCOL_INVALID': EXIT_CONFLICT,
    'EFFECT_UNKNOWN': EXIT_UNKNOWN,
    'CLEANUP_PENDING': EXIT_UNKNOWN,
    'OBSERVATION_TIMEOUT': EXIT_TIMEOUT,
}


def make_envelope(*, request_id: str, command: str, status: str,
                  data: Mapping[str, Any] | None = None,
                  error: CapabilityError | None = None,
                  operation_ref: str | None = None,
                  evidence_refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build one validated envelope projection (JSON object)."""
    result = OperationResult(status=status, data=data, error=error,
                             operation_ref=operation_ref,
                             evidence_refs=tuple(evidence_refs))
    return envelope_from_result(request_id=request_id, command=command, result=result)


def envelope_from_result(*, request_id: str, command: str,
                         result: OperationResult) -> dict[str, Any]:
    validate_result(result)
    if type(request_id) is not str or not request_id:
        raise ContractError('INVALID_INPUT', 'requestId must be a non-empty string')
    if type(command) is not str or not command:
        raise ContractError('INVALID_INPUT', 'command must be a non-empty string')
    envelope = {
        'apiVersion': ENVELOPE_API_VERSION,
        'requestId': request_id,
        'command': command,
        'status': result.status,
        'data': result.data,
        'error': None if result.error is None else {
            'code': result.error.code,
            'message': result.error.message,
            'retryable': result.error.retryable,
        },
        'operationRef': result.operation_ref,
        'evidenceRefs': list(result.evidence_refs),
    }
    canonical_json(envelope)
    return envelope


def validate_envelope(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate one envelope's closed shape and value bounds."""
    if not isinstance(envelope, Mapping):
        raise ContractError('INVALID_INPUT', 'envelope must be a JSON object')
    expected = {'apiVersion', 'requestId', 'command', 'status', 'data', 'error',
                'operationRef', 'evidenceRefs'}
    if set(envelope) != expected:
        raise ContractError('INVALID_INPUT', 'envelope keys differ from the contract')
    if envelope['apiVersion'] != ENVELOPE_API_VERSION:
        raise ContractError('INVALID_INPUT', 'envelope apiVersion is unsupported')
    for key in ('requestId', 'command'):
        value = envelope[key]
        if type(value) is not str or not value:
            raise ContractError('INVALID_INPUT', f'envelope {key} must be a non-empty string')
    error = envelope['error']
    if error is not None:
        if not isinstance(error, Mapping) or set(error) != {'code', 'message', 'retryable'}:
            raise ContractError('INVALID_INPUT', 'envelope error has an unsupported shape')
    refs = envelope['evidenceRefs']
    if not isinstance(refs, (list, tuple)) or any(type(item) is not str or not item for item in refs):
        raise ContractError('INVALID_INPUT', 'envelope evidenceRefs must be strings')
    result = OperationResult(
        status=envelope['status'], data=envelope['data'],
        error=None if error is None else CapabilityError(
            code=error['code'], message=error['message'], retryable=error['retryable']),
        operation_ref=envelope['operationRef'], evidence_refs=tuple(refs))
    validate_result(result)
    canonical_json(envelope)
    return envelope


def exit_code(envelope: Mapping[str, Any]) -> int:
    """Map one validated envelope to the documented process exit code."""
    validate_envelope(envelope)
    status = envelope['status']
    if status == 'completed':
        return EXIT_COMPLETED
    if status == 'accepted':
        return EXIT_ACCEPTED
    error = envelope['error']
    if error is not None:
        return _EXIT_BY_ERROR.get(error['code'], EXIT_UNKNOWN)
    return EXIT_REFUSED if status == 'refused' else EXIT_UNKNOWN


__all__ = [
    'ENVELOPE_API_VERSION', 'EXIT_COMPLETED', 'EXIT_REFUSED', 'EXIT_ACCEPTED',
    'EXIT_UNSUPPORTED', 'EXIT_CONFLICT', 'EXIT_UNKNOWN', 'EXIT_TIMEOUT',
    'make_envelope', 'envelope_from_result', 'validate_envelope', 'exit_code',
]
