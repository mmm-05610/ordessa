"""A verifiable native terminal failure closes only its own Work invocation.

These tests use the real schema-17 Engineering library and Work chain. The
transport is a labelled double: it creates a receipt in the original ACP
records shape and never opens a process or network connection.
"""
import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_infrastructure.encoding import canonical_bytes
import test_work_invoke_generation as work_invoke_generation
from test_work_invoke_generation import (
    ACTION,
    STEP,
    WORK_ID,
    _command_payload,
    _command_status,
    _invoke_generation,
    _unit_ref,
    close_chain,
    context,
)
from test_itemized_source_chain import build_itemized_chain
from test_real_source_chain import PRINCIPAL, SCOPE, run_full_chain
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16
from work_step_access_fixture import enable_controlled_work_steps


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)


def _native_digest(value):
    """Match UnitRecords' digest of the canonical ``{'value': value}`` wrapper."""
    return "sha256:" + hashlib.sha256(canonical_bytes({"value": value})).hexdigest()


def _frame(raw):
    text = json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n"
    encoded = text.encode("utf-8")
    return {
        "raw": raw,
        "frameUtf8": text,
        "frameDigest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


class _TerminalTransport:
    """Freeze and capture a native-shaped terminal receipt without sending."""

    def __init__(self, blobs, *, mode="failed", partial_text="", corrupt=None):
        self.blobs = blobs
        self.mode = mode
        self.partial_text = partial_text
        self.corrupt = corrupt
        self.sends = 0
        self._unit_ref = None
        self._params = None
        self.after_capture = None

    def freeze_input(self, unit_ref, params):
        self._unit_ref = dict(unit_ref)
        self._params = dict(params, sessionId="session-1")
        raw = canonical_bytes(self._params)
        digest_value = {
            "value": {"unitRef": self._unit_ref, "params": self._params}
        }
        return raw, Digest(
            "sha256", hashlib.sha256(canonical_bytes(digest_value)).hexdigest()
        )

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return "q" * 64

    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        from contextlib import contextmanager

        @contextmanager
        def handoff():
            yield

        return handoff()

    def send(self, binding, *, timeout=60):
        self.sends += 1
        if self.mode == "send_error":
            raise RuntimeError("controlled transport send failure")

    def capture(self, binding):
        if self.mode == "capture_error":
            raise RuntimeError("controlled transport capture failure")
        if self.mode == "missing":
            return SimpleNamespace(blob_ref=None, state="failed")

        receipt = self._receipt(binding)
        raw = canonical_bytes(receipt)
        blob_ref = self.blobs.put_verified(
            raw,
            Digest("sha256", hashlib.sha256(raw).hexdigest()),
            "application/json",
        )
        if self.after_capture is not None:
            self.after_capture()
        return SimpleNamespace(blob_ref=blob_ref, state=receipt["state"])

    def _receipt(self, binding):
        unit_ref = dict(self._unit_ref)
        params = dict(self._params)
        operation_ref = binding.execution_operation_ref
        rpc_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": params,
        }
        request = _frame(rpc_request)
        error_response = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32603, "message": "controlled failure"},
        }
        events = []
        if self.partial_text:
            events.append(
                {
                    "sequence": 1,
                    "sessionMatched": True,
                    "raw": {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "session-1",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": self.partial_text},
                            },
                        },
                    },
                }
            )
        if self.mode == "unknown":
            state = "unknown"
            response = None
            summary = None
        else:
            state = "failed"
            response = error_response
            events.append(
                {
                    "sequence": len(events) + 1,
                    "sessionMatched": False,
                    "raw": error_response,
                }
            )
            text = "".join(
                event["raw"].get("params", {})
                .get("update", {})
                .get("content", {})
                .get("text", "")
                for event in events
                if event["sessionMatched"]
            )
            summary = {
                "text": text,
                "textDigest": _native_digest(text),
                "stopReason": None,
                "eventCount": len(events),
                "knownRemoteFailure": True,
                "successfulRpcResponse": False,
                "modelQualityVerified": False,
            }
        receipt = {
            "contractVersion": "unit-acp-turn/1",
            "operationRef": operation_ref,
            "unitRef": unit_ref,
            "unitIntentDigest": hashlib.sha256(b"controlled Unit intent").hexdigest(),
            "nativeBinding": {"sessionId": "session-1"},
            "input": {"unitRef": unit_ref, "params": params},
            "inputDigest": _native_digest({"unitRef": unit_ref, "params": params}),
            "state": state,
            "revision": 4,
            "request": request,
            "events": events,
            "eventsDigest": _native_digest(events),
            "response": response,
            "responseDigest": _native_digest(response),
            "observationAssociation": "session-request-window",
            "summary": summary,
        }
        self._corrupt_receipt(receipt)
        return receipt

    def _corrupt_receipt(self, receipt):
        """Make independently mismatched evidence for the negative cases."""
        if self.corrupt == "unit":
            receipt["unitRef"]["unitId"] = "other-unit"
            receipt["input"]["unitRef"]["unitId"] = "other-unit"
            receipt["inputDigest"] = _native_digest(receipt["input"])
        elif self.corrupt == "operation":
            receipt["operationRef"] = "other-operation"
        elif self.corrupt in {"input", "session"}:
            new_params = dict(receipt["input"]["params"])
            if self.corrupt == "input":
                new_params["prompt"] = str(new_params.get("prompt", "")) + " altered"
            else:
                new_params["sessionId"] = "other-session"
                receipt["nativeBinding"]["sessionId"] = "other-session"
                for event in receipt["events"]:
                    event_params = event["raw"].get("params")
                    if isinstance(event_params, dict):
                        event_params["sessionId"] = "other-session"
                        event["sessionMatched"] = True
                receipt["eventsDigest"] = _native_digest(receipt["events"])
            receipt["input"]["params"] = new_params
            receipt["inputDigest"] = _native_digest(receipt["input"])
            receipt["request"] = _frame(
                dict(receipt["request"]["raw"], params=new_params)
            )
        elif self.corrupt == "frame":
            receipt["request"]["frameUtf8"] += " "


