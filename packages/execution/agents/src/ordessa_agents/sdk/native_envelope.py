"""Closed ``agent-native/1`` envelope values for the dynamic native surface.

The public entry points (``agents.native.*``) accept a *protocol-shaped* native
message. This module validates only the platform envelope and preserves the
native message (unknown fields included) for the bound provider codec. It owns
no runtime state, no store and no authority; ``native_runtime`` and the original
``Records`` owner do.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .instances import AgentInstanceRef
from .interactions import InteractionsRefused, _canonical, _digest, _digest_of, _text

NATIVE_ENVELOPE_VERSION = 'agent-native/1'
OPERATION_REF_VERSION = 'agent-native-operation-ref/2'
PENDING_REF_VERSION = 'agent-native-pending-ref/1'

KINDS = frozenset({'request', 'notify'})
OPERATION_STATES = frozenset({'accepted', 'sent', 'completed', 'failed', 'cancelled',
                              'refused', 'unknown'})
EVENT_KINDS = frozenset({'response', 'notification', 'reverse_request', 'lifecycle',
                         'oversize', 'gap'})
CAPABILITY_NAMES = frozenset({'request', 'notify', 'events', 'reverse_requests'})

MAX_MESSAGE_BYTES = 1048576
MAX_EVENT_BYTES = 1048576
MAX_PAGE_EVENTS = 256
DEFAULT_PAGE_EVENTS = 100
JOURNAL_MAX_EVENTS = 4096
JOURNAL_MAX_BYTES = 8 * 1024 * 1024
MAX_NATIVE_REQUEST_ID = 128
MAX_PENDING_PAYLOAD = 262144


def _message_bytes(value, name='nativeMessage'):
    """Canonical bytes of the native message; unknown fields are preserved."""
    if type(value) is not dict:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', name + ' must be a JSON object')
    raw = _canonical(value).encode('utf-8')
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', name + ' size')
    return raw


def message_digest(value):
    return 'sha256:' + hashlib.sha256(_message_bytes(value)).hexdigest()


def input_digest(*, kind, protocol_id, session_id, message):
    """Canonical dispatch identity; the same value is the idempotency content."""
    if kind not in KINDS:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'kind')
    _text(protocol_id, 'protocol id')
    _text(session_id, 'session id')
    _message_bytes(message)
    return _digest_of({'schemaVersion': NATIVE_ENVELOPE_VERSION, 'kind': kind,
                       'protocolId': protocol_id, 'sessionId': session_id,
                       'nativeMessage': message})


def validate_request_id(request_id):
    _text(request_id, 'requestId', MAX_NATIVE_REQUEST_ID)
    return request_id


def validate_cursor(cursor):
    """Cursors are opaque ``s<seq>`` tokens; ``None`` means "from the start"."""
    if cursor is None:
        return 0
    if type(cursor) is not str or not cursor.startswith('s'):
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'cursor')
    digits = cursor[1:]
    if not digits.isdigit() or len(digits) > 18:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'cursor')
    value = int(digits)
    if value < 0:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'cursor')
    return value


def format_cursor(seq):
    if type(seq) is not int or seq < 0:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'cursor sequence')
    return 's' + str(seq)


def validate_page_limit(limit):
    if limit is None:
        return DEFAULT_PAGE_EVENTS
    if type(limit) is not int or type(limit) is bool or not 1 <= limit <= MAX_PAGE_EVENTS:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'limit')
    return limit


@dataclass(frozen=True)
class OperationRef:
    """Public reference to one accepted native operation."""

    instance_ref: AgentInstanceRef
    request_key: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'instance')
        _digest(self.request_key, 'request key')

    def projection(self):
        return {'schemaVersion': OPERATION_REF_VERSION,
                'instanceRef': self.instance_ref.projection(),
                'requestKey': self.request_key}

    @classmethod
    def decode(cls, value):
        if type(value) is not dict or set(value) != {'schemaVersion', 'instanceRef', 'requestKey'}:
            raise InteractionsRefused('DECODE_INVALID', 'operation ref')
        if value['schemaVersion'] != OPERATION_REF_VERSION:
            raise InteractionsRefused('DECODE_INVALID', 'operation ref version')
        return cls(AgentInstanceRef.decode(value['instanceRef']), value['requestKey'])


@dataclass(frozen=True)
class PendingRequestRef:
    """One observed reverse request, bound to its instance connection generation."""

    instance_ref: AgentInstanceRef
    connection_generation: int
    native_request_id: str
    protocol_id: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'instance')
        if type(self.connection_generation) is not int or type(self.connection_generation) is bool \
                or self.connection_generation < 0:
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'connection generation')
        _text(self.native_request_id, 'native request id', 512)
        _text(self.protocol_id, 'protocol id')

    def projection(self):
        return {'schemaVersion': PENDING_REF_VERSION,
                'instanceRef': self.instance_ref.projection(),
                'connectionGeneration': self.connection_generation,
                'nativeRequestId': self.native_request_id,
                'protocolId': self.protocol_id}

    @classmethod
    def decode(cls, value):
        if type(value) is not dict or set(value) != {'schemaVersion', 'instanceRef',
                'connectionGeneration', 'nativeRequestId', 'protocolId'}:
            raise InteractionsRefused('DECODE_INVALID', 'pending ref')
        if value['schemaVersion'] != PENDING_REF_VERSION:
            raise InteractionsRefused('DECODE_INVALID', 'pending ref version')
        return cls(AgentInstanceRef.decode(value['instanceRef']),
                   value['connectionGeneration'], value['nativeRequestId'], value['protocolId'])


def describe_result(instance_ref, *, protocol_id, protocol_version, session_id, capabilities,
                    availability='available', reason=None):
    """Closed description of the bound native protocol; no caller-chosen routing."""
    if type(instance_ref) is not AgentInstanceRef:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'instance')
    _text(protocol_id, 'protocol id')
    # 0 means "the bound codec is unavailable, version unknown"; it is never a
    # positive claim about a protocol this platform cannot speak.
    if type(protocol_version) is not int or protocol_version < 0:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'protocol version')
    if session_id is not None:
        _text(session_id, 'session id')
    if type(capabilities) not in (tuple, frozenset, set) or not set(capabilities) <= CAPABILITY_NAMES:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'capabilities')
    if availability not in ('available', 'unavailable'):
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'availability')
    if availability == 'unavailable' and not reason:
        raise InteractionsRefused('NATIVE_VALUE_INVALID', 'unavailable needs a reason')
    if reason is not None:
        _text(reason, 'reason', 512)
    return {'schemaVersion': 'agent-native-description/1',
            'instanceRef': instance_ref.projection(), 'protocolId': protocol_id,
            'protocolVersion': protocol_version, 'sessionId': session_id,
            'categories': {name: ('reverse_requests' if name == 'reverseRequests' else name)
                           in set(capabilities)
                           for name in ('request', 'notify', 'events', 'reverseRequests')},
            'availability': availability, 'reason': reason}


@dataclass(frozen=True)
class Observation:
    """One stored native observation (pure read value)."""

    operation_ref: OperationRef
    kind: str
    state: str
    protocol_id: str
    session_id: str
    input_digest: str
    accepted_at: str
    updated_at: str
    response: dict | None = None
    error: dict | None = None
    delivery: dict | None = None

    def projection(self):
        value = {'schemaVersion': 'agent-native-observation/1',
                 'operationRef': self.operation_ref.projection(),
                 'kind': self.kind, 'state': self.state,
                 'protocolId': self.protocol_id, 'sessionId': self.session_id,
                 'inputDigest': self.input_digest,
                 'acceptedAt': self.accepted_at, 'updatedAt': self.updated_at}
        if self.response is not None:
            value['response'] = self.response
        if self.error is not None:
            value['error'] = self.error
        if self.delivery is not None:
            value['delivery'] = self.delivery
        return value


def event_projection(*, seq, kind, payload, payload_digest, operation_ref, observed_at):
    return {'schemaVersion': 'agent-native-event/1', 'seq': seq, 'kind': kind,
            'payload': payload, 'payloadDigest': payload_digest,
            'operationRef': None if operation_ref is None else operation_ref.projection(),
            'observedAt': observed_at}


__all__ = ['NATIVE_ENVELOPE_VERSION', 'OPERATION_REF_VERSION', 'PENDING_REF_VERSION',
           'KINDS', 'OPERATION_STATES', 'EVENT_KINDS', 'CAPABILITY_NAMES',
           'MAX_MESSAGE_BYTES', 'MAX_EVENT_BYTES', 'MAX_PAGE_EVENTS', 'DEFAULT_PAGE_EVENTS',
           'JOURNAL_MAX_EVENTS', 'JOURNAL_MAX_BYTES',
           'message_digest', 'input_digest', 'validate_request_id', 'validate_cursor',
           'format_cursor', 'validate_page_limit', 'OperationRef', 'PendingRequestRef',
           'describe_result', 'Observation', 'event_projection']
