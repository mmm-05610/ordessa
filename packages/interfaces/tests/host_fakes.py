"""Shared fakes for the generic host tests; no domain owner is imported."""
from __future__ import annotations

from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, CapabilityError, OperationDescriptor,
    OperationResult, compute_descriptor_digest,
)


def make_capability(capability_id='demo', *, handler=None, version='1',
                    operation_ids=('demo.run',), cli=None, mcp=None,
                    input_schema=None, output_schema=None):
    operations = []
    for operation_id in operation_ids:
        operations.append(OperationDescriptor(
            id=operation_id,
            input_schema=input_schema or {'type': 'object',
                                          'properties': {'value': {'type': 'integer'}},
                                          'additionalProperties': False},
            output_schema=output_schema or {'type': 'object'},
            scopes=(operation_id,),
            cli=cli, mcp=mcp))
    stub = CapabilityDescriptor(id=capability_id, version=version,
                                operations=tuple(operations), descriptor_digest='sha256:' + '0' * 64)
    descriptor = CapabilityDescriptor(id=capability_id, version=version,
                                      operations=tuple(operations),
                                      descriptor_digest=compute_descriptor_digest(stub))
    handlers = {}
    for operation_id in operation_ids:
        async def call(request, context, _id=operation_id):
            if handler is not None:
                return await handler(request, context)
            return OperationResult(status='completed', data=dict(request))
        handlers[operation_id] = call
    return Capability(descriptor=descriptor, handlers=handlers)


class FakeEntryPoint:
    def __init__(self, name, factory):
        self.name = name
        self._factory = factory

    def load(self):
        return {'factory': self._factory}


class FakeFactory:
    def __init__(self, capability):
        self.capability = capability
        self.built = 0

    def build(self, bindings):
        self.built += 1
        return self.capability


def refused(code='INVALID_INPUT', message='refused'):
    return OperationResult(status='refused',
                           error=CapabilityError(code=code, message=message))
