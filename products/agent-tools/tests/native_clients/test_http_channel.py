"""L1 fixture tests for the frozen loopback HTTP/SSE channel (G4/G5/G9/G11/G12).

Positive paths run against an in-process fake upstream built on
``http.server.ThreadingHTTPServer`` bound to 127.0.0.1 on an ephemeral port.
This is a fixture-level (L1) fake upstream only: no real harness process, no
real data. These tests pin the seam's framing, typed-failure and no-retry
behaviour, and are not evidence of upstream compatibility.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from ordessa_agent_tools.native_clients import (
    ChannelClosed,
    FramingError,
    HttpChannelFailure,
    LoopbackHttpChannel,
    NonLoopbackRefused,
    SseEvent,
)

#: Valid SSE fixture: a comment line to ignore, a custom multiline event that
#: keeps id/retry, an unknown event type preserved verbatim (G4), and a
#: default "message" event that carries only an id.
SSE_OK = (
    ": keepalive comment, not an event\n"
    "\n"
    "event: custom\n"
    "data: first line\n"
    "data: second line\n"
    "id: evt-42\n"
    "retry: 2500\n"
    "\n"
    "event: future.unknownType\n"
    'data: {"k": "v"}\n'
    "\n"
    "id: trailing-id\n"
    "data: no event name\n"
    "\n"
).encode("utf-8")

#: Raw invalid UTF-8 inside a data line -> typed framing failure (G5).
SSE_BAD_UTF8 = b": ping\n\ndata: \xff\xfe not utf-8\n\n"


def _make_fake_upstream_handler(
    state: dict[str, Any], sse_ok: Path, sse_bad_utf8: Path
) -> type[BaseHTTPRequestHandler]:
    """Build a request handler for the L1 fake upstream, sharing ``state``."""

    class FakeUpstreamHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # keep fixture output quiet

        def _bytes_response(self, status: int, content_type: str, raw: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)

        def _json_response(self, status: int, payload: Any) -> None:
            self._bytes_response(status, "application/json", json.dumps(payload).encode("utf-8"))

        def _record(self, method: str, body: Any = None) -> None:
            state["requests"].append({"method": method, "path": self.path, "body": body})

        def do_GET(self) -> None:
            self._record("GET")
            if self.path == "/empty":
                self._bytes_response(204, "application/json", b"")
            elif self.path == "/sse":
                self._bytes_response(200, "text/event-stream", sse_ok.read_bytes())
            elif self.path == "/sse-bad-utf8":
                self._bytes_response(200, "text/event-stream", sse_bad_utf8.read_bytes())
            elif self.path == "/sse-error":
                self._json_response(503, {"error": "unavailable"})
            elif self.path == "/counted-500":
                state["counted_500"] += 1
                self._json_response(
                    500, {"error": "boom", "server_request_number": state["counted_500"]}
                )
            else:
                self._json_response(404, {"error": "no such fixture route", "path": self.path})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else None
            self._record("POST", body)
            if self.path == "/echo":
                self._json_response(
                    200,
                    {
                        "method": "POST",
                        "path": self.path,
                        "body": body,
                        "content_type": self.headers.get("Content-Type"),
                    },
                )
            else:
                self._json_response(404, {"error": "no such fixture route", "path": self.path})

    return FakeUpstreamHandler


@dataclass
class FakeUpstream:
    """Handle to the L1 fake upstream; every request it saw is recorded."""

    base_url: str
    state: dict[str, Any]

    def channel(self, **kwargs: Any) -> LoopbackHttpChannel:
        return LoopbackHttpChannel(self.base_url, **kwargs)

    def request_count(self, path: str) -> int:
        return sum(1 for request in self.state["requests"] if request["path"] == path)


@pytest.fixture()
def fake_upstream(tmp_path: Path) -> Iterator[FakeUpstream]:
    """L1 fixture: in-process fake upstream on 127.0.0.1:<ephemeral>.

    SSE payloads are fixture files under pytest's ``tmp_path``. Teardown
    shuts the server down and joins its thread so the test leaves no residue.
    """
    sse_ok = tmp_path / "sse_ok.sse"
    sse_ok.write_bytes(SSE_OK)
    sse_bad_utf8 = tmp_path / "sse_bad_utf8.sse"
    sse_bad_utf8.write_bytes(SSE_BAD_UTF8)
    state: dict[str, Any] = {"requests": [], "counted_500": 0}
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _make_fake_upstream_handler(state, sse_ok, sse_bad_utf8)
    )
    thread = threading.Thread(target=server.serve_forever, name="fake-upstream", daemon=True)
    thread.start()
    upstream = FakeUpstream(f"http://127.0.0.1:{server.server_address[1]}", state)
    try:
        yield upstream
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "fake upstream thread did not stop (residue)"


# -- G9/G12: loopback-only destination refusal (counter-examples) -------------


@pytest.mark.parametrize(
    "base_url",
    [
        "http://0.0.0.0:1/",  # wildcard bind address, not a usable client destination
        "http://example.com/",  # name that is not a loopback literal
        "https://127.0.0.1:1/",  # loopback host but non-http scheme
        "http://192.168.7.7:1/",  # non-loopback IPv4 literal
        "http://[2001:db8::1]:1/",  # non-loopback IPv6 literal
        "ftp://127.0.0.1:1/",  # non-http scheme
    ],
)
def test_non_loopback_destination_refused(base_url: str) -> None:
    """Counter-example (G9/G12): non-loopback destination is refused at construction.

    L1 fixture: no upstream is contacted; the constructor must refuse before
    any socket work.
    """
    with pytest.raises(NonLoopbackRefused) as excinfo:
        LoopbackHttpChannel(base_url)
    assert excinfo.value.code == "NON_LOOPBACK_REFUSED"
    assert isinstance(excinfo.value, HttpChannelFailure)


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:1", "http://localhost:1", "http://[::1]:1"],
)
def test_loopback_destinations_accepted_without_connecting(base_url: str) -> None:
    """Counterpart (G9): the accepted loopback forms construct without connecting.

    L1 fixture: construction only; no fake upstream is used and no request is
    made.
    """
    channel = LoopbackHttpChannel(base_url, timeout=0.1)
    channel.close()


# -- positive paths against the fake upstream ---------------------------------


def test_l1_request_json_roundtrip_fake_upstream(fake_upstream: FakeUpstream) -> None:
    """L1 fake upstream: request_json POSTs JSON and decodes the JSON reply."""
    channel = fake_upstream.channel(timeout=5)
    try:
        status, decoded = channel.request_json("POST", "/echo", body={"prompt": "hi", "n": 1})
    finally:
        channel.close()
    assert status == 200
    assert decoded == {
        "method": "POST",
        "path": "/echo",
        "body": {"prompt": "hi", "n": 1},
        "content_type": "application/json",
    }
    assert fake_upstream.request_count("/echo") == 1


def test_l1_request_json_empty_body_is_none_fake_upstream(fake_upstream: FakeUpstream) -> None:
    """L1 fake upstream: a bodyless 204 response decodes to ``None``."""
    channel = fake_upstream.channel(timeout=5)
    try:
        status, decoded = channel.request_json("GET", "/empty")
    finally:
        channel.close()
    assert status == 204
    assert decoded is None


def test_l1_sse_event_identity_preserved_fake_upstream(fake_upstream: FakeUpstream) -> None:
    """L1 fake upstream: SSE parsing keeps native identity and ignores comments.

    Positive (G4/G5): custom event name, multi-line data aggregation, id/retry
    kept, unknown event type surfaced verbatim, default name for a nameless
    event, ``:`` comment dropped and ``\\n\\n`` terminates each event.
    """
    channel = fake_upstream.channel(timeout=5)
    try:
        events = list(channel.stream_events("/sse"))
    finally:
        channel.close()
    assert events == [
        SseEvent(event="custom", data="first line\nsecond line", id="evt-42", retry=2500),
        SseEvent(event="future.unknownType", data='{"k": "v"}', id=None, retry=None),
        SseEvent(event="message", data="no event name", id="trailing-id", retry=None),
    ]
    # the ": keepalive comment" line produced no event
    assert all("keepalive comment" not in event.data for event in events)


def test_l1_sse_invalid_utf8_is_typed_framing_failure(fake_upstream: FakeUpstream) -> None:
    """Counter-example (G5): invalid UTF-8 in the stream raises typed FramingError.

    L1 fake upstream: the payload file holds raw ``\\xff\\xfe`` bytes; parsing
    must stop with a typed failure rather than a bare UnicodeDecodeError.
    """
    channel = fake_upstream.channel(timeout=5)
    try:
        with pytest.raises(FramingError) as excinfo:
            list(channel.stream_events("/sse-bad-utf8"))
    finally:
        channel.close()
    assert excinfo.value.code == "FRAMING_ERROR"


def test_l1_sse_http_error_status_is_typed(fake_upstream: FakeUpstream) -> None:
    """Counter-example: a 5xx on the SSE route raises typed HTTP_STATUS.

    L1 fake upstream: the fake answers 503 before any event bytes; no retry,
    no silent empty stream.
    """
    channel = fake_upstream.channel(timeout=5)
    try:
        with pytest.raises(HttpChannelFailure) as excinfo:
            list(channel.stream_events("/sse-error"))
    finally:
        channel.close()
    assert excinfo.value.code == "HTTP_STATUS"
    assert "503" in excinfo.value.detail


def test_l1_no_auto_retry_on_500_fake_upstream(fake_upstream: FakeUpstream) -> None:
    """Counter-example (G11): request_json never auto-retries a 500.

    L1 fake upstream counts requests: one client call must surface the 500 as
    a returned status, with the server seeing exactly one request. A second
    explicit call is caller-owned and moves the counter to two.
    """
    channel = fake_upstream.channel(timeout=5)
    try:
        status, decoded = channel.request_json("GET", "/counted-500")
        assert status == 500
        assert decoded == {"error": "boom", "server_request_number": 1}
        assert fake_upstream.state["counted_500"] == 1
        assert fake_upstream.request_count("/counted-500") == 1
        # only an explicit caller retry produces a second request
        status2, decoded2 = channel.request_json("GET", "/counted-500")
        assert status2 == 500
        assert decoded2 == {"error": "boom", "server_request_number": 2}
    finally:
        channel.close()


def test_l1_calls_after_close_are_channel_closed(fake_upstream: FakeUpstream) -> None:
    """Counter-example: request_json and stream_events after close() are typed refusals.

    L1 fake upstream: close() releases the channel; neither call may reach the
    fake, so its request log stays empty.
    """
    channel = fake_upstream.channel(timeout=5)
    channel.close()
    with pytest.raises(ChannelClosed) as excinfo:
        channel.request_json("GET", "/echo")
    assert excinfo.value.code == "CHANNEL_CLOSED"
    with pytest.raises(ChannelClosed) as excinfo:
        list(channel.stream_events("/sse"))
    assert excinfo.value.code == "CHANNEL_CLOSED"
    assert fake_upstream.state["requests"] == []
