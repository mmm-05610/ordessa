"""Focused owner-side SDK admission/quiescence tests; no process or network."""
import asyncio
import threading

import pytest
from acp.exceptions import RequestError
from ordessa_execution_agents.harness.transport import WriterLeaseRefused

from ordessa_units.sessions.sdk_client import SdkAcpClient, _ManagedTransport


class _UnusedChannel:
    def close(self):
        return None


def _client():
    return SdkAcpClient(_UnusedChannel(), connect=False)


def test_admitted_operation_blocks_quiesce_then_closes_new_admission():
    client = _client()
    try:
        with client.admitted_operation():
            assert client._active_native_operations == 1
            assert client.try_quiesce() is False
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
        assert client.try_quiesce() is True
        with pytest.raises(WriterLeaseRefused, match='quiesced'):
            with client.admitted_operation():
                pytest.fail('closed native admission was entered')
    finally:
        client.detach()


def test_quiesce_refuses_from_sdk_loop_thread():
    client = _client()
    completed = threading.Event()
    result = []

    async def inspect_from_owner_loop():
        result.append(client.try_quiesce())
        completed.set()

    try:
        client._thread.start()
        client.run_process_operation(inspect_from_owner_loop(), timeout=2)
        assert completed.wait(timeout=2)
        assert result == [False]
        assert client.try_quiesce() is True
    finally:
        client.detach()


def test_request_admission_spans_round_trip_lock_and_future_result():
    client = _client()
    started = threading.Event()
    thread_result = []
    release_request = None

    class PendingConnection:
        async def send_request(self, _method, _params):
            nonlocal release_request
            release_request = asyncio.Event()
            started.set()
            await release_request.wait()
            return {'ok': True}

        async def close(self):
            return None

    client.sdk_connection = PendingConnection()
    client._validate = lambda *_args, **_kwargs: None

    def request_thread():
        try:
            thread_result.append(client.request('unit/test', {}, timeout=20))
        except BaseException as error:
            thread_result.append(error)

    thread = threading.Thread(target=request_thread)
    round_trip_lock_held = False
    try:
        client._thread.start()
        client._round_trip_lock.acquire()
        round_trip_lock_held = True
        thread.start()
        deadline = threading.Event()
        for _ in range(200):
            if client._active_native_operations == 1:
                break
            deadline.wait(0.01)
        assert client._active_native_operations == 1
        assert client.try_quiesce() is False
        client._round_trip_lock.release()
        round_trip_lock_held = False
        assert started.wait(timeout=2)
        assert client._active_native_operations == 2  # sync request + async SDK request
        assert client.try_quiesce() is False
        # Let the original request finish; no retry or replacement request.
        client._loop.call_soon_threadsafe(release_request.set)
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert thread_result == [{'ok': True}]
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
    finally:
        if round_trip_lock_held:
            client._round_trip_lock.release()
        if thread.is_alive() and release_request is not None:
            client._loop.call_soon_threadsafe(release_request.set)
            thread.join(timeout=2)
        client.detach()


def test_async_request_remains_active_until_cancellation_finally_completes():
    client = _client()
    started = threading.Event()
    cancellation_started = threading.Event()
    finish_cancellation = None

    class CancellationDelayedConnection:
        async def send_request(self, _method, _params):
            nonlocal finish_cancellation
            finish_cancellation = asyncio.Event()
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_started.set()
                await finish_cancellation.wait()
                raise

        async def close(self):
            return None

    client.sdk_connection = CancellationDelayedConnection()
    client._validate = lambda *_args, **_kwargs: None
    try:
        client._thread.start()
        future = client._submit(client._request('unit/test', {}, 20, None, None))
        assert started.wait(timeout=2)
        assert client._active_native_operations == 1
        assert future.cancel()
        assert cancellation_started.wait(timeout=2)
        assert client._active_native_operations == 1
        assert client.try_quiesce() is False
        client._loop.call_soon_threadsafe(finish_cancellation.set)
        for _ in range(200):
            if client._active_native_operations == 0:
                break
            threading.Event().wait(0.01)
        assert future.done()
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
    finally:
        if finish_cancellation is not None:
            client._loop.call_soon_threadsafe(finish_cancellation.set)
        client.detach()


