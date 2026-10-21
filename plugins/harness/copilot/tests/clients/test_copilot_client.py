"""Positive and counter-example tests for the Copilot CLI consumer client.

**Fake upstream, fixture level (L1)** — every test runs against a scripted
fake peer process that reproduces the JSON-RPC record shapes pinned in N009
from the official docs and the python SDK source (protocol version 3). These
tests prove the consumer's framing/identity/typed-failure/safety behaviour
only; they are NOT real-process L2 evidence (no ``copilot`` binary is
installed or executed here) and must not be counted as upstream compatibility.

Gates covered (docs/implementation/specifications/030-native-harness-expansion/acceptance.md):

- G1  connect negotiates protocolVersion 3; out-of-range is a hard failure —
      no downgrade, no retry.
- G4  unknown events preserved verbatim; permission callbacks answered on the
      SAME JSON-RPC id; no auto-approve.
- G6  send returns a {messageId} receipt that is never completion; cancel is
      real evidence ({success, error}); no fabricated sessionId.
- G11 lost receipt: timeout keeps the ledger entry; the peer saw exactly one
      write per request (no re-send).
- G12 launch specs are refused before spawn without the documented server
      flags or with auto-approve flags; no token parameter exists.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport.channel import (
    ChannelClosed,
    LaunchSpec,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_copilot.client import (
    EVENT_TYPES,
    FAMILY_ID,
    PERMISSION_DECISIONS,
    SDK_PROTOCOL_VERSION,
    CopilotClient,
    CopilotConfigurationError,
    CopilotNotConnected,
    CopilotProtocolError,
    CopilotRpcError,
    describe,
)

PEER = textwrap.dedent(
    r"""
    import json, sys

    MODE = sys.argv[-1] if len(sys.argv) > 1 else "silent-all"
    counts = {"recv": 0}
    methods = {}
    replies = 0
    decisions = []

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def read():
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(0)
        counts["recv"] += 1
        msg = json.loads(line)
        name = msg.get("method") or "<reply>"
        methods[name] = methods.get(name, 0) + 1
        return msg

    def reply_result(msg, result):
        send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def handle(msg):
        method = msg.get("method")
        if method == "connect":
            if MODE == "legacy":
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32601, "message": "Unhandled method connect"}})
            elif MODE == "old-protocol":
                reply_result(msg, {"protocolVersion": 2, "serverVersion": "old"})
            else:
                assert msg["params"]["supportedTaskKinds"] == ["agent", "client", "shell"]
                reply_result(msg, {"protocolVersion": 3, "serverVersion": "1.0.91-fake"})
            return True
        if method == "ping":
            reply_result(msg, {"version": "1.0.90-legacy", "protocolVersion": 3})
            return True
        if method == "session.create":
            params = msg.get("params", {})
            reply_result(msg, {"sessionId": params.get("sessionId") or "sess-native-1",
                               "requestPermission": params.get("requestPermission")})
            return True
        if method == "session.resume":
            reply_result(msg, {"sessionId": msg["params"]["sessionId"], "resumed": True})
            return True
        if method == "session.abort":
            reply_result(msg, {"success": True, "error": None})
            return True
        return False

    def drain():
        global replies, decisions
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            counts["recv"] += 1
            msg = json.loads(line)
            if "id" in msg and "method" not in msg:
                replies += 1
                result = msg.get("result")
                if isinstance(result, dict) and "kind" in result:
                    decisions.append(result["kind"])
            else:
                name = msg.get("method") or "<reply>"
                methods[name] = methods.get(name, 0) + 1

    def serve():
        while True:
            msg = read()
            if handle(msg):
                continue
            send({"jsonrpc": "2.0", "id": msg.get("id"),
                  "error": {"code": -32601,
                            "message": "Unknown method: %s" % msg.get("method")}})

    try:
        if MODE == "silent-all":
            pass
        elif MODE in ("handshake", "legacy", "old-protocol", "connect-only", "session"):
            handle(read())
            serve()
        elif MODE == "full":
            handle(read())  # connect
            handle(read())  # session.create
            msg = read()  # session.send
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"messageId": "msg-1"}})
            send({"jsonrpc": "2.0", "method": "assistant.message_delta",
                  "params": {"delta": "hi"}})
            send({"jsonrpc": "2.0", "method": "future.unknownEvent",
                  "params": {"keep": "verbatim"}})
            send({"jsonrpc": "2.0", "method": "session.idle",
                  "params": {"sessionId": "sess-native-1"}})
        elif MODE == "permission":
            handle(read())  # connect
            handle(read())  # session.create
            msg = read()  # session.send
            send({"jsonrpc": "2.0", "id": 777, "method": "permission.request",
                  "params": {"requestId": "perm-1",
                             "permission": {"kind": "shell", "command": "ls -la"}}})
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"messageId": "msg-1"}})
            send({"jsonrpc": "2.0", "method": "session.idle", "params": {}})
        elif MODE == "cancel":
            handle(read())  # connect
            handle(read())  # session.create
            msg = read()  # session.send
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"messageId": "msg-1"}})
            handle(read())  # session.abort
            send({"jsonrpc": "2.0", "method": "session.idle", "params": {}})
        elif MODE == "silent-send":
            handle(read())  # connect
            handle(read())  # session.create
            read()  # session.send: no receipt at all
        else:
            raise SystemExit("unknown mode %s" % MODE)
        drain()
    finally:
        sys.stderr.write(json.dumps(
            {"recv": counts["recv"], "methods": methods,
             "replies": replies, "decisions": decisions}))
        sys.stderr.flush()
    """
)


def launch_client(tmp_path, mode: str) -> CopilotClient:
    script = tmp_path / "fake_copilot_peer.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script), "--headless", "--stdio", mode],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    return CopilotClient.launch(spec, name=f"fake-copilot-{mode}")


def peer_log(client: CopilotClient) -> dict:
    return json.loads(client.stderr_tail())


def connect(client: CopilotClient) -> None:
    client.connect(timeout=5)


# -- positive paths ------------------------------------------------------------


def test_describe_has_no_runtime_ready_claim() -> None:
    facts = describe()
    assert facts["familyId"] == FAMILY_ID == "copilot"
    assert facts["protocol"] == "copilot-cli-jsonrpc/3"
    assert facts["protocolVersion"] == SDK_PROTOCOL_VERSION == 3
    assert "runtimeReady" not in json.dumps(facts)
    assert "session.send" in facts["knownMethods"]
    assert "session.abort" in facts["knownMethods"]
    assert "session.idle" in facts["eventTypes"]
    assert "reject" in facts["permissionDecisions"]
    assert "auto-approve" not in facts["permissionDecisions"]


def test_connect_handshake_negotiates_protocol_version(tmp_path) -> None:
    client = launch_client(tmp_path, "handshake")
    try:
        negotiated = client.connect(
            timeout=5,
            client_info={
                "applicationName": "ordessa-cli",
                "applicationVersion": "0.1.0a2",
            },
        )
        assert negotiated["handshake"] == "connected"
        assert negotiated["negotiatedProtocolVersion"] == 3
        assert negotiated["result"]["serverVersion"] == "1.0.91-fake"
        assert client.handshake == "connected"
        assert client.negotiated_protocol_version == 3
        assert client.pending == {}
    finally:
        exit_code = client.close()
        assert exit_code == 0
    log = peer_log(client)
    assert log["methods"] == {"connect": 1}


def test_connect_legacy_server_falls_back_to_ping(tmp_path) -> None:
    """Documented -32601 fallback: legacy servers answer `ping` instead."""
    client = launch_client(tmp_path, "legacy")
    try:
        negotiated = client.connect(timeout=5)
        assert negotiated["handshake"] == "legacy-ping"
        assert negotiated["negotiatedProtocolVersion"] == 3
        assert negotiated["result"]["version"] == "1.0.90-legacy"
    finally:
        client.close()
    log = peer_log(client)
    assert log["methods"] == {"connect": 1, "ping": 1}  # exactly one fallback


def test_out_of_range_protocol_is_a_hard_failure(tmp_path) -> None:
    """G1: min == max == 3; a version 2 server is refused, never downgraded."""
    client = launch_client(tmp_path, "old-protocol")
    try:
        with pytest.raises(CopilotProtocolError) as excinfo:
            client.connect(timeout=5)
        assert excinfo.value.code == "PROTOCOL_MISMATCH"
        assert "protocolVersion 2" in str(excinfo.value)
        assert client.handshake == "none"
    finally:
        client.close()
    log = peer_log(client)
    assert log["methods"] == {"connect": 1}  # no retry, no second handshake


def test_create_session_returns_native_session_id(tmp_path) -> None:
    client = launch_client(tmp_path, "session")
    try:
        connect(client)
        created = client.create_session(
            session_id="user-alice-task-1", model="gpt-5", reasoning_effort="high", timeout=5
        )
        assert created["sessionId"] == "user-alice-task-1"  # peer's native id, verbatim
        assert created["requestPermission"] is True
        assert client.session_id == "user-alice-task-1"
    finally:
        client.close()


def test_resume_session_reuses_native_session(tmp_path) -> None:
    client = launch_client(tmp_path, "session")
    try:
        connect(client)
        client.create_session(timeout=5)
        resumed = client.resume_session("sess-native-1", timeout=5)
        assert resumed == {"sessionId": "sess-native-1", "resumed": True}
        assert client.session_id == "sess-native-1"
    finally:
        client.close()
    log = peer_log(client)
    assert log["methods"]["session.resume"] == 1


def test_send_receipt_is_not_completion_and_wait_idle_completes(tmp_path) -> None:
    """G6: the send result is a {messageId} receipt; session.idle is the
    completion evidence — the receipt is never relabelled."""
    client = launch_client(tmp_path, "full")
    try:
        connect(client)
        client.create_session(timeout=5)
        receipt = client.send("hello", timeout=5)
        assert receipt == {"messageId": "msg-1"}
        assert "status" not in receipt and "completed" not in receipt
        idle = client.wait_idle(timeout=5)
        assert idle["method"] == "session.idle"
        assert idle["params"] == {"sessionId": "sess-native-1"}
        assert client.pending == {}
    finally:
        client.close()


def test_unknown_events_preserved_verbatim(tmp_path) -> None:
    """G4: a future/unknown notification keeps method and params byte-for-byte."""
    client = launch_client(tmp_path, "full")
    try:
        connect(client)
        client.create_session(timeout=5)
        client.send("hello", timeout=5)
        client.wait_idle(timeout=5)
        unknown = [e for e in client.events() if e.get("method") == "future.unknownEvent"]
        assert len(unknown) == 1
        assert unknown[0]["params"] == {"keep": "verbatim"}
    finally:
        client.close()


def test_permission_callback_answered_on_same_id(tmp_path) -> None:
    """G4/SAFETY: the caller decides; the reply keeps the peer's JSON-RPC id."""
    client = launch_client(tmp_path, "permission")
    seen = []

    def on_request(frame) -> None:
        seen.append(frame)
        client.reply_permission(frame["id"], "reject")  # explicit caller decision

    try:
        connect(client)
        client.create_session(timeout=5)
        receipt = client.send("PERMITME", timeout=5, on_request=on_request)
        assert receipt == {"messageId": "msg-1"}
        assert seen and seen[0]["id"] == 777  # native callback id preserved
        assert seen[0]["method"] == "permission.request"
        assert seen[0]["params"]["requestId"] == "perm-1"
    finally:
        client.close()
    log = peer_log(client)
    assert log["replies"] == 1
    assert log["decisions"] == ["reject"]  # the caller's decision, nothing else


