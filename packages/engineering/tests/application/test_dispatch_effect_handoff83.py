"""Source83 receiving tests for the original Engineering byte-write cut.

The SDK peer and native bytes are controlled fixtures; W10 admission, the
opaque handoff, the original Engineering dispatch row, and the SQLite
effect-write transaction are real. No network or model call is made.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from ordessa_engineering.adapters.native_records.recorded_dispatch import (
    RecordedDispatchExecution,
    engineering_effect_write_guard_factory,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_observations import (
    MAX_EXECUTION_RECEIPT_BYTES,
)
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from test_dispatch_effect_cut import prepared


DISPATCH = "engineering.executions.dispatch"
TOKEN = "controlled-source83-instance-token"
_NOW = datetime.strptime("2026-10-11T12:00:00.000000Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(
    tzinfo=timezone.utc
)


class _FixedAdmissionDateTime(datetime):
    """Freeze only the adapter's wall clock; monotonic token expiry stays real."""

    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is None else _NOW.astimezone(tz)


def _freeze_admission_clock(monkeypatch):
    monkeypatch.setattr(
        "ordessa_system_access_bindings.engineering.datetime", _FixedAdmissionDateTime
    )


class _Records:
    """Small native digest peer; it does not report native completion."""

    acp_turn_evidence_max_bytes = MAX_EXECUTION_RECEIPT_BYTES

    def __init__(self):
        self.prompt_capacity_calls = []

    def validate_acp_prompt_capacity(self, unit_ref, params):
        self.prompt_capacity_calls.append((dict(unit_ref), params))
        return None

    @staticmethod
    def acp_prompt_input_digest(unit_ref, params):
        raw = canonical_bytes(params)
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, prompt_digest):
        return "sha256:" + hashlib.sha256(
            canonical_bytes([unit_ref, operation_ref, prompt_digest])
        ).hexdigest()

    @staticmethod
    def query_acp_turn(*_args, **_kwargs):
        raise AssertionError("controlled handoff test must not claim a native receipt")


class _SyntheticCaptureRecords(_Records):
    """Explicit synthetic receipt peer for the dispatch continuation test."""

    @staticmethod
    def query_acp_turn(unit_ref, operation_ref, invocation, *, input_digest,
                       expected_prompt_input_digest):
        assert invocation.facts["inputDigest"] == input_digest
        return {
            "contractVersion": "unit-acp-turn/1",
            "unitRef": dict(unit_ref),
            "operationRef": operation_ref,
            "inputDigest": expected_prompt_input_digest,
            "state": "completed",
            "revision": 1,
        }


class _SyntheticHistoryRead:
    """Test-only cold-read gate; it does not authenticate a real native source."""

    @contextmanager
    def guard_history_read(self, context, package, unit_ref):
        assert context.scope == package.scope
        assert unit_ref["unitId"] == "synthetic-unit"
        yield {"synthetic_native_facts": True}


