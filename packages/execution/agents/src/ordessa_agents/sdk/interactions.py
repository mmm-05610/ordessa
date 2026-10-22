"""F1.2 §12 recorded interaction source — the official closed surface.

Authority is external (`InteractionAuthorityPort`); this module verifies it and
never issues or copies it. The endpoint's `communicate.send_guarded` owns the
one physical frame write and enters a *synchronous* write guard at that cut; the
caller cannot supply a writer. Four identities stay separate:
`engineering_attempt_ref` (external correlation), `agent_operation_ref` (agents'
turn), `endpoint_request_id` (derived from the closed frame request) and
`endpoint_operation_ref` (the endpoint effect owner's own id, never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol
import asyncio
import math
import time
import threading
from threading import RLock
from contextlib import contextmanager
from uuid import uuid4

from .instances import AgentInstanceRef, EndpointRef
from .prepare import EndpointError, PreparedConfigurationRef
from ..profiles import ProfileRevisionRef, encode_revision_ref, decode_revision_ref
from .prepare import _prepared_from

DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
STATES = frozenset({'reserved', 'possibly-written', 'completed', 'failed', 'unknown'})
SEND_STATES = frozenset({'not_sent', 'possibly_sent', 'confirmed'})
MAX_BYTES = 262144
MAX_FRESH_TURNS = 256
FRESH_TURN_SECONDS = 300


class InteractionsRefused(RuntimeError):
    def __init__(self, code, message=''):
        super().__init__(f'{code}: {message}' if message else code)
        self.code = code


def _text(value, name, limit=512):
    if type(value) is not str or not value or len(value) > limit:
        raise InteractionsRefused('VALUE_INVALID', name)
    if any(ord(char) < 0x20 or ord(char) == 0x7f for char in value):
        raise InteractionsRefused('VALUE_INVALID', name)
    return value


def _digest(value, name='digest'):
    if type(value) is not str or not DIGEST.match(value):
        raise InteractionsRefused('VALUE_INVALID', name)
    return value


def _canonical(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise InteractionsRefused('VALUE_INVALID', 'not finite JSON') from None


def _digest_of(value) -> str:
    return 'sha256:' + hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _writer_epoch(records,instance_ref,scope):
    from .manager import ManagerRefused
    try:return records.writer_epoch(instance_ref,scope)
    except ManagerRefused as error:raise InteractionsRefused(error.code) from None


def _closed(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        raise InteractionsRefused('DECODE_INVALID', name)
    return value


def _canonical_object(value):
    if type(value) is not dict:
        raise InteractionsRefused('DECODE_INVALID', 'JSON object required')
    return _canonical(value).encode('utf-8')


def _object_bytes(raw):
    try:
        value = json.loads(raw)
        if type(value) is not dict or _canonical_object(value) != raw:
            raise ValueError()
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise InteractionsRefused('VALUE_INVALID', 'canonical JSON object required') from None


@dataclass(frozen=True)
class TurnRef:
    instance_ref: AgentInstanceRef
    turn_id: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'turn instance')
        _text(self.turn_id, 'turn_id')

    def projection(self):
        return {'schemaVersion': 'agent-turn-ref/1',
                'instanceRef': self.instance_ref.projection(), 'turnId': self.turn_id}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'instanceRef', 'turnId'}, 'turn ref')
        if value['schemaVersion'] != 'agent-turn-ref/1':
            raise InteractionsRefused('DECODE_INVALID', 'turn ref version')
        return cls(AgentInstanceRef.decode(value['instanceRef']), value['turnId'])


@dataclass(frozen=True)
class FrozenPrompt:
    instance_ref: AgentInstanceRef
    session_id: str
    params_bytes: bytes
    input_digest: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'prompt instance')
        _text(self.session_id, 'session_id')
        if type(self.params_bytes) is not bytes or not self.params_bytes:
            raise InteractionsRefused('VALUE_INVALID', 'params_bytes')
        if len(self.params_bytes) > MAX_BYTES:
            raise InteractionsRefused('VALUE_INVALID', 'params_bytes too large')
        params = _object_bytes(self.params_bytes)
        if _canonical(params).encode('utf-8') != self.params_bytes:
            raise InteractionsRefused('VALUE_INVALID', 'params must be canonical JSON')
        if params.get('sessionId') != self.session_id:
            raise InteractionsRefused('VALUE_INVALID', 'fixed session mismatch')
        _digest(self.input_digest)
        if self.input_projection_digest() != self.input_digest:
            raise InteractionsRefused('VALUE_INVALID', 'input_digest does not match the closed projection')

    def input_projection(self):
        return {'schemaVersion': 'agent-prompt-input/1',
                'instanceRef': self.instance_ref.projection(),
                'sessionId': self.session_id,
                'params': json.loads(self.params_bytes.decode('utf-8'))}

    def input_projection_digest(self):
        return _digest_of(self.input_projection())

    def projection(self):
        return {'schemaVersion': 'agent-frozen-prompt/1',
                'instanceRef': self.instance_ref.projection(), 'sessionId': self.session_id,
                'paramsBytes': json.loads(self.params_bytes), 'inputDigest': self.input_digest}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'instanceRef', 'sessionId', 'paramsBytes', 'inputDigest'},
                'frozen prompt')
        if value['schemaVersion'] != 'agent-frozen-prompt/1':
            raise InteractionsRefused('DECODE_INVALID', 'frozen prompt version')
        return cls(AgentInstanceRef.decode(value['instanceRef']), value['sessionId'],
                   _canonical_object(value['paramsBytes']), value['inputDigest'])


@dataclass(frozen=True)
class TurnReadQuery:
    turn_ref: TurnRef
    expected_input_digest: str
    query_digest: str

    def __post_init__(self):
        if type(self.turn_ref) is not TurnRef:
            raise InteractionsRefused('VALUE_INVALID', 'turn_ref')
        _digest(self.expected_input_digest)
        _digest(self.query_digest)
        if self.query_projection_digest() != self.query_digest:
            raise InteractionsRefused('VALUE_INVALID', 'query_digest does not match the closed projection')

    def query_projection(self):
        return {'schemaVersion': 'agent-turn-query/1', 'turnRef': self.turn_ref.projection(),
                'expectedInputDigest': self.expected_input_digest}

    def query_projection_digest(self):
        return _digest_of(self.query_projection())

    def projection(self):
        return {**self.query_projection(),'queryDigest':self.query_digest}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'turnRef', 'expectedInputDigest', 'queryDigest'}, 'turn query')
        if value['schemaVersion'] != 'agent-turn-query/1':
            raise InteractionsRefused('DECODE_INVALID', 'turn query version')
        return cls(TurnRef.decode(value['turnRef']), value['expectedInputDigest'], value['queryDigest'])


@dataclass(frozen=True)
class TurnReceipt:
    turn_ref: TurnRef
    session_id: str
    agent_operation_ref: str
    endpoint_request_id: str | None
    endpoint_operation_ref: str | None
    engineering_attempt_ref: str | None
    input_digest: str
    state: str
    revision: int
    observation_bytes: bytes
    observation_digest: str

    def __post_init__(self):
        if type(self.turn_ref) is not TurnRef:
            raise InteractionsRefused('VALUE_INVALID', 'turn_ref')
        _text(self.session_id, 'session_id')
        _text(self.agent_operation_ref, 'agent_operation_ref')
        for name in ('endpoint_request_id', 'endpoint_operation_ref', 'engineering_attempt_ref'):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        _digest(self.input_digest)
        if type(self.state) is not str or self.state not in STATES:
            raise InteractionsRefused('VALUE_INVALID', 'state')
        if type(self.revision) is not int or type(self.revision) is bool or self.revision < 1:
            raise InteractionsRefused('VALUE_INVALID', 'revision')
        if type(self.observation_bytes) is not bytes or len(self.observation_bytes) > MAX_BYTES:
            raise InteractionsRefused('VALUE_INVALID', 'observation_bytes')
        observation = _object_bytes(self.observation_bytes)
        if _canonical(observation).encode('utf-8') != self.observation_bytes:
            raise InteractionsRefused('VALUE_INVALID', 'observation must be canonical JSON')
        _digest(self.observation_digest)
        if 'sha256:' + hashlib.sha256(self.observation_bytes).hexdigest() != self.observation_digest:
            raise InteractionsRefused('VALUE_INVALID', 'observation_digest does not match bytes')
        if len(_canonical(self.projection()).encode('utf-8')) > MAX_BYTES:
            raise InteractionsRefused('VALUE_INVALID', 'complete turn receipt too large')

    def projection(self):
        return {'schemaVersion': 'agent-protocol-turn/1', 'turnRef': self.turn_ref.projection(),
                'sessionId': self.session_id, 'agentOperationRef': self.agent_operation_ref,
                'endpointRequestId': self.endpoint_request_id,
                'endpointOperationRef': self.endpoint_operation_ref,
                'engineeringAttemptRef': self.engineering_attempt_ref,
                'inputDigest': self.input_digest, 'state': self.state,
                'revision': self.revision,
                'observationBytes': json.loads(self.observation_bytes),
                'observationDigest': self.observation_digest}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'turnRef', 'sessionId', 'agentOperationRef',
                        'endpointRequestId', 'endpointOperationRef', 'engineeringAttemptRef',
                        'inputDigest', 'state', 'revision', 'observationBytes',
                        'observationDigest'}, 'turn receipt')
        if value['schemaVersion'] != 'agent-protocol-turn/1':
            raise InteractionsRefused('DECODE_INVALID', 'turn receipt version')
        return cls(TurnRef.decode(value['turnRef']), value['sessionId'],
                   value['agentOperationRef'], value['endpointRequestId'],
                   value['endpointOperationRef'], value['engineeringAttemptRef'],
                   value['inputDigest'], value['state'], value['revision'],
                   _canonical_object(value['observationBytes']), value['observationDigest'])


@dataclass(frozen=True)
class BindingProvenance:
    instance_ref: AgentInstanceRef
    revision: int
    profile_ref: ProfileRevisionRef
    prepared_plan_digest: str
    endpoint_ref: EndpointRef
    directory_binding_digest: str
    source_revision: str
    configuration_refs: tuple[PreparedConfigurationRef, ...]
    captured_at: str
    observation_digest: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef or type(self.endpoint_ref) is not EndpointRef:
            raise InteractionsRefused('VALUE_INVALID', 'provenance identity')
        if self.profile_ref is None or type(self.profile_ref) is not ProfileRevisionRef:
            raise InteractionsRefused('PROVENANCE_UNAVAILABLE', 'original profile facts')
        if type(self.revision) is not int or type(self.revision) is bool or self.revision < 1:
            raise InteractionsRefused('VALUE_INVALID', 'revision')
        _digest(self.prepared_plan_digest)
        _digest(self.directory_binding_digest)
        _text(self.source_revision, 'source_revision')
        if type(self.configuration_refs) is not tuple or any(
                type(item) is not PreparedConfigurationRef for item in self.configuration_refs):
            raise InteractionsRefused('VALUE_INVALID', 'configuration_refs')
        _text(self.captured_at, 'captured_at')
        _digest(self.observation_digest)
        if self._digest() != self.observation_digest:
            raise InteractionsRefused('VALUE_INVALID', 'observation_digest does not match the projection')

    def _projection(self):
        return {'schemaVersion': 'agent-binding-provenance/1',
                'instanceRef': self.instance_ref.projection(), 'revision': self.revision,
                'profileRef': encode_revision_ref(self.profile_ref),
                'preparedPlanDigest': self.prepared_plan_digest,
                'endpointRef': self.endpoint_ref.projection(),
                'directoryBindingDigest': self.directory_binding_digest,
                'sourceRevision': self.source_revision,
                'configurationRefs': [item.projection() for item in self.configuration_refs],
                'capturedAt': self.captured_at}

    def _digest(self):
        return _digest_of(self._projection())

    def projection(self):
        return {**self._projection(), 'observationDigest': self.observation_digest}


    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion','instanceRef','revision','profileRef','preparedPlanDigest',
            'endpointRef','directoryBindingDigest','sourceRevision','configurationRefs','capturedAt',
            'observationDigest'}, 'binding provenance')
        if value['schemaVersion'] != 'agent-binding-provenance/1' or type(value['configurationRefs']) is not list:
            raise InteractionsRefused('DECODE_INVALID', 'binding provenance version/refs')
        return cls(AgentInstanceRef.decode(value['instanceRef']),value['revision'],
            decode_revision_ref(value['profileRef']),value['preparedPlanDigest'],
            EndpointRef.decode(value['endpointRef']),value['directoryBindingDigest'],value['sourceRevision'],
            tuple(_prepared_from(v) for v in value['configurationRefs']),value['capturedAt'],value['observationDigest'])


@dataclass(frozen=True)
class WriteBinding:
    turn_ref: TurnRef
    session_id: str
    agent_operation_ref: str
    endpoint_request_id: str
    engineering_attempt_ref: str | None
    input_digest: str
    frame_digest: str

    def __post_init__(self):
        if type(self.turn_ref) is not TurnRef:
            raise InteractionsRefused('VALUE_INVALID', 'turn_ref')
        _text(self.session_id, 'session_id')
        _text(self.agent_operation_ref, 'agent_operation_ref')
        _text(self.endpoint_request_id, 'endpoint_request_id')
        if self.engineering_attempt_ref is not None:
            _text(self.engineering_attempt_ref, 'engineering_attempt_ref')
        _digest(self.input_digest)
        _digest(self.frame_digest)

    def projection(self):
        return {'schemaVersion': 'agent-write-binding/1', 'turnRef': self.turn_ref.projection(),
                'sessionId': self.session_id, 'agentOperationRef': self.agent_operation_ref,
                'endpointRequestId': self.endpoint_request_id,
                'engineeringAttemptRef': self.engineering_attempt_ref,
                'inputDigest': self.input_digest, 'frameDigest': self.frame_digest}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'turnRef', 'sessionId', 'agentOperationRef',
                        'endpointRequestId', 'engineeringAttemptRef', 'inputDigest',
                        'frameDigest'}, 'write binding')
        if value['schemaVersion'] != 'agent-write-binding/1':
            raise InteractionsRefused('DECODE_INVALID', 'write binding version')
        return cls(TurnRef.decode(value['turnRef']), value['sessionId'],
                   value['agentOperationRef'], value['endpointRequestId'],
                   value['engineeringAttemptRef'], value['inputDigest'], value['frameDigest'])


@dataclass(frozen=True)
class CancelBinding:
    """One original ACP ``session/cancel`` notification; no turn is claimed."""
    instance_ref: AgentInstanceRef
    session_id: str
    agent_operation_ref: str
    endpoint_request_id: str
    frame_digest: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'instance_ref')
        _text(self.session_id, 'session_id')
        _text(self.agent_operation_ref, 'agent_operation_ref')
        _text(self.endpoint_request_id, 'endpoint_request_id')
        _digest(self.frame_digest)

    def projection(self):
        return {'schemaVersion': 'agent-cancel-binding/1',
                'instanceRef': self.instance_ref.projection(),
                'sessionId': self.session_id,
                'agentOperationRef': self.agent_operation_ref,
                'endpointRequestId': self.endpoint_request_id,
                'frameDigest': self.frame_digest}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'instanceRef', 'sessionId', 'agentOperationRef',
                        'endpointRequestId', 'frameDigest'}, 'cancel binding')
        if value['schemaVersion'] != 'agent-cancel-binding/1':
            raise InteractionsRefused('DECODE_INVALID', 'cancel binding version')
        return cls(AgentInstanceRef.decode(value['instanceRef']), value['sessionId'],
                   value['agentOperationRef'], value['endpointRequestId'],
                   value['frameDigest'])


@dataclass(frozen=True)
class CancelReceipt:
    """Physical cancel-notification evidence; acceptance is not cancellation."""
    instance_ref: AgentInstanceRef
    session_id: str
    agent_operation_ref: str
    endpoint_request_id: str
    frame_digest: str
    state: str
    delivery: str
    bytes_sent: int | None = None
    error_code: str | None = None

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'instance_ref')
        _text(self.session_id, 'session_id')
        _text(self.agent_operation_ref, 'agent_operation_ref')
        _text(self.endpoint_request_id, 'endpoint_request_id')
        _digest(self.frame_digest)
        if self.state not in ('accepted', 'refused', 'unknown'):
            raise InteractionsRefused('VALUE_INVALID', 'cancel state')
        if self.delivery not in ('confirmed', 'possibly_sent', 'not_sent', 'completed', 'unknown'):
            raise InteractionsRefused('VALUE_INVALID', 'cancel delivery')
        if self.bytes_sent is not None and (type(self.bytes_sent) is not int
                                            or self.bytes_sent < 0):
            raise InteractionsRefused('VALUE_INVALID', 'bytes_sent')
        if self.error_code is not None:
            _text(self.error_code, 'error_code')

    def projection(self):
        return {'schemaVersion': 'agent-cancel-receipt/1',
                'instanceRef': self.instance_ref.projection(),
                'sessionId': self.session_id,
                'agentOperationRef': self.agent_operation_ref,
                'endpointRequestId': self.endpoint_request_id,
                'frameDigest': self.frame_digest,
                'state': self.state, 'delivery': self.delivery,
                'bytesSent': self.bytes_sent, 'errorCode': self.error_code}

    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion', 'instanceRef', 'sessionId', 'agentOperationRef',
                        'endpointRequestId', 'frameDigest', 'state', 'delivery',
                        'bytesSent', 'errorCode'}, 'cancel receipt')
        if value['schemaVersion'] != 'agent-cancel-receipt/1':
            raise InteractionsRefused('DECODE_INVALID', 'cancel receipt version')
        return cls(AgentInstanceRef.decode(value['instanceRef']), value['sessionId'],
                   value['agentOperationRef'], value['endpointRequestId'],
                   value['frameDigest'], value['state'], value['delivery'],
                   value['bytesSent'], value['errorCode'])


@dataclass(frozen=True)
class GuardedSendObservation:
    operation_ref: str
    status: str
    bytes_sent: int | None
    error: EndpointError | None = None

    def __post_init__(self):
        _text(self.operation_ref, 'operation_ref')
        if type(self.status) is not str or self.status not in SEND_STATES:
            raise InteractionsRefused('VALUE_INVALID', 'send status')
        if self.bytes_sent is not None and (type(self.bytes_sent) is not int
                                            or type(self.bytes_sent) is bool or self.bytes_sent < 0):
            raise InteractionsRefused('VALUE_INVALID', 'bytes_sent')
        if self.error is not None and type(self.error) is not EndpointError:
            raise InteractionsRefused('VALUE_INVALID', 'typed bounded endpoint error required')
        if self.status == 'not_sent':
            if self.bytes_sent != 0 or self.error is None:
                raise InteractionsRefused('VALUE_INVALID', 'not_sent needs zero bytes and a bounded error')
        elif self.error is not None:
            raise InteractionsRefused('VALUE_INVALID', 'a sent frame carries no unsent error')

    def projection(self):
        return {'schemaVersion': 'agent-guarded-send-observation/1', 'operationRef': self.operation_ref,
                'status': self.status, 'bytesSent': self.bytes_sent,
                'error': None if self.error is None else self.error.projection()}


    @classmethod
    def decode(cls, value):
        _closed(value, {'schemaVersion','operationRef','status','bytesSent','error'}, 'guarded send')
        if value['schemaVersion'] != 'agent-guarded-send-observation/1':
            raise InteractionsRefused('DECODE_INVALID', 'guarded send version')
        error=value['error']
        if error is not None:
            _closed(error, {'code','diagnostic'}, 'endpoint error')
            error=EndpointError(error['code'],error['diagnostic'])
        return cls(value['operationRef'],value['status'],value['bytesSent'],error)


class WriteGuardPort(Protocol):
    """Additive guarded write on the SAME communicate member (§12.4)."""

    def guard_write(self, binding: WriteBinding, invocation: object): ...


class InteractionAuthorityPort(Protocol):
    """Externally issued authority. Checks raise on refusal and return nothing."""

    def principal_scope(self, invocation: object) -> str: ...

    def check_read_turn(self, invocation: object, query: TurnReadQuery) -> None: ...

    def check_read_binding(self, invocation: object, instance_ref: AgentInstanceRef) -> None: ...

    def check_send(self, invocation: object, binding: WriteBinding) -> None: ...
    def check_cancel(self, invocation: object, binding: CancelBinding) -> None: ...
    def check_native_dispatch(self,invocation,binding) -> None: ...
    def check_read_native_operation(self,invocation,operation_ref,input_digest) -> None: ...
    def guard_native_dispatch(self,invocation,binding): ...


def _check(authority, name, *args):
    if authority is None or not callable(getattr(authority, name, None)):
        raise InteractionsRefused('AUTHORITY_UNAVAILABLE', name)
    try:
        result = getattr(authority, name)(*args)
        if result is not None:
            raise InteractionsRefused('AUTHORITY_PROTOCOL_INVALID', name)
    except InteractionsRefused:
        raise
    except Exception as error:
        code = getattr(error, 'code', None) or 'AUTHORITY_REFUSED'
        raise InteractionsRefused(code, name) from None


def freeze_prompt(instance_ref: AgentInstanceRef, params_bytes: bytes) -> FrozenPrompt:
    """Derive the closed prompt identity; pure, no dispatch or authorization."""
    if type(params_bytes) is not bytes or not params_bytes:
        raise InteractionsRefused('VALUE_INVALID', 'params_bytes')
    raw = params_bytes
    if _canonical(json.loads(raw.decode('utf-8'))).encode('utf-8') != raw:
        raise InteractionsRefused('VALUE_INVALID', 'params must be canonical JSON')
    params = json.loads(raw.decode('utf-8'))
    session_id = params.get('sessionId') if isinstance(params, dict) else None
    if type(session_id) is not str or not session_id:
        raise InteractionsRefused('VALUE_INVALID', 'params must carry the fixed sessionId')
    projection = {'schemaVersion': 'agent-prompt-input/1',
                  'instanceRef': instance_ref.projection(), 'sessionId': session_id,
                  'params': params}
    return FrozenPrompt(instance_ref, session_id, raw, _digest_of(projection))


def turn_query(turn_ref: TurnRef, expected_input_digest: str) -> TurnReadQuery:
    projection = {'schemaVersion': 'agent-turn-query/1', 'turnRef': turn_ref.projection(),
                  'expectedInputDigest': expected_input_digest}
    return TurnReadQuery(turn_ref, expected_input_digest, _digest_of(projection))


def endpoint_request_id(agent_operation_ref, endpoint_ref, frame_digest):
    return _digest_of({'schemaVersion':'agent-endpoint-frame-request/1',
        'agentOperationRef':agent_operation_ref,'endpointRef':endpoint_ref.projection(),
        'frameDigest':frame_digest,'frameOrdinal':0})


def cancel_endpoint_request_id(agent_operation_ref, endpoint_ref, frame_digest):
    return _digest_of({'schemaVersion':'agent-cancel-frame-request/1',
        'agentOperationRef':agent_operation_ref,'endpointRef':endpoint_ref.projection(),
        'frameDigest':frame_digest,'frameOrdinal':0})


class InteractionService:
    """One original Records owner for instance bindings and turn observations.

    Instance metadata is published by trusted materialization into the SAME
    owner, never inferred from an endpoint/ref/digest supplied by a caller.
    """
    def __init__(self, records, authority, endpoint_resolver=None, native_prompts=None,
                 native_codecs=None):
        from .manager import Records
        if type(records) is not Records:
            raise InteractionsRefused('ORIGINAL_RECORDS_REQUIRED')
        if not all(callable(getattr(authority,n,None)) for n in
                ('principal_scope','check_send','check_read_turn','check_read_binding')):
            raise InteractionsRefused('AUTHORITY_UNAVAILABLE')
        self.records,self.authority,self.endpoint_resolver=records,authority,endpoint_resolver
        if native_prompts is None:native_prompts={}
        if not isinstance(native_prompts, dict):raise InteractionsRefused('NATIVE_PROMPT_HANDLERS_INVALID')
        self._native_prompts=dict(native_prompts)
        if native_codecs is None:native_codecs={}
        if not isinstance(native_codecs, dict):raise InteractionsRefused('NATIVE_CODECS_INVALID')
        self._native_codecs=dict(native_codecs)
        self._native=None
        # One process owns the live receiver for accepted native operations. A
        # fresh owner must turn any accepted-but-unresolved row into unknown
        # instead of pretending the previous process still holds it.
        try:
            records.expire_unresolved_native_operations()
        except Exception:
            pass
        self._fresh={}
        self._fresh_lock=RLock()
        self._receiving=set()

    def native(self):
        """The one native runtime registry over the SAME records/authority."""
        if self._native is None:
            from .native_runtime import NativeRuntimeRegistry
            self._native=NativeRuntimeRegistry(self)
        return self._native

    def close(self):
        """Cancel live receiver tasks; never stop an externally owned endpoint."""
        native=self._native
        self._native=None
        if native is None:return
        for runtime in list(native._runtimes.values()):
            runtime._closed=True
            runtime._stop.set()
            if runtime._read_task is not None:
                runtime._read_task.cancel()
        native._runtimes.clear()

    def expire_instance(self, instance_ref, *, reason='PROCESS_STOPPED'):
        """The instance's process is gone: its live receiver and accepted native
        work must become an explicit unknown instead of a fake live handle."""
        if type(instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'instance')
        from .native_runtime import _runtime_key
        native=self._native
        if native is not None:
            key=_runtime_key(instance_ref)
            runtime=native._runtimes.pop(key,None)
            if runtime is not None:
                runtime._closed=True
                runtime._stop.set()
                if runtime._read_task is not None:
                    runtime._read_task.cancel()
        try:
            self.records.expire_native_operations_for_instance(
                instance_ref.instance_id, reason=reason)
        except Exception:
            pass

    async def cancel_session(self, instance_ref, *, request_id, invocation, write_guard, deadline):
        """Send one original ACP ``session/cancel`` notification.

        A durable claim precedes the physical write; the same request id and
        frame replay the stored receipt and never resend. A notification has no
        response, so acceptance means the frame was written, not that the
        provider has already cancelled anything.
        """
        import hashlib
        if not callable(getattr(write_guard, 'guard_write', None)):
            raise InteractionsRefused('WRITE_GUARD_REQUIRED')
        if self.endpoint_resolver is None or not callable(getattr(self.endpoint_resolver, 'resolve', None)):
            raise InteractionsRefused('ENDPOINT_UNAVAILABLE')
        if deadline is None:
            raise InteractionsRefused('DEADLINE_REQUIRED')
        loop = asyncio.get_running_loop()
        if deadline <= loop.time():
            raise InteractionsRefused('CANCEL_DEADLINE_ELAPSED')
        scope = self._scope(invocation)
        provenance, session = self._instance(instance_ref, scope)
        binding_row = self.records.operation(
            _digest_of({'namespace': instance_ref.namespace,
                        'instanceId': instance_ref.instance_id}), 'instance-binding')
        if binding_row is None:
            raise InteractionsRefused('INSTANCE_BINDING_UNAVAILABLE')
        protocol = binding_row.payload.get('protocolId')
        # Deterministic per (scope, instance, requestId): a replay must rebuild
        # the SAME frame, otherwise a native cancel (whose frame carries the
        # operation id) would conflict with its own stored receipt.
        key = self._key(instance_ref, request_id, scope)
        operation = 'agent-operation/' + key.split(':', 1)[1]
        if protocol == 'acp':
            frame = (_canonical({'jsonrpc': '2.0', 'method': 'session/cancel',
                                 'params': {'sessionId': session}}) + '\n').encode()
        else:
            handler = self._native_handler(protocol)
            try:
                frame = handler.encode_cancel(session, operation)
            except Exception:
                raise InteractionsRefused('CANCEL_FRAME_INVALID') from None
        frame_digest = 'sha256:' + hashlib.sha256(frame).hexdigest()
        child = cancel_endpoint_request_id(operation, provenance.endpoint_ref, frame_digest)
        binding = CancelBinding(instance_ref, session, operation, child, frame_digest)
        _check(self.authority, 'check_cancel', invocation, binding)
        target = _canonical({'instanceRef': instance_ref.projection(),
                             'endpointRef': provenance.endpoint_ref.projection(),
                             'sessionId': session, 'action': 'cancel'})
        request_digest = _digest_of({'inputDigest': frame_digest, 'action': 'cancel'})
        state, record = self.records.claim(key, 'cancel', principal=scope, target=target,
            request_digest=request_digest, operation_ref=operation,
            payload={'cancelBinding': binding.projection()})
        if state == 'existing':
            if record.request_digest != request_digest:
                raise InteractionsRefused('REQUEST_CONFLICT')
            _check(self.authority, 'check_read_binding', invocation, instance_ref)
            return self._cancel_receipt(record)
        try:
            bound = await self.endpoint_resolver.resolve(provenance.endpoint_ref, invocation)
            sent = await bound.communicate.send_guarded(frame, child, deadline, invocation,
                binding=binding, write_guard=write_guard)
            if type(sent) is not GuardedSendObservation:
                raise InteractionsRefused('CANCEL_OBSERVATION_INVALID')
            status = 'refused' if sent.status == 'not_sent' else 'accepted'
            receipt = CancelReceipt(instance_ref, session, operation, child, frame_digest,
                status, sent.status, sent.bytes_sent,
                None if sent.error is None else sent.error.code)
            self.records.complete(key, 'cancel', status=status, operation_ref=operation,
                                  payload={'cancelReceipt': receipt.projection()})
            return receipt
        except BaseException:
            # Cancellation/KeyboardInterrupt leave the reservation unresolved.
            # Any other failure after the claim is unknown, never a resend.
            try:
                receipt = CancelReceipt(instance_ref, session, operation, child, frame_digest,
                    'unknown', 'unknown', None, 'CANCEL_UNCONFIRMED')
                self.records.complete(key, 'cancel', status='unknown', operation_ref=operation,
                                      payload={'cancelReceipt': receipt.projection()})
            except Exception:
                pass
            raise

    def _cancel_receipt(self, record):
        if record.status == 'reserved':
            return CancelReceipt(
                AgentInstanceRef.decode(record.payload['cancelBinding']['instanceRef']),
                record.payload['cancelBinding']['sessionId'],
                record.payload['cancelBinding']['agentOperationRef'],
                record.payload['cancelBinding']['endpointRequestId'],
                record.payload['cancelBinding']['frameDigest'],
                'unknown', 'unknown', None, 'CANCEL_UNCONFIRMED')
        try:
            receipt = CancelReceipt.decode(record.payload['cancelReceipt'])
        except Exception:
            raise InteractionsRefused('RECORD_CORRUPT') from None
        if receipt.state != record.status or receipt.agent_operation_ref != record.operation_ref:
            raise InteractionsRefused('RECORD_CORRUPT')
        return receipt

    def _prune_fresh(self):
        now=time.monotonic()
        for key,(_,_,expires) in tuple(self._fresh.items()):
            if expires<=now:self._fresh.pop(key,None)

    def invalidate_invocation(self, invocation):
        """Original operation owner drops its private associations on end/cancel.

        This can only remove send eligibility; it never changes records or grants.
        An expired/dropped reservation remains observable as unknown, never fresh.
        """
        with self._fresh_lock:
            self._prune_fresh()
            for key,(issued,_,_) in tuple(self._fresh.items()):
                if issued is invocation:self._fresh.pop(key,None)

    def _fresh_for(self,key):
        with self._fresh_lock:
            self._prune_fresh()
            return self._fresh.get(key)

    def _scope(self, invocation):
        try:scope=self.authority.principal_scope(invocation)
        except Exception:raise InteractionsRefused('AUTHORITY_REFUSED') from None
        return _text(scope,'verified principal scope')

    def _instance(self, instance_ref, scope=None):
        if type(instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID','instance reference')
        key=_digest_of({'namespace':instance_ref.namespace,'instanceId':instance_ref.instance_id})
        record=self.records.operation(key,'instance-binding')
        if (record is None or record.status!='completed' or record.target!=_canonical(instance_ref.projection())
                or scope is not None and record.principal!=scope):
            raise InteractionsRefused('PROVENANCE_UNAVAILABLE')
        try:
            self.records.validate_instance_origin(record)
            provenance=BindingProvenance.decode(record.payload['provenance'])
            session=record.payload['sessionId']
            if record.payload.get('protocolId') is not None:_text(session,'original session')
            elif session is not None:raise ValueError('invalid session')
        except Exception:raise InteractionsRefused('PROVENANCE_UNAVAILABLE') from None
        if provenance.instance_ref!=instance_ref:
            raise InteractionsRefused('PROVENANCE_UNAVAILABLE')
        return provenance,session

    def _protocol(self,instance_ref):
        key=_digest_of({'namespace':instance_ref.namespace,'instanceId':instance_ref.instance_id})
        original=self.records.operation(key,'instance-binding')
        if original is None:raise InteractionsRefused('INSTANCE_BINDING_UNAVAILABLE')
        return original.payload.get('protocolId')

    def _native_handler(self,protocol):
        handler=self._native_prompts.get(protocol)
        if handler is None:raise InteractionsRefused('PROTOCOL_UNSUPPORTED')
        return handler

    def _prompt_frame(self,instance_ref,prompt,operation_ref):
        protocol=self._protocol(instance_ref)
        if protocol=='acp':
            from .acp import prompt_frame
            return prompt_frame(prompt.params_bytes,operation_ref)
        handler=self._native_handler(protocol)
        _,session=self._instance(instance_ref)
        try:
            return handler.encode_prompt(session,prompt.params_bytes,operation_ref)
        except Exception:
            raise InteractionsRefused('PROMPT_FRAME_INVALID') from None

    def freeze_prompt(self, instance_ref, params_bytes):
        _,session=self._instance(instance_ref)
        prompt=freeze_prompt(instance_ref,params_bytes)
        if prompt.session_id!=session:
            raise InteractionsRefused('FIXED_SESSION_MISMATCH')
        return prompt

    def turn_query(self, turn_ref, expected_input_digest):
        return turn_query(turn_ref,expected_input_digest)

    def read_binding(self, instance_ref, *, invocation):
        _check(self.authority,'check_read_binding',invocation,instance_ref)
        provenance,_=self._instance(instance_ref,self._scope(invocation))
        return provenance

    def _key(self, instance_ref, request_id, scope):
        _text(request_id,'request_id')
        return _digest_of({'scope':scope,'namespace':instance_ref.namespace,
            'instanceId':instance_ref.instance_id,'requestId':request_id})

    def _row_receipt(self, record):
        try:receipt=TurnReceipt.decode(record.payload['turnReceipt'])
        except Exception:raise InteractionsRefused('RECORD_CORRUPT') from None
        if (receipt.turn_ref.turn_id!=record.turn_id or receipt.agent_operation_ref!=record.operation_ref
                or receipt.state!=record.status):
            raise InteractionsRefused('RECORD_CORRUPT')
        if record.status=='reserved' and self._fresh_for(record.request_id) is None:
            from dataclasses import replace
            receipt=replace(receipt,state='unknown')
        return receipt

    def query_turn(self, query, *, invocation):
        if type(query) is not TurnReadQuery:raise InteractionsRefused('VALUE_INVALID','query')
        _check(self.authority,'check_read_turn',invocation,query)
        scope=self._scope(invocation)
        record=self.records.turn(query.turn_ref.turn_id)
        if record is None or record.principal!=scope:
            raise InteractionsRefused('READ_NOT_AUTHORIZED')
        receipt=self._row_receipt(record)
        if receipt.turn_ref!=query.turn_ref or receipt.input_digest!=query.expected_input_digest:
            raise InteractionsRefused('OBSERVATION_MISMATCH')
        return receipt

    def reserve_turn(self, instance_ref, prompt, *, request_id, engineering_attempt_ref, invocation):
        with self._fresh_lock:
            self._prune_fresh()
            return self._reserve_turn(instance_ref,prompt,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,invocation=invocation)

    def _reserve_turn(self, instance_ref, prompt, *, request_id, engineering_attempt_ref, invocation):
        scope=self._scope(invocation)
        provenance,session=self._instance(instance_ref,scope)
        if type(prompt) is not FrozenPrompt or prompt.instance_ref!=instance_ref or prompt.session_id!=session:
            raise InteractionsRefused('FIXED_SESSION_MISMATCH')
        # Revalidate after any attempted object mutation by trusted Python.
        FrozenPrompt.decode(prompt.projection())
        if engineering_attempt_ref is not None:_text(engineering_attempt_ref,'engineering attempt')
        key=self._key(instance_ref,request_id,scope)
        target=_canonical({'instanceRef':instance_ref.projection(),'endpointRef':provenance.endpoint_ref.projection(),
                           'sessionId':session})
        digest=_digest_of({'inputDigest':prompt.input_digest,'engineeringAttemptRef':engineering_attempt_ref})
        existing=self.records.operation(key,'turn')
        if existing is not None:
            if (existing.principal,existing.target,existing.request_digest)!=(scope,target,digest):
                raise InteractionsRefused('REQUEST_CONFLICT')
            return self.query_turn(turn_query(self._row_receipt(existing).turn_ref,prompt.input_digest),invocation=invocation)
        if len(self._fresh)>=MAX_FRESH_TURNS:
            raise InteractionsRefused('FRESH_CAPACITY_EXHAUSTED')
        turn=TurnRef(instance_ref,'turn/'+uuid4().hex);operation='agent-operation/'+uuid4().hex
        frame_digest='sha256:'+hashlib.sha256(self._prompt_frame(instance_ref,prompt,operation)).hexdigest()
        child=endpoint_request_id(operation,provenance.endpoint_ref,frame_digest)
        write=WriteBinding(turn,session,operation,child,engineering_attempt_ref,prompt.input_digest,frame_digest)
        _check(self.authority,'check_send',invocation,write)
        receipt=TurnReceipt(turn,session,operation,child,None,engineering_attempt_ref,prompt.input_digest,
                            'reserved',1,b'{}','sha256:'+hashlib.sha256(b'{}').hexdigest())
        epoch=_writer_epoch(self.records,instance_ref,scope)
        payload={'turnReceipt':receipt.projection(),'requestId':request_id,'frameDigest':frame_digest,
                 'controlEpoch':epoch}
        state,record=self.records.claim(key,'turn',principal=scope,target=target,request_digest=digest,
            operation_ref=operation,payload=payload,turn_id=turn.turn_id)
        if state=='existing':
            return self.query_turn(turn_query(self._row_receipt(record).turn_ref,prompt.input_digest),invocation=invocation)
        self._fresh[key]=(invocation,prompt,time.monotonic()+FRESH_TURN_SECONDS)
        return receipt

    async def prompt_recorded(self, instance_ref, prompt, *, request_id, engineering_attempt_ref,
                              invocation, write_guard, deadline):
        try:
            receipt=await self._prompt_recorded(instance_ref,prompt,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,invocation=invocation,
                write_guard=write_guard,deadline=deadline)
            # Executing a send does not grant reading original protocol facts.
            return self.query_turn(turn_query(receipt.turn_ref,receipt.input_digest),invocation=invocation)
        finally:
            # Direct callers have the same operation-end semantics as Manager.
            # Even refusal before child dispatch ends this original fresh flow;
            # its durable parent remains history, never a later send ticket.
            self.invalidate_invocation(invocation)

    async def _prompt_recorded(self, instance_ref, prompt, *, request_id, engineering_attempt_ref,
                              invocation, write_guard, deadline):
        scope=self._scope(invocation)
        if type(instance_ref) is not AgentInstanceRef or type(prompt) is not FrozenPrompt:
            raise InteractionsRefused('VALUE_INVALID','instance/prompt')
        if self._native is not None and self._native.has_live(instance_ref):
            # ONE reader per instance: while an accepted native operation owns the
            # receive loop, a synchronous prompt must not start a second reader.
            raise InteractionsRefused('SESSION_BUSY','native runtime owns the receive loop')
        key=self._key(instance_ref,request_id,scope)
        record=self.records.operation(key,'turn')
        provenance,session=self._instance(instance_ref,scope)
        digest=_digest_of({'inputDigest':prompt.input_digest,'engineeringAttemptRef':engineering_attempt_ref})
        target=_canonical({'instanceRef':instance_ref.projection(),'endpointRef':provenance.endpoint_ref.projection(),
                           'sessionId':session})
        if record is not None:
            if (record.principal,record.target,record.request_digest)!=(scope,target,digest):
                raise InteractionsRefused('REQUEST_CONFLICT')
            receipt=self._row_receipt(record)
            fresh=self._fresh_for(key)
            if fresh is None or fresh[0] is not invocation:
                return self.query_turn(turn_query(receipt.turn_ref,prompt.input_digest),invocation=invocation)
        if (not callable(getattr(write_guard,'guard_write',None)) or type(deadline) not in (int,float)
                or not math.isfinite(deadline) or deadline<=asyncio.get_running_loop().time()):
            raise InteractionsRefused('WRITER_GUARD_UNSUPPORTED')
        if record is None:
            self.reserve_turn(instance_ref,prompt,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,invocation=invocation)
            record=self.records.operation(key,'turn')
            receipt=self._row_receipt(record)
            fresh=self._fresh_for(key)
            if fresh is None or fresh[0] is not invocation:
                return self.query_turn(turn_query(receipt.turn_ref,prompt.input_digest),invocation=invocation)
        if fresh[1]!=prompt:raise InteractionsRefused('REQUEST_CONFLICT')
        frame=self._prompt_frame(instance_ref,prompt,receipt.agent_operation_ref)
        if record.payload.get('frameDigest')!='sha256:'+hashlib.sha256(frame).hexdigest():
            raise InteractionsRefused('RECORD_CORRUPT')
        write=WriteBinding(receipt.turn_ref,session,receipt.agent_operation_ref,receipt.endpoint_request_id,
            engineering_attempt_ref,prompt.input_digest,record.payload['frameDigest'])
        _check(self.authority,'check_send',invocation,write)
        with self._fresh_lock:
            self._prune_fresh()
            if self._fresh.get(key) is not fresh:
                return self.query_turn(turn_query(receipt.turn_ref,prompt.input_digest),invocation=invocation)
            if instance_ref in self._receiving:raise InteractionsRefused('SESSION_BUSY')
            session_target=_canonical({'endpointRef':provenance.endpoint_ref.projection(),'protocolId':'acp'})
            session_record=self.records.enter_protocol_session(_digest_of({'protocolSession':session_target}),
                principal=scope,target=session_target,turn=record)
            self._fresh.pop(key)  # consumes original flow before ANY await/effect
            self._receiving.add(instance_ref)
        service=self
        captured_epoch=record.payload.get('controlEpoch')
        task,thread=asyncio.current_task(),threading.get_ident()
        guard_used=False
        class CurrentGuard:
            @contextmanager
            def guard_write(self,binding,actual_invocation):
                nonlocal guard_used
                if (guard_used or binding!=write or actual_invocation is not invocation
                        or asyncio.current_task() is not task or threading.get_ident()!=thread):
                    raise InteractionsRefused('WRITE_BINDING_MISMATCH')
                guard_used=True
                if type(captured_epoch) is not int:
                    raise InteractionsRefused('WRITER_EPOCH_UNAVAILABLE')
                _check(service.authority,'check_send',actual_invocation,binding)
                with write_guard.guard_write(binding,actual_invocation):
                    if deadline<=asyncio.get_running_loop().time():
                        raise InteractionsRefused('WRITE_DEADLINE_ELAPSED')
                    with service.records.guard_writer_epoch(instance_ref,scope,captured_epoch):
                        _check(service.authority,'check_send',actual_invocation,binding)
                        yield
        try:
            try:
                from .endpoint import BoundEndpoint
                if not callable(getattr(self.endpoint_resolver,'resolve',None)):
                    raise InteractionsRefused('ENDPOINT_UNAVAILABLE')
                bound=await self.endpoint_resolver.resolve(provenance.endpoint_ref,invocation)
                if type(bound) is not BoundEndpoint or bound.ref!=provenance.endpoint_ref:
                    raise InteractionsRefused('ENDPOINT_IDENTITY_MISMATCH')
                send=getattr(bound.communicate,'send_guarded',None)
                if not callable(send):raise InteractionsRefused('WRITER_GUARD_UNSUPPORTED')
                if not callable(getattr(bound.communicate,'receive',None)):raise InteractionsRefused('PROTOCOL_RECEIVE_UNAVAILABLE')
            except Exception:
                return self._finish_turn(record,receipt,'failed',{'delivery':'not_sent','reason':'endpoint_unavailable'})
            try:
                sent=await send(frame,write.endpoint_request_id,deadline,invocation,binding=write,write_guard=CurrentGuard())
                if type(sent) is not GuardedSendObservation:raise InteractionsRefused('OBSERVATION_INVALID')
            except BaseException as error:
                unknown=self._finish_turn(record,receipt,'unknown',{'delivery':'possibly_sent'})
                if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
                return unknown
            # Physical acknowledgement is NOT an observed protocol reply.
            state='failed' if sent.status=='not_sent' else 'possibly-written'
            delivery={'delivery':sent.status,'bytesSent':sent.bytes_sent}
            physical=self._finish_turn(record,receipt,state,delivery,sent.operation_ref)
            if state=='failed':return physical
            current=self.records.turn(receipt.turn_ref.turn_id)
            protocol=self._protocol(instance_ref)
            if protocol=='acp':
                from .acp import observe_prompt
                observer=lambda: observe_prompt(bound.communicate.receive,
                    operation_ref=receipt.agent_operation_ref,session_id=session,deadline=deadline,
                    invocation=invocation,delivery=delivery)
            else:
                from .native_prompt import observe_native_prompt
                handler=self._native_handler(protocol)
                observer=lambda: observe_native_prompt(bound.communicate.receive,handler,
                    session_id=session,deadline=deadline,invocation=invocation,delivery=delivery)
            try:
                terminal,observation=await observer()
            except asyncio.CancelledError:
                self._finish_turn(current,physical,'unknown',{**delivery,'reason':'protocol_receive_cancelled'},sent.operation_ref)
                raise
            return self._finish_turn(current,physical,terminal,observation,sent.operation_ref)
        finally:
            try:
                original=self.records.turn(receipt.turn_ref.turn_id)
                # Only a positively known terminal protocol response (or known
                # not-sent failure) releases this original session. Unknown/crash
                # stays unavailable; no owner-death/reconnect inference.
                self.records.leave_protocol_session(session_record,
                    resolved=original is not None and original.status in ('completed','failed'))
            finally:
                with self._fresh_lock:self._receiving.discard(instance_ref)

    def _finish_turn(self, record, receipt, state, observation, endpoint_operation_ref=None):
        from dataclasses import replace
        raw=_canonical_object(observation)
        updated=replace(receipt,state=state,revision=receipt.revision+1,
            endpoint_operation_ref=endpoint_operation_ref,observation_bytes=raw,
            observation_digest='sha256:'+hashlib.sha256(raw).hexdigest())
        payload={**record.payload,'turnReceipt':updated.projection()}
        if record.status=='reserved':
            self.records.complete(record.request_id,'turn',status=state,operation_ref=receipt.agent_operation_ref,payload=payload)
        else:self.records.advance_turn(record,status=state,payload=payload)
        return updated


__all__=['InteractionsRefused','TurnRef','FrozenPrompt','TurnReadQuery','TurnReceipt',
    'BindingProvenance','WriteBinding','GuardedSendObservation','WriteGuardPort','InteractionAuthorityPort',
    'freeze_prompt','turn_query','InteractionService']
