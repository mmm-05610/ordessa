"""Local-only trace of SDK open inside the original UnitManager start path.

This is a diagnostic, not Pi or model validation. It reuses the real local
owner fixture and records timing/thread/module facts only.
"""
import asyncio
import errno
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import traceback

import pytest

pytest_plugins = ("test_local_owner",)


def test_sdk_loop_pipe_wakes_callback_coroutine_cancel_and_stop():
    """Keep original asyncio queue/Futures working when socket wake is denied."""
    from ordessa_units.sessions.sdk_client import SdkAcpClient

    class UnusedChannel:
        def close(self):
            return None

    blocked_send_errnos = []

    class BlockedSocket:
        def __init__(self, sock):
            self._sock = sock

        def send(self, *_args, **_kwargs):
            blocked_send_errnos.append(errno.EPERM)
            raise PermissionError(errno.EPERM, "controlled socketpair wake denial")

        def __getattr__(self, name):
            return getattr(self._sock, name)

    client = SdkAcpClient(UnusedChannel(), connect=False)
    loop = client._loop
    original_csock = loop._csock
    loop._csock = BlockedSocket(original_csock)
    started = threading.Event()
    callback_ran = threading.Event()
    coroutine_started = threading.Event()
    coroutine_cancelled = threading.Event()
    loop.call_soon(started.set)
    thread_started = False
    read_fd, write_fd = client._wakeup_read_fd, client._wakeup_write_fd
    try:
        client._thread.start()
        thread_started = True
        assert started.wait(timeout=2)

        loop.call_soon_threadsafe(callback_ran.set)
        assert callback_ran.wait(timeout=2)

        async def wait_for_cancel():
            coroutine_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                coroutine_cancelled.set()
                raise

        future = asyncio.run_coroutine_threadsafe(wait_for_cancel(), loop)
        assert coroutine_started.wait(timeout=2)
        assert future.cancel() is True
        assert coroutine_cancelled.wait(timeout=2)
        assert future.cancelled()

        # detach() submits its cleanup coroutine and stop callback through the
        # same public loop method, then the loop owner closes its own pipe FDs.
        client.detach()
        assert not client._thread.is_alive()
        assert loop.is_closed()
        assert client._wakeup_closed
        assert client._wakeup_read_fd is None and client._wakeup_write_fd is None
        assert len(blocked_send_errnos) >= 5
        assert set(blocked_send_errnos) == {errno.EPERM}
        for fd in (read_fd, write_fd):
            with pytest.raises(OSError) as closed:
                os.fstat(fd)
            assert closed.value.errno == errno.EBADF
    finally:
        if thread_started and client._thread.is_alive():
            client.detach()
        elif not thread_started and not loop.is_closed():
            client.detach()


def test_sdk_loop_pipe_initialization_failure_closes_fds_and_loop(monkeypatch):
    import ordessa_units.sessions.sdk_client as sdk_client

    class UnusedChannel:
        def close(self):
            return None

    real_pipe = os.pipe
    opened_fds = []
    created_loops = []
    real_new_event_loop = sdk_client.asyncio.new_event_loop
    real_set_blocking = os.set_blocking

    def record_pipe():
        fds = real_pipe()
        opened_fds.extend(fds)
        return fds

    def record_loop():
        loop = real_new_event_loop()
        created_loops.append(loop)
        return loop

    calls = 0

    def fail_second_set_blocking(fd, blocking):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EPERM, "controlled pipe setup failure")
        return real_set_blocking(fd, blocking)

    monkeypatch.setattr(sdk_client.os, "pipe", record_pipe)
    monkeypatch.setattr(sdk_client.asyncio, "new_event_loop", record_loop)
    monkeypatch.setattr(sdk_client.os, "set_blocking", fail_second_set_blocking)

    with pytest.raises(OSError) as failure:
        sdk_client.SdkAcpClient(UnusedChannel(), connect=False)
    assert failure.value.errno == errno.EPERM
    assert len(opened_fds) == 2
    for fd in opened_fds:
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF
    assert len(created_loops) == 1
    assert created_loops[0].is_closed()


