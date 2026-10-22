"""One live receiver per instance and the async ``agents.native.*`` surface.

A runtime owns the *single* reader of its bound endpoint's ``communicate.receive``
and the single writer lock for native frames. The public operations only claim,
enqueue, read the journal or answer an observed reverse request; the runtime
performs the physical guarded write and the frame observation. All durable facts
live in the original ``Records`` owner (see ``native_envelope`` for the closed
values and ``manager.Records`` for the additive tables).

No dialect is interpreted here: the bound provider codec classifies frames and
encodes the caller's protocol-shaped message. No authority is issued here: the
original interaction authority is checked at submit and again inside the
physical write guard.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .endpoint import BoundEndpoint
from .instances import AgentInstanceRef
from .interactions import (InteractionsRefused, _canonical, _check, _digest_of,
                           GuardedSendObservation)
from .native_envelope import (KINDS, MAX_EVENT_BYTES, OperationRef, PendingRequestRef,
                              event_projection, format_cursor, input_digest,
                              message_digest, validate_cursor, validate_page_limit,
                              validate_request_id)
from .manager import ManagerRefused

IDLE_READ_SECONDS = 1.0
DISPATCH_SECONDS = 30.0
MAX_FRAME_BUFFER = 4 * 1024 * 1024
MAX_PROMPT_BYTES = 1048576


class NativeRuntimeRefused(InteractionsRefused):
    """Alias kept for callers that want the native vocabulary explicitly."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def native_dispatch_request_id(endpoint_ref, frame_digest):
    """Endpoint-child request id for one native dispatch frame (ordinal 0)."""
    return _digest_of({'schemaVersion': 'agent-native-dispatch-request/1',
                       'endpointRef': endpoint_ref.projection(),
                       'frameDigest': frame_digest, 'frameOrdinal': 0})


@dataclass(frozen=True)
class NativeDispatchBinding:
    """The closed identity of one physical native frame write."""

    instance_ref: AgentInstanceRef
    endpoint_ref: object
    kind: str
    request_key: str
    protocol_id: str
    session_id: str
    input_digest: str
    frame_digest: str
    endpoint_request_id: str
    wire_id: str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'instance')
        if self.kind not in ('request', 'notify', 'reply'):
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'binding kind')
        from .interactions import _digest, _text
        for name, value in (('request key', self.request_key),
                            ('input digest', self.input_digest),
                            ('frame digest', self.frame_digest),
                            ('endpoint request', self.endpoint_request_id)):
            _digest(value, name)
        _text(self.protocol_id, 'protocol id')
        _text(self.session_id, 'session id') if self.session_id else None
        _text(self.wire_id, 'wire id')
        if not callable(getattr(self.endpoint_ref, 'projection', None)):
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'endpoint ref')

    def projection(self):
        return {'schemaVersion': 'agent-native-dispatch/1',
                'instanceRef': self.instance_ref.projection(),
                'endpointRef': self.endpoint_ref.projection(),
                'kind': self.kind, 'requestKey': self.request_key,
                'protocolId': self.protocol_id, 'sessionId': self.session_id,
                'inputDigest': self.input_digest, 'frameDigest': self.frame_digest,
                'endpointRequestId': self.endpoint_request_id, 'wireId': self.wire_id}


def _wire_id(request_key):
    return 'native/' + request_key.split(':', 1)[1]


def _operation_ref(instance_ref, request_key):
    return OperationRef(instance_ref, request_key)


class _GuardPort:
    """Adapt the runtime's synchronous cut closure to the endpoint's port shape."""

    def __init__(self, cut):
        self._cut = cut

    def guard_write(self, binding, invocation):
        return self._cut(binding, invocation)


@dataclass
class _Inflight:
    key: str
    operation: str
    kind: str
    wire_id: str
    binding: NativeDispatchBinding
    write_guard: object
    deadline: float
    instance_ref: AgentInstanceRef
    session_id: str
    protocol_id: str
    input_digest: str
    control_epoch: int
    invocation: object
    request_method: str | None = None
    request_message: dict | None = None
    pending_response: dict | None = None
    sent_at: str | None = None


