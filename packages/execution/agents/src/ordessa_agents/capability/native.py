"""``agents.native.*`` — the dynamic native interaction surface.

The six operations only validate the closed envelope and delegate to the ONE
original InteractionService runtime. No per-method wrapper, no caller-supplied
protocol id, no second store: the protocol comes from the instance's bound
Harness provider, and every durable fact lives in the original Records owner.
"""
from __future__ import annotations

import asyncio

from ordessa_agents.public import AgentInstanceRef, InteractionService
from ordessa_agents.sdk.interactions import InteractionsRefused
from ordessa_agents.sdk.native_envelope import OperationRef, PendingRequestRef
from ordessa_interfaces_contracts import (Capability, CapabilityDescriptor, CapabilityError,
                                          OperationDescriptor, OperationResult,
                                          compute_descriptor_digest, validate_capability)


def _closed(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


def _schemas():
    obj = {'type': 'object'}
    text = {'type': 'string', 'minLength': 1, 'maxLength': 512}
    message = {'type': 'object'}
    cursor = {'type': ['string', 'null'], 'maxLength': 32}
    limit = {'type': ['integer', 'null'], 'minimum': 1, 'maximum': 256}
    return {
        'agents.native.describe': _closed({'instanceRef': obj}),
        'agents.native.request': _closed({'instanceRef': obj, 'requestId': text,
                                          'nativeMessage': message}),
        'agents.native.notify': _closed({'instanceRef': obj, 'requestId': text,
                                         'nativeMessage': message}),
        'agents.native.query': _closed({'operationRef': obj, 'expectedInputDigest':
                                        {'type': ['string', 'null'], 'maxLength': 80}},
                                       ['operationRef']),
        'agents.native.events': _closed({'instanceRef': obj, 'cursor': cursor,
                                         'limit': limit}, ['instanceRef']),
        'agents.native.respond': _closed({'pendingRequestRef': obj, 'requestId': text,
                                          'response': message}),
    }


_FLAGS = {
    'instanceRef': ('--instance-ref', 'json-file'),
    'requestId': ('--request-id-value', 'string'),
    'nativeMessage': ('--native-message', 'json-file'),
    'operationRef': ('--operation-ref', 'json-file'),
    'expectedInputDigest': ('--expected-input-digest', 'string'),
    'cursor': ('--cursor', 'string'),
    'limit': ('--limit', 'number'),
    'pendingRequestRef': ('--pending-request-ref', 'json-file'),
    'response': ('--response', 'json-file'),
}


def descriptor():
    """Static native-operation surface; no owner or store is bound."""
    obj = {'type': 'object'}
    operations = tuple(OperationDescriptor(name, schema, obj, cli={
        'command': 'agents native', 'operation': name.split('.')[-1],
        'args': tuple({'name': field, 'flags': (_FLAGS[field][0],),
                       'type': _FLAGS[field][1]}
                      for field in schema['properties'])})
        for name, schema in _schemas().items())
    base = CapabilityDescriptor('agents', 'agent-native-operations/2', operations, '')
    return CapabilityDescriptor(base.id, base.version, base.operations,
                                compute_descriptor_digest(base))


def _refused(code):
    if code in {'PRODUCT_ROOT_CHANGED', 'INVOCATION_PRINCIPAL_UNAVAILABLE',
                'FORGED_INVOCATION', 'AUTHORITY_UNAVAILABLE'}:
        return OperationResult('refused', error=CapabilityError(
            'AUTHORITY_UNAVAILABLE', 'Original native authority is unavailable'))
    if 'DENIED' in code or 'AUTHORIZED' in code or 'REVOKED' in code:
        return OperationResult('refused', error=CapabilityError(
            'PERMISSION_DENIED', 'Original native authority refused'))
    if code in {'PROTOCOL_UNSUPPORTED', 'NATIVE_PROTOCOL_UNSUPPORTED',
                'NATIVE_ENDPOINT_UNAVAILABLE', 'NATIVE_CONNECTION_LOST'}:
        return OperationResult('refused', error=CapabilityError(
            'CAPABILITY_UNSUPPORTED', 'Bound native protocol capability unavailable'))
    if code in {'REQUEST_CONFLICT', 'NATIVE_PENDING_STALE',
                'NATIVE_PENDING_ALREADY_ANSWERED', 'NATIVE_PENDING_CLOSED',
                'SESSION_BUSY', 'RECORD_CHANGED'}:
        return OperationResult('refused', error=CapabilityError(
            'CONFLICT', 'Native operation conflicts with a recorded fact'))
    if code in {'DEADLINE_REQUIRED', 'DISPATCH_DEADLINE_ELAPSED'}:
        return OperationResult('refused', error=CapabilityError(
            'OBSERVATION_TIMEOUT', 'Native operation deadline elapsed'))
    if code in {'EVENT_CURSOR_EXPIRED', 'NATIVE_OPERATION_UNKNOWN',
                'NATIVE_PENDING_UNKNOWN', 'READ_NOT_AUTHORIZED'}:
        return OperationResult('refused', error=CapabilityError(
            'INVALID_INPUT', 'Native observation reference is not readable'))
    return OperationResult('refused', error=CapabilityError(
        'INVALID_INPUT', 'Invalid native operation input'))


def build_native_capability(source, *, invocation_resolver, write_guard):
    if type(source) is not InteractionService or not callable(invocation_resolver):
        raise TypeError('original InteractionService and authenticated invocation resolver required')
    if not callable(getattr(write_guard, 'guard_write', None)):
        raise TypeError('original physical write guard required')
    schemas = _schemas()
    registry = source.native()

    async def invoke_describe(request, context):
        invocation = invocation_resolver(context)
        if invocation is None:
            raise InteractionsRefused('FORGED_INVOCATION')
        return registry.describe(AgentInstanceRef.decode(request['instanceRef']),
                                 invocation=invocation)

    async def invoke_submit(request, context, kind):
        invocation = invocation_resolver(context)
        if invocation is None:
            raise InteractionsRefused('FORGED_INVOCATION')
        return await registry.submit(
            AgentInstanceRef.decode(request['instanceRef']), kind=kind,
            request_id=request['requestId'], message=request['nativeMessage'],
            invocation=invocation, write_guard=write_guard,
            deadline=_dispatch_deadline(context))

    async def invoke_query(request, context):
        invocation = invocation_resolver(context)
        if invocation is None:
            raise InteractionsRefused('FORGED_INVOCATION')
        return registry.query(request['operationRef'], invocation=invocation,
                              expected_input_digest=request.get('expectedInputDigest'))

    async def invoke_events(request, context):
        invocation = invocation_resolver(context)
        if invocation is None:
            raise InteractionsRefused('FORGED_INVOCATION')
        return registry.events(AgentInstanceRef.decode(request['instanceRef']),
                               cursor=request.get('cursor'), limit=request.get('limit'),
                               invocation=invocation)

    async def invoke_respond(request, context):
        invocation = invocation_resolver(context)
        if invocation is None:
            raise InteractionsRefused('FORGED_INVOCATION')
        return await registry.respond(
            PendingRequestRef.decode(request['pendingRequestRef']),
            request_id=request['requestId'], response=request['response'],
            invocation=invocation, write_guard=write_guard,
            deadline=_dispatch_deadline(context))

    raw = {
        'agents.native.describe': invoke_describe,
        'agents.native.request': lambda request, context: invoke_submit(request, context, 'request'),
        'agents.native.notify': lambda request, context: invoke_submit(request, context, 'notify'),
        'agents.native.query': invoke_query,
        'agents.native.events': invoke_events,
        'agents.native.respond': invoke_respond,
    }

    async def guarded(request, context, operation):
        try:
            value = await raw[operation](request, context)
            state = value.get('state') if isinstance(value, dict) else None
            status = 'completed' if operation in (
                'agents.native.describe', 'agents.native.query', 'agents.native.events') else (
                'accepted' if state in ('accepted', 'sent') else (
                    'unknown' if state in ('unknown', None) and operation != 'agents.native.request'
                    else 'completed' if state == 'completed' else 'accepted'))
            return OperationResult(status, data=value)
        except InteractionsRefused as error:
            return _refused(error.code)
        except (ValueError, TypeError, KeyError):
            return _refused('INVALID_INPUT')

    handlers = {name: (lambda request, context, _name=name:
                       guarded(request, context, _name)) for name in raw}
    result = Capability(descriptor(), handlers)
    validate_capability(result)
    return result


def _dispatch_deadline(context):
    loop = asyncio.get_running_loop()
    return loop.time() + 30.0


__all__ = ['descriptor', 'build_native_capability']
