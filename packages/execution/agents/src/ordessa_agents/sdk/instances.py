"""F1 endpoint and agent-instance references (DESIGN §3.2).

Two closed values only: what an endpoint *is* (issuer-scoped identity plus the
descriptor digest the provider published) and what one prepared agent instance
is (namespace + instance id + the digest of its immutable binding). Neither value
carries authority: no path, no credential, no grant, no EnvironmentRef/UseRef.

The instance binding digest is published only after preparation fixes the
binding; a failed preparation returns an operation reference and an instance id,
never an invented final digest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ENDPOINT_SCHEMA = 'agent-endpoint/1'
INSTANCE_SCHEMA = 'agent-instance/1'
MAX_ID = 512
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


class ReferenceError_(ValueError):
    """Closed, sanitized refusal for one reference value."""


def _text(value, name):
    if type(value) is not str or not value or len(value) > MAX_ID:
        raise ReferenceError_(f'{name} must be a bounded nonempty string')
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise ReferenceError_(f'{name} must not contain control characters')
    return value


def _digest(value, name):
    if type(value) is not str or not DIGEST.match(value):
        raise ReferenceError_(f'{name} must be sha256:<64 lowercase hex>')
    return value


@dataclass(frozen=True)
class EndpointRef:
    issuer: str
    endpoint_id: str
    revision: str
    descriptor_digest: str

    def __post_init__(self):
        _text(self.issuer, 'issuer')
        _text(self.endpoint_id, 'endpoint_id')
        _text(self.revision, 'revision')
        _digest(self.descriptor_digest, 'descriptor_digest')

    def projection(self) -> dict:
        return {'schemaVersion': ENDPOINT_SCHEMA, 'issuer': self.issuer,
                'endpointId': self.endpoint_id, 'revision': self.revision,
                'descriptorDigest': self.descriptor_digest}

    @classmethod
    def decode(cls, value) -> 'EndpointRef':
        if type(value) is not dict or set(value) != {
                'schemaVersion', 'issuer', 'endpointId', 'revision', 'descriptorDigest'}:
            raise ReferenceError_('endpoint reference is not the closed projection')
        if value['schemaVersion'] != ENDPOINT_SCHEMA:
            raise ReferenceError_('endpoint reference schemaVersion is not agent-endpoint/1')
        return cls(value['issuer'], value['endpointId'], value['revision'],
                   value['descriptorDigest'])


@dataclass(frozen=True)
class AgentInstanceRef:
    namespace: str
    instance_id: str
    binding_digest: str

    def __post_init__(self):
        _text(self.namespace, 'namespace')
        _text(self.instance_id, 'instance_id')
        _digest(self.binding_digest, 'binding_digest')

    def projection(self) -> dict:
        # Exactly these four keys: the instance reference never carries grants,
        # environment facts or a second state identity.
        return {'schemaVersion': INSTANCE_SCHEMA, 'namespace': self.namespace,
                'instanceId': self.instance_id, 'bindingDigest': self.binding_digest}

    @classmethod
    def decode(cls, value) -> 'AgentInstanceRef':
        if type(value) is not dict or set(value) != {
                'schemaVersion', 'namespace', 'instanceId', 'bindingDigest'}:
            raise ReferenceError_('agent instance reference is not the closed projection')
        if value['schemaVersion'] != INSTANCE_SCHEMA:
            raise ReferenceError_('agent instance schemaVersion is not agent-instance/1')
        return cls(value['namespace'], value['instanceId'], value['bindingDigest'])


__all__ = ['ENDPOINT_SCHEMA', 'INSTANCE_SCHEMA', 'ReferenceError_', 'EndpointRef',
           'AgentInstanceRef']
