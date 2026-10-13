"""New ACP-frame tests for the dsh client (L1 controlled peers only).

The peer here is a scripted fake upstream (L1) — it proves client-side ACP
JSON-RPC 2.0 framing, correlation, session/load absence, unknown preservation,
no-retry, receipt≠completion and typed-failure behaviour, NOT real dsh
compatibility. Real-binary verification is registered NOT_RUN in
``runtime-process-evidence.md`` (real dsh process startup is forbidden in this
package by rules 6/9).
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_execution_agents.harness.transport import (
    ChannelClosed,
    LaunchSpec,
    LostReceipt,
    Message,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_dsh.client import (
    DshAcpClient,
    DshRpcError,
    PromptTurnFailed,
    describe,
)

PEER = textwrap.dedent(
    """
    import json, sys
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    counter = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        msg = json.loads(line)
        method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": 1,
                  "agentCapabilities": {"loadSession": False},
                  "agentInfo": {"name": "dsh-fake", "version": "0.1.5-rc.1-fake"}}})
        elif method == "session/new":
            counter += 1
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "ses-%d" % counter, "configOptions": []}})
        elif method == "session/prompt":
            text = (params.get("content") or [{}])[0].get("text", "")
            send({"jsonrpc": "2.0", "method": "session/update",
                  "params": {"sessionId": params.get("sessionId"), "turnId": "turn-1",
                             "type": "message_chunk", "delta": "..."}})
            send({"jsonrpc": "2.0", "method": "future/unknownEvent", "params": {"keep": "verbatim"}})
            if text == "FAILME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "error", "error": {"message": "boom"}}})
            elif text == "CANCELME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
            elif text != "SLOWME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "session/cancel":
            send({"jsonrpc": "2.0", "id": rid, "result": {"cancelled": False}})
        elif method == "session/close":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/set_config_option":
            send({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": []}})
        elif method == "session/resume":
            send({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": []}})
        elif method == "session/load":
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "session/load is not supported"}})
        elif method == "session/permissionDemo":
            send({"jsonrpc": "2.0", "id": 42, "method": "session/request_permission",
                  "params": {"sessionId": "ses-1", "turnId": "turn-1",
                             "toolCall": {"toolCallId": "tc-1", "title": "run"}}})
            reply = json.loads(sys.stdin.readline())
            send({"jsonrpc": "2.0", "id": rid, "result": {"outcome": reply.get("result", {}).get("outcome")}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown method: %s" % method}})
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_dsh.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script)],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    channel = ProcessChannel.launch(spec, name="fake-dsh")
    yield DshAcpClient(channel)
    channel.close()


class ScriptedChannel:
    """Controlled wire records only; no claim of a real dsh process."""

    def __init__(self, messages=()):
        from collections import deque
        self.messages = deque(messages)
        self.sent = []
        self.replies = []

    def send_raw(self, raw):
        self.sent.append(raw)

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.sent.append(payload)

    def next_message(self, *, timeout):
        if not self.messages:
            raise ChannelClosed("controlled disconnect")
        return Message(self.messages.popleft())

    def reply(self, request_id, result):
        self.replies.append((request_id, result))


def response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


# -- handshake / identity -----------------------------------------------------


def test_initialize_handshake_and_initialized_notification(client) -> None:
    info = client.initialize(timeout=5)
    assert info["agentInfo"]["name"] == "dsh-fake"
    assert client._initialized is True


def test_every_client_frame_carries_the_jsonrpc_header() -> None:
    channel = ScriptedChannel([response("req-1", {"protocolVersion": 1}),
                               response("req-2", {"sessionId": "ses-1"})])
    scripted = DshAcpClient(channel)
    scripted.initialize(timeout=1)
    scripted.new_session(cwd="/tmp/work", timeout=1)
    assert channel.sent[0] == {"jsonrpc": "2.0", "id": "req-1", "method": "initialize",
                               "params": {"clientInfo": {"name": "ordessa-harness-dsh",
                                                          "title": "Ordessa dsh Provider",
                                                          "version": "0.1.0a1"},
                                          "capabilities": {}}}
    assert channel.sent[1] == {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    assert channel.sent[2] == {"jsonrpc": "2.0", "id": "req-2", "method": "session/new",
                               "params": {"cwd": "/tmp/work"}}


def test_new_session_returns_real_session_identity(client) -> None:
    client.initialize(timeout=5)
    result = client.new_session(cwd="/tmp/work", timeout=5)
    assert result["sessionId"] == "ses-1"


def test_unknown_events_are_preserved_verbatim(client) -> None:
    client.initialize(timeout=5)
    client.prompt("ses-1", text="hello", timeout=5)
    methods = [e.get("method") for e in client.events()]
    assert "session/update" in methods
    assert "future/unknownEvent" in methods  # G4: never dropped
    unknown = next(e for e in client.events() if e.get("method") == "future/unknownEvent")
    assert unknown["params"] == {"keep": "verbatim"}


# -- receipt≠completion fences ----------------------------------------------


def test_prompt_terminal_stop_reason_is_accepted_verbatim(client) -> None:
    client.initialize(timeout=5)
    result = client.prompt("ses-1", text="hello", timeout=5)
    assert result == {"stopReason": "end_turn"}  # terminal receipt, verbatim


def test_prompt_failed_turn_raises_typed_with_raw_kept(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(PromptTurnFailed) as excinfo:
        client.prompt("ses-1", text="FAILME", timeout=5)
    assert excinfo.value.stop_reason == "error"
    assert excinfo.value.raw["error"]["message"] == "boom"


def test_prompt_cancelled_turn_raises_typed(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(PromptTurnFailed) as excinfo:
        client.prompt("ses-1", text="CANCELME", timeout=5)
    assert excinfo.value.stop_reason == "cancelled"


def test_prompt_receipt_is_not_completion_for_unknown_status() -> None:
    channel = ScriptedChannel([response("req-1", {"stopReason": "future"})])
    scripted = DshAcpClient(channel)
    with pytest.raises(LostReceipt):
        scripted.prompt("ses-1", text="once")
    assert scripted._pending == {"req-1": "session/prompt"}  # outcome stays unknown


@pytest.mark.parametrize("result", [{}, {"stopReason": ""}, {"stopReason": 1},
                                     {"stopReason": "end_turn", "result": {}}])
def test_malformed_prompt_response_never_reports_success(result) -> None:
    channel = ScriptedChannel([response("req-1", result)])
    scripted = DshAcpClient(channel)
    if result == {"stopReason": "end_turn", "result": {}}:
        # structurally terminal; extra keys are preserved verbatim
        assert scripted.prompt("ses-1", text="once") == result
    else:
        with pytest.raises(LostReceipt):
            scripted.prompt("ses-1", text="once")
        assert scripted._pending == {"req-1": "session/prompt"}


def test_prompt_timeout_is_unknown_and_never_resends(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(RequestTimeout):
        client.prompt("ses-1", text="SLOWME", timeout=0.2)
    pending = dict(client._pending)  # the original id stays pending, outcome unknown
    assert pending and list(pending.values()) == ["session/prompt"]
    with pytest.raises(LostReceipt):
        client.prompt("ses-1", text="hello", timeout=1)  # earlier receipt unknown
    assert client._pending == pending  # nothing was re-sent, nothing was cleared


def test_second_prompt_while_pending_is_refused_without_resend() -> None:
    channel = ScriptedChannel([])
    scripted = DshAcpClient(channel)
    scripted._pending["req-1"] = "session/prompt"
    scripted._prompt_requests["req-1"] = "ses-1"
    with pytest.raises(LostReceipt, match="recover without resending"):
        scripted.prompt("ses-1", text="once")
    assert channel.sent == []


class TimeoutChannel(ScriptedChannel):
    """Scripted wire records whose empty state times out instead of closing."""

    def next_message(self, *, timeout):
        if not self.messages:
            raise RequestTimeout("controlled", None, timeout)
        return Message(self.messages.popleft())


def test_late_prompt_receipt_is_recovered_read_only() -> None:
    channel = TimeoutChannel([])
    scripted = DshAcpClient(channel)
    with pytest.raises(RequestTimeout) as error:
        scripted.prompt("ses-1", text="once", timeout=0.01)
    native_id = error.value.request_id
    assert scripted._pending == {native_id: "session/prompt"}
    channel.messages.append(response(native_id, {"stopReason": "end_turn"}))
    scripted.next_event()  # late receipt may be buffered by another consumer
    receipt = scripted.recover_request(native_id)
    assert receipt == {"stopReason": "end_turn"}
    assert scripted._pending == {}
    assert len(channel.sent) == 1  # nothing was re-sent


# -- session/load absence in all three mechanisms ----------------------------


def test_describe_declares_no_load_method_and_an_explicit_absence() -> None:
    facts = describe()
    assert "session/load" not in facts["knownMethods"]
    assert facts["absentMethods"] == ["session/load"]
    assert not any("load" in name for name in facts["knownMethods"])


def test_client_has_no_load_method_or_constant() -> None:
    import ordessa_harness_dsh.client as client_module
    client_methods = [name for name in dir(DshAcpClient) if "load" in name.lower()]
    module_constants = [name for name in dir(client_module)
                        if name.isupper() and "LOAD" in name]
    assert client_methods == []  # no load method, no load constant, no load fallback
    assert module_constants == []


def test_native_load_rejection_surfaces_as_typed_error_without_retry(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(DshRpcError) as excinfo:
        client.command("session/load", sessionId="ses-1", cwd="/tmp/work", timeout=5)
    assert excinfo.value.raw_error["code"] == -32601
    assert "not supported" in str(excinfo.value)
    with pytest.raises(DshRpcError):
        client.command("session/load", sessionId="ses-1", cwd="/tmp/work", timeout=5)
    assert client._pending == {}  # exactly two sends for two explicit calls — no retry


def test_resume_frame_exists_but_is_not_a_recovery_fallback(client) -> None:
    client.initialize(timeout=5)
    result = client.resume_session("ses-1", timeout=5)
    assert result == {"configOptions": []}  # frame round trip; semantics unverified
    with pytest.raises(ValueError):
        client.resume_session("ses-1", sessionId="other", timeout=5)


# -- no retry, generic errors -----------------------------------------------


def test_remote_error_keeps_raw_error(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(DshRpcError) as excinfo:
        client.command("future/method", timeout=5)
    assert excinfo.value.raw_error["code"] == -32601
    assert client._pending == {}


def test_unknown_method_is_not_auto_retried(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(DshRpcError):
        client.command("future/method", timeout=5)
    with pytest.raises(DshRpcError):
        client.command("future/method", timeout=5)
    assert client._pending == {}


def test_malformed_response_keeps_pending_unknown() -> None:
    channel = ScriptedChannel([{"jsonrpc": "2.0", "id": "req-1", "result": {}, "error": {"message": "bad"}}])
    scripted = DshAcpClient(channel)
    with pytest.raises(LostReceipt):
        scripted.command("future/method")
    assert scripted._pending == {"req-1": "future/method"}


def test_close_then_use_is_channel_closed(client) -> None:
    client.initialize(timeout=5)
    client.close()
    with pytest.raises(ChannelClosed):
        client.command("future/method", timeout=2)


# -- session frames round trip ----------------------------------------------


def test_cancel_close_and_config_frames_round_trip(client) -> None:
    client.initialize(timeout=5)
    assert client.cancel("ses-1", timeout=5) == {"cancelled": False}
    assert client.close_session("ses-1", timeout=5) == {}
    assert client.set_config_option("ses-1", "model", "new-model", timeout=5) == {"configOptions": []}


def test_prompt_overrides_cannot_change_target_or_input(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(ValueError):
        client.prompt("ses-1", text="once", sessionId="other")
    with pytest.raises(ValueError):
        client.prompt("ses-1", text="once", content=[])
    with pytest.raises(ValueError):
        client.prompt("ses-1", text="once", prompt="other")
    with pytest.raises(ValueError):
        client.prompt("ses-1", text=1)  # input must be explicit text


# -- permission reverse requests --------------------------------------------


def test_permission_reverse_request_keeps_identity_and_caller_decides(client) -> None:
    client.initialize(timeout=5)
    seen = []

    def on_request(message):
        seen.append(message)
        client.reply_permission(message.id, "selected", option_id="opt-1")

    result = client._request("session/permissionDemo", {}, timeout=5, on_request=on_request)
    assert seen and seen[0].id == 42  # native callback id preserved (G4)
    assert seen[0].method == "session/request_permission"
    assert result["outcome"] == {"outcome": "selected", "optionId": "opt-1"}


def test_invalid_permission_outcomes_are_refused_locally(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(ValueError):
        client.reply_permission(1, "auto-approve")  # never a valid outcome
    with pytest.raises(ValueError):
        client.reply_permission(1, "selected")  # missing option id
    with pytest.raises(ValueError):
        client.reply_permission(1, "cancelled", option_id="opt-1")  # cancelled carries none
    with pytest.raises(ValueError):
        client.reply_permission(1, "selected", option_id=True)


def test_permission_never_auto_answered_and_duplicate_reply_refused() -> None:
    reverse = {"jsonrpc": "2.0", "id": 42, "method": "session/request_permission",
               "params": {"sessionId": "ses-1", "turnId": "turn-1"}}
    channel = ScriptedChannel([reverse])
    scripted = DshAcpClient(channel)
    scripted.next_event()
    assert channel.replies == []  # never answered on its own initiative
    scripted.reply_permission(42, "cancelled")
    assert channel.replies == [(42, {"outcome": {"outcome": "cancelled"}})]
    with pytest.raises(ValueError):
        scripted.reply_permission(42, "selected", option_id="opt-1")  # already consumed


def test_duplicate_reverse_request_id_is_framing_error() -> None:
    reverse = {"jsonrpc": "2.0", "id": 42, "method": "session/request_permission", "params": {}}
    channel = ScriptedChannel([reverse, reverse])
    scripted = DshAcpClient(channel)
    scripted.next_event()
    from ordessa_execution_agents.harness.transport import FramingError
    with pytest.raises(FramingError):
        scripted.next_event()