class _UnitPeer:
    """Controlled synchronous prompt entry with a real SDK target Thread."""

    def __init__(self, records, target, *, fixed_session="fixed-session", wait_response=False,
                 fail_after_write=False, pause_before_write=False, cancel_before_write=False):
        self.records = records
        self.effect_write_thread = target
        self.fixed_session = fixed_session
        self.fixed_factory = None
        self.messages = Queue()
        self.write_done = Event()
        self.response_wait = Event()
        self.release_response = Event()
        self.wait_response = wait_response
        self.fail_after_write = fail_after_write
        self.prompt_count = 0
        self.pause_before_write = pause_before_write
        self.cancel_before_write = cancel_before_write
        self.guard_received = Event()
        self.allow_write = Event()
        if not pause_before_write:
            self.allow_write.set()

    def require_effect_write_guard(self, factory):
        if factory is not self.fixed_factory:
            raise RuntimeError("the fixed original operation guard is required")

    @property
    def projection(self):
        return SimpleNamespace(read_session=lambda _unit: SimpleNamespace(
            native_facts={"sessionId": self.fixed_session}
        ))

    def prompt(self, unit_ref, lease, *, operation_ref, timeout=60, **params):
        # Matches the original prompt owner: the fixed factory is invoked
        # synchronously on the caller before the SDK target receives the guard.
        self.prompt_count += 1
        input_digest = self.records.acp_prompt_input_digest(unit_ref, params)
        guard = self.fixed_factory(unit_ref, operation_ref, input_digest, params)
        frame = (json.dumps({
            "jsonrpc": "2.0", "id": "source83-request",
            "method": "session/prompt", "params": params,
        }, separators=(",", ":")) + "\n").encode()
        self.messages.put((guard, frame))
        self.guard_received.set()
        if not self.write_done.wait(timeout):
            raise TimeoutError("controlled SDK byte cut did not finish")
        self.response_wait.set()
        if self.cancel_before_write:
            raise TimeoutError("controlled target cancelled before writing")
        if self.wait_response and not self.release_response.wait(timeout):
            raise TimeoutError("controlled SDK response wait was not released")
        if self.fail_after_write:
            raise TimeoutError("controlled peer leaves send outcome unknown")
        # This is deliberately not treated as an authenticated native receipt.
        return {"controlled_peer": True}


def _wire_scope(scope):
    return WireScope(scope.realm_id, scope.project_id)


def _make_access(scope):
    authority = InstanceAccessAuthority(
        lambda: TOKEN,
        principal_id="source83-instance",
        legacy_principal=None,
        grants=(AccessGrant(_wire_scope(scope), (DISPATCH,)),),
    )
    caller = authority.authenticate(f"Bearer {TOKEN}")
    return authority, caller, EngineeringCommandAccess(authority)


def _sdk_target(unit, write_fd, *, errors):
    """Run the actual EffectWriteGuard on its exact target Thread."""

    def run():
        try:
            guard, frame = unit.messages.get(timeout=4)
            if not unit.allow_write.wait(4):
                raise TimeoutError("controlled SDK write gate was not released")

            async def bounded_write():
                async with guard.hold(frame):
                    if unit.cancel_before_write:
                        asyncio.current_task().cancel()
                        await asyncio.sleep(0)
                    # The only emitted bytes are this controlled local frame.
                    os.write(write_fd, frame)
                # Re-entering the same public byte guard must not grant a
                # second write after the one-use handoff was consumed.
                with pytest.raises(ApplicationError):
                    async with guard.hold(frame):
                        os.write(write_fd, frame)

            asyncio.run(bounded_write())
        except BaseException as exc:
            errors.append(exc)
        finally:
            unit.write_done.set()

    return run


def _prepare_real_handoff(tmp_path, monkeypatch):
    from test_implementation_dispatch import NOW, UNIT, _setup

    library, factory, owner, _old_execution, _calls, grant, package, _intent = _setup(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "ordessa_engineering.application.usecases.support.clock.utc_now", lambda: NOW
    )
    _freeze_admission_clock(monkeypatch)
    authority, caller, access = _make_access(package.scope)
    owner.access = access
    records = _Records()
    params = {"sessionId": "fixed-session", "prompt": []}
    raw = canonical_bytes(params)
    prompt_digest = Digest("sha256", hashlib.sha256(raw).hexdigest())
    prompt_ref = owner.blobs.put_verified(raw, prompt_digest, "application/json")
    operation_ref = "source83-original-operation"
    with factory.begin(package.scope) as uow:
        control = uow.authorization.get_control(grant.ref)
        binding = DispatchBinding(
            package.scope, "run-1", "source_review", 1, 1, package.ref,
            grant.ref, grant.intent.digest, control["version"],
            (("edit_repository", "effect-action"),), canonical_bytes(UNIT),
            operation_ref, prompt_ref, prompt_digest,
            records.acp_turn_query_digest(UNIT, operation_ref, "sha256:" + prompt_digest.hex),
            ("submission",),
        )
        from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
        encoded = encode_dispatch(binding)
        uow.authorization.consume_action(
            grant.ref, action="edit_repository", action_instance_id="effect-action",
            target_digest=binding.digest, now=NOW,
        )
        uow.dispatch.reserve(
            binding.run_id, binding.step_id, binding.attempt, package.scope,
            encoded, Digest("sha256", hashlib.sha256(encoded).hexdigest()), operation_ref,
        )
        uow.dispatch.transition(
            binding.run_id, binding.step_id, binding.attempt, package.scope,
            expected_version=0, fence=binding.fence, phase="possibly_written",
        )
        uow.commit()
    return library, factory, owner, grant, package, authority, caller, access, records