def test_sdk_loop_pipe_write_failure_and_full_pipe_are_explicit_and_idempotent(monkeypatch):
    import ordessa_units.sessions.sdk_client as sdk_client

    class UnusedChannel:
        def close(self):
            return None

    failed_write_client = sdk_client.SdkAcpClient(UnusedChannel(), connect=False)
    failed_write_fds = (failed_write_client._wakeup_read_fd,
                        failed_write_client._wakeup_write_fd)
    original_write = os.write

    def deny_write(_fd, _payload):
        raise OSError(errno.EPERM, "controlled pipe write failure")

    monkeypatch.setattr(sdk_client.os, "write", deny_write)
    with pytest.raises(RuntimeError, match="SDK loop wake pipe write failed"):
        failed_write_client._call_soon_threadsafe(lambda: None)
    failed_write_client.detach()
    failed_write_client.detach()
    assert failed_write_client._wakeup_closed
    for fd in failed_write_fds:
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF

    monkeypatch.setattr(sdk_client.os, "write", original_write)
    full_pipe_client = sdk_client.SdkAcpClient(UnusedChannel(), connect=False)
    full_pipe_fds = (full_pipe_client._wakeup_read_fd,
                     full_pipe_client._wakeup_write_fd)
    while True:
        try:
            os.write(full_pipe_client._wakeup_write_fd, b"x" * 4096)
        except BlockingIOError:
            break
    handle = full_pipe_client._call_soon_threadsafe(lambda: None)
    assert not handle.cancelled()
    full_pipe_client.detach()
    full_pipe_client.detach()
    assert full_pipe_client._wakeup_closed
    for fd in full_pipe_fds:
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF


def test_sdk_loop_pipe_waits_when_idle_and_repeated_detach_releases_once():
    from ordessa_units.sessions.sdk_client import SdkAcpClient

    class UnusedChannel:
        def close(self):
            return None

    client = SdkAcpClient(UnusedChannel(), connect=False)
    selector = client._loop._selector
    original_select = selector.select
    select_calls = 0
    entered_select = threading.Event()

    def count_select(timeout=None):
        nonlocal select_calls
        select_calls += 1
        entered_select.set()
        return original_select(timeout)

    selector.select = count_select
    read_fd, write_fd = client._wakeup_read_fd, client._wakeup_write_fd
    client._thread.start()
    try:
        assert entered_select.wait(timeout=2)
        calls_while_idle = select_calls
        assert calls_while_idle >= 1
        client._thread.join(timeout=0.05)
        assert client._thread.is_alive()
        assert select_calls == calls_while_idle
    finally:
        client.detach()
    client.detach()
    assert client._loop.is_closed()
    for fd in (read_fd, write_fd):
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF


