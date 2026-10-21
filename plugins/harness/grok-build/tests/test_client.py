"""New ACP-frame tests for the grok-build client (L1 controlled peers only).

The peer here is a scripted fake upstream (L1) — it proves client-side ACP
JSON-RPC 2.0 framing, correlation, authenticate-extension gating, absent-method
registrations (kill_task/get_task_output/session reopen), unknown preservation,
no-retry, receipt≠completion and typed-failure behaviour, NOT real grok-build
compatibility. Real-binary verification is registered NOT_RUN in
``runtime-process-evidence.md`` (real grok process startup is forbidden in this
package by rules 6/9).
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from ordessa_agents.harness.transport import (
    ChannelClosed,
    LaunchSpec,
    LostReceipt,
    Message,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_grok_build.client import (
    GrokBuildAcpClient,
    GrokBuildAuthenticationRefused,
    GrokBuildRpcError,
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
                  "agentCapabilities": {},
                  "agentInfo": {"name": "grok-fake", "version": "1.0.46-fake"}}})
        elif method == "session/new":
            counter += 1
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "ses-%d" % counter}})
        elif method == "session/prompt":
            text = (params.get("content") or [{}])[0].get("text", "")
            send({"jsonrpc": "2.0", "method": "session/update",
                  "params": {"sessionId": params.get("sessionId"), "turnId": "turn-1",
                             "sessionUpdate": "agent_message_chunk",
                             "content": {"type": "text", "text": "..."}}})
            send({"jsonrpc": "2.0", "method": "future/unknownEvent", "params": {"keep": "verbatim"}})
            if text == "FAILME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "error", "error": {"message": "boom"}}})
            elif text == "CANCELME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
            elif text != "SLOWME":
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "session/cancel":
            send({"jsonrpc": "2.0", "id": rid, "result": {"cancelled": False}})
        else:
            # kill_task / get_task_output / session/load / session/resume and
            # everything else: absent registrations, typed unknown-method error.
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown method: %s" % method}})
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_grok_build.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script)],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    channel = ProcessChannel.launch(spec, name="fake-grok-build")
    yield GrokBuildAcpClient(channel)
    channel.close()


class ScriptedChannel:
    """Controlled wire records only; no claim of a real grok-build process."""

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

    def reply_error(self, request_id, *, code, message, data=None):
        self.replies.append((request_id, {"code": code, "message": message, "data": data}))


def response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


# -- handshake / identity -----------------------------------------------------


def test_initialize_handshake_and_initialized_notification(client) -> None:
    info = client.initialize(timeout=5)
    assert info["agentInfo"]["name"] == "grok-fake"
    assert client._initialized is True


def test_every_client_frame_carries_the_jsonrpc_header() -> None:
    channel = ScriptedChannel([response("req-1", {"protocolVersion": 1}),
                               response("req-2", {"sessionId": "ses-1"})])
    scripted = GrokBuildAcpClient(channel)
    scripted.initialize(timeout=1)
    scripted.new_session(cwd="/tmp/work", timeout=1)
    assert channel.sent[0] == {"jsonrpc": "2.0", "id": "req-1", "method": "initialize",
                               "params": {"clientInfo": {"name": "ordessa-harness-grok-build",
                                                          "title": "Ordessa Grok Build Provider",
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


# -- authenticate extension: gated, typed-refused before any write ------------


def test_describe_declares_authenticate_as_a_gated_extension() -> None:
    facts = describe()
    assert "authenticate" in facts["gatedMethods"]
    assert "xai.api_key|cached_token" in facts["gatedMethods"]["authenticate"]
    assert "never inferred" in facts["gatedMethods"]["authenticate"]


def test_authenticate_is_typed_refused_and_writes_nothing() -> None:
    channel = ScriptedChannel([])
    scripted = GrokBuildAcpClient(channel)
    for method_id in ("xai.api_key", "cached_token", "future/unknown-method"):
        with pytest.raises(GrokBuildAuthenticationRefused) as excinfo:
            scripted.authenticate(method_id)
        assert excinfo.value.code == "GROKBUILD_AUTHENTICATION_REFUSED"
        assert "never" in str(excinfo.value)
    assert channel.sent == [] and scripted._pending == {} and scripted._events == []


def test_client_has_no_standard_authenticate_chain_surface() -> None:
    # The extension is gated at the named method; there is no auto-login, no
    # credential reader and no server->client authenticate answer helper.
    scripted_names = [name for name in dir(GrokBuildAcpClient)
                      if "auth" in name.lower() or "login" in name.lower()]
    assert scripted_names == ["authenticate"]  # the single gated extension entry


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
    scripted = GrokBuildAcpClient(channel)
    with pytest.raises(LostReceipt):
        scripted.prompt("ses-1", text="once")
    assert scripted._pending == {"req-1": "session/prompt"}  # outcome stays unknown


@pytest.mark.parametrize("result", [{}, {"stopReason": ""}, {"stopReason": 1},
                                     {"stopReason": "end_turn", "result": {}}])
def test_malformed_prompt_response_never_reports_success(result) -> None:
    channel = ScriptedChannel([response("req-1", result)])
    scripted = GrokBuildAcpClient(channel)
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
    scripted = GrokBuildAcpClient(channel)
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
    scripted = GrokBuildAcpClient(channel)
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


# -- absent-method registrations (kill_task/get_task_output/session reopen) ---


def test_describe_declares_absent_methods_exactly() -> None:
    facts = describe()
    assert facts["absentMethods"] == ["kill_task", "get_task_output",
                                      "session/load", "session/resume"]
    assert not any(name in facts["knownMethods"]
                   for name in ("kill_task", "get_task_output", "load", "resume", "close"))


def test_client_has_no_absent_method_or_constant() -> None:
    import ordessa_harness_grok_build.client as client_module
    client_methods = [name for name in dir(GrokBuildAcpClient)
                      if any(word in name.lower()
                             for word in ("kill", "task_output", "load", "resume", "close_session"))]
    module_constants = [name for name in dir(client_module)
                        if name.isupper() and any(word in name
                                                  for word in ("KILL", "TASK", "LOAD", "RESUME", "CLOSE"))]
    assert client_methods == []  # no absent method, no absent constant, no fallback
    assert module_constants == []


@pytest.mark.parametrize("method", ["kill_task", "get_task_output",
                                    "session/load", "session/resume"])
def test_absent_method_surfaces_as_typed_unknown_without_fallback(client, method) -> None:
    client.initialize(timeout=5)
    with pytest.raises(GrokBuildRpcError) as excinfo:
        client.command(method, sessionId="ses-1", cwd="/tmp/work", timeout=5)
    assert excinfo.value.raw_error["code"] == -32601
    assert client._pending == {}  # exactly one send per explicit call — no retry
    with pytest.raises(GrokBuildRpcError):
        client.command(method, sessionId="ses-1", cwd="/tmp/work", timeout=5)
    assert client._pending == {}


# -- no retry, generic errors -----------------------------------------------


def test_remote_error_keeps_raw_error(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(GrokBuildRpcError) as excinfo:
        client.command("future/method", timeout=5)
    assert excinfo.value.raw_error["code"] == -32601
    assert client._pending == {}


def test_unknown_method_is_not_auto_retried(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(GrokBuildRpcError):
        client.command("future/method", timeout=5)
    with pytest.raises(GrokBuildRpcError):
        client.command("future/method", timeout=5)
    assert client._pending == {}


def test_malformed_response_keeps_pending_unknown() -> None:
    channel = ScriptedChannel([{"jsonrpc": "2.0", "id": "req-1", "result": {}, "error": {"message": "bad"}}])
    scripted = GrokBuildAcpClient(channel)
    with pytest.raises(LostReceipt):
        scripted.command("future/method")
    assert scripted._pending == {"req-1": "future/method"}


def test_close_then_use_is_channel_closed(client) -> None:
    client.initialize(timeout=5)
    client.close()
    with pytest.raises(ChannelClosed):
        client.command("future/method", timeout=2)


# -- session frames round trip ----------------------------------------------


def test_cancel_frame_round_trips(client) -> None:
    client.initialize(timeout=5)
    assert client.cancel("ses-1", timeout=5) == {"cancelled": False}


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


# -- reverse requests (never auto-answered) ----------------------------------


def test_reverse_request_is_preserved_and_never_auto_answered() -> None:
    reverse = {"jsonrpc": "2.0", "id": 42, "method": "future/ask", "params": {"keep": True}}
    channel = ScriptedChannel([reverse])
    scripted = GrokBuildAcpClient(channel)
    scripted.next_event()
    assert channel.replies == []  # never answered on its own initiative (SAFETY)
    scripted.reply_request(42, {"caller": "answer"})
    assert channel.replies == [(42, {"caller": "answer"})]
    with pytest.raises(ValueError):
        scripted.reply_request(42, {"again": True})  # already consumed


def test_reply_request_error_round_trip() -> None:
    reverse = {"jsonrpc": "2.0", "id": 42, "method": "future/ask", "params": {}}
    channel = ScriptedChannel([reverse])
    scripted = GrokBuildAcpClient(channel)
    scripted.next_event()
    scripted.reply_request_error(42, code=-32603, message="caller refused")
    assert channel.replies == [(42, {"code": -32603, "message": "caller refused", "data": None})]
    assert scripted._reverse_requests == {}
    with pytest.raises(ValueError):
        scripted.reply_request_error(42, code=-1, message="again")


def test_duplicate_reverse_request_id_is_framing_error() -> None:
    reverse = {"jsonrpc": "2.0", "id": 42, "method": "future/ask", "params": {}}
    channel = ScriptedChannel([reverse, reverse])
    scripted = GrokBuildAcpClient(channel)
    scripted.next_event()
    from ordessa_agents.harness.transport import FramingError
    with pytest.raises(FramingError):
        scripted.next_event()
