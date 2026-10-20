"""Remote mode over the existing bounded CapabilityClient.

The same registered operation/metadata surface is projected locally; no
business handler is copied. Missing discovery or a foreign/invalid envelope
refuses composition instead of falling back to a local host.
"""
from __future__ import annotations

import asyncio
import uuid

from ordessa_interfaces.system_access import CapabilityRegistry
from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, CapabilityError, OperationDescriptor,
    OperationResult, compute_descriptor_digest, envelope_from_result,
)
from ordessa_system_access_client import CapabilityClient, ClientError

_READ_ONLY = (
    'profiles.capabilities', 'profiles.list', 'profiles.readEntry', 'profiles.read',
    'profiles.preview', 'agents.get', 'agents.query', 'agents.harness.list',
    'agents.harness.describe', 'environments.providers', 'environments.list',
    'environments.inspect', 'environments.use-inspect', 'environments.endpoint-inspect',
    'decisions.validate', 'decisions.get', 'decisions.evidence', 'decisions.query',
)


class RemoteRefused(RuntimeError):
    code = 'CAPABILITY_UNSUPPORTED'


def _effectful(operation_id: str) -> bool:
    return operation_id not in _READ_ONLY


def _descriptor(value) -> OperationDescriptor:
    try:
        return OperationDescriptor(
            value['id'], value['inputSchema'], value['outputSchema'],
            tuple(value.get('scopes') or ()), value.get('cli'), value.get('mcp'))
    except (KeyError, TypeError):
        raise RemoteRefused('remote operation descriptor is invalid') from None


def load_remote_registry(client: CapabilityClient) -> CapabilityRegistry:
    """Fetch the published descriptors explicitly; no implicit local fallback."""
    request_id = uuid.uuid4().hex
    listing = client.capabilities(request_id)
    if listing['status'] != 'completed' or not isinstance(listing['data'], dict):
        raise RemoteRefused('remote capability discovery is unavailable')
    operations = listing['data'].get('operations')
    if not isinstance(operations, list):
        raise RemoteRefused('remote operation listing is invalid')
    grouped: dict[str, list[OperationDescriptor]] = {}
    for entry in operations:
        if not isinstance(entry, dict) or type(entry.get('id')) is not str:
            raise RemoteRefused('remote operation listing is invalid')
        operation_id = entry['id']
        described = client.describe(operation_id, uuid.uuid4().hex)
        if described['status'] != 'completed' or not isinstance(described['data'], dict):
            raise RemoteRefused('remote operation descriptor is unavailable: ' + operation_id)
        body = described['data'].get('operation')
        capability_id = described['data'].get('capability')
        if not isinstance(body, dict) or body.get('id') != operation_id or not isinstance(capability_id, str):
            raise RemoteRefused('remote operation descriptor is invalid: ' + operation_id)
        grouped.setdefault(capability_id, []).append(_descriptor(body))
    registry = CapabilityRegistry()
    for capability_id, descriptors in grouped.items():
        base = CapabilityDescriptor(capability_id, 'remote/1', tuple(descriptors), '')

        async def unavailable(request, context):
            return OperationResult('refused', error=CapabilityError(
                'CAPABILITY_UNSUPPORTED', 'remote handler is not local'))

        capability = Capability(
            CapabilityDescriptor(base.id, base.version, base.operations,
                                 compute_descriptor_digest(base)),
            {descriptor.id: unavailable for descriptor in descriptors})
        registry.register(capability)
    registry.freeze()
    return registry


class RemoteHost:
    def __init__(self, *, client: CapabilityClient, registry: CapabilityRegistry):
        self.client = client
        self.registry = registry

    def envelope(self, *, command: str, request_id: str, result: OperationResult):
        return envelope_from_result(request_id=request_id, command=command, result=result)

    async def call(self, operation_id: str, request, context) -> OperationResult:
        try:
            value = await asyncio.to_thread(
                self.client.invoke, operation_id, dict(request), context.request_id,
                effectful=_effectful(operation_id))
        except ClientError as error:
            return _client_error_result(error)
        error = value['error']
        result = OperationResult(
            value['status'], value['data'],
            None if error is None else CapabilityError(error['code'], error['message'],
                                                      error['retryable']),
            value['operationRef'], tuple(value['evidenceRefs']))
        return result


def _client_error_result(error: ClientError) -> OperationResult:
    if error.exit_code == 6:
        return OperationResult('unknown', error=CapabilityError('EFFECT_UNKNOWN', error.message))
    if error.exit_code == 7:
        return OperationResult('unknown', error=CapabilityError('OBSERVATION_TIMEOUT', error.message))
    if error.exit_code == 5:
        return OperationResult('refused', error=CapabilityError('CONFLICT', error.message))
    if error.exit_code == 4:
        return OperationResult('refused', error=CapabilityError('CAPABILITY_UNSUPPORTED', error.message))
    if error.exit_code == 3:
        return OperationResult('refused', error=CapabilityError('PERMISSION_DENIED', error.message))
    return OperationResult('refused', error=CapabilityError('INVALID_INPUT', error.message))


__all__ = ['RemoteHost', 'RemoteRefused', 'load_remote_registry']
