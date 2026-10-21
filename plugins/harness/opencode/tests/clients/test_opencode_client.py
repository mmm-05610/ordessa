"""N004 OpenCode client tests — L1 fake upstream (http.server on loopback).

These prove client-side behaviour only; no real opencode binary exists on this
machine (L2 untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ordessa_agents.harness.transport.http import (
    ChannelClosed,
    LoopbackHttpChannel,
    NonLoopbackRefused,
)
from ordessa_harness_opencode.client import OpenCodeApiError, OpenCodeClient

HITS: dict[str, int] = {}


class FakeOpenCode(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _send_json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.path == "/global/health":
            self._send_json(200, {"healthy": True, "version": "fake-0.0.1"})
        elif self.path == "/event":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = [
                "event: server.connected\ndata: {}\n\n",
                "event: session.updated\ndata: {\"sessionID\":\"s1\"}\n\n",
                "event: future.unknownType\ndata: {\"keep\":\"verbatim\"}\n\n",
            ]
            for event in events:
                self.wfile.write(event.encode())
        else:
            self._send_json(404, {"error": "no route " + self.path})

    def do_POST(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}
        if self.path == "/session":
            self._send_json(200, {"id": "s1", "title": body.get("title")})
        elif self.path == "/session/s1/message":
            if body.get("parts") == "HANGUP":
                self._send_json(500, {"error": "boom"})
            else:
                self._send_json(200, {"info": {"id": "m1", "role": "user"}, "parts": []})
        elif self.path == "/session/s1/prompt_async":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/session/s1/abort":
            self._send_json(200, {"aborted": True})
        else:
            self._send_json(404, {"error": "no route"})


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenCode)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    HITS.clear()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_l1_handshake_and_session_create(server) -> None:
    client = OpenCodeClient.connect(server)
    health = client.initialize()
    assert health == {"healthy": True, "version": "fake-0.0.1"}
    session = client.create_session(title="t")
    assert session["id"] == "s1"
    client.close()


def test_l1_send_is_receipt_not_completion(server) -> None:
    client = OpenCodeClient.connect(server)
    result = client.send("s1", [{"type": "text", "text": "hi"}])
    # the response is the recorded message — not any assistant answer
    assert result["info"]["id"] == "m1"
    assert "completion" not in json.dumps(result)
    client.close()


def test_l1_sse_unknown_events_preserved_and_disconnect_not_completion(server) -> None:
    client = OpenCodeClient.connect(server)
    events = list(client.events(max_events=3))
    kinds = [e.event for e in events]
    assert kinds[0] == "server.connected"
    assert "future.unknownType" in kinds  # G4 unknown preserved
    unknown = next(e for e in events if e.event == "future.unknownType")
    assert json.loads(unknown.data) == {"keep": "verbatim"}
    # stream ended — must NOT be treated as task completion (G6 counter-example)
    assert all(e.event != "task.completed" for e in events)
    client.close()


def test_l1_cancel_uses_explicit_abort_route(server) -> None:
    client = OpenCodeClient.connect(server)
    assert client.cancel("s1") == {"aborted": True}
    assert HITS.get("/session/s1/abort") == 1
    client.close()


def test_l1_prompt_async_204_is_acceptance_only(server) -> None:
    client = OpenCodeClient.connect(server)
    assert client.send_async("s1", [{"type": "text", "text": "go"}]) == 204
    client.close()


def test_l1_non_loopback_refused() -> None:
    with pytest.raises(NonLoopbackRefused):
        OpenCodeClient.connect("http://example.com:4096")


def test_l1_api_error_is_typed_and_never_retried(server) -> None:
    client = OpenCodeClient.connect(server)
    with pytest.raises(OpenCodeApiError) as excinfo:
        client.send("s1", "HANGUP")
    assert excinfo.value.status == 500
    assert HITS.get("/session/s1/message") == 1  # one send, no retry (G11)
    client.close()


def test_l1_unknown_route_is_typed_error(server) -> None:
    client = OpenCodeClient.connect(server)
    with pytest.raises(OpenCodeApiError):
        client.session_status()  # fake upstream lacks this route
    client.close()


def test_l1_close_then_use_is_channel_closed(server) -> None:
    client = OpenCodeClient.connect(server)
    client.close()
    with pytest.raises(ChannelClosed):
        client.initialize()