class _OpenTrace:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = False
        self.events = []
        self.sdk_thread_stack_at_timeout = []

    def mark(self, stage, *, always=False, **facts):
        with self.lock:
            if (self.active or always) and len(self.events) < 256:
                self.events.append({
                    "stage": stage,
                    "monotonicNs": time.monotonic_ns(),
                    "threadId": threading.get_ident(),
                    **facts,
                })

    @staticmethod
    def _module(filename):
        parts = Path(filename).parts
        for root in (
            "ordessa_units", "ordessa_environments", "ordessa_environments_local",
            "ordessa_execution_agents", "acp",
        ):
            try:
                index = parts.index(root)
            except ValueError:
                continue
            return ".".join(parts[index:])
        return "stdlib." + Path(filename).stem

    def capture_sdk_stack(self, thread):
        ident = thread.ident
        frame = sys._current_frames().get(ident) if ident is not None else None
        if frame is None:
            return
        self.sdk_thread_stack_at_timeout = [
            {"module": self._module(item.filename), "function": item.name,
             "line": int(item.lineno)}
            for item in traceback.extract_stack(frame, limit=20)
        ]

    def write(self, tmp_path):
        evidence_dir = Path(tmp_path) / "sdk-open-boundary-evidence"
        evidence_dir.mkdir(mode=0o700)
        path = evidence_dir / "stages.json"
        data = json.dumps({
            "events": self.events,
            "sdkThreadStackAtTimeout": self.sdk_thread_stack_at_timeout,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return path


def _install_open_trace(monkeypatch, trace, *, before_open=None, after_open=None):
    from acp.connection import Connection
    from ordessa_environments.management.store import SQLiteEnvironmentStore
    from ordessa_execution_agents.harness.transport.environment_channel import EnvironmentProcessChannel
    from ordessa_units.sessions.sdk_client import SdkAcpClient, _ManagedTransport

    original_connection_init = Connection.__init__
    original_check_use = SQLiteEnvironmentStore.check_use
    original_next_message = EnvironmentProcessChannel.next_message_async
    original_open_connection = SdkAcpClient.open_connection
    original_run = SdkAcpClient._run
    original_submit = SdkAcpClient._submit
    original_open = SdkAcpClient._open
    original_receive = _ManagedTransport.receive

    def connection_init(instance, *args, **kwargs):
        trace.mark("sdk-connection-init.enter")
        try:
            return original_connection_init(instance, *args, **kwargs)
        finally:
            trace.mark("sdk-connection-init.exit")

    def check_use(store, *args, **kwargs):
        trace.mark("environment-store.check-use.enter")
        try:
            result = original_check_use(store, *args, **kwargs)
        except BaseException as error:
            trace.mark("environment-store.check-use.error",
                       exceptionClass=type(error).__module__ + "." + type(error).__qualname__)
            raise
        trace.mark("environment-store.check-use.exit")
        return result

    async def next_message(channel, *args, **kwargs):
        trace.mark("environment-channel.next-message.enter")
        try:
            result = await original_next_message(channel, *args, **kwargs)
        except BaseException as error:
            trace.mark("environment-channel.next-message.error",
                       exceptionClass=type(error).__module__ + "." + type(error).__qualname__)
            raise
        trace.mark("environment-channel.next-message.exit")
        return result

    def run(client):
        trace.mark("sdk-loop.run.enter")
        try:
            return original_run(client)
        finally:
            trace.mark("sdk-loop.run.exit")

    async def open_coroutine(client):
        trace.mark("sdk-open-coroutine.enter")
        try:
            return await original_open(client)
        finally:
            trace.mark("sdk-open-coroutine.exit")

    async def receive(transport):
        trace.mark("sdk-transport.receive.enter")
        try:
            result = await original_receive(transport)
        except BaseException as error:
            trace.mark("sdk-transport.receive.error",
                       exceptionClass=type(error).__module__ + "." + type(error).__qualname__)
            raise
        trace.mark("sdk-transport.receive.exit")
        return result

    class ObservedFuture:
        def __init__(self, future, client):
            self._future, self._client = future, client

        def result(self, timeout=None):
            trace.mark("sdk-open-future.wait.enter")
            try:
                result = self._future.result(timeout=timeout)
            except BaseException as error:
                trace.mark("sdk-open-future.wait.error",
                           exceptionClass=type(error).__module__ + "." + type(error).__qualname__,
                           done=self._future.done(), cancelled=self._future.cancelled())
                if isinstance(error, TimeoutError) and trace.active:
                    trace.capture_sdk_stack(self._client._thread)
                raise
            trace.mark("sdk-open-future.wait.exit",
                       done=self._future.done(), cancelled=self._future.cancelled())
            return result

        def cancel(self):
            result = self._future.cancel()
            trace.mark("sdk-open-future.cancel", accepted=result,
                       done=self._future.done(), cancelled=self._future.cancelled())
            return result

        def __getattr__(self, name):
            return getattr(self._future, name)

    def submit(client, coroutine):
        return ObservedFuture(original_submit(client, coroutine), client)

    def open_connection(client):
        with trace.lock:
            trace.active = True
            trace.events.append({"stage": "sdk-open-connection.enter",
                                 "monotonicNs": time.monotonic_ns(),
                                 "threadId": threading.get_ident()})
        try:
            if before_open is not None:
                before_open()
            result = original_open_connection(client)
        except BaseException as error:
            trace.mark("sdk-open-connection.error",
                       exceptionClass=type(error).__module__ + "." + type(error).__qualname__)
            if after_open is not None:
                after_open("error")
            raise
        finally:
            trace.mark("sdk-open-connection.exit")
            with trace.lock:
                trace.active = False
        if after_open is not None:
            after_open("returned")
        return result

    monkeypatch.setattr(Connection, "__init__", connection_init)
    monkeypatch.setattr(SQLiteEnvironmentStore, "check_use", check_use)
    monkeypatch.setattr(EnvironmentProcessChannel, "next_message_async", next_message)
    monkeypatch.setattr(SdkAcpClient, "open_connection", open_connection)
    monkeypatch.setattr(SdkAcpClient, "_run", run)
    monkeypatch.setattr(SdkAcpClient, "_submit", submit)
    monkeypatch.setattr(SdkAcpClient, "_open", open_coroutine)
    monkeypatch.setattr(_ManagedTransport, "receive", receive)


def test_real_local_unit_start_records_sdk_open_stages(live_owner, monkeypatch, tmp_path):
    """Observe one real manager-held start; no Apps secret input or remote call."""
    trace = _OpenTrace()
    _install_open_trace(monkeypatch, trace)
    world = live_owner
    unit = None
    try:
        unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    except BaseException as error:
        trace.mark("public-unit-create.error",
                   exceptionClass=type(error).__module__ + "." + type(error).__qualname__)
        raise
    finally:
        trace.write(tmp_path)

    stages = [event["stage"] for event in trace.events]
    assert "sdk-open-connection.enter" in stages
    assert "sdk-open-future.wait.exit" in stages
    assert "sdk-open-coroutine.exit" in stages
    assert "sdk-connection-init.exit" in stages
    assert "environment-channel.next-message.enter" in stages
    assert unit.snapshot()["state"] == "confirmed"
    assert unit.close(world.owner.authorization())["state"] == "confirmed"
    assert world.public_manager.close(world.owner.authorization())["state"] == "confirmed"


def test_use_check_blocks_behind_competing_sqlite_immediate_transaction(live_owner, tmp_path):
    """Confirm the check-use busy-wait candidate without starting a child."""
    world = live_owner
    use = world.environment.acquire("sdk-open-check-use-diagnostic", sharing=True)
    entered = threading.Event()
    completed = threading.Event()
    errors = []
    store = world.environment_manager.store
    original_check_use = store.check_use

    def check_use(use_id, *, allow_unknown=False):
        entered.set()
        try:
            return original_check_use(use_id, allow_unknown=allow_unknown)
        except BaseException as error:
            errors.append(type(error).__module__ + "." + type(error).__qualname__)
            raise
        finally:
            completed.set()

    store.check_use = check_use
    connection = sqlite3.connect(store.path, timeout=1, isolation_level=None)
    worker = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        worker = threading.Thread(
            target=use.check,
            args=(world.environment.identity, use.generation),
            name="controlled-store-check",
        )
        worker.start()
        assert entered.wait(timeout=2)
        assert not completed.wait(timeout=0.05)
        connection.execute("ROLLBACK")
        assert completed.wait(timeout=2)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert errors == []
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
        if worker is not None:
            worker.join(timeout=2)
        store.check_use = original_check_use
        use.release()


def test_public_unit_open_future_under_environment_store_writer_competition(
        live_owner, monkeypatch, tmp_path):
    """Hold one real SQLite RESERVED lock only at the original SDK open edge."""
    world = live_owner
    trace = _OpenTrace()
    lock_requested = threading.Event()
    lock_acquired = threading.Event()
    release_writer = threading.Event()
    writer_errors = []

    def writer():
        if not lock_requested.wait(timeout=8) or release_writer.is_set():
            return
        connection = sqlite3.connect(world.environment_manager.store.path,
                                     timeout=1, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            trace.mark("controlled-writer.reserved", always=True)
            lock_acquired.set()
            if not release_writer.wait(timeout=8):
                writer_errors.append("bounded-release-timeout")
        except BaseException as error:
            writer_errors.append(type(error).__module__ + "." + type(error).__qualname__)
            lock_acquired.set()
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()
            trace.mark("controlled-writer.released", always=True)

    def before_open():
        trace.mark("controlled-writer.requested-at-open")
        lock_requested.set()
        if not lock_acquired.wait(timeout=2):
            raise RuntimeError("controlled SQLite writer did not acquire its lock")

    def after_open(outcome):
        trace.mark("controlled-writer.rollback-requested", always=True,
                   outcome=outcome)
        release_writer.set()

    _install_open_trace(monkeypatch, trace, before_open=before_open,
                        after_open=after_open)
    lock_thread = threading.Thread(target=writer, name="owned-sqlite-writer")
    lock_thread.start()
    unit = None
    create_error = None
    try:
        unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    except BaseException as error:
        create_error = type(error).__module__ + "." + type(error).__qualname__
    finally:
        release_writer.set()
        lock_requested.set()
        lock_thread.join(timeout=3)
        trace.write(tmp_path)

    assert not lock_thread.is_alive()
    assert writer_errors == []
    events = tuple(trace.events)
    stages = tuple(event["stage"] for event in events)
    assert "controlled-writer.reserved" in stages
    assert "environment-store.check-use.enter" in stages
    assert "sdk-open-coroutine.exit" in stages
    timeout_events = [event for event in events
                      if event["stage"] == "sdk-open-future.wait.error"
                      and event.get("exceptionClass") in {"builtins.TimeoutError", "TimeoutError"}]
    if create_error is not None:
        # This is the causal contention case: the receive-side check enters
        # before the existing SDK future deadline but cannot return while the
        # controlled writer owns the real Environment database.
        assert create_error.endswith("UnitLifecycleRefused")
        assert timeout_events
        timeout_at = timeout_events[0]["monotonicNs"]
        check_entered_before_timeout = any(
            event["stage"] == "environment-store.check-use.enter"
            and event["monotonicNs"] < timeout_at for event in events
        )
        check_returned_before_timeout = any(
            event["stage"] == "environment-store.check-use.exit"
            and event["monotonicNs"] < timeout_at for event in events
        )
        assert check_entered_before_timeout and not check_returned_before_timeout
        assert timeout_events[0].get("done") is False
        assert timeout_events[0].get("cancelled") is False
        assert trace.sdk_thread_stack_at_timeout
        instances = tuple(world.original_manager._units.values())
        assert len(instances) == 1
        instance, identity = instances[0]
        session = world.records.owner_read_session(identity["unitId"])
        assert session.state == "unknown"
        record = instance.channel_factory.owned_record
        assert record is not None
        process_state = record.process.observe().state
        trace.mark("unknown-retained.owned-process-state", always=True,
                   sessionState=session.state, processState=process_state)
    else:
        # A read-only/deferred gate should finish despite another connection's
        # RESERVED lock; the open future must complete before rollback is sent.
        future_exit = next(event for event in events
                           if event["stage"] == "sdk-open-future.wait.exit")
        rollback_request = next(event for event in events
                                if event["stage"] == "controlled-writer.rollback-requested")
        assert future_exit["monotonicNs"] < rollback_request["monotonicNs"]
        assert unit.snapshot()["state"] == "confirmed"
        assert unit.close(world.owner.authorization())["state"] == "confirmed"
        assert world.public_manager.close(world.owner.authorization())["state"] == "confirmed"
