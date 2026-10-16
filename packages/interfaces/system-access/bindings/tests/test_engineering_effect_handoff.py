"""Focused receiving tests for the original one-use ACP write handoff.

These tests use the real InstanceAccessAuthority and EngineeringCommandAccess.
They do not mock the authority lock, issue grants, or invoke a native/model
provider. The actual bounded native writer remains an Execution-owned caller.
"""
from contextvars import copy_context
from dataclasses import replace
import asyncio
from contextlib import asynccontextmanager
import json
import os
from queue import Queue
from threading import Event, Thread
import time

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


DISPATCH = "engineering.executions.dispatch"
SCOPE = Scope("first-case", "word-count")
OTHER_SCOPE = EngineeringScope("first-case", "other-project")
ACTION_INSTANCES = (("edit_repository", "first-case-edit-1"),)
INVOCATION_KEY = bytes.fromhex("a1" * 32)


def _access():
    authority = InstanceAccessAuthority(
        lambda: "controlled-first-case-token",
        principal_id="first-case-instance",
        legacy_principal=None,
        grants=(AccessGrant(SCOPE, (DISPATCH,)),),
    )
    caller = authority.authenticate("Bearer controlled-first-case-token")
    return authority, caller, EngineeringCommandAccess(authority)


def _must_refuse(call):
    try:
        call()
    except ApplicationError:
        return
    raise AssertionError("handoff misuse unexpectedly retained authority")


def _consume(access, token, context, *, invocation_key, action_instances):
    with access.consume_effect_write(
        token,
        context,
        invocation_key=invocation_key,
        action_instances=action_instances,
    ):
        return None


