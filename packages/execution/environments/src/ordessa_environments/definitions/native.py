"""The neutral envelope of the thin native management entry (``environments.native.*``).

This module is a *declaration*, not an implementation: it names no gateway, SDK,
transport, RPC or provider. It freezes

* the closed action set a provider may map onto its own control plane,
* the four public facts — describe, request, query and events — and
* the bounds every value in them must respect.

The authority for a native fact is the same store the normal lifecycle uses.
This envelope owns no state, no store and no runtime: a provider answers in
neutral facts, and the capability records them beside every other command.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .errors import EnvironmentRefused

#: Version of the neutral envelope itself.
NATIVE_ENVELOPE_VERSION = 'environment-native/1'
#: Version of the description fact (``describe``).
NATIVE_DESCRIPTION_VERSION = 'environment-native-description/1'
#: Version of one provider's own management facts.
NATIVE_MANAGEMENT_VERSION = 'environment-native-management/1'
#: Version of one stored native observation (``request`` / ``query``).
NATIVE_OBSERVATION_VERSION = 'environment-native-observation/1'
#: Version of the query fact.
NATIVE_QUERY_VERSION = 'environment-native-query/1'
#: Version of one native event.
NATIVE_EVENT_VERSION = 'environment-native-event/1'
#: Version of the event page.
NATIVE_EVENTS_VERSION = 'environment-native-events/1'

#: The closed action set. Every action is a read: the thin native entry never
#: creates, deletes or mutates a resource. A provider maps each action onto its
#: own official call and refuses everything else.
NATIVE_ACTIONS = ('list', 'inspect', 'health')

#: The states a stored native fact may carry. ``unknown`` is a stored fact, not
#: a missing one: it keeps the correlation id so the outcome is never repeated.
NATIVE_STATES = ('completed', 'unknown')

#: The bounded length of one native request id.
MAX_NATIVE_REQUEST_ID = 128
#: The largest event page a caller may ask for.
MAX_PAGE_EVENTS = 256
#: The event page size used when the caller states none.
DEFAULT_PAGE_EVENTS = 100


def validate_request_id(value) -> str:
    """One bounded, stable request id; it is the idempotency key of a request."""
    if (type(value) is not str or not 0 < len(value) <= MAX_NATIVE_REQUEST_ID
            or any(ord(char) < 32 for char in value)):
        raise EnvironmentRefused('native request id must be a bounded stable reference')
    return value


def validate_action(value) -> str:
    """Only the closed action set may leave this layer."""
    if value not in NATIVE_ACTIONS:
        raise EnvironmentRefused('native action is outside the closed set')
    return value


def validate_cursor(value) -> int:
    """Cursors are opaque ``s<sequence>`` tokens; ``None`` starts at the beginning."""
    if value is None:
        return 0
    if type(value) is not str or not value.startswith('s'):
        raise EnvironmentRefused('native cursor is invalid')
    digits = value[1:]
    if not digits or len(digits) > 18 or any(char not in '0123456789' for char in digits):
        raise EnvironmentRefused('native cursor is invalid')
    sequence = int(digits)
    if sequence < 0:
        raise EnvironmentRefused('native cursor is invalid')
    return sequence


def format_cursor(sequence) -> str:
    """The opaque spelling of one sequence position."""
    if type(sequence) is not int or isinstance(sequence, bool) or sequence < 0:
        raise EnvironmentRefused('native cursor sequence is invalid')
    return 's' + str(sequence)


def validate_page_limit(value) -> int:
    """The bounded page size of an event page."""
    if value is None:
        return DEFAULT_PAGE_EVENTS
    if (type(value) is not int or isinstance(value, bool)
            or not 1 <= value <= MAX_PAGE_EVENTS):
        raise EnvironmentRefused('native page limit is invalid')
    return value


@dataclass(frozen=True)
class NativeRequest:
    """One bounded native management request.

    The request names a provider, one action of the closed set and the request
    id that makes it idempotent. A reference is optional: only an action that
    addresses one resource needs it.
    """

    provider: str
    action: str
    request_id: str
    reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.provider) is not str or not self.provider:
            raise EnvironmentRefused('native request requires a provider')
        validate_action(self.action)
        validate_request_id(self.request_id)
        if self.reference is not None and (type(self.reference) is not str or not self.reference):
            raise EnvironmentRefused('native reference must be a bounded reference')

    def projection(self) -> dict:
        return {'schemaVersion': NATIVE_ENVELOPE_VERSION, 'provider': self.provider,
                'action': self.action, 'requestId': self.request_id,
                'reference': self.reference}


@dataclass(frozen=True)
class NativeObservation:
    """One stored native fact: the request, its correlation and its outcome.

    ``correlation_id`` is what ties the stored fact to the dispatched call. An
    ``unknown`` observation keeps it, so the outcome can be read later and is
    never dispatched a second time.
    """

    request_id: str
    provider: str
    action: str
    state: str
    correlation_id: str
    backend_id: str | None = None
    environment_identity: str | None = None
    result: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        validate_action(self.action)
        if self.state not in NATIVE_STATES:
            raise EnvironmentRefused('native observation state is invalid')
        if type(self.correlation_id) is not str or not self.correlation_id:
            raise EnvironmentRefused('native observation requires a correlation id')
        if self.result is not None and not isinstance(self.result, Mapping):
            raise EnvironmentRefused('native observation result must be a mapping')

    def projection(self) -> dict:
        return {'schemaVersion': NATIVE_OBSERVATION_VERSION, 'requestId': self.request_id,
                'provider': self.provider, 'action': self.action, 'state': self.state,
                'correlationId': self.correlation_id, 'backendId': self.backend_id,
                'environmentIdentity': self.environment_identity,
                'result': None if self.result is None else dict(self.result)}


@dataclass(frozen=True)
class NativeEvent:
    """One recorded native request, as an event of the owner's native stream."""

    sequence: int
    request_id: str
    state: str
    operation_ref: str
    provider: str | None = None
    action: str | None = None
    backend_id: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or isinstance(self.sequence, bool) or self.sequence < 0:
            raise EnvironmentRefused('native event sequence is invalid')
        validate_request_id(self.request_id)
        if type(self.operation_ref) is not str or not self.operation_ref:
            raise EnvironmentRefused('native event requires an operation reference')

    def projection(self) -> dict:
        return {'schemaVersion': NATIVE_EVENT_VERSION, 'seq': self.sequence,
                'requestId': self.request_id, 'state': self.state,
                'operationRef': self.operation_ref, 'provider': self.provider,
                'action': self.action, 'backendId': self.backend_id, 'status': self.status}


