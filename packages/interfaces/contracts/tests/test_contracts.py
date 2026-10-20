"""Contract-shape tests for the frozen F1 capability contracts (DESIGN §3.1)."""
from __future__ import annotations

import math

import pytest

from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, CapabilityError, ContractError,
    ENVELOPE_API_VERSION, ERROR_CODES, EXIT_ACCEPTED, EXIT_COMPLETED,
    EXIT_CONFLICT, EXIT_REFUSED, EXIT_TIMEOUT, EXIT_UNKNOWN, EXIT_UNSUPPORTED,
    OperationDescriptor, OperationResult, canonical_json, compute_descriptor_digest,
    envelope_from_result, exit_code, make_envelope, validate_capability,
    validate_envelope, validate_result,
)


def _descriptor(*, operations=None, digest=None, capability_id='demo',
                version='1') -> CapabilityDescriptor:
    operations = operations if operations is not None else (
        OperationDescriptor(
            id='demo.run',
            input_schema={'type': 'object', 'properties': {'value': {'type': 'integer'}}},
            output_schema={'type': 'object'},
            scopes=('demo.run',),
        ),
    )
    descriptor = CapabilityDescriptor(id=capability_id, version=version,
                                      operations=tuple(operations),
                                      descriptor_digest=digest or 'sha256:0' * 1)
    if digest is None:
        descriptor = CapabilityDescriptor(id=capability_id, version=version,
                                          operations=tuple(operations),
                                          descriptor_digest=compute_descriptor_digest(descriptor))
    return descriptor


def _handler(result=None):
    async def call(request, context):
        return result if result is not None else OperationResult(status='completed', data={})
    return call


def test_digest_is_stable_canonical_and_order_sensitive():
    first = _descriptor()
    second = _descriptor()
    assert first.descriptor_digest == second.descriptor_digest
    assert first.descriptor_digest.startswith('sha256:')
    assert len(first.descriptor_digest) == len('sha256:') + 64
    reordered = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={
            'type': 'object', 'properties': {'value': {'type': 'integer'}}},
            output_schema={'type': 'object'}, scopes=('demo.run',)),
        OperationDescriptor(id='demo.other', input_schema={'type': 'object'},
                            output_schema={'type': 'object'}),
    ))
    single = _descriptor()
    assert reordered.descriptor_digest != single.descriptor_digest


def test_canonical_json_is_sorted_compact_utf8_and_finite():
    raw = canonical_json({'b': 1, 'a': 'é', 'l': [2, 1]})
    assert raw == '{"a":"é","b":1,"l":[2,1]}'.encode()
    with pytest.raises(ContractError, match='finite'):
        canonical_json({'x': math.inf})
    with pytest.raises(ContractError, match='finite'):
        canonical_json({'x': math.nan})
    with pytest.raises(ContractError, match='strings'):
        canonical_json({1: 'x'})
    with pytest.raises(ContractError):
        canonical_json({'x': object()})


def test_capability_validation_requires_unique_owned_ids_and_exact_handlers():
    capability = Capability(descriptor=_descriptor(), handlers={'demo.run': _handler()})
    assert validate_capability(capability) is capability.descriptor

    duplicate = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'}),
        OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'}),
    ))
    with pytest.raises(ContractError, match='repeats'):
        validate_capability(Capability(descriptor=duplicate, handlers={'demo.run': _handler()}))

    foreign = _descriptor(operations=(
        OperationDescriptor(id='other.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'}),
    ))
    with pytest.raises(ContractError, match='not owned'):
        validate_capability(Capability(descriptor=foreign, handlers={'other.run': _handler()}))

    with pytest.raises(ContractError, match='exactly'):
        validate_capability(Capability(descriptor=capability.descriptor,
                                       handlers={'demo.run': _handler(), 'demo.extra': _handler()}))

    with pytest.raises(ContractError, match='not callable'):
        validate_capability(Capability(descriptor=capability.descriptor,
                                       handlers={'demo.run': 'not-callable'}))


def test_digest_mismatch_and_unsupported_shapes_are_refused():
    bad = CapabilityDescriptor(id='demo', version='1', operations=_descriptor().operations,
                               descriptor_digest='sha256:' + '0' * 64)
    with pytest.raises(ContractError, match='digest differs'):
        validate_capability(Capability(descriptor=bad, handlers={'demo.run': _handler()}))

    schema_not_object = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={'type': 'array'},
                            output_schema={'type': 'object'}),
    ))
    with pytest.raises(ContractError, match='object'):
        validate_capability(Capability(descriptor=schema_not_object,
                                       handlers={'demo.run': _handler()}))