def _start_case(tmp_path, *, mode="failed", partial_text="", corrupt=None):
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library, backup_path=(tmp_path / "schema16.backup.sqlite").resolve())
    chain = run_full_chain(env)
    transport = _TerminalTransport(
        env.blobs, mode=mode, partial_text=partial_text, corrupt=corrupt
    )
    env.service.attach_declared_generation_handles(
        blobs=env.blobs,
        execution=transport,
        unit_ref_resolver=lambda context, binding, profile_ref: _unit_ref(),
    )
    return env, chain, transport


def _operation(env, request_id):
    return asyncio.run(
        env.service.query(
            "engineering.operations.get",
            {"request_id": request_id},
            context("terminal-failure-cold-read"),
        )
    )


def _package_count(env):
    connection = sqlite3.connect(env.library.path)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM eng_packages WHERE package_id=?",
            ("generated-package-1",),
        ).fetchone()[0]
    finally:
        connection.close()


def _bind_real_work_access(env, *, token_box, rotate_after_child=None):
    """Use the real issued authority only at Work's parent/child boundary."""
    wire_scope = WireScope(SCOPE.realm_id, SCOPE.project_id)
    authority = InstanceAccessAuthority(
        lambda: token_box[0],
        principal_id=PRINCIPAL,
        legacy_principal=None,
        grants=(AccessGrant(
            wire_scope,
            ("engineering.work.invoke", "engineering.work.get",
             "engineering.executions.dispatch"),
        ),),
    )
    caller = authority.authenticate(f"Bearer {token_box[0]}")
    access = EngineeringCommandAccess(authority)
    env.service._work_step_admission = (
        lambda context, operation, request_id: access.admit_work_step(
            context, operation, request_id=request_id
        )
    )

    if rotate_after_child is not None:
        original_guard = authority.guard

        def rotate_after_dispatch_guard(principal, scope, operation):
            from contextlib import contextmanager

            @contextmanager
            def guarded():
                with original_guard(principal, scope, operation):
                    yield
                if operation == "engineering.executions.dispatch" and rotate_after_child[0]:
                    token_box[0] += "-rotated"
                    rotate_after_child[0] = False

            return guarded()

        # Rotate only after the child lease exits successfully, so the test
        # isolates the parent-grant revalidation performed on resume.
        authority.guard = rotate_after_dispatch_guard
    return access, caller, wire_scope


