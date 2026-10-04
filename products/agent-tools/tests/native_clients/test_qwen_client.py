"""N007 Qwen serve client tests — L1 fake upstream (http.server on loopback).

These prove client-side behaviour only; no real qwen binary exists on this
machine (L2 untested, registered). The fake upstream is marked L1 in test
names and is never presented as upstream compatibility evidence.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ordessa_agent_tools.native_clients import (
    ChannelClosed,
    LoopbackHttpChannel,
    NonLoopbackRefused,
)
from ordessa_agent_tools.native_clients.qwen import (
    QwenApiError,
    QwenClient,
    TURN_TERMINAL_EVENTS,
)

HITS: dict[str, int] = {}
BODIES: dict[str, object] = {}
HEADERS_SEEN: dict[str, str] = {}


class FakeQwenServe(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _send_json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _record(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.headers.get("X-Qwen-Client-Id"):
            HEADERS_SEEN["X-Qwen-Client-Id"] = self.headers["X-Qwen-Client-Id"]

    def do_GET(self):
        self._record()
        if self.path == "/capabilities":
            self._send_json(
                200,
                {
                    "v": 1,
                    "protocolVersions": {"current": "v1", "supported": ["v1"]},
                    "mode": "http-bridge",
                    "features": ["health", "capabilities", "session_create"],
                    "workspaceCwd": "/fake/workspace",
                },
            )
        elif self.path == "/session/s1/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            frames = [
                "event: session_update\n"
                'data: {"id":1,"v":1,"type":"session_update",'
                '"data":{"sessionUpdate":"agent_message_chunk"}}\n\n',
                "event: turn_complete\n"
                'data: {"id":2,"v":1,"type":"turn_complete",'
                '"data":{"promptId":"p-1","stopReason":"end_turn"}}\n\n',
                "event: future.unknownType\n"
                'data: {"id":3,"v":1,"type":"future.unknownType",'
                '"data":{"keep":"verbatim"}}\n\n',
            ]
            for frame in frames:
                self.wfile.write(frame.encode())
        else:
            self._send_json(404, {"error": "no route " + self.path, "code": "session_not_found"})

    def do_POST(self):
        self._record()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else {}
        BODIES[self.path] = body
        if self.path == "/session":
            self._send_json(
                200,
                {
                    "sessionId": "s1",
                    "workspaceCwd": body.get("cwd", "/fake/workspace"),
                    "attached": body.get("cwd") == "/attached/work",
                },
            )
        elif self.path == "/session/s1/prompt":
            if body.get("prompt") == "HANGUP":
                self._send_json(500, {"error": "boom"})
            else:
                self._send_json(
                    202, {"promptId": "p-1", "lastEventId": 42, "eventEpoch": "e-1"}
                )
        elif self.path == "/session/s1/cancel":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/session/s1/permission/p1":
            self._send_json(200, {})
        else:
            self._send_json(404, {"error": "no route " + self.path})

    def do_DELETE(self):
        self._record()
        if self.path == "/session/s1":
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(404, {"error": "no route " + self.path})


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeQwenServe)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    HITS.clear()
    BODIES.clear()
    HEADERS_SEEN.clear()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_l1_handshake_capabilities_verbatim_and_client_id_header(server) -> None:
    client = QwenClient.connect(server, client_id="c1")
    caps = client.initialize()
    assert caps["v"] == 1
    assert caps["protocolVersions"] == {"current": "v1", "supported": ["v1"]}
    assert caps["workspaceCwd"] == "/fake/workspace"
    assert HEADERS_SEEN["X-Qwen-Client-Id"] == "c1"
    client.close()


def test_l1_create_session_defaults_to_thread_scope(server) -> None:
    client = QwenClient.connect(server)
    session = client.create_session()
    assert session["sessionId"] == "s1"  # native id surfaced verbatim
    assert session["attached"] is False
    assert BODIES["/session"]["sessionScope"] == "thread"  # no silent shared session
    client.close()


def test_l1_attached_session_is_surfaced_not_rewritten(server) -> None:
    client = QwenClient.connect(server)
    session = client.create_session(cwd="/attached/work", session_scope="single")
    # the daemon already owned a session; the attach fact is surfaced, never
    # converted into a "new" session by the client
    assert session["attached"] is True
    assert session["sessionId"] == "s1"
    assert BODIES["/session"]["sessionScope"] == "single"
    client.close()


def test_l1_send_is_receipt_not_completion(server) -> None:
    client = QwenClient.connect(server)
    receipt = client.send("s1", [{"type": "text", "text": "hi"}])
    assert receipt == {"promptId": "p-1", "lastEventId": 42, "eventEpoch": "e-1"}
    # the receipt never claims a completed answer (G6 counter-example)
    assert "completion" not in json.dumps(receipt)
    assert "stopReason" not in receipt
    client.close()


def test_l1_sse_unknown_preserved_and_stream_end_not_completion(server) -> None:
    client = QwenClient.connect(server)
    events = list(client.events("s1", max_events=3))
    kinds = [event.event for event in events]
    assert kinds == ["session_update", "turn_complete", "future.unknownType"]
    unknown = next(e for e in events if e.event == "future.unknownType")
    assert json.loads(unknown.data)["data"] == {"keep": "verbatim"}  # G4
    terminal = next(e for e in events if e.event in TURN_TERMINAL_EVENTS)
    assert json.loads(terminal.data)["data"]["promptId"] == "p-1"
    # the stream ended; ending is NOT a completion frame and none was invented
    assert TURN_TERMINAL_EVENTS == {"turn_complete", "turn_error"}
    assert all(e.event != "completed" for e in events)
    client.close()


def test_l1_cancel_uses_explicit_route(server) -> None:
    client = QwenClient.connect(server)
    assert client.cancel("s1") == 204
    assert HITS.get("/session/s1/cancel") == 1
    client.close()


def test_l1_close_session_route(server) -> None:
    client = QwenClient.connect(server)
    assert client.close_session("s1") == 204
    assert HITS.get("/session/s1") == 1
    client.close()


def test_l1_permission_vote_is_explicit_and_never_automatic(server) -> None:
    client = QwenClient.connect(server)
    assert HITS.get("/session/s1/permission/p1", 0) == 0  # nothing auto-voted
    with pytest.raises(ValueError):
        client.respond_permission("s1", "p1")  # no default choice
    assert HITS.get("/session/s1/permission/p1", 0) == 0  # refused before any write
    result = client.respond_permission("s1", "p1", option_id="proceed_once")
    assert result == {}
    assert HITS.get("/session/s1/permission/p1") == 1
    assert BODIES["/session/s1/permission/p1"] == {
        "outcome": {"outcome": "selected", "optionId": "proceed_once"}
    }
    client.close()


def test_l1_non_loopback_refused() -> None:
    with pytest.raises(NonLoopbackRefused):
        QwenClient.connect("http://example.com:4170")


def test_l1_api_error_is_typed_and_never_retried(server) -> None:
    client = QwenClient.connect(server)
    with pytest.raises(QwenApiError) as excinfo:
        client.send("s1", "HANGUP")
    assert excinfo.value.status == 500
    assert HITS.get("/session/s1/prompt") == 1  # one send, no retry (G11)
    client.close()


def test_l1_unknown_route_is_typed_error(server) -> None:
    client = QwenClient.connect(server)
    with pytest.raises(QwenApiError) as excinfo:
        client.session_status("s1")  # fake upstream lacks the status route
    assert excinfo.value.status == 404
    client.close()


def test_l1_close_then_use_is_channel_closed(server) -> None:
    client = QwenClient.connect(server)
    client.close()
    with pytest.raises(ChannelClosed):
        client.initialize()


def test_describe_has_no_runtime_ready() -> None:
    from ordessa_agent_tools.native_clients import qwen

    described = qwen.describe()
    assert described["familyId"] == "qwen"
    assert "runtimeReady" not in described
    assert described["protocol"] == "qwen-serve-http/1"


def test_loopback_channel_is_the_only_transport_accepted(server) -> None:
    # the client is a thin consumer of the frozen seam: the channel it wraps
    # is exactly LoopbackHttpChannel, so loopback enforcement cannot drift
    client = QwenClient.connect(server)
    assert isinstance(client._channel, LoopbackHttpChannel)
    client.close()
