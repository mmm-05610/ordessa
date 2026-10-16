"""Official ACP Connection on the original managed environment byte channel.

This synchronous facade adapts existing Unit/lease consumers; JSON-RPC IDs,
pending requests, dispatch and replies belong to the official SDK. It never
spawns. SDK close detaches; only the original Unit stop closes its process.
"""
import asyncio
from collections import defaultdict, deque
from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import ContextVar
import json
import os
import threading
from contextlib import contextmanager

from acp import schema
from acp.exceptions import RequestError
from ordessa_infrastructure.process.framing import FramingError, Message
from ordessa_execution_agents.harness.transport import ChannelClosed, LostReceipt, RequestTimeout, WriterLeaseRefused
from ordessa_execution_agents.harness.protocols.acp import AcpRemoteError
from ordessa_execution_agents.harness.protocols.acp.callbacks import reply_error, reply_result
from ordessa_execution_agents.harness.protocols.acp.connection import open_sdk_connection
from ordessa_execution_agents.harness.protocols.acp.interaction import invoke_bound_callback
from ordessa_execution_agents.harness.protocols.acp.sessions import validate_request, validate_response
from ordessa_execution_agents.harness.transport import EffectWriteGuard, EffectWriteRefused

_dispatch = ContextVar('unit_sdk_dispatch', default=None)


class _ManagedTransport:
    def __init__(self, client):
        self.client = client
        self.detached = False

    async def send(self, payload):
        callback_admission = self.client._claim_callback_response(payload)
        try:
            self.client._check_write_authority()
            active = _dispatch.get()
            if active is not None and payload.get('method') == active['method'] and 'id' in payload:
                active['id'] = payload['id']
                self.client._outgoing[payload['id']] = active
                guard = active['guard']
            else:
                guard = None
            if active is None or payload.get('method') != active['method'] or 'id' not in payload:
                await self.client._channel.send_raw_async(payload)
            else:
                frame = (json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')
                # Every original SDK request has a receipt obligation, including
                # prompt/initialize without a configuration effect guard.
                def before_native_write():
                    self.client._check_write_authority()
                    if guard is not None:
                        guard(payload)
                fields = {'before_write': before_native_write}
                if active['effect_write_guard'] is not None:
                    fields['effect_write_guard'] = active['effect_write_guard']
                await self.client._channel.send_frame_async(frame, **fields)
        finally:
            if callback_admission is not None:
                self.client._finish_admission()

    async def receive(self):
        while not self.detached:
            try:
                message = await self.client._channel.next_message_async(timeout=.05)
                return message.raw
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError):
                return None
        return None

    async def close(self):
        self.detached = True