def _invoke_under_real_parent(env, chain, transport, access, caller, wire_scope,
                              request_id, current_parent, monkeypatch):
    original_context = work_invoke_generation.context

    def selected_context(request_id_value):
        if request_id_value == "invoke-generation":
            return current_parent[0]
        return original_context(request_id_value)

    monkeypatch.setattr(work_invoke_generation, "context", selected_context)
    with access.admit(
        caller,
        wire_scope,
        "engineering.work.invoke",
        request_id=request_id,
        trace_id="terminal-failure-real-access",
    ) as parent_context:
        current_parent[0] = parent_context
        result = _invoke_generation(env, chain, transport)
        access.require(parent_context, "engineering.work.invoke")
        return result


def test_native_terminal_failure_closes_parent_without_a_package_and_reentry_is_safe(tmp_path):
    """A matched final RPC error may be reported, never turned into success."""
    env, _chain, transport = _start_case(
        tmp_path, partial_text="partial answer before provider failure"
    )
    try:
        first = _invoke_generation(env, _chain, transport)
        payload = _command_payload(first) or {}
        assert _command_status(first) == "rejected", payload
        assert payload.get("state") == "failed", payload
        generation = [
            step for step in payload.get("steps", [])
            if step.get("business", {}).get("error_code")
                == "WORK_ACTION_GENERATION_NATIVE_FAILED"
        ]
        assert len(generation) == 1, payload
        business = generation[0]["business"]
        assert business["state"] == "failed"
        assert business["partial_output_observed"] is True
        assert business["completion_semantics"] == (
            "native_failure_recorded_side_effects_unconfirmed"
        )
        assert business["run_association"]["phase"] == "failed"
        assert "result_blob_ref" in business and business["result_blob_ref"]
        assert transport.sends == 1
        assert _package_count(env) == 0

        operation = _operation(env, "invoke-generation")
        assert operation["journal_state"] == "rejected", operation
        assert operation["state"] == "failed", operation
        operation_id = operation["operation_id"]
        work = asyncio.run(
            env.service.query(
                "engineering.work.get",
                {"work_id": WORK_ID},
                context("terminal-failure-work-cold-read"),
            )
        )
        assert work["generation_dispatch"]["phase"] == "failed", work

        replay = _invoke_generation(env, _chain, transport)
        assert _command_status(replay) == "rejected"
        assert transport.sends == 1
        assert _package_count(env) == 0

        # Reopen the same SQLite database and query the durable command row
        # through the application read use case, after all re-entry checks.
        from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
            EngineeringLibrary,
        )
        from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import (
            SQLiteUoWFactory,
        )
        from ordessa_engineering.application.usecases.queries.commands import read_operation

        path = env.library.path
        env.library.close()
        reopened = EngineeringLibrary.open(path, library_id="local-source-chain")
        try:
            reopened_factory = SQLiteUoWFactory(reopened)
            with reopened_factory.begin(SCOPE, "read") as uow:
                cold = read_operation(uow, context("terminal-reopen-read"),
                                      "invoke-generation")
            assert cold["operation_id"] == operation_id, cold
            assert cold["state"] == "failed" and cold["journal_state"] == "rejected", cold
            assert cold["business"]["state"] == "failed", cold
            assert cold["business"]["failed_step"] == "draft", cold
            assert cold["retry_allowed"] is False, cold
        finally:
            reopened.close()
    finally:
        close_chain(env)