def test_handoff_is_one_use_exact_thread_and_limited_to_original_dispatch():
    authority, caller, access = _access()
    handoffs: Queue = Queue()
    consumed = Event()
    response_wait = Event()
    thread_errors = []
    context_box = []
    origin_context_copy = []
    read_fd, write_fd = os.pipe()
    expected_bytes = b'{"controlled":"ACP-byte-cut"}'

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            context = context_box[0]
            parent_context = origin_context_copy[0]
            # The SDK thread receives the original Context copied while the
            # parent admission was active, as run_coroutine_threadsafe does.
            # It still cannot use the suspended parent lease directly.
            _must_refuse(lambda: parent_context.run(access.require, context, DISPATCH))
            _must_refuse(lambda: parent_context.run(access.current_context))

            def bounded_write():
                with access.consume_effect_write(
                    token,
                    context,
                    invocation_key=INVOCATION_KEY,
                    action_instances=ACTION_INSTANCES,
                ):
                    access.require(context, DISPATCH)
                    assert access.current_context() is context
                    assert access.current_context().request_id == "first-case-dispatch-1"
                    _must_refuse(lambda: access.require(context, "engineering.proposals.create"))
                    # Controlled bounded bytes only; this is not an actual ACP call.
                    os.write(write_fd, expected_bytes)

            parent_context.run(bounded_write)
            _must_refuse(lambda: access.require(context, DISPATCH))
            _must_refuse(access.current_context)
            _must_refuse(lambda: _consume(access,
                token,
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
            ))
            consumed.set()
            if not response_wait.wait(3):
                raise AssertionError("controlled response wait was not released")
        except BaseException as error:
            thread_errors.append(error)
            consumed.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-original-sdk")
    sdk_thread.start()
    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-1",
            trace_id="first-case-dispatch-1",
        ) as context:
            context_box.append(context)
            origin_context_copy.append(copy_context())
            with access.handoff_effect_write(
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
                target_thread=sdk_thread,
                expires_at=time.monotonic() + 5,
            ) as token:
                # The origin lease is suspended while the SDK thread writes.
                _must_refuse(lambda: access.require(context, DISPATCH))
                _must_refuse(access.current_context)
                with pytest.raises(ApplicationError):
                    with access.admit(
                        caller, SCOPE, DISPATCH,
                        request_id="nested-first-case-dispatch",
                        trace_id="nested-first-case-dispatch",
                    ):
                        pass
                with pytest.raises(ApplicationError):
                    with access.guard_current_capability(context, SCOPE, DISPATCH):
                        pass
                wrong_thread_errors = []

                def wrong_thread_consume():
                    try:
                        _consume(access, token, context,
                            invocation_key=INVOCATION_KEY,
                            action_instances=ACTION_INSTANCES)
                    except ApplicationError:
                        return
                    except BaseException as error:
                        wrong_thread_errors.append(error)
                        return
                    wrong_thread_errors.append("non-target thread consumed handoff")

                wrong_thread = Thread(target=wrong_thread_consume, name="wrong-handoff-thread")
                wrong_thread.start()
                wrong_thread.join(timeout=3)
                assert not wrong_thread.is_alive()
                assert wrong_thread_errors == []
                handoffs.put(token)
                assert consumed.wait(3), "SDK thread did not finish the bounded write cut"
            # The original command admission is restored after the byte cut.
            access.require(context, DISPATCH)
            assert access.current_context() is context
            response_wait.set()
        assert os.read(read_fd, len(expected_bytes)) == expected_bytes
        with pytest.raises(ApplicationError):
            access.current_context()
        sdk_thread.join(timeout=3)
        assert not sdk_thread.is_alive()
        assert thread_errors == []
    finally:
        response_wait.set()
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("mismatch", ["context", "equal_context", "invocation", "actions"])
def test_handoff_rejects_foreign_context_or_changed_native_binding(mismatch):
    _authority, caller, access = _access()
    handoffs: Queue = Queue()
    finished = Event()
    errors = []
    context_box = []

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            context = context_box[0]
            if mismatch == "context":
                consume_context = replace(context, scope=OTHER_SCOPE)
            elif mismatch == "equal_context":
                consume_context = replace(context)
                assert consume_context == context and consume_context is not context
            else:
                consume_context = context
            key = bytes.fromhex("b2" * 32) if mismatch == "invocation" else INVOCATION_KEY
            actions = (("run_checks", "different-action-1"),) if mismatch == "actions" else ACTION_INSTANCES
            _must_refuse(lambda: _consume(access,
                token,
                consume_context,
                invocation_key=key,
                action_instances=actions,
            ))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-mismatched-sdk")
    sdk_thread.start()
    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-mismatch",
            trace_id="first-case-dispatch-mismatch",
        ) as context:
            context_box.append(context)
            with access.handoff_effect_write(
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
                target_thread=sdk_thread,
                expires_at=time.monotonic() + 5,
            ) as token:
                handoffs.put(token)
                assert finished.wait(3)
        sdk_thread.join(timeout=3)
        assert not sdk_thread.is_alive()
        assert errors == []
    finally:
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)


def test_revoke_completes_during_response_wait_then_stales_outer_admission():
    authority, caller, access = _access()
    handoffs: Queue = Queue()
    write_done = Event()
    response_wait = Event()
    revoke_done = Event()
    thread_errors = []
    context_box = []

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            context = context_box[0]
            with access.consume_effect_write(
                token,
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
            ):
                access.require(context, DISPATCH)
            # This is the simulated native response wait, outside the SDK
            # authority lock and outside the bounded byte-write lease.
            write_done.set()
            if not response_wait.wait(3):
                raise AssertionError("controlled native response wait was not released")
        except BaseException as error:
            thread_errors.append(error)
            write_done.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-sdk-response-wait")
    sdk_thread.start()

    def revoke():
        try:
            authority.revoke()
        except BaseException as error:
            thread_errors.append(error)
        finally:
            revoke_done.set()

    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-revoke",
            trace_id="first-case-dispatch-revoke",
        ) as context:
            context_box.append(context)
            with pytest.raises(ApplicationError):
                with access.handoff_effect_write(
                    context,
                    invocation_key=INVOCATION_KEY,
                    action_instances=ACTION_INSTANCES,
                    target_thread=sdk_thread,
                    expires_at=time.monotonic() + 5,
                ) as token:
                    handoffs.put(token)
                    assert write_done.wait(3)
                    revoke_thread = Thread(target=revoke, name="controlled-revoke")
                    revoke_thread.start()
                    # Revocation may wait for the bounded write cut above, but
                    # must finish before the external response wait is released.
                    revoked_while_waiting = revoke_done.wait(0.5)
                    response_wait.set()
                    revoke_thread.join(timeout=3)
                    assert revoked_while_waiting, "revoke waited for native response/network wait"
            sdk_thread.join(timeout=3)
            assert not sdk_thread.is_alive()
            assert thread_errors == []
    finally:
        response_wait.set()
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)