def test_permission_without_handler_is_never_auto_approved(tmp_path) -> None:
    """SAFETY: no on_request → the permission frame stays unanswered."""
    client = launch_client(tmp_path, "permission")
    try:
        connect(client)
        client.create_session(timeout=5)
        receipt = client.send("PERMITME", timeout=5)
        assert receipt == {"messageId": "msg-1"}
        pending = client.unanswered_requests()
        assert len(pending) == 1
        assert pending[0]["id"] == 777
        assert pending[0]["params"]["permission"]["command"] == "ls -la"
    finally:
        client.close()
    log = peer_log(client)
    assert log["replies"] == 0
    assert log["decisions"] == []


def test_cancel_returns_native_abort_result(tmp_path) -> None:
    """G6: cancellation is real evidence ({success, error}), never 'completed'."""
    client = launch_client(tmp_path, "cancel")
    try:
        connect(client)
        client.create_session(timeout=5)
        client.send("long task", timeout=5)
        aborted = client.cancel(timeout=5)
        assert aborted == {"success": True, "error": None}
        assert client.wait_idle(timeout=5)["method"] == "session.idle"
    finally:
        client.close()
    log = peer_log(client)
    assert log["methods"]["session.abort"] == 1


def test_close_then_use_is_channel_closed(tmp_path) -> None:
    """G6/G8: close() reaps this client's owned fake peer only."""
    client = launch_client(tmp_path, "handshake")
    try:
        connect(client)
    finally:
        client.close()
    with pytest.raises(ChannelClosed):
        client.command("session.send", timeout=2, prompt="hi")