def test_cancel_notification_keeps_async_admission_after_sync_timeout():
    client = _client()
    notification_started = threading.Event()
    finish_notification = None
    call_result = []

    class PendingConnection:
        async def send_notification(self, _method, _params):
            nonlocal finish_notification
            finish_notification = asyncio.Event()
            notification_started.set()
            await finish_notification.wait()

        async def close(self):
            return None

    client.sdk_connection = PendingConnection()

    def cancel_thread():
        try:
            client.cancel(timeout=0.02, sessionId='session')
        except BaseException as error:
            call_result.append(error)

    thread = threading.Thread(target=cancel_thread)
    try:
        client._thread.start()
        thread.start()
        assert notification_started.wait(timeout=2)
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert call_result and isinstance(call_result[0], TimeoutError)
        # The synchronous caller timed out, but notification coroutine remains
        # admitted until its own finally completes.
        assert client._active_native_operations == 1
        assert client.try_quiesce() is False
        client._loop.call_soon_threadsafe(finish_notification.set)
        for _ in range(100):
            if client._active_native_operations == 0:
                break
            threading.Event().wait(0.01)
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
    finally:
        if finish_notification is not None:
            client._loop.call_soon_threadsafe(finish_notification.set)
        client.detach()


def test_event_wait_is_an_admitted_native_operation():
    client = _client()
    returned = []
    thread = threading.Thread(target=lambda: returned.append(client.next_event(timeout=2)))
    try:
        thread.start()
        for _ in range(200):
            if client._active_native_operations == 1:
                break
            threading.Event().wait(0.01)
        assert client._active_native_operations == 1
        assert client.try_quiesce() is False
        event = object()
        with client._event_condition:
            client._events.append(event)
            client._event_condition.notify_all()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert returned == [event]
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
    finally:
        thread.join(timeout=2)
        client.detach()


def test_reverse_callback_is_counted_for_its_effect_span_and_refused_after_quiesce():
    client = _client()
    callback_entered = threading.Event()
    release_callback = threading.Event()
    response_started = threading.Event()
    release_response = threading.Event()
    callback_called = []
    task_result = []
    params = {'sessionId': 'fixed', 'path': '/controlled/file'}
    raw = {'jsonrpc': '2.0', 'id': 7, 'method': 'fs/write_text_file', 'params': params}
    key = client._key(raw['method'], params)
    client._reverse[key].append(raw)

    def blocking_callback(message):
        callback_called.append(message.raw['id'])
        callback_entered.set()
        assert release_callback.wait(timeout=2)
        client.reply_request(message.raw['id'], {})

    client._active_callback = blocking_callback

    class HeldResponseChannel:
        async def send_raw_async(self, payload):
            assert payload == {'jsonrpc': '2.0', 'id': 7, 'result': {}}
            response_started.set()
            assert release_response.wait(timeout=2)

    client._channel = HeldResponseChannel()
    client.transport = _ManagedTransport(client)

    def dispatch_callback():
        try:
            task_result.append(asyncio.run(client._handle(raw['method'], params, False)))
        except BaseException as error:
            task_result.append(error)

    callback_thread = threading.Thread(target=dispatch_callback)
    try:
        callback_thread.start()
        assert callback_entered.wait(timeout=2)
        assert client.try_quiesce() is False
        release_callback.set()
        callback_thread.join(timeout=2)
        assert not callback_thread.is_alive()
        assert callback_called == [7]
        assert task_result == [{}]
        # The callback effect has completed, but official ACP still needs to
        # write its response. That native response span remains admitted.
        assert client._active_native_operations == 1
        response_thread = threading.Thread(target=lambda: asyncio.run(client.transport.send(
            {'jsonrpc': '2.0', 'id': 7, 'result': {}})))
        response_thread.start()
        assert response_started.wait(timeout=2)
        assert client.try_quiesce() is False
        release_response.set()
        response_thread.join(timeout=2)
        assert not response_thread.is_alive()
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True

        late_raw = {'jsonrpc': '2.0', 'id': 8, 'method': 'fs/write_text_file',
                    'params': {'sessionId': 'fixed', 'path': '/late/file'}}
        with pytest.raises(RequestError) as refused:
            asyncio.run(client._handle(late_raw['method'], late_raw['params'], False))
        assert refused.value.code == -32000
        assert callback_called == [7]
    finally:
        release_callback.set()
        release_response.set()
        callback_thread.join(timeout=2)
        client.detach()