def _prepare_unreserved_dispatch(tmp_path, monkeypatch):
    from test_implementation_dispatch import NOW, _setup

    library, factory, owner, _old_execution, _calls, grant, package, _intent = _setup(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "ordessa_engineering.application.usecases.support.clock.utc_now", lambda: NOW
    )
    _freeze_admission_clock(monkeypatch)
    authority, caller, access = _make_access(package.scope)
    owner.access = access
    return library, factory, owner, grant, package, authority, caller, access, _Records()


def test_original_engineering_uow_cut_consumes_handoff_on_target_thread(
    tmp_path, monkeypatch
):
    library, factory, owner, grant, package, authority, caller, access, records = (
        _prepare_real_handoff(tmp_path, monkeypatch)
    )
    read_fd, write_fd = os.pipe()
    errors = []
    unit = _UnitPeer(records, None)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-target")
    unit.effect_write_thread = sdk
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-write", trace_id="source83-write",
        ) as context:
            fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
            unit.fixed_factory = fixed
            execution = RecordedDispatchExecution(
                records, unit, object(), owner.blobs,
                effect_write_guard_factory=fixed,
            )
            with owner.factory.begin(package.scope, "read") as uow:
                row = uow.dispatch.get("run-1", "source_review", 1, package.scope)
                from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
                binding = decode_dispatch(row["binding_bytes"])
            assert row["dispatch_phase"] == "possibly_written"
            original_consume = access.consume_effect_write

            @contextmanager
            def exact_consume(token, actual_context, *, invocation_key, action_instances):
                assert actual_context is context
                assert invocation_key == bytes.fromhex(binding.digest.hex)
                assert type(invocation_key) is bytes and len(invocation_key) == 32
                assert action_instances == binding.action_instances
                with original_consume(
                    token, actual_context,
                    invocation_key=invocation_key,
                    action_instances=action_instances,
                ):
                    yield

            access.consume_effect_write = exact_consume
            with execution.guard_effect_handoff(
                context, binding, access=access, timeout=4
            ):
                receipt = execution.send(binding, timeout=4)
                assert receipt == {"controlled_peer": True}
                assert records.prompt_capacity_calls == [
                    (dict(_unit_value()), {"sessionId": "fixed-session", "prompt": []})
                ]
                assert unit.response_wait.is_set()
            access.require(context, DISPATCH)

        sdk.join(timeout=4)
        assert not sdk.is_alive()
        assert errors == []
        frame = os.read(read_fd, 4096)
        parsed = json.loads(frame)
        assert parsed["method"] == "session/prompt"
        assert parsed["params"]["sessionId"] == "fixed-session"
        assert len(bytes.fromhex(binding.digest.hex)) == 32
        assert binding.action_instances == (("edit_repository", "effect-action"),)
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
            assert uow.dispatch.get("run-1", "source_review", 1, package.scope)[
                "dispatch_phase"
            ] == "possibly_written"
    finally:
        unit.release_response.set()
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_revocation_completes_during_response_wait_without_refund_or_replay(
    tmp_path, monkeypatch
):
    library, factory, owner, grant, package, authority, caller, access, records = (
        _prepare_unreserved_dispatch(tmp_path, monkeypatch)
    )
    read_fd, write_fd = os.pipe()
    errors = []
    unit = _UnitPeer(records, None, wait_response=True)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-revoke")
    unit.effect_write_thread = sdk
    sdk.start()
    caller_errors = []
    caller_ready = Event()
    caller_finished = Event()

    def dispatch_caller():
        try:
            with access.admit(
                caller, _wire_scope(package.scope), DISPATCH,
                request_id="source83-revoke-wait", trace_id="source83-revoke-wait",
            ) as context:
                fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
                unit.fixed_factory = fixed
                owner.execution = RecordedDispatchExecution(
                    records, unit, object(), owner.blobs,
                    effect_write_guard_factory=fixed,
                )
                caller_ready.set()
                owner.dispatch(
                    "run-1", "source_review", 1, _unit_value(),
                    {"prompt": "controlled revoke"}, ("edit_repository",), context,
                )
        except BaseException as exc:
            caller_errors.append(exc)
        finally:
            caller_finished.set()

    caller_thread = Thread(target=dispatch_caller, name="source83-command-caller")
    caller_thread.start()
    try:
        assert caller_ready.wait(3)
        reached_wait = unit.response_wait.wait(4)
        if not reached_wait and caller_finished.is_set():
            error_codes = [getattr(exc, "code", type(exc).__name__) for exc in caller_errors]
            pytest.fail(f"dispatch exited before response wait; caller errors: {error_codes}")
        assert reached_wait, "write did not reach the unlocked response wait"
        # `handoff_effect_write` has released the original authority lease here;
        # revocation must finish while the caller awaits the controlled peer.
        authority.revoke()
        unit.release_response.set()
        caller_thread.join(timeout=4)
        sdk.join(timeout=4)
        assert not caller_thread.is_alive() and not sdk.is_alive()
        assert len(caller_errors) == 1
        assert isinstance(caller_errors[0], ApplicationError)
        # The handoff token was already consumed, but revocation ended the
        # parent admission. The resumed owner refuses its UNKNOWN transition
        # through the original command-access check.
        assert caller_errors[0].code == "ACCESS_AUTHORITY_UNAVAILABLE"
        assert errors == []
        frame = os.read(read_fd, 4096)
        assert b"session/prompt" in frame
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            row = uow.dispatch.get("run-1", "source_review", 1, package.scope)
            assert row["dispatch_phase"] == "possibly_written"
            # This revokes the W10 credential epoch only. The separate
            # Engineering approval control remains granted.
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
        # Existing action consumption remains immutable; no refund or replay
        # path is introduced by a lost/revoked response.
        assert library._connection.execute(
            "SELECT count(*) FROM eng_action_consumptions"
        ).fetchone()[0] == 1
    finally:
        unit.release_response.set()
        if caller_thread.is_alive():
            caller_thread.join(timeout=4)
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_credential_epoch_revoked_before_target_consume_never_writes(
    tmp_path, monkeypatch
):
    library, factory, owner, grant, package, authority, caller, access, records = (
        _prepare_real_handoff(tmp_path, monkeypatch)
    )
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    errors = []
    unit = _UnitPeer(records, None, pause_before_write=True)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-epoch")
    unit.effect_write_thread = sdk
    sdk.start()
    caller_errors = []

    def caller_send():
        try:
            with access.admit(
                caller, _wire_scope(package.scope), DISPATCH,
                request_id="source83-epoch", trace_id="source83-epoch",
            ) as context:
                fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
                unit.fixed_factory = fixed
                execution = RecordedDispatchExecution(
                    records, unit, object(), owner.blobs,
                    effect_write_guard_factory=fixed,
                )
                with execution.guard_effect_handoff(
                    context, _dispatch_binding(factory, package.scope),
                    access=access, timeout=4,
                ):
                    execution.send(_dispatch_binding(factory, package.scope), timeout=4)
        except BaseException as exc:
            caller_errors.append(exc)

    caller_thread = Thread(target=caller_send, name="source83-epoch-caller")
    caller_thread.start()
    try:
        assert unit.guard_received.wait(3), "fixed SDK guard was not prepared on caller thread"
        authority.revoke()
        unit.allow_write.set()
        caller_thread.join(timeout=4)
        sdk.join(timeout=4)
        assert not caller_thread.is_alive() and not sdk.is_alive()
        assert len(caller_errors) == 1
        assert isinstance(caller_errors[0], ApplicationError)
        assert caller_errors[0].code == "ACCESS_DENIED"
        assert len(errors) == 1 and isinstance(errors[0], ApplicationError)
        with pytest.raises(BlockingIOError):
            os.read(read_fd, 4096)
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            assert uow.dispatch.get("run-1", "source_review", 1, package.scope)[
                "dispatch_phase"
            ] == "possibly_written"
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
        assert library._connection.execute(
            "SELECT count(*) FROM eng_action_consumptions"
        ).fetchone()[0] == 1
    finally:
        unit.allow_write.set()
        if caller_thread.is_alive():
            caller_thread.join(timeout=4)
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_fixed_factory_accepts_fresh_admission_and_refuses_ended_context(
    tmp_path, monkeypatch
):
    """The fixed writer is reusable; each handoff must use its live admission."""
    library, factory, owner, _grant, package, _authority, caller, access, records = (
        _prepare_real_handoff(tmp_path, monkeypatch)
    )
    binding = _dispatch_binding(factory, package.scope)
    read_fd, write_fd = os.pipe()
    errors = []
    unit = _UnitPeer(records, None)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-fresh-admission")
    unit.effect_write_thread = sdk
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-first-admission", trace_id="source83-first-admission",
        ) as first_context:
            fixed = engineering_effect_write_guard_factory(
                owner, first_context, records, owner.blobs
            )
            unit.fixed_factory = fixed
        execution = RecordedDispatchExecution(
            records, unit, object(), owner.blobs,
            effect_write_guard_factory=fixed,
        )

        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-second-admission", trace_id="source83-second-admission",
        ) as current_context:
            with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
                with execution.guard_effect_handoff(
                    first_context, binding, access=access, timeout=4
                ):
                    pytest.fail("an ended admission cannot be reused by the fixed factory")
            with execution.guard_effect_handoff(
                current_context, binding, access=access, timeout=4
            ):
                assert execution.send(binding, timeout=4) == {"controlled_peer": True}
            access.require(current_context, DISPATCH)

        sdk.join(timeout=4)
        assert not sdk.is_alive()
        assert errors == []
        assert b"session/prompt" in os.read(read_fd, 4096)
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            assert uow.dispatch.get("run-1", "source_review", 1, package.scope)[
                "dispatch_phase"
            ] == "possibly_written"
    finally:
        unit.release_response.set()
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_target_cancellation_exits_original_guard_without_stale_lease_or_write(
    tmp_path, monkeypatch
):
    library, factory, owner, grant, package, _authority, caller, access, records = (
        _prepare_unreserved_dispatch(tmp_path, monkeypatch)
    )
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    errors = []
    unit = _UnitPeer(records, None, cancel_before_write=True)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-cancel")
    unit.effect_write_thread = sdk
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-cancel", trace_id="source83-cancel",
        ) as context:
            fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
            unit.fixed_factory = fixed
            owner.execution = RecordedDispatchExecution(
                records, unit, object(), owner.blobs,
                effect_write_guard_factory=fixed,
            )
            result = owner.dispatch(
                "run-1", "source_review", 1, _unit_value(),
                {"prompt": "controlled cancellation"}, ("edit_repository",), context,
            )
            assert result["phase"] == "unknown"
            access.require(context, DISPATCH)

        sdk.join(timeout=4)
        assert not sdk.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], asyncio.CancelledError)
        with pytest.raises(BlockingIOError):
            os.read(read_fd, 4096)
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            assert uow.dispatch.get("run-1", "source_review", 1, package.scope)[
                "dispatch_phase"
            ] == "unknown"
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
        assert library._connection.execute(
            "SELECT count(*) FROM eng_action_consumptions"
        ).fetchone()[0] == 1
    finally:
        unit.release_response.set()
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_handoff_preflight_refuses_foreign_context_scope_operation_and_actions(
    tmp_path, monkeypatch
):
    library, factory, owner, _grant, package, _authority, caller, access, records = (
        _prepare_real_handoff(tmp_path, monkeypatch)
    )
    stop = Event()
    sdk = Thread(target=lambda: stop.wait(3), name="source83-unentered-target")
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-refusal", trace_id="source83-refusal",
        ) as context:
            fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
            unit = _UnitPeer(records, sdk)
            unit.fixed_factory = fixed
            execution = RecordedDispatchExecution(
                records, unit, object(), owner.blobs,
                effect_write_guard_factory=fixed,
            )
            with factory.begin(package.scope, "read") as uow:
                from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
                binding = decode_dispatch(uow.dispatch.get(
                    "run-1", "source_review", 1, package.scope
                )["binding_bytes"])

            foreign_context = replace(context, request_id="source83-foreign")
            with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
                with execution.guard_effect_handoff(
                    foreign_context, binding, access=access, timeout=2
                ):
                    pytest.fail("a copied/replaced command context cannot issue a handoff")

            wrong_scope = EngineeringScope(package.scope.realm_id, "other-project")
            wrong_package = replace(binding.package_ref, project_id=wrong_scope.project_id)
            wrong_approval = replace(binding.approval_ref, project_id=wrong_scope.project_id)
            wrong_scope_binding = replace(
                binding, scope=wrong_scope, package_ref=wrong_package,
                approval_ref=wrong_approval,
            )
            with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_HANDOFF_BINDING_INVALID"):
                with execution.guard_effect_handoff(
                    context, wrong_scope_binding, access=access, timeout=2
                ):
                    pytest.fail("a handoff cannot cross the selected Engineering scope")

            for wrong in (
                replace(binding, execution_operation_ref="another-operation"),
                replace(binding, action_instances=(("run_checks", "other-instance"),)),
            ):
                with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_BINDING_MISMATCH"):
                    with execution.guard_effect_handoff(
                        context, wrong, access=access, timeout=2
                    ):
                        pytest.fail("only the exact persisted operation and actions may hand off")

            assert sdk.is_alive()
            assert unit.messages.empty()
    finally:
        stop.set()
        sdk.join(timeout=3)
        assert not sdk.is_alive()
        assert not library._connection.in_transaction
        library.close()