class SdkAcpClient:
    def __init__(self, channel, *, name='unit-acp', connect=True, require_effect_write_guard=False,
                 effect_write_owner=None):
        if type(require_effect_write_guard) is not bool:
            raise EffectWriteRefused('explicit operation guard selection required')
        if require_effect_write_guard and effect_write_owner is None:
            raise EffectWriteRefused('original recorded prompt owner required')
        self._require_effect_write_guard = require_effect_write_guard
        self._write_authority = None
        self._effect_write_owner = effect_write_owner
        self._channel = channel  # same LeaseBoundChannel, resolved by original lease port
        self._session_id = None
        self._last_response = None
        self._events = deque()
        self._reverse = defaultdict(deque)
        self._outgoing = {}
        self._active_callback = None
        self._active_observation = None
        self._observation_failure = None
        self._round_trip_lock = threading.RLock()
        self._event_condition = threading.Condition()
        self._operation_lock = threading.RLock()
        self._native_admission_open = True
        self._active_native_operations = 0
        self._callback_response_admissions = defaultdict(deque)
        if type(connect) is not bool:
            raise TypeError('explicit SDK connection mode required')
        self._loop = asyncio.new_event_loop()
        self._wakeup_lock = threading.Lock()
        self._wakeup_read_fd = None
        self._wakeup_write_fd = None
        self._wakeup_closed = False
        try:
            if not all(hasattr(os, name) for name in ('pipe', 'set_blocking', 'set_inheritable')):
                raise RuntimeError('SDK loop pipe wake is unavailable on this platform')
            self._wakeup_read_fd, self._wakeup_write_fd = os.pipe()
            os.set_blocking(self._wakeup_read_fd, False)
            os.set_blocking(self._wakeup_write_fd, False)
            os.set_inheritable(self._wakeup_read_fd, False)
            os.set_inheritable(self._wakeup_write_fd, False)
            self._loop.add_reader(self._wakeup_read_fd, self._drain_wakeup_pipe)
            self._loop_call_soon_threadsafe = self._loop.call_soon_threadsafe
            # Keep asyncio's original callback queue and Future semantics. The
            # pipe is only an additional process-local selector wake source.
            self._loop.call_soon_threadsafe = self._call_soon_threadsafe
            self._thread = threading.Thread(target=self._run, name='unit-official-acp', daemon=True)
        except BaseException:
            try:
                self._close_wakeup_pipe()
            finally:
                self._loop.close()
            raise
        if connect:
            try:
                self.open_connection()
            except BaseException:
                # A directly constructed client has no retained factory owner.
                self.detach()
                raise

    def open_connection(self):
        """Open after the original factory retains this exact client/channel.

        A failed open keeps this retained client's original IO loop available
        for authorized stop. Process byte IO cannot transfer to another loop.
        Only the Unit's separately authorized stop/release may dispose it.
        """
        if self._thread.ident is not None or self._loop.is_closed():
            raise RuntimeError('Original SDK connection already attempted; no reopen')
        self._thread.start()
        opening = self._submit(self._open())
        try:
            opening.result(timeout=5)
        except BaseException:
            opening.cancel()
            raise

    def bind_write_authority(self, check):
        """Retain the selected connection's real permission; never replace it."""
        if not callable(check) or self._write_authority is not None and self._write_authority is not check:
            raise WriterLeaseRefused('Original current Unit write authority required')
        self._write_authority = check

    @contextmanager
    def admitted_operation(self):
        """Retain one native request/callback span against owner quiescence."""
        with self._operation_lock:
            if not self._native_admission_open:
                raise WriterLeaseRefused('Original ACP native admission is quiesced')
            self._active_native_operations += 1
        try:
            yield
        finally:
            with self._operation_lock:
                self._active_native_operations -= 1
                if self._active_native_operations < 0:
                    self._active_native_operations = 0
                    raise RuntimeError('SDK native operation count underflow')

    def _retain_callback_response(self, request_id):
        """Keep an incoming callback admitted until its SDK reply write ends."""
        key = self._callback_response_key(request_id)
        if key is None:
            raise WriterLeaseRefused('Original ACP callback response identity is unavailable')
        with self._operation_lock:
            if not self._native_admission_open or self._active_native_operations <= 0:
                raise WriterLeaseRefused('Original ACP callback admission is unavailable')
            self._active_native_operations += 1
            self._callback_response_admissions[key].append(object())

    def _claim_callback_response(self, payload):
        """Take the exact original callback admission for one SDK response."""
        if not isinstance(payload, dict) or 'method' in payload or 'id' not in payload:
            return None
        key = self._callback_response_key(payload['id'])
        if key is None:
            return None
        with self._operation_lock:
            pending = self._callback_response_admissions.get(key)
            if not pending:
                return None
            token = pending.popleft()
            if not pending:
                self._callback_response_admissions.pop(key, None)
            return token

    @staticmethod
    def _callback_response_key(request_id):
        # Preserve the JSON-RPC ID's exact JSON type. This also lets malformed
        # but parseable IDs reach an error response without leaking admission.
        try:
            encoded = json.dumps(request_id, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False, separators=(',', ':'))
        except (TypeError, ValueError, OverflowError, RecursionError):
            return None
        return type(request_id), encoded

    def _finish_admission(self):
        with self._operation_lock:
            self._active_native_operations -= 1
            if self._active_native_operations < 0:
                self._active_native_operations = 0
                raise RuntimeError('SDK native operation count underflow')

    def _release_orphaned_callback_responses(self):
        """Release only replies whose SDK request tasks finished during close."""
        with self._operation_lock:
            count = sum(len(items) for items in self._callback_response_admissions.values())
            self._callback_response_admissions.clear()
            self._active_native_operations -= count
            if self._active_native_operations < 0:
                self._active_native_operations = 0
                raise RuntimeError('SDK native operation count underflow')

    def try_quiesce(self) -> bool:
        """Close new native admission only when this owner is already idle.

        This is intentionally nonblocking. It neither waits for outstanding
        work nor asserts that the remote peer has no late bytes or callbacks.
        """
        if threading.current_thread() is self._thread:
            return False
        with self._operation_lock:
            if self._active_native_operations:
                return False
            self._native_admission_open = False
            return True

    def _check_write_authority(self):
        if self._write_authority is not None:
            self._write_authority()

    @property
    def has_io_loop(self):
        return self._thread.is_alive()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.run_until_complete(self._loop.shutdown_default_executor())
            finally:
                try:
                    self._close_wakeup_pipe()
                finally:
                    self._loop.close()

    def _call_soon_threadsafe(self, callback, *args, context=None):
        """Use asyncio's queue plus an owned pipe to wake this private loop."""
        with self._wakeup_lock:
            if self._wakeup_closed or self._wakeup_write_fd is None:
                raise RuntimeError('SDK loop wake pipe is closed')
            handle = self._loop_call_soon_threadsafe(callback, *args, context=context)
            try:
                written = os.write(self._wakeup_write_fd, b'\0')
            except BlockingIOError:
                # A full pipe is already readable, so a wake is pending.
                return handle
            except OSError as exc:
                handle.cancel()
                raise RuntimeError('SDK loop wake pipe write failed') from exc
            if written != 1:
                handle.cancel()
                raise RuntimeError('SDK loop wake pipe write was incomplete')
            return handle

    def _drain_wakeup_pipe(self):
        read_fd = self._wakeup_read_fd
        if read_fd is None or self._wakeup_closed:
            raise RuntimeError('SDK loop wake pipe reader is closed')
        while True:
            try:
                if not os.read(read_fd, 4096):
                    raise RuntimeError('SDK loop wake pipe reached EOF')
            except InterruptedError:
                continue
            except BlockingIOError:
                return
            except OSError as exc:
                raise RuntimeError('SDK loop wake pipe read failed') from exc

    def _close_wakeup_pipe(self):
        with self._wakeup_lock:
            if self._wakeup_closed:
                return
            self._wakeup_closed = True
            read_fd, write_fd = self._wakeup_read_fd, self._wakeup_write_fd
            self._wakeup_read_fd = None
            self._wakeup_write_fd = None
            remove_error = None
            if read_fd is not None and not self._loop.is_closed():
                try:
                    self._loop.remove_reader(read_fd)
                except BaseException as exc:
                    remove_error = exc
            close_error = None
            for fd in (read_fd, write_fd):
                if fd is None:
                    continue
                try:
                    os.close(fd)
                except OSError as exc:
                    if close_error is None:
                        close_error = exc
            if remove_error is not None:
                raise RuntimeError('SDK loop wake pipe reader cleanup failed') from remove_error
            if close_error is not None:
                raise RuntimeError('SDK loop wake pipe descriptor cleanup failed') from close_error

    def _submit(self, coroutine):
        try:
            return asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            close = getattr(coroutine, 'close', None)
            if callable(close):
                close()
            raise

    async def _open(self):
        self.transport = _ManagedTransport(self)
        self.sdk_connection = open_sdk_connection(self._handle, self.transport, self._observe)

    @staticmethod
    def _key(method, params):
        return method, json.dumps(params, sort_keys=True, ensure_ascii=False, allow_nan=False)

    def _observe(self, event):
        if event.direction.value != 'incoming':
            return
        raw = event.message
        if self._active_observation is not None:
            try:
                self._active_observation(raw)
            except Exception as error:
                # The SDK's observer contract isolates observer failures.
                # Retain ours and refuse a complete durable outcome below.
                self._observation_failure = error
        if 'method' in raw and 'id' in raw:
            self._reverse[self._key(raw['method'], raw.get('params'))].append(raw)
        elif 'method' not in raw and 'id' in raw and raw['id'] in self._outgoing:
            active = self._outgoing[raw['id']]
            active['receipt'] = raw
            self._channel.acknowledge_frame(raw['id'])
        else:
            with self._event_condition:
                self._events.append(Message(raw=raw))
                self._event_condition.notify_all()

    async def _handle(self, method, params, notification):
        if notification:
            return None
        try:
            with self.admitted_operation():
                raw = self._reverse[self._key(method, params)].popleft()
                # SDK dispatch lacks the request id; the observer retained its
                # original frame so the callback can reply exactly once.
                try:
                    result = invoke_bound_callback(raw, self._active_callback)
                except Exception:
                    # ACP catches handler errors and writes a JSON-RPC error
                    # response after this coroutine returns. Keep admission
                    # through that same response attempt.
                    self._retain_callback_response(raw['id'])
                    raise
                self._retain_callback_response(raw['id'])
                return result
        except WriterLeaseRefused as error:
            # A late reverse request after local quiescence is explicitly
            # refused before the Unit callback can perform an effect.
            raise RequestError(-32000, 'Original ACP native admission is quiesced') from error

    @staticmethod
    def _validate(method, params, result=None):
        if result is None:
            validate_request(method, params)
        else:
            validate_response(method, result)

    async def _request(self, method, params, timeout, callback, guard, observation=None, effect_write_guard=None):
        with self.admitted_operation():
            self._validate(method, params)
            active = {'method':method, 'guard':guard, 'id':None, 'receipt':None,
                      'effect_write_guard':effect_write_guard}
            self._active_callback = callback
            self._active_observation = observation
            self._observation_failure = None
            token = _dispatch.set(active)
            try:
                try:
                    result = await asyncio.wait_for(self.sdk_connection.send_request(method, params), timeout)
                except asyncio.TimeoutError as error:
                    self._fence_unknown_request(active)
                    raise RequestTimeout(method, active['id'], timeout) from error
                except RequestError as error:
                    raise AcpRemoteError(method, active['id'], error.to_error_obj()) from error
                except ConnectionError as error:
                    self._fence_unknown_request(active)
                    raise LostReceipt(method, active['id'], 'Official SDK connection lost after dispatch') from error
                self._last_response = active['receipt']
                if self._observation_failure is not None:
                    raise RuntimeError('Original durable ACP observation failed') from self._observation_failure
                self._validate(method, params, result)
                return result
            finally:
                if active['receipt'] is not None:
                    self._last_response = active['receipt']
                self._outgoing.pop(active['id'], None)
                self._active_callback = None
                self._active_observation = None
                _dispatch.reset(token)

    def _fence_unknown_request(self, active):
        if active['id'] is not None and active['receipt'] is None:
            try:
                self._channel.mark_input_unknown()
            except (WriterLeaseRefused, ChannelClosed):
                # The original lease is already cut; never replace or clear it.
                pass

    def command(self, method, *, timeout=10, on_request=None, before_write=None, on_observation=None,
                effect_write_guard=None, _effect_write_owner=None, **params):
        return self.request(method, params, timeout=timeout, on_request=on_request,
                            before_write=before_write, on_observation=on_observation,
                            effect_write_guard=effect_write_guard, _effect_write_owner=_effect_write_owner)

    def request(self, method, params, *, timeout=10, on_request=None, before_write=None,
                on_observation=None, effect_write_guard=None, _effect_write_owner=None):
        """Preserve native params, including keys also used by local controls."""
        if (effect_write_guard is not None and (type(effect_write_guard) is not EffectWriteGuard or method != 'session/prompt')
                or self._require_effect_write_guard and method == 'session/prompt'
                    and (effect_write_guard is None or _effect_write_owner is not self._effect_write_owner)):
            raise EffectWriteRefused('original operation prompt write guard required')
        with self.admitted_operation():
            with self._round_trip_lock:
                future = self._submit(self._request(method, params, timeout, on_request, before_write, on_observation, effect_write_guard))
                try:
                    return future.result(timeout=timeout+2)
                except FutureTimeout:
                    future.cancel()
                    raise RequestTimeout(method, None, timeout) from None

    def initialize(self, *, timeout=10, before_write=None, **capabilities):
        return self.command('initialize', timeout=timeout, before_write=before_write,
                            protocolVersion=1, clientCapabilities=capabilities)

    def new_session(self, *, timeout=10, **params):
        result = self.command('session/new', timeout=timeout, **params)
        self._session_id = result['sessionId']
        return result

    def load_session(self, *, timeout=10, **params):
        result = self.command('session/load', timeout=timeout, **params)
        self._session_id = params['sessionId']
        return result

    @property
    def session_id(self):
        return self._session_id

    @property
    def effect_write_thread(self):
        """Return this guarded client’s actual live SDK-loop Thread.

        Engineering’s access handoff binds to the real execution target rather
        than a copied thread id. The caller receives the Thread object through
        this explicit owner API; `_thread` remains private. This is a read-only
        target lookup, not permission or a native-operation lease.
        """
        if not self._require_effect_write_guard or self._effect_write_owner is None:
            raise EffectWriteRefused('Fixed operation write guard is not configured')
        with self._operation_lock:
            if not self._native_admission_open or self._active_native_operations:
                raise EffectWriteRefused('Original SDK native admission is unavailable or busy')
            thread = self._thread
        transport = getattr(self, 'transport', None)
        if (thread is threading.current_thread() or thread.ident is None or not thread.is_alive()
                or self._loop.is_closed() or not self._loop.is_running()
                or transport is None or transport.detached or self._wakeup_closed):
            raise EffectWriteRefused('Original SDK execution target is not live')
        return thread

    def prompt(self, *, timeout=60, on_request=None, **params):
        return self.command('session/prompt', timeout=timeout, on_request=on_request, **params)

    def cancel(self, *, timeout=10, **params):
        schema.CancelNotification.model_validate(params)
        with self.admitted_operation():
            async def admitted_notification():
                with self.admitted_operation():
                    return await self.sdk_connection.send_notification('session/cancel', params)
            self._submit(admitted_notification()).result(timeout=timeout)

    def reply_request(self, request_id, result):
        reply_result(request_id, result)

    def reply_request_error(self, request_id, *, code, message, data=None):
        reply_error(request_id, code=code, message=message, data=data)

    def events(self):
        with self._event_condition:
            return tuple(self._events)

    def next_event(self, *, timeout=10):
        with self.admitted_operation():
            with self._event_condition:
                if not self._events:
                    self._event_condition.wait_for(lambda:bool(self._events), timeout=timeout)
                if not self._events:
                    raise RequestTimeout('event', None, timeout)
                return self._events.popleft()

    def run_process_operation(self, coroutine, *, timeout):
        return self._submit(coroutine).result(timeout=timeout)

    def detach(self):
        if self._thread.is_alive():
            async def detach_io():
                connection = getattr(self, 'sdk_connection', None)
                if connection is not None:
                    await connection.close()
                # The official SDK has now shut down its request tasks. Any
                # callback admission not consumed by a response send belongs
                # to a cancelled/aborted task and can be released safely.
                self._release_orphaned_callback_responses()
                transport = getattr(self, 'transport', None)
                if transport is not None:
                    await transport.close()
                # These tasks belong only to this client's private loop. They
                # never authorize process cancellation or release a shared Use.
                pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            try:
                self._submit(detach_io()).result(timeout=5)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError('Official SDK loop failed to detach')
        elif self._thread.ident is None and not self._loop.is_closed():
            try:
                self._close_wakeup_pipe()
            finally:
                self._loop.close()

    def close(self):
        self.detach()
        return self._channel.close()
