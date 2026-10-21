"""N010 Goose client tests — L1 fake ACP upstream.

Proves shared-seam ACP handling for the goose family layer; no real goose
binary here (L2 untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport.channel import LaunchSpec, ProcessChannel
from ordessa_agents.harness.protocols.acp import AcpRemoteError
from ordessa_harness_goose.client import GooseClient

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
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "1", "agentCapabilities": {}}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "gs-1"}})
        elif method == "session/prompt":
            send({"jsonrpc": "2.0", "id": 42, "method": "session/request_permission",
                  "params": {"sessionId": "gs-1", "toolCall": {"toolCallId": "t1"}, "options": []}})
            reply = json.loads(sys.stdin.readline())
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn", "reply": reply.get("result")}})
        elif method == "_goose/extensionMethod":
            send({"jsonrpc": "2.0", "id": rid, "result": {"goose": "ok"}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no method %s" % method}})
        send({"jsonrpc": "2.0", "method": "_goose/telemetryLike", "params": {"keep": "verbatim"}})
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_goose.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build([sys.executable, str(script)], home=str(tmp_path / "home"), cwd=str(tmp_path))
    channel = ProcessChannel.launch(spec, name="fake-goose")
    yield GooseClient(channel)
    channel.close()


def test_l1_initialize_and_session(client) -> None:
    assert client.initialize(timeout=5)["protocolVersion"] == "1"
    assert client.new_session(timeout=5)["sessionId"] == "gs-1"
    assert client.session_id == "gs-1"


def test_l1_permission_callback_identity_and_no_auto_approve(client) -> None:
    client.initialize(timeout=5)
    client.new_session(timeout=5)
    seen = []

    def on_request(message):
        seen.append(message)
        client.reply_permission(message.id, "cancelled")

    result = client.prompt(timeout=5, on_request=on_request, prompt={"text": "go"})
    assert seen[0].id == 42
    assert result["reply"]["outcome"]["outcome"] == "cancelled"


def test_l1_unknown_extension_methods_preserved(client) -> None:
    client.initialize(timeout=5)
    client.new_session(timeout=5)
    client.prompt(timeout=5, on_request=lambda m: client.reply_request(m.id, {"outcome": {"outcome": "rejected"}}))
    client.pump(timeout=1)
    methods = [e.raw.get("method") for e in client.events()]
    assert "_goose/telemetryLike" in methods  # G4


def test_l1_generic_command_and_typed_error(client) -> None:
    client.initialize(timeout=5)
    assert client.command("_goose/extensionMethod", timeout=5) == {"goose": "ok"}
    with pytest.raises(AcpRemoteError):
        client.command("notAMethod", timeout=5)


def test_l1_cancel_is_notification(client) -> None:
    client.initialize(timeout=5)
    client.cancel(sessionId="gs-1")
    client.new_session(timeout=5)  # channel still healthy


def test_launch_refuses_unauthenticated_flag_before_spawn(tmp_path) -> None:
    # SAFETY counter-example: bypassing the harness planner still cannot get
    # --dangerously-unauthenticated through the client launch path.
    script = tmp_path / "fake_goose.py"
    script.write_text("import time; time.sleep(5)", encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script), "--dangerously-unauthenticated"],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    with pytest.raises(ValueError):
        GooseClient.launch(spec)