# -- counter-examples ----------------------------------------------------------


def test_invalid_permission_decision_rejected_and_no_auto_approve_helper(tmp_path) -> None:
    """SAFETY: 'auto-approve' is not a documented decision and no helper exists."""
    client = launch_client(tmp_path, "handshake")
    try:
        connect(client)
        with pytest.raises(ValueError):
            client.reply_permission(777, "auto-approve")
        assert not hasattr(client, "auto_approve")
        assert not hasattr(CopilotClient, "auto_approve")
        assert "auto-approve" not in PERMISSION_DECISIONS
    finally:
        client.close()


def test_reply_permission_for_unseen_request_is_refused(tmp_path) -> None:
    """The client never fabricates a permission response for a frame it never saw."""
    client = launch_client(tmp_path, "connect-only")
    try:
        connect(client)
        with pytest.raises(ValueError):
            client.reply_permission("never-seen", "reject")
    finally:
        client.close()


def test_lost_receipt_timeout_never_resent(tmp_path) -> None:
    """G11: one write, typed timeout, ledger stays unknown, no re-send."""
    client = launch_client(tmp_path, "silent-send")
    try:
        connect(client)
        client.create_session(timeout=5)
        with pytest.raises(RequestTimeout) as excinfo:
            client.send("NOREPLY", timeout=0.5)
        assert excinfo.value.method == "session.send"
        assert excinfo.value.code == "REQUEST_TIMEOUT"
        assert list(client.pending.values()) == ["session.send"]  # unknown kept
    finally:
        exit_code = client.close()
        assert exit_code == 0
    log = peer_log(client)
    assert log["methods"]["session.send"] == 1  # exactly one write, no retry


