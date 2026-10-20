"""F1 bound-endpoint surface: six independent capabilities, never one authority.

Members are separate restricted objects. Holding `launcher` says nothing about
`observe`, `communicate`, `terminate`, `detach` or `files`: each port validates
its own invocation at its own effect boundary, and a refusal of one member is not
a statement about the others (DESIGN §3.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .instances import EndpointRef, ReferenceError_

MEMBER_NAMES = ('launcher', 'observe', 'communicate', 'terminate', 'detach', 'files')
DELIVERY_STATES = frozenset({'not_sent', 'possibly_sent', 'confirmed'})
PROCESS_STATES = frozenset({'accepted', 'running', 'exited', 'unknown'})
FORBIDDEN_DESCRIPTOR_KEYS = frozenset({'environmentRef', 'environment_ref', 'useRef', 'use_ref',
                                       'resourceRef', 'resource_ref', 'grant', 'authority'})
MAX_FRAME_BYTES = 1024 * 1024
MAX_PAGE_EVENTS = 256
MAX_PAGE_BYTES = 1024 * 1024


class EndpointValueError(ValueError):
    """Closed, sanitized refusal for one endpoint value."""


def _text(value, name, limit=512):
    if type(value) is not str or not value or len(value) > limit:
        raise EndpointValueError(f'{name} must be a bounded nonempty string')
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise EndpointValueError(f'{name} must not contain control characters')
    return value


def _sealed(value, name):
    if not isinstance(value, Mapping):
        raise EndpointValueError(f'{name} must be a JSON object')
    frozen = {}
    for key, item in value.items():
        if type(key) is not str:
            raise EndpointValueError(f'{name} must use string JSON keys')
        if key in FORBIDDEN_DESCRIPTOR_KEYS:
            raise EndpointValueError(f'{name} must not carry resource/authority facts')
        frozen[key] = item
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class ProcessObservation:
    state: str
    observed_at: str
    native_identity_digest: str | None = None
    exit_code: int | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if self.state not in PROCESS_STATES:
            raise EndpointValueError('process state is not a frozen value')
        _text(self.observed_at, 'observed_at')
        if self.native_identity_digest is not None:
            _text(self.native_identity_digest, 'native_identity_digest')
        if self.exit_code is not None and (type(self.exit_code) is not int or type(self.exit_code) is bool):
            raise EndpointValueError('exit_code must be an integer or None')
        if type(self.evidence_refs) is not tuple:
            raise EndpointValueError('evidence_refs must be a tuple')
        for ref in self.evidence_refs:
            _text(ref, 'evidence ref')


    def projection(self):
        return {'schemaVersion':'agent-process-observation/1','state':self.state,
                'observedAt':self.observed_at,'nativeIdentityDigest':self.native_identity_digest,
                'exitCode':self.exit_code,'evidenceRefs':list(self.evidence_refs)}


@dataclass(frozen=True)
class SendObservation:
    status: str
    bytes_observed: int
    delivery: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ('accepted', 'completed', 'refused', 'unknown'):
            raise EndpointValueError('send status is not a frozen value')
        if type(self.bytes_observed) is not int or type(self.bytes_observed) is bool or self.bytes_observed < 0:
            raise EndpointValueError('bytes_observed must be a nonnegative integer')
        if self.delivery not in DELIVERY_STATES:
            raise EndpointValueError('delivery must be not_sent, possibly_sent or confirmed')
        if type(self.evidence_refs) is not tuple:
            raise EndpointValueError('evidence_refs must be a tuple')


@dataclass(frozen=True)
class ProtocolEvent:
    kind: str
    payload_digest: str
    payload_bytes: bytes

    def __post_init__(self):
        _text(self.kind, 'event kind', 128)
        _text(self.payload_digest, 'payload digest')
        if type(self.payload_bytes) is not bytes or len(self.payload_bytes) > MAX_PAGE_BYTES:
            raise EndpointValueError('event payload is too large')


@dataclass(frozen=True)
class ProtocolEventPage:
    """One bounded page; a cursor never means "ask again forever"."""

    events: tuple[ProtocolEvent, ...]
    cursor: str | None = None
    has_more: bool = False

    def __post_init__(self):
        if type(self.events) is not tuple or len(self.events) > MAX_PAGE_EVENTS:
            raise EndpointValueError('a page carries at most 256 events')
        if any(type(event) is not ProtocolEvent for event in self.events):
            raise EndpointValueError('page contains a foreign event')
        if sum(len(event.payload_bytes) for event in self.events) > MAX_PAGE_BYTES:
            raise EndpointValueError('page payload exceeds 1MiB')
        if self.cursor is not None:
            _text(self.cursor, 'cursor')
        if type(self.has_more) is not bool:
            raise EndpointValueError('has_more must be a bool')
        if self.has_more and self.cursor is None:
            raise EndpointValueError('a page with more events must carry a cursor')


class ObservePort(Protocol):
    async def observe(self, deadline, invocation) -> ProcessObservation: ...


class CommunicatePort(Protocol):
    async def send_guarded(self, frame: bytes, request_id, deadline, invocation, *, binding, write_guard): ...
    async def send(self, effect_id, frame: bytes, deadline, invocation) -> SendObservation: ...
    async def receive(self, cursor, deadline, invocation) -> ProtocolEventPage: ...


class TerminatePort(Protocol):
    async def terminate(self, request_id, force, deadline, invocation): ...


class DetachPort(Protocol):
    async def detach(self, request_id, invocation): ...


class FilesPort(Protocol):
    async def verify(self, prepared_ref, invocation): ...
    async def materialize(self, artifact, request_id, invocation): ...


@dataclass(frozen=True)
class BoundEndpoint:
    """What one endpoint *is* plus which capabilities were separately granted.

    A missing member is "not granted to this binding", never an implied yes/no
    about another member. The descriptor carries safe facts only.
    """

    ref: EndpointRef
    descriptor: Mapping[str, Any] = field(default_factory=dict)
    launcher: object | None = None
    observe: object | None = None
    communicate: object | None = None
    terminate: object | None = None
    detach: object | None = None
    files: object | None = None

    def __post_init__(self):
        if type(self.ref) is not EndpointRef:
            raise EndpointValueError('bound endpoint needs an EndpointRef')
        object.__setattr__(self, 'descriptor', _sealed(self.descriptor, 'descriptor'))

    def members(self) -> tuple[str, ...]:
        return tuple(name for name in MEMBER_NAMES if getattr(self, name) is not None)


__all__ = ['MEMBER_NAMES', 'DELIVERY_STATES', 'PROCESS_STATES', 'EndpointValueError',
           'lifecycle_guarded',
           'ProcessObservation', 'SendObservation', 'ProtocolEvent', 'ProtocolEventPage',
           'ObservePort', 'CommunicatePort', 'TerminatePort', 'DetachPort', 'FilesPort',
           'BoundEndpoint']


async def lifecycle_guarded(bound, action, request_id, invocation, *, binding, guard,
                            force=False):
    """Route ONE lifecycle effect through the mandatory guarded member.

    `terminate_guarded` / `detach_guarded` are internal restricted port methods
    (not public wire members) that must recheck `binding` synchronously and run
    `guard` around the actual OS signal / association-close mutation. The frozen
    six public members are unchanged. A member without the guarded entry refuses
    before any effect; the unguarded method is never a fallback.
    """
    if action not in ('stop', 'detach'):
        raise EndpointValueError('LIFECYCLE_ACTION_INVALID')
    name = 'terminate_guarded' if action == 'stop' else 'detach_guarded'
    member = getattr(bound, 'terminate' if action == 'stop' else 'detach', None)
    guarded = getattr(member, name, None) if member is not None else None
    if not callable(guarded):
        raise EndpointValueError('GUARDED_LIFECYCLE_UNAVAILABLE')
    if not callable(guard):
        raise EndpointValueError('LIFECYCLE_GUARD_REQUIRED')
    if action == 'stop':
        return await guarded(request_id, force, invocation, binding=binding, guard=guard)
    return await guarded(request_id, invocation, binding=binding, guard=guard)