def test_cli_and_mcp_metadata_are_declarative_and_bounded():
    operation = OperationDescriptor(
        id='demo.run', input_schema={'type': 'object'},
        output_schema={'type': 'object'},
        cli={'command': 'demo', 'operation': 'run',
             'args': ({'name': 'input', 'flags': ('--input',), 'type': 'json-file',
                       'required': True, 'jsonPath': 'value'},),
             'render': {'kind': 'fields', 'fields': ('id',)}},
        mcp={'tool': 'demo_run'})
    capability = Capability(descriptor=_descriptor(operations=(operation,)),
                            handlers={'demo.run': _handler()})
    validate_capability(capability)

    bad_type = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'},
                            cli={'command': 'demo', 'operation': 'run',
                                 'args': ({'name': 'x', 'type': 'callable'},)}),
    ))
    with pytest.raises(ContractError, match='type is unsupported'):
        validate_capability(Capability(descriptor=bad_type, handlers={'demo.run': _handler()}))

    bad_render = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'},
                            cli={'command': 'demo', 'operation': 'run',
                                 'render': {'kind': 'python'}}),
    ))
    with pytest.raises(ContractError, match='render kind'):
        validate_capability(Capability(descriptor=bad_render, handlers={'demo.run': _handler()}))

    bad_mcp = _descriptor(operations=(
        OperationDescriptor(id='demo.run', input_schema={'type': 'object'},
                            output_schema={'type': 'object'}, mcp={'name': 'x'}),
    ))
    with pytest.raises(ContractError, match='mcp'):
        validate_capability(Capability(descriptor=bad_mcp, handlers={'demo.run': _handler()}))


def test_result_and_error_validation():
    with pytest.raises(ContractError, match='status'):
        validate_result(OperationResult(status='done'))
    with pytest.raises(ContractError, match='code'):
        validate_result(OperationResult(status='refused',
                                        error=CapabilityError(code='NOPE', message='x')))
    assert validate_result(OperationResult(status='unknown',
                                           error=CapabilityError(code='EFFECT_UNKNOWN', message='x')))
    assert set(ERROR_CODES) >= {'INVALID_INPUT', 'EFFECT_UNKNOWN', 'CLEANUP_PENDING'}


def test_envelope_shape_status_and_exit_codes():
    completed = make_envelope(request_id='r1', command='demo run',
                              status='completed', data={'ok': True}, operation_ref='op-1')
    assert completed['apiVersion'] == ENVELOPE_API_VERSION
    assert set(completed) == {'apiVersion', 'requestId', 'command', 'status', 'data',
                              'error', 'operationRef', 'evidenceRefs'}
    assert exit_code(completed) == EXIT_COMPLETED

    accepted = make_envelope(request_id='r2', command='demo run', status='accepted')
    assert exit_code(accepted) == EXIT_ACCEPTED

    refused = make_envelope(request_id='r3', command='demo run', status='refused',
                            error=CapabilityError(code='INVALID_INPUT', message='bad'))
    assert exit_code(refused) == EXIT_REFUSED

    unsupported = make_envelope(request_id='r4', command='demo run', status='refused',
                               error=CapabilityError(code='CAPABILITY_UNSUPPORTED', message='no'))
    assert exit_code(unsupported) == EXIT_UNSUPPORTED

    conflict = make_envelope(request_id='r5', command='demo run', status='refused',
                             error=CapabilityError(code='CONFLICT', message='busy'))
    assert exit_code(conflict) == EXIT_CONFLICT

    unknown = make_envelope(request_id='r6', command='demo run', status='unknown',
                            error=CapabilityError(code='EFFECT_UNKNOWN', message='lost'))
    assert exit_code(unknown) == EXIT_UNKNOWN

    timeout = make_envelope(request_id='r7', command='demo run', status='unknown',
                            error=CapabilityError(code='OBSERVATION_TIMEOUT', message='slow'))
    assert exit_code(timeout) == EXIT_TIMEOUT


def test_envelope_validation_refuses_unknown_keys_and_bad_values():
    envelope = make_envelope(request_id='r', command='c', status='completed')
    validate_envelope(envelope)
    with pytest.raises(ContractError, match='keys'):
        validate_envelope({**envelope, 'extra': 1})
    with pytest.raises(ContractError, match='apiVersion'):
        validate_envelope({**envelope, 'apiVersion': 'agent-tools/2'})
    with pytest.raises(ContractError, match='status'):
        validate_envelope({**envelope, 'status': 'done'})
    with pytest.raises(ContractError, match='error'):
        validate_envelope({**envelope, 'error': {'code': 'INVALID_INPUT'}})
    with pytest.raises(ContractError, match='finite'):
        validate_envelope({**envelope, 'data': {'x': math.inf}})


def test_envelope_from_result_matches_make_envelope():
    result = OperationResult(status='refused',
                             error=CapabilityError(code='PERMISSION_DENIED', message='no'))
    assert envelope_from_result(request_id='r', command='c', result=result) == \
        make_envelope(request_id='r', command='c', status='refused', error=result.error)