def description_projection(entries) -> dict:
    """The closed description fact: availability plus the provider's own facts."""
    return {'schemaVersion': NATIVE_DESCRIPTION_VERSION, 'providers': list(entries)}


def events_projection(events, *, cursor, next_cursor, complete, limit) -> dict:
    """One page of native events, with the completeness of that page."""
    return {'schemaVersion': NATIVE_EVENTS_VERSION, 'events': [event.projection() for event in events],
            'cursor': cursor, 'nextCursor': next_cursor, 'complete': bool(complete), 'limit': limit}


__all__ = [
    'NATIVE_ENVELOPE_VERSION', 'NATIVE_DESCRIPTION_VERSION', 'NATIVE_MANAGEMENT_VERSION',
    'NATIVE_OBSERVATION_VERSION', 'NATIVE_QUERY_VERSION', 'NATIVE_EVENT_VERSION',
    'NATIVE_EVENTS_VERSION', 'NATIVE_ACTIONS', 'NATIVE_STATES', 'MAX_NATIVE_REQUEST_ID',
    'MAX_PAGE_EVENTS', 'DEFAULT_PAGE_EVENTS', 'validate_request_id', 'validate_action',
    'validate_cursor', 'format_cursor', 'validate_page_limit', 'NativeRequest',
    'NativeObservation', 'NativeEvent', 'description_projection', 'events_projection',
]
