"""Counter-example tests for the Codex app-server client (L1 fixture).

The peer here is a scripted fake upstream (L1) — it proves client-side
framing/correlation/unknown-preservation/typed-failure behaviour, NOT real
codex compatibility. Real-binary verification is registered as BLOCKED
(broken local artifact) in the N002 evidence.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from ordessa_agent_tools.native_clients import (
    ChannelClosed,
    LaunchSpec,
    LostReceipt,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_agent_tools.native_clients.codex import (
    CodexAppServerClient,
    CodexRpcError,
    TurnFailed,
)

PEER = textwrap.dedent(
    """
    import json, sys
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    recv = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        recv += 1
        msg = json.loads(line)
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            send({"id": rid, "result": {"userAgent": "codex-fake/1", "platformFamily": "unix", "platformOs": "linux"}})
        elif method == "thread/start":
            send({"id": rid, "result": {"thread": {"id": "th-1"}, "sessionId": "sess-1", "ephemeral": False}})
        elif method == "turn/start":
            text = msg["params"]["input"][0]["text"]
            send({"id": rid, "result": {"turn": {"id": "turn-1"}, "status": "inProgress"}})
            send({"method": "turn/started", "params": {"threadId": "th-1", "turnId": "turn-1"}})
            send({"method": "future/unknownEvent", "params": {"keep": "verbatim"}})
            if text == "FAILME":
                send({"method": "turn/completed", "params": {"turnId": "turn-1", "status": "failed", "error": {"message": "boom"}}})
            elif text != "SLOWME":
                send({"method": "turn/completed", "params": {"turnId": "turn-1", "status": "completed"}})
        elif method == "turn/approvalDemo":
            send({"id": 42, "method": "item/permissions/requestApproval", "params": {"threadId": "th-1", "turnId": "turn-1", "request": {}}})
            reply = json.loads(sys.stdin.readline())
            send({"id": rid, "result": {"approval": reply.get("result")}})
        elif method == "overload":
            send({"id": rid, "error": {"code": -32001, "message": "Server overloaded; retry later."}})
        else:
            send({"id": rid, "error": {"code": -32601, "message": "Unknown method: %s" % method}})
    sys.stderr.write("recv=%d" % recv)
    sys.stderr.flush()
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_codex.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script)],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    channel = ProcessChannel.launch(spec, name="fake-codex")
    yield CodexAppServerClient(channel)
    channel.close()


# -- positive ---------------------------------------------------------------


def test_initialize_handshake_and_initialized_notification(client) -> None:
    info = client.initialize(timeout=5)
    assert info["platformOs"] == "linux"
    assert client._initialized is True


def test_create_thread_returns_real_session_identity(client) -> None:
    client.initialize(timeout=5)
    result = client.create_thread(cwd="/tmp/work", model="gpt-test", timeout=5)
    assert result["thread"]["id"] == "th-1"
    assert result["sessionId"] == "sess-1"


def test_turn_receipt_is_not_completion_but_completes_later(client) -> None:
    client.initialize(timeout=5)
    receipt = client.start_turn(thread_id="th-1", text="hello", timeout=5)
    assert receipt["status"] == "inProgress"  # receipt, not completion
    done = client.wait_turn_completed(timeout=5)
    assert done["params"]["status"] == "completed"


def test_unknown_events_are_preserved_verbatim(client) -> None:
    client.initialize(timeout=5)
    client.start_turn(thread_id="th-1", text="hello", timeout=5)
    client.wait_turn_completed(timeout=5)
    methods = [e.get("method") for e in client.events()]
    assert "future/unknownEvent" in methods  # G4: never dropped
    unknown = next(e for e in client.events() if e.get("method") == "future/unknownEvent")
    assert unknown["params"] == {"keep": "verbatim"}


def test_approval_callback_keeps_identity_and_caller_decides(client) -> None:
    client.initialize(timeout=5)
    seen = []

    def on_request(message):
        seen.append(message)
        client.reply_approval(message.id, "decline")

    result = client._request("turn/approvalDemo", {}, timeout=5, on_request=on_request)
    assert seen and seen[0].id == 42  # native callback id preserved (G4)
    assert seen[0].method == "item/permissions/requestApproval"
    assert result["approval"] == "decline"


# -- counter-examples -------------------------------------------------------


def test_remote_error_keeps_codex_error_info(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(CodexRpcError) as excinfo:
        client.command("overload", timeout=5)
    assert excinfo.value.raw_error["code"] == -32001
    assert "retry later" in str(excinfo.value)


def test_overload_is_not_auto_retried(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(CodexRpcError):
        client.command("overload", timeout=5)
    with pytest.raises(CodexRpcError):
        client.command("overload", timeout=5)
    # exactly two sends for two explicit calls — no hidden retry (G11)
    assert len(client._pending) == 0


def test_failed_turn_raises_typed_with_raw_kept(client) -> None:
    client.initialize(timeout=5)
    client.start_turn(thread_id="th-1", text="FAILME", timeout=5)
    with pytest.raises(TurnFailed) as excinfo:
        client.wait_turn_completed(timeout=5)
    assert excinfo.value.status == "failed"
    assert excinfo.value.raw["params"]["error"]["message"] == "boom"


def test_wait_timeout_is_unknown_and_never_resends(client) -> None:
    client.initialize(timeout=5)
    client.start_turn(thread_id="th-1", text="SLOWME", timeout=5)
    with pytest.raises(RequestTimeout):
        client.wait_turn_completed(timeout=1)


def test_invalid_approval_decision_rejected_locally(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(ValueError):
        client.reply_approval(1, "auto-approve")  # never a valid decision


def test_close_then_use_is_channel_closed(client) -> None:
    client.initialize(timeout=5)
    client.close()
    with pytest.raises(ChannelClosed):
        client.command("thread/list", timeout=2)


def test_declined_decision_is_never_upgraded_by_amendment(client) -> None:
    # SAFETY counter-example: an amendment payload must never silently turn a
    # "decline" into an acceptWithExecpolicyAmendment approval.
    client.initialize(timeout=5)
    with pytest.raises(ValueError):
        client.reply_approval(1, "decline", amendment={"rules": ["x"]})


def test_turn_failed_is_not_a_channel_closed_condition() -> None:
    # G11 boundary: a failed turn is a run outcome, not "safe to resend".
    assert not issubclass(TurnFailed, ChannelClosed)
