"""N008 Gemini CLI client tests — L1 fake ACP upstream (scripted JSON-RPC).

Proves client-side ACP handling only; no real gemini binary here (L2
untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agent_tools.native_clients import LaunchSpec, ProcessChannel, RequestTimeout
from ordessa_agent_tools.native_clients._acp import AcpRemoteError
from ordessa_agent_tools.native_clients.gemini_cli import GeminiCliClient

PEER = textwrap.dedent(
    """
    import json, sys
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        msg = json.loads(line)
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "1", "agentCapabilities": {"loadSession": True}}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "s-acp-1", "modes": {"currentModeId": "default"}}})
        elif method == "session/prompt":
            send({"jsonrpc": "2.0", "id": 77, "method": "session/request_permission",
                  "params": {"sessionId": "s-acp-1", "toolCall": {"toolCallId": "tc-1"},
                             "options": [{"optionId": "allow-once", "name": "Allow", "kind": "allow_once"},
                                         {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"}]}})
            reply = json.loads(sys.stdin.readline())
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn", "reply": reply.get("result")}})
        elif method == "session/load":
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "s-acp-loaded"}})
        elif method == "badMethod":
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
        elif method == "hang":
            continue  # never answers: timeout/unknown-outcome path
        else:
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        send({"jsonrpc": "2.0", "method": "session/update",
              "params": {"sessionId": "s-acp-1", "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "hi"}}}})
        send({"jsonrpc": "2.0", "method": "_gemini/customEvent", "params": {"keep": "verbatim"}})
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_gemini.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build([sys.executable, str(script)], home=str(tmp_path / "home"), cwd=str(tmp_path))
    channel = ProcessChannel.launch(spec, name="fake-gemini")
    yield GeminiCliClient(channel)
    channel.close()


def test_l1_initialize_negotiates_protocol_version(client) -> None:
    result = client.initialize(timeout=5)
    assert result["protocolVersion"] == "1"
    assert result["agentCapabilities"]["loadSession"] is True


def test_l1_new_session_binds_real_session_id(client) -> None:
    client.initialize(timeout=5)
    result = client.new_session(timeout=5)
    assert result["sessionId"] == "s-acp-1"
    assert client.session_id == "s-acp-1"


def test_l1_permission_request_keeps_identity_and_caller_decides(client) -> None:
    client.initialize(timeout=5)
    client.new_session(timeout=5)
    seen = []

    def on_request(message):
        seen.append(message)
        client.reply_permission(message.id, "allowed", option_id="allow-once")

    result = client.prompt(timeout=5, on_request=on_request, prompt={"text": "go"})
    assert seen and seen[0].id == 77  # G4 identity preserved
    assert seen[0].method == "session/request_permission"
    assert result["stopReason"] == "end_turn"


def test_l1_custom_methods_and_updates_preserved(client) -> None:
    client.initialize(timeout=5)
    client.new_session(timeout=5)
    client.prompt(timeout=5, on_request=lambda m: client.reply_request(m.id, {"outcome": {"outcome": "rejected"}}))
    client.pump(timeout=1)
    methods = [e.raw.get("method") for e in client.events()]
    assert "session/update" in methods
    assert "_gemini/customEvent" in methods  # '_'-prefix custom method preserved (G4)
    custom = next(e for e in client.events() if e.raw.get("method") == "_gemini/customEvent")
    assert custom.raw["params"] == {"keep": "verbatim"}


def test_l1_remote_error_is_typed(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(AcpRemoteError):
        client.command("badMethod", timeout=5)


def test_l1_load_session_round_trip(client) -> None:
    client.initialize(timeout=5)
    assert client.load_session(timeout=5, sessionId="s-acp-1")["sessionId"] == "s-acp-loaded"


def test_l1_cancel_is_notification_without_response_wait(client) -> None:
    client.initialize(timeout=5)
    client.cancel(sessionId="s-acp-1")  # must not block waiting for a response
    client.new_session(timeout=5)
    assert client.session_id == "s-acp-1"


def test_l1_timeout_is_unknown(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(RequestTimeout):
        client.command("hang", timeout=0.5)
