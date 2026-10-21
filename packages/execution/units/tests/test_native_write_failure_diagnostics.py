"""Trusted, payload-free diagnostics for failures at the native write cut."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ordessa_environments import ProcessHandle, ProcessWaitTimeout
from ordessa_agents.harness.protocols.acp import AcpRemoteError
from ordessa_agents.harness.transport import (
    ChannelClosed,
    EffectWriteGuard,
    LostReceipt,
    RequestTimeout,
    WriterLeaseRefused,
    native_write_failure,
)
from ordessa_units.sessions.environment_channel import EnvironmentProcessChannel
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.sessions.sdk_client import SdkAcpClient


UNIT = {
    "environmentNamespace": "diagnostic-env",
    "unitId": "diagnostic-unit",
    "ownerProviderRef": {},
    "sourceRevision": "diagnostic-revision",
}
PARAMS = {
    "sessionId": "diagnostic-session",
    "prompt": [{"type": "text", "text": "private payload"}],
}
FRAME = (
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "session/prompt",
            "params": PARAMS,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    + "\n"
).encode("utf-8")
DIGEST = "sha256:" + "a" * 64


def _channel(write_stdin):
    process = MagicMock(spec=ProcessHandle)
    process.observe.return_value = SimpleNamespace(state="running")
    process.read_stderr = AsyncMock(return_value=b"")
    process.write_stdin = write_stdin
    channel = EnvironmentProcessChannel(process, name="native-write-diagnostics", managed=True)
    writer = channel.bind_writer(channel.acquire_writer())
    return channel, writer


def _guard(state, *, enter_error=None, release_error=None):
    @asynccontextmanager
    async def acquire(_identity, _deadline):
        state["guard_entered"] += 1
        if enter_error is not None:
            raise enter_error
        state["guard_held"] = True
        try:
            yield
        finally:
            state["guard_held"] = False
            state["guard_released"] += 1
            if release_error is not None:
                raise release_error

    return EffectWriteGuard(UNIT, "diagnostic-operation", DIGEST, PARAMS, acquire)


def _sdk_client(write_stdin, *, read_stdout=None):
    process = MagicMock(spec=ProcessHandle)
    process.observe.return_value = SimpleNamespace(state="running")
    if read_stdout is None:
        async def read_stdout(*, timeout=None, max_bytes=65536):
            await asyncio.Future()
    async def read_stderr(*, timeout=None, max_bytes=65536):
        return b""
    process.read_stdout = read_stdout
    process.read_stderr = read_stderr
    process.write_stdin = write_stdin
    channel = EnvironmentProcessChannel(process, name="official-sdk-diagnostic", managed=True)
    writer = channel.bind_writer(channel.acquire_writer())
    owner = object()
    client = SdkAcpClient(
        writer,
        name="official-sdk-diagnostic",
        connect=True,
        require_effect_write_guard=True,
        effect_write_owner=owner,
    )
    return client, channel, owner


def _sdk_guard(state, params, *, acquire_error=None, release_error=None):
    @asynccontextmanager
    async def acquire(_identity, _deadline):
        state["guard_entered"] += 1
        if acquire_error is not None:
            raise acquire_error
        state["guard_held"] = True
        try:
            yield
        finally:
            state["guard_held"] = False
            state["guard_released"] += 1
            if release_error is not None:
                raise release_error

    return EffectWriteGuard(UNIT, "sdk-diagnostic-operation", DIGEST, params, acquire)


def _diagnostic_params(error):
    report = native_write_failure(error)
    assert report is not None
    assert report["contract"] == "native-write-boundary/1"
    assert report["operation_ref"] == "sdk-diagnostic-operation"
    assert report["input_digest"] == DIGEST
    assert report["unit_ref_digest"] == (
        "sha256:" + hashlib.sha256(safe_json(UNIT).encode("utf-8")).hexdigest()
    )
    assert "payload" not in repr(report)
    assert "diagnostic-session" not in repr(report)
    return report


def _assert_diagnostic(error, *, phase, before_write, write_stdin, acknowledged_bytes):
    assert type(error) in (PermissionError, RuntimeError, OSError, ChannelClosed)
    report = native_write_failure(error)
    assert report == {
        "contract": "native-write-boundary/1",
        "phase": phase,
        "frame_bytes": len(FRAME),
        "before_write": before_write,
        "write_stdin": write_stdin,
        "acknowledged_bytes": acknowledged_bytes,
        "operation_ref": "diagnostic-operation",
        "input_digest": DIGEST,
        "unit_ref_digest": "sha256:" + hashlib.sha256(safe_json(UNIT).encode("utf-8")).hexdigest(),
        "frame_digest": "sha256:" + hashlib.sha256(FRAME).hexdigest(),
    }
    assert set(report) == {
        "contract",
        "phase",
        "frame_bytes",
        "before_write",
        "write_stdin",
        "acknowledged_bytes",
        "operation_ref",
        "input_digest",
        "unit_ref_digest",
        "frame_digest",
    }
    rendered = repr(report)
    assert "private payload" not in rendered
    assert "diagnostic-session" not in rendered
    assert "sk-test-native-diagnostic-secret" not in rendered


@pytest.mark.parametrize(
    ("failure_site", "expected_phase", "expected_before", "expected_stdin", "expected_ack"),
    [
        ("guard_enter", "effect_guard_acquire", "not_entered", "not_entered", None),
        ("before_write", "before_write", "entered", "not_entered", None),
        ("write_error", "write_stdin", "completed", "entered", None),
        ("partial_write", "write_stdin", "completed", "returned", len(FRAME) - 1),
        ("release_error", "guard_release", "completed", "returned", len(FRAME)),
    ],
)
def test_native_write_failure_has_trusted_payload_free_boundary_evidence(
    failure_site, expected_phase, expected_before, expected_stdin, expected_ack
):
    async def exercise():
        state = {
            "guard_entered": 0,
            "guard_held": False,
            "guard_released": 0,
            "before_write": 0,
            "write_calls": 0,
            "write_returned": None,
        }
        marker = RuntimeError(
            "private payload diagnostic-session sk-test-native-diagnostic-secret"
        )
        original_cause = ValueError("private-cause-must-not-be-copied")
        marker.__cause__ = original_cause

        async def write_stdin(data, *, timeout=None):
            assert state["guard_held"]
            assert data == FRAME
            assert timeout is not None and timeout > 0
            state["write_calls"] += 1
            if failure_site == "write_error":
                raise marker
            count = len(data) - 1 if failure_site == "partial_write" else len(data)
            state["write_returned"] = count
            return count

        channel, writer = _channel(write_stdin)
        guard = _guard(
            state,
            enter_error=marker if failure_site == "guard_enter" else None,
            release_error=marker if failure_site == "release_error" else None,
        )

        def before_write():
            state["before_write"] += 1
            if failure_site == "before_write":
                raise marker

        try:
            with pytest.raises(BaseException) as raised:
                await writer.send_frame_async(
                    FRAME,
                    before_write=before_write,
                    effect_write_guard=guard,
                )
            assert raised.value is marker or (
                failure_site == "partial_write" and isinstance(raised.value, ChannelClosed)
            )
            if failure_site != "partial_write":
                assert raised.value.__cause__ is original_cause
            _assert_diagnostic(
                raised.value,
                phase=expected_phase,
                before_write=expected_before,
                write_stdin=expected_stdin,
                acknowledged_bytes=expected_ack,
            )
            assert state["write_calls"] == (
                0 if failure_site in {"guard_enter", "before_write"} else 1
            )
            assert state["before_write"] == (0 if failure_site == "guard_enter" else 1)
            assert state["guard_entered"] == 1
            assert state["guard_released"] == (0 if failure_site == "guard_enter" else 1)
            assert channel._unresolved is True
            with pytest.raises(WriterLeaseRefused):
                await writer.send_raw_async({"method": "must-not-replay"})
        finally:
            if channel._stderr_task is not None:
                await channel._stderr_task

    asyncio.run(exercise())


def test_native_write_failure_rejects_plain_dictionary_spoof():
    forged = {
        "contract": "native-write-boundary/1",
        "phase": "write_acknowledged",
        "frame_bytes": len(FRAME),
        "before_write": "completed",
        "write_stdin": "returned",
        "acknowledged_bytes": len(FRAME),
        "operation_ref": "diagnostic-operation",
        "input_digest": DIGEST,
        "unit_ref_digest": "sha256:" + hashlib.sha256(safe_json(UNIT).encode("utf-8")).hexdigest(),
        "frame_digest": "sha256:" + hashlib.sha256(FRAME).hexdigest(),
    }
    assert native_write_failure(forged) is None
    assert native_write_failure(RuntimeError("ordinary exception")) is None
    forged_error = RuntimeError("ordinary exception")
    forged_error._ordessa_native_write_boundary = forged
    assert native_write_failure(forged_error) is None


def test_official_sdk_preserves_effect_guard_refusal_and_original_exception():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    denial = PermissionError("private payload diagnostic-session sk-test-native-diagnostic-secret")
    original_cause = ValueError("private-cause-must-not-be-copied")
    denial.__cause__ = original_cause

    async def write_stdin(data, *, timeout=None):
        writes.append(data)
        return len(data)

    client, channel, owner = _sdk_client(write_stdin)
    guard = _sdk_guard(state, PARAMS, acquire_error=denial)
    try:
        with pytest.raises(PermissionError) as raised:
            client.prompt(
                timeout=0.1,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        assert raised.value is denial
        assert raised.value.__cause__ is original_cause
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "effect_guard_acquire"
        assert report["before_write"] == "not_entered"
        assert report["write_stdin"] == "not_entered"
        assert report["acknowledged_bytes"] is None
        assert writes == []
        assert channel._unresolved is True
    finally:
        client.detach()


def test_official_sdk_response_timeout_retains_completed_write_boundary_without_retry():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []

    async def write_stdin(data, *, timeout=None):
        assert state["guard_held"]
        writes.append(data)
        return len(data)

    client, channel, owner = _sdk_client(write_stdin)
    guard = _sdk_guard(state, PARAMS)
    try:
        with pytest.raises(RequestTimeout) as raised:
            client.prompt(
                timeout=0.05,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        assert isinstance(raised.value.__cause__, TimeoutError)
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "response_wait"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "returned"
        assert report["acknowledged_bytes"] == len(writes[0])
        assert report["frame_bytes"] == len(writes[0])
        assert report["frame_digest"] == "sha256:" + hashlib.sha256(writes[0]).hexdigest()
        assert len(writes) == 1
        assert channel._unresolved is True
    finally:
        client.detach()


def test_official_sdk_received_remote_error_is_not_reported_as_response_wait():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    responses = asyncio.Queue()

    async def write_stdin(data, *, timeout=None):
        assert state["guard_held"]
        writes.append(data)
        request = json.loads(data)
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32001, "message": "controlled ACP refusal"},
        }
        responses.put_nowait((json.dumps(response, separators=(",", ":")) + "\n").encode())
        return len(data)

    async def read_stdout(*, timeout=None, max_bytes=65536):
        try:
            return await asyncio.wait_for(responses.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ProcessWaitTimeout("controlled no-frame timeout") from None

    client, channel, owner = _sdk_client(write_stdin, read_stdout=read_stdout)
    guard = _sdk_guard(state, PARAMS)
    try:
        with pytest.raises(AcpRemoteError) as raised:
            client.prompt(
                timeout=0.2,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        report = _diagnostic_params(raised.value)
        # The SDK reports a remote error after receiving its correlated response;
        # the write boundary remains acknowledged and the request is not replayed.
        assert report["phase"] == "write_acknowledged"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "returned"
        assert report["acknowledged_bytes"] == len(writes[0])
        assert report["frame_bytes"] == len(writes[0])
        assert client._last_response is not None
        assert len(writes) == 1
        assert channel._unresolved is False
    finally:
        client.detach()


def test_official_sdk_result_validation_failure_is_not_reported_as_response_wait():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    responses = asyncio.Queue()

    async def write_stdin(data, *, timeout=None):
        assert state["guard_held"]
        writes.append(data)
        request = json.loads(data)
        response = {"jsonrpc": "2.0", "id": request["id"], "result": {}}
        responses.put_nowait((json.dumps(response, separators=(",", ":")) + "\n").encode())
        return len(data)

    async def read_stdout(*, timeout=None, max_bytes=65536):
        try:
            return await asyncio.wait_for(responses.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ProcessWaitTimeout("controlled no-frame timeout") from None

    client, channel, owner = _sdk_client(write_stdin, read_stdout=read_stdout)
    guard = _sdk_guard(state, PARAMS)
    try:
        with pytest.raises(ValueError) as raised:
            client.prompt(
                timeout=0.2,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "write_acknowledged"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "returned"
        assert report["acknowledged_bytes"] == len(writes[0])
        assert report["frame_bytes"] == len(writes[0])
        assert client._last_response is not None
        assert len(writes) == 1
        assert channel._unresolved is False
    finally:
        client.detach()


def test_official_sdk_read_failure_after_full_write_preserves_cause_and_response_wait():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    write_completed = asyncio.Event()
    read_failure = OSError("controlled stdout failure with private payload")

    async def write_stdin(data, *, timeout=None):
        assert state["guard_held"]
        writes.append(data)
        write_completed.set()
        return len(data)

    async def read_stdout(*, timeout=None, max_bytes=65536):
        await write_completed.wait()
        raise read_failure

    client, channel, owner = _sdk_client(write_stdin, read_stdout=read_stdout)
    guard = _sdk_guard(state, PARAMS)
    try:
        with pytest.raises(LostReceipt) as raised:
            client.prompt(
                timeout=0.2,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        assert raised.value.__cause__ is read_failure
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "response_wait"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "returned"
        assert report["acknowledged_bytes"] == len(writes[0])
        assert report["frame_bytes"] == len(writes[0])
        assert len(writes) == 1
        assert channel._unresolved is True
    finally:
        client.detach()


def test_official_sdk_read_failure_after_full_write_preserves_cause_and_response_wait():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    write_completed = asyncio.Event()
    read_failure = OSError("controlled stdout failure with private payload")

    async def write_stdin(data, *, timeout=None):
        assert state["guard_held"]
        writes.append(data)
        write_completed.set()
        return len(data)

    async def read_stdout(*, timeout=None, max_bytes=65536):
        await write_completed.wait()
        raise read_failure

    client, channel, owner = _sdk_client(write_stdin, read_stdout=read_stdout)
    guard = _sdk_guard(state, PARAMS)
    try:
        with pytest.raises(LostReceipt) as raised:
            client.prompt(
                timeout=0.2,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        assert raised.value.__cause__ is read_failure
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "response_wait"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "returned"
        assert report["acknowledged_bytes"] == len(writes[0])
        assert report["frame_bytes"] == len(writes[0])
        assert len(writes) == 1
        assert channel._unresolved is True
    finally:
        client.detach()


def test_official_sdk_write_and_guard_release_errors_keep_failure_chain_and_boundary():
    state = {"guard_entered": 0, "guard_held": False, "guard_released": 0}
    writes = []
    write_failure = OSError("write failed private payload")
    original_cause = ValueError("private-write-cause")
    write_failure.__cause__ = original_cause
    release_failure = RuntimeError("release failed private session")

    async def write_stdin(data, *, timeout=None):
        writes.append(data)
        raise write_failure

    client, channel, owner = _sdk_client(write_stdin)
    guard = _sdk_guard(state, PARAMS, release_error=release_failure)
    try:
        with pytest.raises(BaseException) as raised:
            client.prompt(
                timeout=0.2,
                sessionId=PARAMS["sessionId"],
                prompt=PARAMS["prompt"],
                effect_write_guard=guard,
                _effect_write_owner=owner,
            )
        chain = []
        pending = [raised.value]
        while pending:
            error = pending.pop()
            if not isinstance(error, BaseException) or error in chain:
                continue
            chain.append(error)
            if error.__cause__ is not None:
                pending.append(error.__cause__)
            if error.__context__ is not None:
                pending.append(error.__context__)
        assert write_failure in chain
        assert release_failure in chain
        assert original_cause in chain
        report = _diagnostic_params(raised.value)
        assert report["phase"] == "write_stdin"
        assert report["before_write"] == "completed"
        assert report["write_stdin"] == "entered"
        assert report["acknowledged_bytes"] is None
        assert len(writes) == 1
        assert channel._unresolved is True
    finally:
        client.detach()