class InstanceRuntime:
    """The single reader/writer of one live bound endpoint."""

    def __init__(self, registry, *, instance_ref, endpoint, session_id, protocol_id,
                 codec, invocation, generation):
        self._registry = registry
        self._service = registry.service
        self._records = self._service.records
        self.instance_ref = instance_ref
        self.endpoint = endpoint
        self.session_id = session_id
        self.protocol_id = protocol_id
        self.codec = codec
        self.invocation = invocation
        self.generation = generation
        self._loop = asyncio.get_running_loop()
        self._read_task = None
        self._stop = asyncio.Event()
        self._closed = False
        self._buffer = b''
        self._inflight = {}
        self._tasks = set()
        self._write_lock = asyncio.Lock()
        self._turn = None  # (turn_ref, record, delivery) for the one active prompt turn

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if self._read_task is None:
            self._read_task = self._loop.create_task(self._read_loop())

    def alive(self):
        return self._read_task is not None and not self._read_task.done()

    async def close(self):
        self._closed = True
        self._stop.set()
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    # -- submission (called by the registry before any write) --------------

    def register(self, inflight):
        self._inflight[inflight.wire_id] = inflight

    def enqueue(self, inflight, frame):
        self.register(inflight)
        task = self._loop.create_task(self._dispatch(inflight, frame))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- physical dispatch -------------------------------------------------

    async def _dispatch(self, inflight, frame):
        runtime = self
        service = self._service
        try:
            async with self._write_lock:
                if self._closed or self._stop.is_set():
                    self._finish(inflight, 'unknown', error={'code': 'CONNECTION_CLOSED'})
                    return
                if inflight.deadline <= self._loop.time():
                    self._finish(inflight, 'failed', error={'code': 'DISPATCH_DEADLINE_ELAPSED'})
                    return

                @contextmanager
                def guard_write(binding, actual_invocation):
                    if (binding is not inflight.binding
                            or actual_invocation is not inflight.invocation):
                        raise InteractionsRefused('NATIVE_WRITE_BINDING_MISMATCH')
                    _check(service.authority, 'check_native_dispatch',
                           actual_invocation, binding)
                    guarded = getattr(service.authority, 'guard_native_dispatch', None)
                    if not callable(guarded):
                        raise InteractionsRefused('NATIVE_AUTHORITY_GUARD_UNAVAILABLE')
                    with guarded(actual_invocation, binding):
                        with inflight.write_guard.guard_write(binding, actual_invocation):
                            with service.records.guard_writer_epoch(
                                    inflight.instance_ref, service._scope(actual_invocation),
                                    inflight.control_epoch):
                                yield

                try:
                    sent = await self.endpoint.communicate.send_guarded(
                        frame, inflight.binding.endpoint_request_id, inflight.deadline,
                        inflight.invocation, binding=inflight.binding,
                        write_guard=_GuardPort(guard_write))
                except BaseException as error:
                    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                        self._finish(inflight, 'unknown', error={'code': 'DISPATCH_INTERRUPTED'})
                        raise
                    self._finish(inflight, 'refused' if isinstance(
                        error, InteractionsRefused) else 'unknown',
                                 error={'code': getattr(error, 'code', None)
                                        or 'DISPATCH_UNCONFIRMED',
                                        'detail': str(error)[:200]})
                    return
                if type(sent) is not GuardedSendObservation:
                    self._finish(inflight, 'unknown', error={'code': 'DISPATCH_OBSERVATION_INVALID'})
                    return
                if sent.status == 'not_sent':
                    self._finish(inflight, 'refused', error={'code': 'WRITE_NOT_SENT'})
                    return
                inflight.sent_at = _now()
                if inflight.kind == 'notify':
                    self._finish(inflight, 'sent')
        finally:
            self._maybe_stop()

    def _finish(self, inflight, state, *, response=None, error=None, delivery=None):
        self._inflight.pop(inflight.wire_id, None)
        record = self._records.operation(inflight.key, inflight.operation)
        if record is None:
            return
        payload = dict(record.payload)
        payload['state'] = state
        payload['updatedAt'] = _now()
        if inflight.sent_at is not None:
            payload['delivery'] = {
                'status': 'possibly_sent' if state in ('accepted', 'unknown') else 'confirmed',
                'sentAt': inflight.sent_at}
        if response is not None:
            payload['response'] = response
        if error is not None:
            payload['error'] = error
        try:
            if record.status in ('reserved', 'accepted'):
                self._records.advance_native_v2(record, status=state, payload=payload)
        except ManagerRefused:
            pass

    async def deliver(self, binding, frame, deadline, write_guard, invocation):
        """One guarded reply write from a live runtime; no journal read."""
        service = self._service

        @contextmanager
        def guard_write(actual, actual_invocation):
            if actual is not binding or actual_invocation is not invocation:
                raise InteractionsRefused('NATIVE_WRITE_BINDING_MISMATCH')
            _check(service.authority, 'check_native_dispatch', actual_invocation, actual)
            guarded = getattr(service.authority, 'guard_native_dispatch', None)
            if not callable(guarded):
                raise InteractionsRefused('NATIVE_AUTHORITY_GUARD_UNAVAILABLE')
            with guarded(actual_invocation, actual):
                with write_guard.guard_write(actual, actual_invocation):
                    with service.records.guard_writer_epoch(
                            self.instance_ref, service._scope(actual_invocation), self.generation):
                        yield

        async with self._write_lock:
            if self._closed or self._stop.is_set():
                return 'unknown'
            try:
                sent = await self.endpoint.communicate.send_guarded(
                    frame, binding.endpoint_request_id, deadline, invocation,
                    binding=binding, write_guard=_GuardPort(guard_write))
            except BaseException as error:
                if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    raise
                return 'unknown'
        if type(sent) is not GuardedSendObservation:
            return 'unknown'
        if sent.status == 'not_sent':
            return 'refused'
        return 'sent'

    # -- read loop ---------------------------------------------------------

    def _maybe_stop(self):
        if not self._inflight and self._turn is None:
            self._stop.set()

    async def _read_loop(self):
        try:
            while not self._stop.is_set():
                page = await self._read_page()
                if page is None:
                    await asyncio.sleep(0.02)
                    continue
                for event in page.events:
                    self._buffer += event.payload_bytes
                if len(self._buffer) > MAX_FRAME_BUFFER:
                    self._fail_all('FRAME_BUFFER_LIMIT', state='failed')
                    return
                if not self._drain():
                    return
                if not page.has_more and not page.events:
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail_all('RECEIVE_UNAVAILABLE')
        finally:
            self._fail_all('RUNTIME_CLOSED')

    async def _read_page(self):
        deadline = self._loop.time() + IDLE_READ_SECONDS
        try:
            return await self.endpoint.communicate.receive(None, deadline, self.invocation)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if _is_idle(error):
                return None
            raise

    def _drain(self):
        """Parse complete LF frames; returns False when the runtime must stop."""
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            if not line:
                continue
            if len(line) > MAX_EVENT_BYTES:
                # One frame larger than the explicit event bound: record the
                # fact (digest + size) and fail the awaiting operation. Never
                # keep a tail and call it a complete response.
                self._record_event('oversize', None,
                                   {'bytes': len(line), 'digest': _sha256(line)},
                                   operation=None)
                self._fail_all('OUTPUT_LIMIT_EXCEEDED', state='failed')
                return False
            try:
                value = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeError):
                self._record_event('malformed', None, {'bytes': len(line),
                                  'digest': _sha256(line)}, operation=None)
                self._fail_all('PROTOCOL_FRAME_INVALID')
                return False
            if type(value) is not dict:
                self._record_event('malformed', None, {'bytes': len(line),
                                  'digest': _sha256(line)}, operation=None)
                self._fail_all('PROTOCOL_FRAME_INVALID')
                return False
            if not self._handle_frame(value):
                return False
        return True

    def _record_event(self, kind, operation_ref, payload, *, operation):
        try:
            self._records.append_event(
                self.instance_ref, kind=kind,
                operation_ref=None if operation_ref is None else _canonical(operation_ref.projection()),
                payload=payload, connection_generation=self.generation,
                observed_at=_now())
        except ManagerRefused:
            pass

    def _handle_frame(self, value):
        raw = _canonical(value).encode('utf-8')
        if len(raw) > MAX_EVENT_BYTES:
            self._record_event('oversize', None,
                               {'bytes': len(raw), 'digest': _sha256(raw)}, operation=None)
            self._fail_all('OUTPUT_LIMIT_EXCEEDED', state='failed')
            return False
        try:
            kind, correlation, method = self.codec.classify(value)
        except Exception:
            # A frame this codec cannot classify is journaled as malformed; it is
            # never silently treated as a notification or as success.
            self._record_event('malformed', None,
                               {'reason': 'codec_classification_failed'}, operation=None)
            return True
        if kind == 'response':
            inflight = self._inflight.get(correlation) if correlation else None
            operation_ref = None if inflight is None else _operation_ref(
                inflight.instance_ref, inflight.key)
            self._record_event('response', operation_ref, value, operation=inflight)
            if inflight is not None:
                terminal = self._response_state(inflight, value)
                if terminal == 'pending':
                    # The protocol only acknowledged acceptance; keep the
                    # operation open and let the provider's terminal
                    # notification finish it.
                    self._record_pending_response(inflight, value)
                elif terminal == 'completed':
                    self._finish(inflight, 'completed', response=value)
                elif terminal == 'cancelled':
                    self._finish(inflight, 'cancelled', response=value)
                else:
                    self._finish(inflight, 'failed',
                                 response=value, error={'code': 'PROTOCOL_TERMINAL_FAILURE'})
            return True
        if kind == 'reverse_request':
            self._record_event('reverse_request', None, value, operation=None)
            self._observe_reverse(correlation, method, value)
            return True
        # notification / event: journal first, then finish any operation whose
        # provider-declared terminal this notification is, then the active turn.
        operation_ref = None
        self._record_event('notification', operation_ref, value, operation=None)
        self._observe_operation_notification(value, method)
        self._observe_turn(value)
        return True

    def _terminal(self, value):
        try:
            terminal = self.codec.terminal_state(value)
        except Exception:
            return 'failed'
        return terminal

    def _response_state(self, inflight, value):
        handler = getattr(self.codec, 'response_state', None)
        if callable(handler):
            try:
                state = handler(inflight.request_method, value)
                if state in ('pending', 'completed', 'failed', 'cancelled'):
                    return state
            except Exception:
                pass
        return self._terminal(value)

    def _record_pending_response(self, inflight, value):
        inflight.pending_response = value
        record = self._records.operation(inflight.key, inflight.operation)
        if record is None or record.status != 'accepted':
            return
        payload = dict(record.payload)
        payload['response'] = value
        payload['updatedAt'] = _now()
        payload['acceptedObservation'] = True
        try:
            self._records.advance_native_v2(record, status='accepted', payload=payload)
        except ManagerRefused:
            pass

    def _observe_operation_notification(self, value, method):
        handler = getattr(self.codec, 'notification_state', None)
        if not callable(handler):
            return
        matches = []
        for inflight in list(self._inflight.values()):
            # Only a request acknowledged as pending can have a later terminal
            # notification. Unanswered control/read requests are unrelated.
            if inflight.pending_response is None:
                continue
            try:
                state = handler(value, session_id=inflight.session_id,
                                request=inflight.request_message,
                                response=inflight.pending_response)
            except Exception:
                continue
            if state in ('completed', 'failed', 'cancelled'):
                matches.append((inflight, state))
        if len(matches) == 1:
            inflight, state = matches[0]
            self._finish(inflight, state, response=value)
        elif matches:
            # Some native dialects emit an uncorrelated session-level terminal.
            # Never choose an arbitrary operation when multiple turns match.
            for inflight, _ in matches:
                self._finish(inflight, 'unknown',
                             error={'code': 'NATIVE_TERMINAL_AMBIGUOUS'})

    def _observe_reverse(self, native_request_id, method, value):
        if not native_request_id:
            return
        try:
            self._records.record_pending(
                self.instance_ref, connection_generation=self.generation,
                native_request_id=native_request_id, protocol_id=self.protocol_id,
                method=method, payload=value, operation_ref=None, observed_at=_now())
        except ManagerRefused:
            pass

    def _observe_turn(self, value):
        if self._turn is None:
            return
        handler = self._service._native_prompts.get(self.protocol_id)
        if handler is None:
            return
        try:
            accepted = handler.accept(value, session_id=self.session_id)
        except Exception:
            accepted = False
        if not accepted:
            return
        try:
            terminal, observation = handler.outcome(value, session_id=self.session_id)
        except Exception:
            terminal, observation = 'unknown', {'reason': 'prompt_outcome_invalid'}
        turn_ref, record, delivery = self._turn
        self._turn = None
        try:
            current = self._records.turn(turn_ref.turn_id)
            if current is not None and current.status == 'possibly-written':
                self._records.advance_turn(current, status=terminal,
                                           payload={**dict(current.payload),
                                                    'turnReceipt': _advance_receipt(
                                                        current, terminal, observation,
                                                        delivery)})
        except ManagerRefused:
            pass
        self._maybe_stop()

    def _fail_all(self, code, *, state='unknown'):
        for inflight in list(self._inflight.values()):
            self._finish(inflight, state, error={'code': code})
        self._turn = None


