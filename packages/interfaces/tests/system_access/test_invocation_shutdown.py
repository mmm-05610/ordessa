"""Focused drain/admission tests for the real system-access wire service.

These tests qualify the transport counter and lifecycle edges only. They do
not qualify Server composition or any product shutdown ordering.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from threading import Event, Thread

import pytest

from ordessa_interfaces.system_access.services.invocation import WireService
from server_plugin_api import ServerMethodDescriptor, WireError


class _Registry:
    def __init__(self):
        self._methods = {}

    def register(self, descriptor):
        self._methods[descriptor.method_id] = descriptor

    def lookup(self, method_id):
        return self._methods.get(method_id)

    def descriptors(self):
        return tuple(self._methods.values())

    def handler_view(self):
        return {key: value.handler for key, value in self._methods.items()}

    def unregister(self, method_id, *, owner):
        item = self._methods[method_id]
        assert item.owner == owner
        del self._methods[method_id]


class _Authority:
    def verify(self, caller):
        assert caller == "caller"

    def guard_legacy(self, caller):
        return nullcontext()


def _service(handler):
    registry = _Registry()
    service = WireService(
        server_id_provider=lambda: "test-server",
        cursor_secret=b"synthetic-test-secret",
        method_registry=registry,
        token_required=False,
        identity_authority=_Authority(),
    )
    registry.register(ServerMethodDescriptor(
        method_id="test.work",
        required_params=frozenset(),
        optional_params=frozenset(),
        handler=handler,
        owner="test.owner",
        contextual=True,
    ))
    return service


def test_sync_dispatch_failure_releases_activity_and_shutdown_is_idempotent():
    def fail(_params, _caller):
        raise RuntimeError("synthetic handler failure")

    service = _service(fail)
    with pytest.raises(WireError) as caught:
        service.dispatch("test.work", {}, caller="caller")
    assert caught.value.family == "UNAVAILABLE"
    assert service.begin_shutdown() is True
    assert service.begin_shutdown() is True
    assert service.reopen_admission() is True


def test_unknown_and_round_gate_keep_precedence_over_shutdown_admission():
    service = _service(lambda _params, _caller: {"done": True})
    service.bind_round_state(lambda: False)
    assert service.begin_shutdown() is True
    with pytest.raises(WireError) as unknown:
        service.dispatch("test.missing", {}, caller="caller")
    assert unknown.value.message == "test.missing is not a wire/1 method"
    with pytest.raises(WireError) as stopped:
        service.dispatch("test.work", {}, caller="caller")
    assert stopped.value.details["internalCode"] == "ROUND_NOT_STARTED"


def test_close_before_first_await_releases_direct_dispatch_activity():
    async def work(_params, _caller):
        return {"done": True}

    service = _service(work)
    pending = service.dispatch("test.work", {}, caller="caller")
    assert service.begin_shutdown() is False
    assert service.reopen_admission() is False
    pending.close()
    assert service.begin_shutdown() is True


def test_closing_wrapper_does_not_mark_task_idle_during_async_finally():
    async def scenario():
        owner_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_finish = asyncio.Event()

        async def owner_work():
            try:
                owner_started.set()
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_finish.wait()

        owner_task = asyncio.create_task(owner_work())
        await owner_started.wait()
        service = _service(lambda _params, _caller: owner_task)
        pending = service.dispatch("test.work", {}, caller="caller")
        pending.close()
        assert service.begin_shutdown() is False

        owner_task.cancel()
        await cleanup_started.wait()
        assert service.begin_shutdown() is False
        cleanup_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
        await asyncio.sleep(0)
        assert service.begin_shutdown() is True

    asyncio.run(scenario())


def test_driven_native_coroutine_close_stays_pending_until_async_finally_finishes():
    async def scenario():
        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_finish = asyncio.Event()

        async def work(_params, _caller):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_finish.wait()

        service = _service(work)
        pending = service.dispatch("test.work", {}, caller="caller")
        task = asyncio.create_task(pending)
        await entered.wait()
        task.cancel()
        await cleanup_started.wait()
        with pytest.raises(RuntimeError, match="cannot synchronously close"):
            pending.close()
        assert service.begin_shutdown() is False
        cleanup_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.begin_shutdown() is True

    asyncio.run(scenario())


def test_task_cancel_before_first_send_discards_only_unstarted_native_coroutine():
    async def scenario():
        entered = asyncio.Event()

        async def work(_params, _caller):
            entered.set()
            return {"done": True}

        service = _service(work)
        pending = service.dispatch("test.work", {}, caller="caller")
        task = asyncio.create_task(pending)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not entered.is_set()
        assert service.begin_shutdown() is True

    asyncio.run(scenario())


def test_wrapper_refuses_to_close_a_native_coroutine_already_driven_by_owner_task():
    async def scenario():
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def owner_work():
            entered.set()
            await finish.wait()
            return {"done": True}

        owner_coroutine = owner_work()
        owner_task = asyncio.create_task(owner_coroutine)
        await entered.wait()
        service = _service(lambda _params, _caller: owner_coroutine)
        pending = service.dispatch("test.work", {}, caller="caller")
        with pytest.raises(WireError) as caught:
            pending.close()
        assert caught.value.family == "CAPABILITY_UNSUPPORTED"
        assert caught.value.details["internalCode"] == "OWNER_COROUTINE_ALREADY_STARTED"
        assert not owner_task.done()
        assert service.begin_shutdown() is False
        finish.set()
        assert await owner_task == {"done": True}
        assert service.begin_shutdown() is True

    asyncio.run(scenario())


def test_sync_in_flight_dispatch_keeps_shutdown_pending_and_closes_admission():
    entered = Event()
    finish = Event()
    result = []

    def work(_params, _caller):
        entered.set()
        assert finish.wait(timeout=5)
        return {"done": True}

    service = _service(work)
    thread = Thread(target=lambda: result.append(
        service.dispatch("test.work", {}, caller="caller")))
    thread.start()
    assert entered.wait(timeout=5)
    assert service.begin_shutdown() is False
    with pytest.raises(WireError) as caught:
        service.dispatch("test.work", {}, caller="caller")
    assert caught.value.details["internalCode"] == "DISPATCH_ADMISSION_CLOSED"
    finish.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert result == [{"done": True}]
    assert service.begin_shutdown() is True


def test_dispatch_async_holds_activity_through_result_projection_and_reopens_only_idle():
    async def scenario():
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def work(_params, _caller):
            entered.set()
            await finish.wait()
            return {"done": True}

        service = _service(work)
        task = asyncio.create_task(service.dispatch_async("test.work", {}, caller="caller"))
        await entered.wait()
        assert service.begin_shutdown() is False
        assert service.reopen_admission() is False
        hello = service.hello({
            "clientVersions": ["wire/1"],
            "clientPresentationSupports": [],
        })
        assert hello["serverId"] == "test-server"
        with pytest.raises(WireError) as caught:
            service.dispatch("test.work", {}, caller="caller")
        assert caught.value.details["internalCode"] == "DISPATCH_ADMISSION_CLOSED"
        finish.set()
        assert await task == {"done": True}
        assert service.begin_shutdown() is True
        assert service.reopen_admission() is True

    asyncio.run(scenario())


def test_async_failure_and_cancellation_release_activity():
    async def scenario():
        async def fail(_params, _caller):
            raise RuntimeError("synthetic async failure")

        failed = _service(fail)
        with pytest.raises(WireError) as caught:
            await failed.dispatch_async("test.work", {}, caller="caller")
        assert caught.value.family == "UNAVAILABLE"
        assert failed.begin_shutdown() is True

        entered = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_finish = asyncio.Event()

        async def wait_forever(_params, _caller):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await cleanup_finish.wait()

        cancelled = _service(wait_forever)
        task = asyncio.create_task(cancelled.dispatch_async("test.work", {}, caller="caller"))
        await entered.wait()
        assert cancelled.begin_shutdown() is False
        task.cancel()
        await cleanup_started.wait()
        assert cancelled.begin_shutdown() is False
        cleanup_finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.begin_shutdown() is True

    asyncio.run(scenario())


def test_async_hello_remains_untracked_after_business_shutdown():
    async def scenario():
        service = _service(lambda _params, _caller: {"done": True})
        assert service.begin_shutdown() is True
        hello = await service.dispatch_async("server.hello", {
            "clientVersions": ["wire/1"],
            "clientPresentationSupports": [],
        })
        assert hello["serverId"] == "test-server"
        assert service.begin_shutdown() is True

    asyncio.run(scenario())


def test_ready_future_is_not_reaped_until_wrapper_is_awaited_or_closed():
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        future.set_result({"done": True})
        awaited_service = _service(lambda _params, _caller: future)
        pending = awaited_service.dispatch("test.work", {}, caller="caller")
        assert awaited_service.begin_shutdown() is False
        assert await pending == {"done": True}
        assert awaited_service.begin_shutdown() is True

        closed_future = asyncio.get_running_loop().create_future()
        closed_future.set_result({"done": True})
        closed_service = _service(lambda _params, _caller: closed_future)
        unconsumed = closed_service.dispatch("test.work", {}, caller="caller")
        assert closed_service.begin_shutdown() is False
        unconsumed.close()
        assert closed_service.begin_shutdown() is True

    asyncio.run(scenario())


def test_shutdown_poll_cannot_reap_ready_future_before_async_postprocessing():
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        future.set_result({"done": True})
        service = _service(lambda _params, _caller: future)
        observations = []

        class _Gate:
            def observe_wire_result(self, _method, _params, _result, _routes):
                observations.append(service.begin_shutdown())

        service.acp_admission_gate = _Gate()
        service.stream_routes = object()
        original_dispatch = service.dispatch

        def intercept_dispatch(method, params, *, caller=None):
            result = original_dispatch(method, params, caller=caller)
            observations.append(service.begin_shutdown())
            return result

        service.dispatch = intercept_dispatch
        assert await service.dispatch_async("test.work", {}, caller="caller") == {"done": True}
        assert observations == [False, False]
        assert service.begin_shutdown() is True

    asyncio.run(scenario())