def test_expired_handoff_is_refused_on_target_thread():
    _authority, caller, access = _access()
    handoffs: Queue = Queue()
    allow_consume = Event()
    finished = Event()
    errors = []
    context_box = []

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            if not allow_consume.wait(3):
                raise AssertionError("expired-handoff gate was not released")
            _must_refuse(lambda: _consume(access,
                token,
                context_box[0],
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
            ))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-expired-sdk")
    sdk_thread.start()
    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-expired",
            trace_id="first-case-dispatch-expired",
        ) as context:
            context_box.append(context)
            with access.handoff_effect_write(
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
                target_thread=sdk_thread,
                expires_at=time.monotonic() + 0.05,
            ) as token:
                handoffs.put(token)
                time.sleep(0.06)
                allow_consume.set()
                assert finished.wait(3)
        sdk_thread.join(timeout=3)
        assert not sdk_thread.is_alive()
        assert errors == []
    finally:
        allow_consume.set()
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)


def test_revoke_before_token_consumption_refuses_native_write():
    authority, caller, access = _access()
    handoffs: Queue = Queue()
    allow_consume = Event()
    finished = Event()
    errors = []
    context_box = []

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            if not allow_consume.wait(3):
                raise AssertionError("revocation gate was not released")
            _must_refuse(lambda: _consume(
                access,
                token,
                context_box[0],
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
            ))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-revoked-sdk")
    sdk_thread.start()
    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-revoked",
            trace_id="first-case-dispatch-revoked",
        ) as context:
            context_box.append(context)
            with pytest.raises(ApplicationError):
                with access.handoff_effect_write(
                    context,
                    invocation_key=INVOCATION_KEY,
                    action_instances=ACTION_INSTANCES,
                    target_thread=sdk_thread,
                    expires_at=time.monotonic() + 5,
                ) as token:
                    handoffs.put(token)
                    authority.revoke()
                    allow_consume.set()
                    assert finished.wait(3)
            sdk_thread.join(timeout=3)
            assert not sdk_thread.is_alive()
            assert errors == []
    finally:
        allow_consume.set()
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)


def test_pending_token_cannot_be_consumed_after_admission_ends():
    _authority, caller, access = _access()
    handoffs: Queue = Queue()
    finished = Event()
    errors = []
    context_box = []

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            _must_refuse(lambda: _consume(access,
                token,
                context_box[0],
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
            ))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    sdk_thread = Thread(target=sdk_thread_body, name="controlled-ended-admission-sdk")
    sdk_thread.start()
    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-dispatch-ended",
            trace_id="first-case-dispatch-ended",
        ) as context:
            context_box.append(context)
            with access.handoff_effect_write(
                context,
                invocation_key=INVOCATION_KEY,
                action_instances=ACTION_INSTANCES,
                target_thread=sdk_thread,
                expires_at=time.monotonic() + 5,
            ) as token:
                pass
        handoffs.put(token)
        assert finished.wait(3)
        sdk_thread.join(timeout=3)
        assert not sdk_thread.is_alive()
        assert errors == []
    finally:
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)