def test_callback_response_write_failure_releases_exact_admission():
    client = _client()
    params = {'sessionId': 'fixed', 'path': '/controlled/file'}
    raw = {'jsonrpc': '2.0', 'id': 17, 'method': 'fs/write_text_file', 'params': params}
    client._reverse[client._key(raw['method'], params)].append(raw)
    client._active_callback = lambda message: client.reply_request(message.raw['id'], {})

    class FailedResponseChannel:
        async def send_raw_async(self, _payload):
            raise OSError('controlled response write failure')

    client._channel = FailedResponseChannel()
    client.transport = _ManagedTransport(client)
    try:
        assert asyncio.run(client._handle(raw['method'], params, False)) == {}
        assert client._active_native_operations == 1
        with pytest.raises(OSError, match='controlled response write failure'):
            asyncio.run(client.transport.send({'jsonrpc': '2.0', 'id': 17, 'result': {}}))
        assert client._active_native_operations == 0
        assert client._callback_response_admissions == {}
        assert client.try_quiesce() is True
    finally:
        client.detach()


def test_callback_error_reply_keeps_admission_until_sdk_error_response():
    client = _client()
    params = {'sessionId': 'fixed', 'path': '/controlled/file'}
    raw = {'jsonrpc': '2.0', 'id': 19, 'method': 'fs/write_text_file', 'params': params}
    client._reverse[client._key(raw['method'], params)].append(raw)

    def denied_callback(_message):
        raise RequestError(-32000, 'controlled refusal')

    client._active_callback = denied_callback
    response_started = threading.Event()
    release_response = threading.Event()

    class HeldErrorResponseChannel:
        async def send_raw_async(self, payload):
            assert payload == {
                'jsonrpc': '2.0', 'id': 19,
                'error': {'code': -32000, 'message': 'controlled refusal'},
            }
            response_started.set()
            assert release_response.wait(timeout=2)

    client._channel = HeldErrorResponseChannel()
    client.transport = _ManagedTransport(client)
    try:
        with pytest.raises(RequestError):
            asyncio.run(client._handle(raw['method'], params, False))
        assert client._active_native_operations == 1
        response_thread = threading.Thread(target=lambda: asyncio.run(client.transport.send({
            'jsonrpc': '2.0', 'id': 19,
            'error': {'code': -32000, 'message': 'controlled refusal'},
        })))
        response_thread.start()
        assert response_started.wait(timeout=2)
        assert client.try_quiesce() is False
        release_response.set()
        response_thread.join(timeout=2)
        assert not response_thread.is_alive()
        assert client._active_native_operations == 0
        assert client.try_quiesce() is True
    finally:
        release_response.set()
        client.detach()


def test_malformed_callback_id_error_response_does_not_leak_admission():
    client = _client()
    params = {'sessionId': 'fixed'}
    raw = {'jsonrpc': '2.0', 'id': None, 'method': 'fs/read_text_file', 'params': params}
    client._reverse[client._key(raw['method'], params)].append(raw)
    client._active_callback = lambda _message: pytest.fail('invalid ID must refuse before callback')

    class ResponseChannel:
        async def send_raw_async(self, payload):
            assert payload == {
                'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32600, 'message': 'ACP reverse request has no id'},
            }

    client._channel = ResponseChannel()
    client.transport = _ManagedTransport(client)
    try:
        with pytest.raises(RequestError) as refused:
            asyncio.run(client._handle(raw['method'], params, False))
        assert refused.value.code == -32600
        assert client._active_native_operations == 1
        asyncio.run(client.transport.send({
            'jsonrpc': '2.0', 'id': None,
            'error': {'code': -32600, 'message': 'ACP reverse request has no id'},
        }))
        assert client._active_native_operations == 0
        assert client._callback_response_admissions == {}
        assert client.try_quiesce() is True
    finally:
        client.detach()
