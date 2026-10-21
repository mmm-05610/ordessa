"""N011 Vibe client tests — L1 fake ACP upstream.

Proves shared-seam ACP handling for the vibe family layer; no real vibe
binary here (L2 untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport.channel import LaunchSpec, ProcessChannel, RequestTimeout
from ordessa_agents.harness.protocols.acp import AcpRemoteError
from ordessa_harness_vibe.client import VibeClient

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
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "1", "agentCapabilities": {"loadSession": False}}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "vb-1"}})
        elif method == "session/prompt":
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "hang":
            continue
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown"}})
        send({"jsonrpc": "2.0", "method": "_vibe/extensionNotice", "params": {"keep": "verbatim"}})
    """
)


@pytest.fixture()
def client(tmp_path):
    script = tmp_path / "fake_vibe.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build([sys.executable, str(script)], home=str(tmp_path / "home"), cwd=str(tmp_path))
    channel = ProcessChannel.launch(spec, name="fake-vibe")
    yield VibeClient(channel)
    channel.close()


def test_l1_initialize_reports_no_load_session_capability(client) -> None:
    result = client.initialize(timeout=5)
    assert result["agentCapabilities"]["loadSession"] is False  # honest capability surface


def test_l1_session_and_prompt_receipt(client) -> None:
    client.initialize(timeout=5)
    assert client.new_session(timeout=5)["sessionId"] == "vb-1"
    assert client.prompt(timeout=5, prompt={"text": "go"})["stopReason"] == "end_turn"


def test_l1_unknown_extension_preserved(client) -> None:
    client.initialize(timeout=5)
    client.new_session(timeout=5)
    client.prompt(timeout=5, prompt={"text": "go"})
    client.pump(timeout=1)
    methods = [e.raw.get("method") for e in client.events()]
    assert "_vibe/extensionNotice" in methods  # G4
    custom = next(e for e in client.events() if e.raw.get("method") == "_vibe/extensionNotice")
    assert custom.raw["params"] == {"keep": "verbatim"}


def test_l1_typed_error_and_timeout_unknown(client) -> None:
    client.initialize(timeout=5)
    with pytest.raises(AcpRemoteError):
        client.command("notAMethod", timeout=5)
    with pytest.raises(RequestTimeout):
        client.command("hang", timeout=0.5)


def test_l1_close_owned_only(client) -> None:
    client.initialize(timeout=5)
    exit_code = client.close()
    assert exit_code is not None
