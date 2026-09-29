"""Self-check of the controlled ACP peer fixture before any product seam is trusted.

Drives `fixtures/bidirectional_acp_peer.mjs` with a minimal NDJSON stdio client
and proves the four evidence paths the target tests rely on: success, error,
cancel/hold, and teardown.
"""
import json
import os
import queue
import subprocess
import threading
import time

import pytest

from tests.integration.acp_orchestration.conftest import NODE, PEER, peer_events


class PeerClient:
    def __init__(self, tmp_path, environment):
        self.project = tmp_path / "peer-project"
        self.project.mkdir()
        self.process = subprocess.Popen(
            [NODE, str(PEER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=self.project, env=environment,
        )
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._id = 0

    def _pump(self):
        assert self.process.stdout
        for line in self.process.stdout:
            if line.strip():
                self._lines.put(json.loads(line))
        self._lines.put(None)

    def _next(self, timeout=15):
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("peer produced no frame (channel wedged?)") from None

    def _write(self, frame):
        self.process.stdin.write(json.dumps(frame) + "\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self._id += 1
        self.send_request(self._id, method, params)
        return self.answer_for(self._id)

    def send_request(self, request_id, method, params):
        """Send without waiting; the caller reads the answer via `answer_for`."""
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

    def answer_for(self, request_id, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"no answer for request {request_id}")
            frame = self._next(timeout=remaining)
            if frame is None:
                raise AssertionError("peer closed stdout before answering")
            if frame.get("id") == request_id and ("result" in frame or "error" in frame):
                return frame

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def read_until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._next(timeout=max(0.1, deadline - time.monotonic()))
            if frame is None:
                return "EOF"
            if predicate(frame):
                return frame
        raise AssertionError("predicate never matched before timeout")

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    log_base = str(tmp_path / "selfcheck-log")
    monkeypatch.setenv("HD003_LOG", log_base)
    peer = PeerClient(tmp_path, {**os.environ, "HD003_LOG": log_base})
    peer.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    peer.request("authenticate", {"methodId": "none"})
    session = peer.request("session/new", {"cwd": str(peer.project), "mcpServers": []})
    peer.session_id = session["result"]["sessionId"]
    peer.log_base = log_base
    yield peer
    peer.close()
    deadline = time.monotonic() + 5
    while peer.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    peer.process.kill()
    peer.process.wait(timeout=5)


def test_selfcheck_success_roundtrip(client):
    client.send_request(11, "session/prompt", {
        "sessionId": client.session_id, "prompt": [{"type": "text", "text": "hello"}]})
    update = client.read_until(lambda frame: frame.get("method") == "session/update")
    assert update["params"]["update"]["content"]["text"] == "got:hello"
    assert client.answer_for(11)["result"]["stopReason"] == "end_turn"
    rows = peer_events(client.log_base)
    new = [row for row in rows if row.get("event") == "session-new"]
    assert new and new[0]["cwdParam"] == str(client.project)
    assert new[0]["cwd"] == str(client.project)


def test_selfcheck_error_only(client):
    client.send_request(12, "session/prompt", {
        "sessionId": client.session_id,
        "prompt": [{"type": "text", "text": "scenario:rpc-error"}]})
    answer = client.answer_for(12)
    assert answer["error"]["code"] == -32603
    assert answer["error"]["data"] == {"vendorDetail": "keep-me"}


def test_selfcheck_permission_roundtrip(client):
    client.send_request(13, "session/prompt", {
        "sessionId": client.session_id,
        "prompt": [{"type": "text", "text": "scenario:permission"}]})
    reverse = client.read_until(
        lambda frame: frame.get("method") == "session/request_permission")
    assert reverse["id"] == 7777
    option_ids = [option["optionId"] for option in reverse["params"]["options"]]
    assert any(option_id.startswith("grant-") for option_id in option_ids)
    assert any(option_id.startswith("reject-") for option_id in option_ids)
    # The answer must not be fabricated while the client still holds it.
    time.sleep(0.5)
    assert not [row for row in peer_events(client.log_base)
                if row.get("event") == "permission-answer"]
    client._write({"jsonrpc": "2.0", "id": 7777,
                   "result": {"outcome": {"outcome": "selected",
                                          "optionId": option_ids[0]}}})
    assert client.answer_for(13)["result"]["stopReason"] == "end_turn"
    answers = [row for row in peer_events(client.log_base)
               if row.get("event") == "permission-answer"]
    assert answers[0]["frame"]["result"]["outcome"]["optionId"] == option_ids[0]


def test_selfcheck_hold_then_cancel(client):
    client.send_request(14, "session/prompt", {
        "sessionId": client.session_id,
        "prompt": [{"type": "text", "text": "scenario:hang"}]})
    time.sleep(0.3)
    client.notify("session/cancel", {"sessionId": client.session_id})
    assert client.answer_for(14)["result"]["stopReason"] == "cancelled"


def test_selfcheck_die_closes_channel(client):
    client.send_request(15, "session/prompt", {
        "sessionId": client.session_id,
        "prompt": [{"type": "text", "text": "scenario:die"}]})
    chunk = client.read_until(
        lambda frame: frame.get("method") == "session/update")
    assert chunk["params"]["update"]["content"]["text"] == "pre-death-chunk"
    assert client.read_until(lambda frame: True) == "EOF"
    deadline = time.monotonic() + 5
    while client.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.process.returncode == 3


def test_selfcheck_cleanup_on_stdin_close(client):
    assert peer_events(client.log_base)
    client.process.stdin.close()
    deadline = time.monotonic() + 5
    while client.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.process.returncode == 0
    assert [row for row in peer_events(client.log_base)
            if row.get("event") == "stdin-eof"]
