"""Counter-example tests for the Codex app-server client (L1 fixture).

The peer here is a scripted fake upstream (L1) — it proves client-side
framing/correlation/unknown-preservation/typed-failure behaviour, NOT real
codex compatibility. Real-binary verification is registered as BLOCKED
(broken local artifact) in the N002 evidence.
"""

from __future__ import annotations

import sys
import textwrap
import json

import pytest

from ordessa_harness_transport import (
    ChannelClosed,
    LaunchSpec,
    LostReceipt,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_codex.client import (
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
            send({"id": rid, "result": {"thread": {"id": "th-1"}}})
        elif method == "turn/start":
            text = msg["params"]["input"][0]["text"]
            send({"id": rid, "result": {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}})
            send({"method": "turn/started", "params": {"threadId": "th-1", "turn": {"id": "turn-1", "items": [], "status": "inProgress"}}})
            send({"method": "future/unknownEvent", "params": {"keep": "verbatim"}})
            if text == "FAILME":
                send({"method": "turn/completed", "params": {"threadId": "th-1", "turn": {"id": "turn-1", "items": [], "status": "failed", "error": {"message": "boom"}}}})
            elif text != "SLOWME":
                send({"method": "turn/completed", "params": {"threadId": "th-1", "turn": {"id": "turn-1", "items": [], "status": "completed"}}})
        elif method == "turn/approvalDemo":
            send({"id": 42, "method": "item/commandExecution/requestApproval", "params": {"threadId": "th-1", "turnId": "turn-1", "request": {}}})
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
    assert "sessionId" not in result  # thread.id is the native session identity


def test_turn_receipt_is_not_completion_but_completes_later(client) -> None:
    client.initialize(timeout=5)
    receipt = client.start_turn(thread_id="th-1", text="hello", timeout=5)
    assert receipt["turn"]["status"] == "inProgress"  # receipt, not completion
    done = client.wait_turn_completed(timeout=5)
    assert done["params"]["turn"]["status"] == "completed"


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
    assert seen[0].method == "item/commandExecution/requestApproval"
    assert result["approval"] == {"decision": "decline"}


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
    assert excinfo.value.raw["params"]["turn"]["error"]["message"] == "boom"


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


class ScriptedChannel:
    """Controlled wire records only; no claim of a real Codex process."""

    def __init__(self, messages=()):
        from collections import deque
        self.messages = deque(messages)
        self.sent = []
        self.replies = []

    def send_raw(self, raw):
        self.sent.append(raw)

    def next_message(self, *, timeout):
        from ordessa_agent_tools.native_clients._transport import Message
        if not self.messages:
            raise ChannelClosed("controlled disconnect")
        return Message(self.messages.popleft())

    def reply(self, request_id, result):
        self.replies.append((request_id, result))


def completion(thread="th-1", turn="turn-1", status="completed"):
    return {"method": "turn/completed", "params": {"threadId": thread,
            "turn": {"id": turn, "items": [], "status": status, "error": None}}}


def test_wait_correlates_both_thread_and_turn_preserving_unrelated():
    wrong_thread, wrong_turn, right = completion(thread="other"), completion(turn="other"), completion()
    channel = ScriptedChannel([wrong_thread, wrong_turn, right])
    client = CodexAppServerClient(channel)
    assert client.wait_turn_completed(thread_id="th-1", turn_id="turn-1") == right
    assert client.events() == (wrong_thread, wrong_turn, right)
    assert channel.sent == []


def test_completion_buffered_during_rpc_is_available_to_wait():
    done = completion()
    channel = ScriptedChannel([done, {"id": "req-1", "result": {"turn": {"id": "turn-1", "items": [], "status": "inProgress"}}}])
    client = CodexAppServerClient(channel)
    client.start_turn(thread_id="th-1", text="once")
    assert client.wait_turn_completed() == done
    assert len(channel.sent) == 1


@pytest.mark.parametrize("raw", [completion(status="inProgress"), completion(status="future"),
    {"method": "turn/completed", "params": {"status": "completed", "turnId": "turn-1"}}])
def test_invalid_completion_cannot_report_success(raw):
    client = CodexAppServerClient(ScriptedChannel([raw]))
    with pytest.raises(LostReceipt):
        client.wait_turn_completed(thread_id="th-1", turn_id="turn-1")


def test_interrupt_ack_is_not_terminal_completion():
    channel = ScriptedChannel([{"id": "req-1", "result": {}}, completion(status="interrupted")])
    client = CodexAppServerClient(channel)
    assert client.cancel(thread_id="th-1", turn_id="turn-1") == {}
    with pytest.raises(TurnFailed) as error:
        client.wait_turn_completed(thread_id="th-1", turn_id="turn-1")
    assert error.value.status == "interrupted"
    assert channel.sent[0]["params"] == {"threadId": "th-1", "turnId": "turn-1"}


def reverse(method="item/commandExecution/requestApproval"):
    return {"id": 42, "method": method, "params": {"threadId": "th-1", "turnId": "turn-1", "itemId": "item-1"}}


def test_permissions_cannot_receive_command_decision_and_duplicate_reply_refused():
    channel = ScriptedChannel([reverse("item/permissions/requestApproval")])
    client = CodexAppServerClient(channel)
    client.next_event()
    with pytest.raises(ValueError):
        client.reply_approval(42, "accept")
    client.reply_request(42, {"permissions": {}, "scope": "turn"})
    assert channel.replies == [(42, {"permissions": {}, "scope": "turn"})]
    with pytest.raises(ValueError):
        client.reply_request(42, {"permissions": {}})


def test_server_resolved_request_is_not_answered_again():
    channel = ScriptedChannel([reverse(), {"method": "serverRequest/resolved", "params": {"threadId": "th-1", "requestId": 42}}])
    client = CodexAppServerClient(channel)
    client.next_event()
    client.next_event()
    with pytest.raises(ValueError):
        client.reply_approval(42, "accept")
    assert channel.replies == []


def test_execpolicy_reply_uses_native_decision_wrapper():
    channel = ScriptedChannel([reverse()])
    client = CodexAppServerClient(channel)
    client.next_event()
    amendment = {"execpolicy_amendment": ["echo", "safe"]}
    client.reply_approval(42, "acceptWithExecpolicyAmendment", amendment=amendment)
    assert channel.replies == [(42, {"decision": {"acceptWithExecpolicyAmendment": amendment}})]


def test_unknown_start_is_not_resent_and_late_receipt_recovery_only_reads():
    channel = ScriptedChannel()
    client = CodexAppServerClient(channel)
    with pytest.raises(RequestTimeout) as error:
        client.start_turn(thread_id="th-1", text="once", timeout=0)
    with pytest.raises(LostReceipt):
        client.start_turn(thread_id="th-1", text="once")
    channel.messages.append({"id": error.value.request_id, "result": {"turn": {"id": "late", "items": [], "status": "inProgress"}}})
    client.next_event()  # Late receipt may be buffered by another event consumer.
    receipt = client.recover_request(error.value.request_id)
    assert receipt["turn"]["id"] == "late"
    assert client._last_turn == ("th-1", "late")
    assert client._pending == {}
    assert len(channel.sent) == 1


def test_malformed_response_keeps_pending_unknown():
    channel = ScriptedChannel([{"id": "req-1", "result": {}, "error": {"message": "bad"}}])
    client = CodexAppServerClient(channel)
    with pytest.raises(LostReceipt):
        client.command("future/method")
    assert client._pending == {"req-1": "future/method"}


def test_target_overrides_cannot_change_input_or_resume_thread(client):
    with pytest.raises(ValueError):
        client.start_turn(thread_id="th-1", text="once", threadId="other")
    with pytest.raises(ValueError):
        client.start_turn(thread_id="th-1", text="once", input=[])
    with pytest.raises(ValueError):
        client.resume_thread("th-1", threadId="other")


def test_wrong_thread_resolved_does_not_clear_pending_approval():
    channel = ScriptedChannel([reverse(), {"method": "serverRequest/resolved", "params": {"threadId": "other", "requestId": 42}}])
    client = CodexAppServerClient(channel)
    client.next_event()
    client.next_event()
    client.reply_approval(42, "decline")
    assert channel.replies == [(42, {"decision": "decline"})]


def test_permissions_generic_reply_cannot_sneak_command_decision():
    channel = ScriptedChannel([reverse("item/permissions/requestApproval")])
    client = CodexAppServerClient(channel)
    client.next_event()
    with pytest.raises(ValueError):
        client.reply_request(42, {"decision": "accept"})
    assert channel.replies == []
    assert 42 in client._reverse_requests


@pytest.mark.parametrize("turn", [{"id": "turn-1"}, {"id": "turn-1", "items": [], "status": "future"}])
def test_malformed_start_receipt_remains_unknown(turn):
    channel = ScriptedChannel([{"id": "req-1", "result": {"turn": turn}}])
    client = CodexAppServerClient(channel)
    with pytest.raises(LostReceipt):
        client.start_turn(thread_id="th-1", text="once")
    assert client._last_turn is None
    with pytest.raises(LostReceipt):
        client.start_turn(thread_id="th-1", text="once")
    assert len(channel.sent) == 1


def test_remote_error_data_preserved_without_reinterpreting_it():
    data = {"codexErrorInfo": "serverOverloaded", "future": {"value": 1}}
    client = CodexAppServerClient(ScriptedChannel([{"id": "req-1", "error": {"code": -32001, "message": "overloaded", "data": data}}]))
    with pytest.raises(CodexRpcError) as error:
        client.command("future/method")
    assert error.value.remote_data == data


def test_command_once_binds_actual_generated_identity_before_send(client):
    sequence=[]
    original_send=client._channel.send_frame
    def send(wire, *, before_write):
        def guard():
            before_write()
            sequence.append(("send",json.loads(wire)))
        original_send(wire, before_write=guard)
    client._channel.send_frame=send
    def persist(payload):
        sequence.append(("bind",dict(payload)))
        assert payload["id"] not in client._pending
    result=client.command_once("thread/start",{"cwd":"/isolated"},before_send=persist,timeout=5)
    assert result["thread"]["id"] == "th-1"
    assert [entry[0] for entry in sequence] == ["bind","send"]
    assert sequence[0][1] == sequence[1][1]
    assert sequence[0][1]["id"] == "req-1"


def test_command_once_hook_failure_performs_no_native_write(client):
    sent=[]
    original_send=client._channel.send_frame
    def send(wire, *, before_write):
        def guard():
            before_write()
            sent.append(wire)
        original_send(wire, before_write=guard)
    client._channel.send_frame=send
    def refuse(payload): raise RuntimeError("journal refused bind")
    with pytest.raises(RuntimeError,match="journal refused"):
        client.command_once("thread/start",{"cwd":"/isolated"},before_send=refuse)
    assert sent == [] and client._pending == {}


def test_command_once_detached_hook_payload_cannot_change_native_dispatch(client):
    captured=[]
    original_send=client._channel.send_frame
    def send(wire, *, before_write):
        original_send(wire, before_write=before_write)
        captured.append(json.loads(wire))
    client._channel.send_frame=send
    def persist(payload): payload["params"]["cwd"]="/attacker"
    client.command_once("thread/start",{"cwd":"/isolated"},before_send=persist,timeout=5)
    assert captured[0]["params"]["cwd"] == "/isolated"


def test_command_once_timeout_retains_original_id_and_query_does_not_send():
    from ordessa_harness_transport import Message
    class Channel:
        def __init__(self): self.sent=[];self.response=None
        def send_frame(self,wire,*,before_write): before_write();self.sent.append(json.loads(wire))
        def mark_input_unknown(self): pass
        def acknowledge_frame(self,request_id): pass
        def next_message(self,*,timeout):
            if self.response is None: raise RequestTimeout("config/batchWrite",None,timeout)
            result=self.response;self.response=None;return Message(result)
    channel=Channel();client=CodexAppServerClient(channel);bound=[]
    with pytest.raises(RequestTimeout):
        client.command_once("config/batchWrite",{"edits":[]},before_send=lambda payload:bound.append(payload),timeout=0.01)
    native_id=bound[0]["id"]
    assert client._pending == {native_id:"config/batchWrite"}
    channel.response={"id":native_id,"result":{"status":"ok","version":"v2"}}
    assert client.recover_request(native_id,timeout=0.01)["version"] == "v2"
    assert len(channel.sent) == 1 and client._pending == {}
    with pytest.raises(LostReceipt):
        client.command_once("config/batchWrite", {"edits": []}, before_send=lambda payload: None)
    assert len(channel.sent) == 1


def test_command_once_unknown_config_receipt_refuses_new_write_id():
    class Channel:
        def __init__(self):self.sent=[]
        def send_frame(self,wire,*,before_write): before_write();self.sent.append(json.loads(wire))
        def mark_input_unknown(self): pass
        def acknowledge_frame(self,request_id): pass
        def next_message(self,*,timeout):raise RequestTimeout("config/batchWrite",None,timeout)
    channel=Channel();client=CodexAppServerClient(channel)
    with pytest.raises(RequestTimeout):
        client.command_once("config/batchWrite",{"edits":[]},before_send=lambda payload:None,timeout=0.01)
    with pytest.raises(LostReceipt,match="configuration receipt unknown"):
        client.command_once("config/value/write",{"keyPath":"model","value":"new"},before_send=lambda payload:None,timeout=0.01)
    assert len(channel.sent) == 1