def test_unknown_send_keeps_original_debit_and_retry_does_not_send_again(
    tmp_path, monkeypatch
):
    from test_implementation_dispatch import NOW, UNIT, _setup

    library, factory, owner, _old_execution, _calls, grant, package, _intent = _setup(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "ordessa_engineering.application.usecases.support.clock.utc_now", lambda: NOW
    )
    _freeze_admission_clock(monkeypatch)
    authority, caller, access = _make_access(package.scope)
    owner.access = access
    records = _Records()
    read_fd, write_fd = os.pipe()
    errors = []
    unit = _UnitPeer(records, None, fail_after_write=True)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-unknown")
    unit.effect_write_thread = sdk
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-unknown", trace_id="source83-unknown",
        ) as context:
            fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
            unit.fixed_factory = fixed
            owner.execution = RecordedDispatchExecution(
                records, unit, object(), owner.blobs,
                effect_write_guard_factory=fixed,
            )
            first = owner.dispatch(
                "run-1", "source_review", 1, _unit_value(),
                {"prompt": "controlled uncertainty"}, ("edit_repository",), context,
            )
            assert first["phase"] == "unknown"
            second = owner.dispatch(
                "run-1", "source_review", 1, _unit_value(),
                {"prompt": "controlled uncertainty"}, ("edit_repository",), context,
            )
            assert second["phase"] == "unknown"
            assert unit.prompt_count == 1
            access.require(context, DISPATCH)

        sdk.join(timeout=4)
        assert not sdk.is_alive()
        assert errors == []
        frame = os.read(read_fd, 4096)
        assert b"controlled uncertainty" in frame
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            row = uow.dispatch.get("run-1", "source_review", 1, package.scope)
            assert row["dispatch_phase"] == "unknown"
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
        assert library._connection.execute(
            "SELECT count(*) FROM eng_action_consumptions"
        ).fetchone()[0] == 1
    finally:
        unit.release_response.set()
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def test_owner_dispatch_uses_private_receipt_continuation_for_canonical_send(
    tmp_path, monkeypatch
):
    """A controlled receipt traverses the original private continuation only."""
    from test_implementation_dispatch import NOW, _setup

    library, factory, owner, _old_execution, _calls, grant, package, _intent = _setup(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "ordessa_engineering.application.usecases.support.clock.utc_now", lambda: NOW
    )
    _freeze_admission_clock(monkeypatch)
    authority, caller, access = _make_access(package.scope)
    owner.access = access
    records = _SyntheticCaptureRecords()
    read_fd, write_fd = os.pipe()
    errors = []
    unit = _UnitPeer(records, None)
    sdk = Thread(target=_sdk_target(unit, write_fd, errors=errors), name="source83-sdk-success")
    unit.effect_write_thread = sdk
    sdk.start()
    try:
        with access.admit(
            caller, _wire_scope(package.scope), DISPATCH,
            request_id="source83-completed", trace_id="source83-completed",
        ) as context:
            fixed = engineering_effect_write_guard_factory(owner, context, records, owner.blobs)
            unit.fixed_factory = fixed
            owner.history_sources = _SyntheticHistoryRead()
            owner.execution = RecordedDispatchExecution(
                records, unit, object(), owner.blobs,
                query_factory=lambda binding: SimpleNamespace(facts={
                    "inputDigest": binding.expected_query_digest,
                }),
                effect_write_guard_factory=fixed,
            )
            result = owner.dispatch(
                "run-1", "source_review", 1, _unit_value(),
                {"prompt": "controlled completed capture"}, ("edit_repository",), context,
            )
            assert result["phase"] == "completed"
            assert result["engineering_completed"] is False
            assert result["accepted"] is False
            assert result["result_blob_ref"] is not None
            # Public reconcile remains a separate operation; this successful
            # first dispatch used its private receipt continuation.
            assert unit.prompt_count == 1
            access.require(context, DISPATCH)

        sdk.join(timeout=4)
        assert not sdk.is_alive()
        assert errors == []
        assert b"controlled completed capture" in os.read(read_fd, 4096)
        assert not library._connection.in_transaction
        with factory.begin(package.scope, "read") as uow:
            row = uow.dispatch.get("run-1", "source_review", 1, package.scope)
            assert row["dispatch_phase"] == "completed"
            assert uow.authorization.get_control(grant.ref)["state"] == "granted"
        assert library._connection.execute(
            "SELECT count(*) FROM eng_action_consumptions"
        ).fetchone()[0] == 1
    finally:
        unit.release_response.set()
        if sdk.is_alive():
            sdk.join(timeout=4)
        os.close(read_fd)
        os.close(write_fd)
        library.close()


def _unit_value():
    from test_implementation_dispatch import UNIT
    return UNIT


def _dispatch_binding(factory, scope):
    with factory.begin(scope, "read") as uow:
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        return decode_dispatch(uow.dispatch.get(
            "run-1", "source_review", 1, scope
        )["binding_bytes"])