def test_send_before_connect_is_refused_before_any_write(tmp_path) -> None:
    """G3/SAFETY: no handshake → refusal with zero frames on the wire."""
    client = launch_client(tmp_path, "silent-all")
    try:
        with pytest.raises(CopilotNotConnected) as excinfo:
            client.send("hi", timeout=1)
        assert excinfo.value.code == "NOT_CONNECTED"
        assert client.pending == {}
    finally:
        client.close()
    log = peer_log(client)
    assert log["recv"] == 0  # nothing was written


def test_send_without_session_is_refused_before_any_write(tmp_path) -> None:
    """G3: connected but no native session → refusal, no guessed sessionId."""
    client = launch_client(tmp_path, "connect-only")
    try:
        connect(client)
        with pytest.raises(CopilotConfigurationError) as excinfo:
            client.send("hi", timeout=1)
        assert excinfo.value.code == "CONFIGURATION_MISSING"
        assert client.session_id is None
    finally:
        client.close()
    log = peer_log(client)
    assert log["methods"] == {"connect": 1}  # only the handshake ever sent


def test_remote_error_is_typed_with_raw_kept(tmp_path) -> None:
    """A JSON-RPC error object surfaces typed with the raw error preserved."""
    client = launch_client(tmp_path, "handshake")
    try:
        connect(client)
        with pytest.raises(CopilotRpcError) as excinfo:
            client.command("future.unsupported", timeout=5)
        assert excinfo.value.remote_code == -32601
        assert excinfo.value.raw_error["code"] == -32601
        assert client.pending == {}
    finally:
        client.close()


def test_launch_requires_server_mode_before_spawn(tmp_path, monkeypatch) -> None:
    """G1/SAFETY: an argv without --headless/--stdio is refused before spawn."""

    def explode(*args, **kwargs):
        raise AssertionError("must not spawn for a refused launch spec")

    monkeypatch.setattr("subprocess.Popen", explode)
    spec = LaunchSpec.build(
        [sys.executable, "copilot"], home=str(tmp_path / "h"), cwd=str(tmp_path)
    )
    with pytest.raises(ValueError) as excinfo:
        CopilotClient.launch(spec)
    assert "--headless" in str(excinfo.value)

    spec2 = LaunchSpec.build(
        [sys.executable, "copilot", "--headless"],
        home=str(tmp_path / "h"),
        cwd=str(tmp_path),
    )
    with pytest.raises(ValueError) as excinfo2:
        CopilotClient.launch(spec2)
    assert "--stdio" in str(excinfo2.value)


def test_launch_refuses_auto_approve_flags_before_spawn(tmp_path, monkeypatch) -> None:
    """SAFETY: allow-all/yolo flags are refused before any process."""

    def explode(*args, **kwargs):
        raise AssertionError("must not spawn for a refused launch spec")

    monkeypatch.setattr("subprocess.Popen", explode)
    spec = LaunchSpec.build(
        [sys.executable, "--headless", "--stdio", "--allow-all-tools"],
        home=str(tmp_path / "h"),
        cwd=str(tmp_path),
    )
    with pytest.raises(ValueError) as excinfo:
        CopilotClient.launch(spec)
    assert "--allow-all-tools" in str(excinfo.value)


def test_empty_argv_is_refused_before_spawn(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("must not spawn for a refused launch spec")

    monkeypatch.setattr("subprocess.Popen", explode)
    spec = LaunchSpec.build([], home=str(tmp_path / "h"), cwd=str(tmp_path))
    with pytest.raises(ValueError):
        CopilotClient.launch(spec)


def test_process_channel_type_is_frozen_transport(tmp_path) -> None:
    """The client is a consumer of the frozen seam, not a new transport."""
    client = launch_client(tmp_path, "handshake")
    try:
        assert isinstance(client._channel, ProcessChannel)
        assert len(EVENT_TYPES) == len(set(EVENT_TYPES))
    finally:
        client.close()