@pytest.mark.parametrize("corrupt", ["unit", "operation", "input", "session", "frame"])
def test_mismatched_native_failure_evidence_keeps_parent_pending(tmp_path, corrupt):
    env, _chain, transport = _start_case(tmp_path, corrupt=corrupt)
    try:
        with pytest.raises(ApplicationError):
            _invoke_generation(env, _chain, transport)
        assert transport.sends == 1
        operation = _operation(env, "invoke-generation")
        assert operation["journal_state"] == "pending", operation
        assert operation["state"] == "unknown", operation
        work = asyncio.run(
            env.service.query(
                "engineering.work.get",
                {"work_id": WORK_ID},
                context("mismatched-failure-work-cold-read"),
            )
        )
        assert work["generation_dispatch"]["phase"] == "failed", work
        replay = _invoke_generation(env, _chain, transport)
        assert _command_status(replay) == "pending"
        assert transport.sends == 1
    finally:
        close_chain(env)


@pytest.mark.parametrize("mode", ["missing", "unknown", "send_error", "capture_error"])
def test_unproven_or_unresolved_native_outcome_stays_pending_and_never_replays(tmp_path, mode):
    env, _chain, transport = _start_case(tmp_path, mode=mode)
    try:
        with pytest.raises((ApplicationError, RuntimeError)):
            _invoke_generation(env, _chain, transport)
        operation = _operation(env, "invoke-generation")
        assert operation["journal_state"] == "pending", operation
        assert operation["state"] == "unknown", operation
        work = asyncio.run(
            env.service.query(
                "engineering.work.get",
                {"work_id": WORK_ID},
                context("unresolved-failure-work-cold-read"),
            )
        )
        assert work["generation_dispatch"]["phase"] == "unknown", work
        replay = _invoke_generation(env, _chain, transport)
        assert _command_status(replay) == "pending"
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_terminal_failure_uses_real_work_invoke_and_dispatch_grants_and_new_parent_request_does_not_resend(
    tmp_path, monkeypatch
):
    env, chain, transport = _start_case(
        tmp_path, partial_text="partial output before final provider error"
    )
    token_box = ["controlled-terminal-failure-token"]
    access, caller, wire_scope = _bind_real_work_access(env, token_box=token_box)
    current_parent = [None]
    try:
        first = _invoke_under_real_parent(
            env, chain, transport, access, caller, wire_scope,
            "invoke-generation", current_parent, monkeypatch,
        )
        assert _command_status(first) == "rejected"
        assert _operation(env, "invoke-generation")["journal_state"] == "rejected"

        # A distinct parent request reuses the immutable Work/step/attempt
        # failure view; the original effect is not sent a second time.
        try:
            second = _invoke_under_real_parent(
                env, chain, transport, access, caller, wire_scope,
                "invoke-generation-other", current_parent, monkeypatch,
            )
        except ApplicationError as error:
            # A newly derived prompt may not be byte-identical (for example,
            # because its receive-time pin changed); that is a refusal, never
            # permission to dispatch attempt one again.
            assert error.code in {
                "DISPATCH_ATTEMPT_INPUT_MISMATCH",
                "WORK_ACTION_GENERATION_INPUT_MISMATCH",
            }
        else:
            assert _command_status(second) == "rejected"
        assert transport.sends == 1
        assert _package_count(env) == 0
    finally:
        close_chain(env)


def test_parent_grant_rotation_after_child_return_keeps_invoke_pending(tmp_path, monkeypatch):
    env, _chain, transport = _start_case(tmp_path)
    token_box = ["controlled-terminal-failure-token"]
    rotate_after_child = [False]
    access, caller, wire_scope = _bind_real_work_access(
        env, token_box=token_box, rotate_after_child=rotate_after_child
    )
    transport.after_capture = lambda: rotate_after_child.__setitem__(0, True)
    current_parent = [None]
    try:
        with pytest.raises(ApplicationError) as exc:
            _invoke_under_real_parent(
                env, _chain, transport, access, caller, wire_scope,
                "invoke-generation", current_parent, monkeypatch,
            )
        assert exc.value.code == "ACCESS_DENIED"
        assert transport.sends == 1
        operation = _operation(env, "invoke-generation")
        assert operation["journal_state"] == "pending", operation
        assert operation["state"] == "unknown", operation
        work = asyncio.run(
            env.service.query(
                "engineering.work.get",
                {"work_id": WORK_ID},
                context("real-access-rotated-work-read"),
            )
        )
        assert work["generation_dispatch"]["phase"] == "failed", work
    finally:
        close_chain(env)