def test_original_effect_write_guard_cross_task_cleanup_clears_only_delegated_lease():
    """Receive the original SDK hold's wait_for/create_task cleanup contexts."""
    from ordessa_execution_agents.harness.transport import EffectWriteGuard

    authority, caller, access = _access()
    handoffs: Queue = Queue()
    write_done = Event()
    response_wait = Event()
    revoke_done = Event()
    thread_errors = []
    context_box = []
    captured_cut_context = []
    read_fd, write_fd = os.pipe()
    unit_ref = {
        "environmentNamespace": "first-case",
        "unitId": "first-case-unit",
        "ownerProviderRef": {"environmentNamespace": "first-case", "providerId": "controlled"},
        "sourceRevision": "sha256:" + "c" * 64,
    }
    params = {"sessionId": "controlled-session", "prompt": [{"type": "text", "text": "one bounded write"}]}
    input_digest = "sha256:" + "d" * 64
    expected_bytes = b'{"controlled":"original-effect-write-cut"}'
    frame = json.dumps({"jsonrpc": "2.0", "id": 71, "method": "session/prompt",
                        "params": params}, separators=(",", ":")).encode()

    def sdk_thread_body():
        try:
            token = handoffs.get(timeout=3)
            context = context_box[0]

            @asynccontextmanager
            async def acquire(identity, deadline):
                assert identity["unitRef"] == unit_ref
                assert identity["operationRef"] == "first-case-native-operation"
                assert identity["inputDigest"] == input_digest
                with access.consume_effect_write(
                    token,
                    context,
                    invocation_key=INVOCATION_KEY,
                    action_instances=ACTION_INSTANCES,
                ):
                    access.require(context, DISPATCH)
                    assert access.current_context() is context
                    assert access.current_context().request_id == "first-case-effect-write-1"
                    captured_cut_context.append(copy_context())
                    # This is a controlled pipe write through the original
                    # EffectWriteGuard hold, not an actual ACP/provider call.
                    assert os.write(write_fd, expected_bytes) == len(expected_bytes)
                    yield

            async def exercise_original_hold():
                guard = EffectWriteGuard(
                    unit_ref, "first-case-native-operation", input_digest, params,
                    acquire, timeout=2, release_timeout=1,
                )
                async with guard.hold(frame):
                    pass
                assert len(captured_cut_context) == 1
                cut_context = captured_cut_context[0]
                _must_refuse(lambda: cut_context.run(access.require, context, DISPATCH))
                _must_refuse(lambda: cut_context.run(access.current_context))
                write_done.set()

            asyncio.run(exercise_original_hold())
            if not response_wait.wait(3):
                raise AssertionError("controlled response wait was not released")
        except BaseException as error:
            thread_errors.append(error)
            write_done.set()

    sdk_thread = Thread(target=sdk_thread_body, name="original-effect-write-sdk")
    sdk_thread.start()

    def revoke():
        try:
            authority.revoke()
        except BaseException as error:
            thread_errors.append(error)
        finally:
            revoke_done.set()

    try:
        with access.admit(
            caller, SCOPE, DISPATCH,
            request_id="first-case-effect-write-1",
            trace_id="first-case-effect-write-1",
        ) as context:
            context_box.append(context)
            with pytest.raises(ApplicationError):
                with access.handoff_effect_write(
                    context,
                    invocation_key=INVOCATION_KEY,
                    action_instances=ACTION_INSTANCES,
                    target_thread=sdk_thread,
                    expires_at=time.monotonic() + 5,
                ) as token:
                    handoffs.put(token)
                    assert write_done.wait(3), "original EffectWriteGuard did not finish cleanup"
                    revoke_thread = Thread(target=revoke, name="effect-write-response-revoke")
                    revoke_thread.start()
                    revoked_during_wait = revoke_done.wait(0.5)
                    response_wait.set()
                    revoke_thread.join(timeout=3)
                    assert revoked_during_wait, "revoke waited for response/network wait"
            sdk_thread.join(timeout=3)
            assert not sdk_thread.is_alive()
            assert thread_errors == []
    finally:
        response_wait.set()
        if sdk_thread.is_alive():
            sdk_thread.join(timeout=3)
        os.close(write_fd)
        assert os.read(read_fd, len(expected_bytes)) == expected_bytes
        assert os.read(read_fd, 1) == b""
        os.close(read_fd)
