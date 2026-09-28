"""A real controlled peer supplies native identity; relay claims supply none."""
from __future__ import annotations

import json
import os
import queue
import shutil
import time
from pathlib import Path

from ordessa_harness.server_acp.access_entry import AccessEntryTransport
from ordessa_harness.server_acp.registry import AcpChannelRegistry


ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins/harness/runtime/access-entry.mjs"
PEER = ROOT / "tests/integration/acp_orchestration/fixtures/bidirectional_acp_peer.mjs"


class Records:
    def __init__(self):
        self.count = 0

    def create_session(self, **_kwargs):
        return "accepted", {"session_id": f"ledger-{self.count + 1}"}

    def create_turn(self, **_kwargs):
        self.count += 1
        return True, "accepted", {"turn_id": f"execution-{self.count}"}

    def finish_cancelled(self, *_args, **_kwargs):
        pass


class Profiles:
    def get(self, _profile_id):
        return {"config_revision": 1, "config_object_digest": "sha256:profile"}


def test_real_controlled_peer_session_new_observation_is_channel_bound(tmp_path):
    node = shutil.which("node")
    assert node is not None
    replies: queue.Queue[str] = queue.Queue()

    def launch(*, harness_id, cwd, on_line, on_exit):
        def receive(line):
            replies.put(line)
            on_line(line)

        return AccessEntryTransport(
            node=node, entry=str(ENTRY), harness_id=harness_id, cwd=cwd,
            adapter={"command": node, "args": [str(PEER)]},
            on_line=receive, on_exit=on_exit,
            environment={**os.environ, "HD003_LOG": str(tmp_path / "peer")},
            controlled_test_peer=True,
        ).start()

    registry = AcpChannelRegistry(session_records=Records(), profile_records=Profiles(), launch=launch)
    opened = registry.acquire(harness_id="pi", workspace_id="ws", profile_id="p", cwd=str(tmp_path))
    channel = registry.get(opened["connectionId"])
    assert channel is not None
    try:
        assert registry.native_session_observation(opened["connectionId"], "claimed") is None
        # A client claim in a different method is not native identity evidence.
        channel.transport.send_line(json.dumps({"jsonrpc": "2.0", "id": 1,
            "method": "session/prompt", "params": {"sessionId": "claimed", "prompt": []}}))
        channel.transport.send_line(json.dumps({"jsonrpc": "2.0", "id": 2,
            "method": "session/new", "params": {"cwd": str(tmp_path), "mcpServers": []}}))
        deadline = time.monotonic() + 3
        native = None
        while time.monotonic() < deadline:
            frame = json.loads(replies.get(timeout=max(.01, deadline - time.monotonic())))
            if frame.get("id") == 2:
                native = frame["result"]["sessionId"]
                break
        assert native
        fact = registry.native_session_observation(opened["connectionId"], native)
        assert fact is not None
        assert (fact.connection_id, fact.execution_id, fact.ledger_session_id,
                fact.native_session_id) == (opened["connectionId"], opened["executionId"],
                                            "ledger-1", native)
        assert registry.native_session_observation("other", native) is None
    finally:
        assert registry.release(opened["connectionId"])["released"] is True
    assert registry.native_session_observation(opened["connectionId"], native) is None


def test_only_unique_correlated_agent_success_can_establish_identity(tmp_path):
    sent = []
    callbacks = []

    class Transport:
        def send_line(self, line):
            sent.append(line)

        def terminate(self):
            pass

    def launch(*, on_line, **_kwargs):
        callbacks.append(on_line)
        return Transport()

    registry = AcpChannelRegistry(session_records=Records(), profile_records=Profiles(), launch=launch)
    opened = registry.acquire(harness_id="pi", workspace_id="ws", profile_id="p", cwd=str(tmp_path))
    channel = registry.get(opened["connectionId"])
    assert channel is not None

    def client(request_id, method="session/new"):
        line = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                           "params": {"cwd": str(tmp_path), "sessionId": "claimed"}})
        channel.transport.send_line(line)
        assert sent[-1] == line  # transparent client-to-Agent bytes

    def agent(request_id, native, **extra):
        callbacks[0](json.dumps({"jsonrpc": "2.0", "id": request_id,
                                 "result": {"sessionId": native}, **extra}))

    callbacks[0](json.dumps({"jsonrpc": "2.0", "method": "session/update",
                             "params": {"sessionId": "forged"}}))
    client(1, "session/prompt")
    agent(1, "claimed")
    assert registry.native_session_observation(opened["connectionId"], "claimed") is None
    client(2)
    agent(999, "unrelated")
    assert registry.native_session_observation(opened["connectionId"], "unrelated") is None
    client(2)  # duplicate ID makes the pending response ambiguous
    agent(2, "duplicated")
    assert registry.native_session_observation(opened["connectionId"], "duplicated") is None
    client(3)
    callbacks[0](json.dumps({"jsonrpc": "2.0", "id": 3, "error": {"code": -1},
                             "result": {"sessionId": "error"}}))
    assert registry.native_session_observation(opened["connectionId"], "error") is None
    client(4)
    agent(4, "valid")
    assert registry.native_session_observation(opened["connectionId"], "valid") is not None

    second = registry.acquire(harness_id="pi", workspace_id="other", profile_id="p", cwd=str(tmp_path))
    assert registry.native_session_observation(second["connectionId"], "valid") is None
    registry.release(opened["connectionId"])
    assert registry.native_session_observation(opened["connectionId"], "valid") is None
    callbacks[0](json.dumps({"jsonrpc": "2.0", "id": 5, "result": {"sessionId": "late"}}))
    assert registry.native_session_observation(opened["connectionId"], "late") is None
    registry.stop_all()


def test_failed_send_never_promotes_a_later_agent_reply(tmp_path):
    callbacks = []

    class Transport:
        def send_line(self, _line):
            raise OSError("write failed")

        def terminate(self):
            pass

    def launch(*, on_line, **_kwargs):
        callbacks.append(on_line)
        return Transport()

    registry = AcpChannelRegistry(session_records=Records(), profile_records=Profiles(), launch=launch)
    opened = registry.acquire(harness_id="pi", workspace_id="ws", profile_id="p", cwd=str(tmp_path))
    channel = registry.get(opened["connectionId"])
    assert channel is not None
    import pytest
    with pytest.raises(OSError, match="write failed"):
        channel.transport.send_line('{"jsonrpc":"2.0","id":1,"method":"session/new"}')
    callbacks[0]('{"jsonrpc":"2.0","id":1,"result":{"sessionId":"forged"}}')
    assert registry.native_session_observation(opened["connectionId"], "forged") is None
    registry.stop_all()