def _advance_receipt(record, terminal, observation, delivery):
    """Rewrite only the receipt revision fields; identity is unchanged."""
    from dataclasses import replace
    from .interactions import TurnReceipt
    try:
        receipt = TurnReceipt.decode(record.payload['turnReceipt'])
    except Exception:
        return record.payload.get('turnReceipt')
    raw = _canonical({**delivery, **observation}).encode('utf-8')
    updated = replace(receipt, state=terminal, revision=receipt.revision + 1,
                      observation_bytes=raw,
                      observation_digest='sha256:' + _sha256(raw)[len('sha256:'):])
    return updated.projection()


def _sha256(raw):
    import hashlib
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _is_idle(error):
    if isinstance(error, TimeoutError):
        return True
    return type(error).__name__ in ('ProcessWaitTimeout', 'TimeoutError')


class NativeRuntimeRegistry:
    """Owns the live runtimes and serves the six public native operations."""

    def __init__(self, service):
        self.service = service
        self._runtimes = {}
        self._lock = None

    # -- helpers -----------------------------------------------------------

    def _set_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()

    def _scope(self, invocation):
        return self.service._scope(invocation)

    def codec(self, protocol_id):
        codecs = getattr(self.service, '_native_codecs', {})
        codec = codecs.get(protocol_id)
        if codec is None:
            raise InteractionsRefused('PROTOCOL_UNSUPPORTED', protocol_id)
        return codec

    def live(self, instance_ref):
        return self._runtimes.get(_runtime_key(instance_ref))

    def has_live(self, instance_ref):
        runtime = self.live(instance_ref)
        return runtime is not None and runtime.alive()

    # -- describe ----------------------------------------------------------

    def describe(self, instance_ref, *, invocation):
        if type(instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'instance')
        _check(self.service.authority, 'check_native_describe', invocation, instance_ref)
        scope = self._scope(invocation)
        self.service._instance(instance_ref, scope)
        protocol_id = self.service._protocol(instance_ref)
        try:
            codec = self.codec(protocol_id)
        except InteractionsRefused:
            return _describe(instance_ref, protocol_id=protocol_id, version=0,
                             session_id=None, capabilities=(), availability='unavailable',
                             reason='provider codec unavailable')
        session_id = self.service._instance(instance_ref, scope)[1]
        return _describe(instance_ref, protocol_id=protocol_id,
                         version=getattr(codec, 'protocol_version', 1),
                         session_id=session_id,
                         capabilities=getattr(codec, 'capabilities', ()),
                         availability='available')

    # -- submit ------------------------------------------------------------

    async def submit(self, instance_ref, *, kind, request_id, message, invocation,
                     write_guard, deadline):
        if kind not in KINDS:
            raise InteractionsRefused('NATIVE_VALUE_INVALID', 'kind')
        validate_request_id(request_id)
        message_digest(message)
        scope = self._scope(invocation)
        provenance, session_id = self.service._instance(instance_ref, scope)
        protocol_id = self.service._protocol(instance_ref)
        codec = self.codec(protocol_id)
        capabilities = set(getattr(codec, 'capabilities', ()))
        if kind == 'notify' and 'notify' not in capabilities:
            raise InteractionsRefused('NATIVE_PROTOCOL_UNSUPPORTED', 'notify')
        if kind == 'request' and 'request' not in capabilities:
            raise InteractionsRefused('NATIVE_PROTOCOL_UNSUPPORTED', 'request')
        digest = input_digest(kind=kind, protocol_id=protocol_id,
                              session_id=session_id, message=message)
        key = self.service._key(instance_ref, request_id, scope)
        operation = 'native-request' if kind == 'request' else 'native-notify'
        wire_id = _wire_id(key)
        target = _canonical({'instanceRef': instance_ref.projection(),
                             'protocolId': protocol_id, 'sessionId': session_id,
                             'kind': kind})
        try:
            if kind == 'request':
                frame = codec.encode_request(wire_id, message)
            else:
                frame = codec.encode_notify(message)
        except Exception:
            raise InteractionsRefused('NATIVE_PROTOCOL_UNSUPPORTED', 'message') from None
        frame_digest = 'sha256:' + _sha256(frame)[len('sha256:'):]
        endpoint_request_id = native_dispatch_request_id(provenance.endpoint_ref, frame_digest)
        binding = NativeDispatchBinding(instance_ref, provenance.endpoint_ref, kind, key,
                                        protocol_id, session_id, digest, frame_digest,
                                        endpoint_request_id, wire_id)
        _check(self.service.authority, 'check_native_dispatch', invocation, binding)
        payload = {'kind': kind, 'protocolId': protocol_id, 'sessionId': session_id,
                   'instanceRef': instance_ref.projection(),
                   'requestId': request_id, 'inputDigest': digest, 'wireId': wire_id,
                   'frameDigest': frame_digest,
                   'endpointRequestId': endpoint_request_id,
                   'state': 'accepted', 'acceptedAt': _now()}
        try:
            state, record = self.service.records.claim(
                key, operation, principal=scope, target=target,
                request_digest=digest, payload=payload)
        except ManagerRefused as error:
            raise InteractionsRefused(error.code or 'RECORDS_UNAVAILABLE') from None
        if state == 'existing':
            return _acceptance(instance_ref, record)
        try:
            control_epoch = self.service.records.writer_epoch(instance_ref, scope)
        except ManagerRefused as error:
            self._finish_record(record, 'refused', error={'code': error.code})
            raise InteractionsRefused(error.code) from None
        record = self.service.records.advance_native_v2(
            record, status='accepted',
            payload={**payload, 'updatedAt': _now(), 'controlEpoch': control_epoch})
        try:
            runtime = await self._ensure_runtime(instance_ref, provenance, session_id,
                                                 protocol_id, codec, invocation, scope)
        except InteractionsRefused as error:
            self._finish_record(record, 'failed',
                                error={'code': 'NATIVE_ENDPOINT_UNAVAILABLE'})
            raise InteractionsRefused('NATIVE_ENDPOINT_UNAVAILABLE', error.code) from None
        inflight = _Inflight(key=key, operation=operation, kind=kind, wire_id=wire_id,
                             binding=binding, write_guard=write_guard,
                             deadline=asyncio.get_running_loop().time() + DISPATCH_SECONDS,
                             instance_ref=instance_ref, session_id=session_id,
                             protocol_id=protocol_id, input_digest=digest,
                             control_epoch=control_epoch, invocation=invocation,
                             request_method=message.get('method') or message.get('type'),
                             request_message=json.loads(_canonical(message)))
        runtime.enqueue(inflight, frame)
        return _acceptance(instance_ref, record)

    def _finish_record(self, record, state, *, error=None):
        try:
            payload = {**dict(record.payload), 'state': state, 'updatedAt': _now()}
            if error is not None:
                payload['error'] = error
            self.service.records.advance_native_v2(record, status=state, payload=payload)
        except ManagerRefused:
            pass

    async def _ensure_runtime(self, instance_ref, provenance, session_id, protocol_id,
                              codec, invocation, scope):
        self._set_lock()
        async with self._lock:
            key = _runtime_key(instance_ref)
            current = self._runtimes.get(key)
            if current is not None and current.alive():
                return current
            endpoint = await self.service.endpoint_resolver.resolve(
                provenance.endpoint_ref, invocation)
            if (type(endpoint) is not BoundEndpoint
                    or endpoint.ref != provenance.endpoint_ref
                    or not callable(getattr(endpoint.communicate, 'receive', None))
                    or not callable(getattr(endpoint.communicate, 'send_guarded', None))):
                raise InteractionsRefused('NATIVE_ENDPOINT_UNAVAILABLE')
            try:
                generation = self.service.records.writer_epoch(instance_ref, scope)
            except ManagerRefused:
                raise InteractionsRefused('NATIVE_CONNECTION_GENERATION_UNAVAILABLE') from None
            self.service.records.expire_pending(instance_ref, updated_at=_now())
            runtime = InstanceRuntime(self, instance_ref=instance_ref, endpoint=endpoint,
                                      session_id=session_id, protocol_id=protocol_id,
                                      codec=codec, invocation=invocation,
                                      generation=generation)
            self._runtimes[key] = runtime
            runtime.start()
            return runtime

    # -- query -------------------------------------------------------------

    def query(self, operation_ref, *, invocation, expected_input_digest=None):
        ref = OperationRef.decode(operation_ref) if type(operation_ref) is dict else operation_ref
        if type(ref) is not OperationRef:
            raise InteractionsRefused('VALUE_INVALID', 'operation ref')
        if expected_input_digest is not None:
            from .interactions import _digest
            _digest(expected_input_digest, 'expected input digest')
        _check(self.service.authority, 'check_read_native_operation', invocation, ref,
               expected_input_digest)
        scope = self._scope(invocation)
        record = None
        for operation in ('native-request', 'native-notify'):
            record = self.service.records.operation(ref.request_key, operation)
            if record is not None:
                break
        if record is None:
            raise InteractionsRefused('NATIVE_OPERATION_UNKNOWN')
        if record.principal != scope:
            raise InteractionsRefused('READ_NOT_AUTHORIZED')
        if expected_input_digest is not None and record.request_digest != expected_input_digest:
            raise InteractionsRefused('OBSERVATION_MISMATCH')
        payload = dict(record.payload)
        state = record.status
        if state == 'reserved':
            state = 'unknown'
        value = {'schemaVersion': 'agent-native-observation/1',
                 'operationRef': ref.projection(),
                 'kind': payload.get('kind'), 'state': state,
                 'protocolId': payload.get('protocolId'),
                 'sessionId': payload.get('sessionId'),
                 'inputDigest': payload.get('inputDigest'),
                 'acceptedAt': payload.get('acceptedAt'),
                 'updatedAt': payload.get('updatedAt') or payload.get('acceptedAt')}
        for name in ('response', 'error', 'delivery'):
            if payload.get(name) is not None:
                value[name] = payload[name]
        return value

    # -- events ------------------------------------------------------------

    def events(self, instance_ref, *, cursor, limit, invocation):
        if type(instance_ref) is not AgentInstanceRef:
            raise InteractionsRefused('VALUE_INVALID', 'instance')
        _check(self.service.authority, 'check_read_native_events', invocation, instance_ref)
        scope = self._scope(invocation)
        self.service._instance(instance_ref, scope)
        after_seq = validate_cursor(cursor)
        page_limit = validate_page_limit(limit)
        rows = self.service.records.event_page(instance_ref, after_seq=after_seq,
                                               limit=page_limit)
        has_more = len(rows) > page_limit
        rows = rows[:page_limit]
        first_seq, last_seq, dropped_events, dropped_bytes = \
            self.service.records.journal_bounds(instance_ref)
        if cursor is not None and first_seq > 1 and after_seq < first_seq - 1:
            raise InteractionsRefused('EVENT_CURSOR_EXPIRED')
        events = []
        for (seq, kind, operation_ref_json, payload_text, payload_digest, payload_bytes,
             generation, observed_at) in rows:
            operation_ref = (None if operation_ref_json is None
                             else OperationRef.decode(json.loads(operation_ref_json)))
            try:
                payload = json.loads(payload_text)
            except ValueError:
                payload = {'corrupt': True, 'digest': payload_digest}
            events.append(event_projection(seq=seq, kind=kind, payload=payload,
                                           payload_digest=payload_digest,
                                           operation_ref=operation_ref,
                                           observed_at=observed_at))
        return {'schemaVersion': 'agent-native-event-page/1',
                'instanceRef': instance_ref.projection(),
                'events': events,
                'nextCursor': (format_cursor(rows[-1][0]) if rows
                               else (None if cursor is None else cursor)),
                'hasMore': has_more,
                'completeness': {'firstSeq': first_seq, 'lastSeq': last_seq,
                                 'droppedEvents': dropped_events,
                                 'droppedBytes': dropped_bytes}}

    # -- respond -----------------------------------------------------------

    async def respond(self, pending_ref, *, request_id, response, invocation,
                      write_guard, deadline):
        ref = PendingRequestRef.decode(pending_ref) if type(pending_ref) is dict else pending_ref
        if type(ref) is not PendingRequestRef:
            raise InteractionsRefused('VALUE_INVALID', 'pending request ref')
        validate_request_id(request_id)
        message_digest(response)
        _check(self.service.authority, 'check_native_respond', invocation, ref)
        scope = self._scope(invocation)
        pending = self.service.records.pending_request(ref.instance_ref, ref.native_request_id)
        if pending is None:
            raise InteractionsRefused('NATIVE_PENDING_UNKNOWN')
        if pending['connectionGeneration'] != ref.connection_generation:
            raise InteractionsRefused('NATIVE_PENDING_STALE')
        if pending['protocolId'] != ref.protocol_id:
            raise InteractionsRefused('NATIVE_PENDING_STALE')
        digest = _digest_of({'schemaVersion': 'agent-native-reply/1',
                             'pending': ref.projection(), 'response': response})
        key = self.service._key(ref.instance_ref, request_id, scope)
        operation = 'native-reply'
        target = _canonical({'pending': ref.projection()})
        payload = {'kind': 'reply', 'pendingRequestRef': ref.projection(),
                   'inputDigest': digest, 'state': 'accepted', 'acceptedAt': _now()}
        try:
            state, record = self.service.records.claim(
                key, operation, principal=scope, target=target,
                request_digest=digest, payload=payload)
        except ManagerRefused as error:
            raise InteractionsRefused(error.code or 'RECORDS_UNAVAILABLE') from None
        if state == 'existing':
            return _reply_acceptance(record)
        if pending['state'] == 'answered':
            self._finish_record(record, 'refused',
                                error={'code': 'NATIVE_PENDING_ALREADY_ANSWERED'})
            raise InteractionsRefused('NATIVE_PENDING_ALREADY_ANSWERED')
        if pending['state'] != 'pending':
            self._finish_record(record, 'refused',
                                error={'code': 'NATIVE_PENDING_CLOSED'})
            raise InteractionsRefused('NATIVE_PENDING_CLOSED')
        runtime = self.live(ref.instance_ref)
        if runtime is None or not runtime.alive():
            self._finish_record(record, 'refused',
                                error={'code': 'NATIVE_CONNECTION_LOST'})
            raise InteractionsRefused('NATIVE_CONNECTION_LOST')
        if runtime.generation != ref.connection_generation:
            self._finish_record(record, 'refused', error={'code': 'NATIVE_PENDING_STALE'})
            raise InteractionsRefused('NATIVE_PENDING_STALE')
        codec = self.codec(ref.protocol_id)
        if 'reverse_requests' not in set(getattr(codec, 'capabilities', ())):
            self._finish_record(record, 'refused',
                                error={'code': 'NATIVE_PROTOCOL_UNSUPPORTED'})
            raise InteractionsRefused('NATIVE_PROTOCOL_UNSUPPORTED', 'reverse requests')
        try:
            frame = codec.encode_reply(ref.native_request_id, response)
        except Exception:
            self._finish_record(record, 'refused', error={'code': 'NATIVE_REPLY_INVALID'})
            raise InteractionsRefused('NATIVE_REPLY_INVALID') from None
        frame_digest = 'sha256:' + _sha256(frame)[len('sha256:'):]
        provenance = self.service._instance(ref.instance_ref, scope)[0]
        endpoint_request_id = native_dispatch_request_id(provenance.endpoint_ref, frame_digest)
        binding = NativeDispatchBinding(ref.instance_ref, provenance.endpoint_ref, 'reply', key,
                                        ref.protocol_id, runtime.session_id,
                                        digest, frame_digest, endpoint_request_id,
                                        'reply/' + ref.native_request_id)
        _check(self.service.authority, 'check_native_dispatch', invocation, binding)
        record = self.service.records.advance_native_v2(
            record, status='accepted', payload={**payload, 'updatedAt': _now()})
        # Reserve the pending request before the first await. Another request id
        # must not answer it while this write is in flight or its outcome is lost.
        if not self.service.records.mark_pending(ref.instance_ref, ref.native_request_id,
                                                 state='claimed', updated_at=_now()):
            self._finish_record(record, 'refused', error={'code': 'NATIVE_PENDING_CLOSED'})
            raise InteractionsRefused('NATIVE_PENDING_CLOSED')
        try:
            delivered = await runtime.deliver(binding, frame, deadline, write_guard, invocation)
        except BaseException:
            self.service.records.mark_pending(ref.instance_ref, ref.native_request_id,
                                              state='unknown', updated_at=_now(),
                                              expected_state='claimed')
            self._finish_record(record, 'unknown', error={'code': 'DISPATCH_UNCONFIRMED'})
            raise
        if delivered == 'sent':
            self.service.records.mark_pending(ref.instance_ref, ref.native_request_id,
                                              state='answered', updated_at=_now(),
                                              expected_state='claimed')
            self._finish_record(record, 'sent')
        elif delivered == 'refused':
            self.service.records.mark_pending(ref.instance_ref, ref.native_request_id,
                                              state='pending', updated_at=_now(),
                                              expected_state='claimed')
            self._finish_record(record, 'refused', error={'code': 'WRITE_NOT_SENT'})
        else:
            self.service.records.mark_pending(ref.instance_ref, ref.native_request_id,
                                              state='unknown', updated_at=_now(),
                                              expected_state='claimed')
            self._finish_record(record, 'unknown', error={'code': 'DISPATCH_UNCONFIRMED'})
        return _reply_acceptance(self.service.records.operation(key, operation))

    # -- teardown ----------------------------------------------------------

    async def close_all(self):
        for runtime in list(self._runtimes.values()):
            await runtime.close()
        self._runtimes.clear()


def _runtime_key(instance_ref):
    return instance_ref.namespace + '/' + instance_ref.instance_id


def _describe(instance_ref, *, protocol_id, version, session_id, capabilities,
              availability, reason=None):
    from .native_envelope import describe_result
    return describe_result(instance_ref, protocol_id=protocol_id,
                           protocol_version=version, session_id=session_id,
                           capabilities=capabilities, availability=availability,
                           reason=reason)


def _acceptance(instance_ref, record):
    payload = dict(record.payload)
    state = record.status
    if state == 'reserved':
        state = 'unknown'
    return {'schemaVersion': 'agent-native-acceptance/1',
            'operationRef': OperationRef(instance_ref, record.request_id).projection(),
            'kind': payload.get('kind'), 'state': state,
            'inputDigest': payload.get('inputDigest'),
            'acceptedAt': payload.get('acceptedAt')}


def _reply_acceptance(record):
    payload = dict(record.payload)
    state = record.status
    if state == 'reserved':
        state = 'unknown'
    return {'schemaVersion': 'agent-native-reply/1',
            'pendingRequestRef': payload.get('pendingRequestRef'),
            'state': state, 'inputDigest': payload.get('inputDigest'),
            'acceptedAt': payload.get('acceptedAt')}
