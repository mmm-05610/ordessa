"""Offline negatives for the MCP->Ordessa transport (no MCP SDK, no remote host).

Every case uses a local controlled server on a loopback ephemeral port; nothing
is ever sent to an arbitrary address.
"""
import http.server
import json
import threading

import pytest

from ordessa_mcp_server.transport import (
    MAX_BYTES, TransportRefused, validate_endpoint, validate_method, wire_call,
)


class _Recorder(http.server.BaseHTTPRequestHandler):
    """A controlled local server; its handler is swapped per test."""

    handler = staticmethod(lambda self: None)

    def do_POST(self):
        type(self).handler(self)

    def log_message(self, *args):
        pass


def _serve(handler):
    """Start a loopback server on an ephemeral port; return (origin, server)."""
    class Bound(_Recorder):
        pass

    Bound.handler = staticmethod(handler)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Bound)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


@pytest.mark.parametrize("method", [
    "../evil", "a.b/c", "a.b?x=1", "a.b#frag", "a.b\r\nX-Injected: 1", "nodot",
    "a..b", "A.b", "a.b ", "a. b", "", "a.b\nc",
])
def test_method_pattern_refuses_path_query_fragment_and_crlf(method):
    with pytest.raises(TransportRefused):
        validate_method(method)


@pytest.mark.parametrize("method", ["server.hello", "agents.capabilities", "a.b.c"])
def test_method_pattern_accepts_bare_wire_names(method):
    assert validate_method(method) == method


@pytest.mark.parametrize("endpoint", [
    "http://example.com", "http://user:pass@127.0.0.1:1", "http://127.0.0.1:1?x=1",
    "http://127.0.0.1:1#f", "http://127.0.0.1:1/path", "ftp://127.0.0.1", "http://[::1]:1/ok",
    "http://127.0.0.1:1\n", "",
])
def test_endpoint_refuses_non_origin_or_non_loopback_http(endpoint):
    with pytest.raises(TransportRefused):
        validate_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:1234", "https://ordessa.example"])
def test_endpoint_accepts_loopback_http_or_https(endpoint):
    assert validate_endpoint(endpoint) == endpoint


def test_missing_token_fails_locally_without_a_socket():
    with pytest.raises(TransportRefused, match="token"):
        wire_call("http://127.0.0.1:1", "", "server.hello")


def test_redirect_is_refused_and_authorization_is_not_forwarded():
    victim_hits = []
    victim, victim_server = _serve(
        lambda self: victim_hits.append(self.headers.get("Authorization")))

    def redirect(self):
        self.send_response(302)
        self.send_header("Location", victim + self.path)
        self.end_headers()

    origin, server = _serve(redirect)
    try:
        with pytest.raises(TransportRefused, match="REDIRECT_REFUSED"):
            wire_call(origin, "secret", "server.hello")
        assert victim_hits == []  # the bearer token never reached the redirect target
    finally:
        server.shutdown()
        victim_server.shutdown()


def test_oversized_response_is_refused():
    def big(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"x" * (MAX_BYTES + 10))

    origin, server = _serve(big)
    try:
        # A non-effectful method keeps the observation-failure class.
        with pytest.raises(TransportRefused, match="WIRE_RESPONSE_INVALID"):
            wire_call(origin, "t", "agents.capabilities")
    finally:
        server.shutdown()


def test_invalid_wire_envelope_is_refused_without_leaking_the_body():
    def bad(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"secret": "leak-me"}')

    origin, server = _serve(bad)
    try:
        with pytest.raises(TransportRefused) as refusal:
            wire_call(origin, "t", "server.hello")
        assert "leak-me" not in str(refusal.value)
    finally:
        server.shutdown()


def test_valid_envelope_returns_the_result():
    def good(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    origin, server = _serve(good)
    try:
        assert wire_call(origin, "t", "server.hello") == {"ok": True}
    finally:
        server.shutdown()


def test_effectfulness_comes_from_the_published_metadata():
    from ordessa_mcp_server.transport import effectful

    assert effectful("agents.capabilities") is False
    assert effectful("agents.profiles.list") is False
    assert effectful("agents.profiles.create") is True
    # An unknown method is treated as possibly-effectful, never as a safe read.
    assert effectful("unknown.method") is True


def _drop_response(self):
    """Accept the request then close with no body (a lost response)."""
    self.rfile.read(int(self.headers.get("Content-Length", "0")))
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.end_headers()
    self.close_connection = True


def test_lost_effectful_response_is_unknown_not_a_safe_failure():
    """A possibly-delivered write whose response is lost is OUTCOME_UNKNOWN.

    The controlled server only *receives* the request (no persisted write), so
    this shows the class, not that the write committed.
    """
    origin, server = _serve(_drop_response)
    try:
        with pytest.raises(TransportRefused, match="OUTCOME_UNKNOWN"):
            wire_call(origin, "t", "agents.profiles.create", {"requestId": "r1"})
        # A lost *observation* (non-effectful) is a different, non-unknown class.
        with pytest.raises(TransportRefused) as read_refusal:
            wire_call(origin, "t", "agents.capabilities", {})
        assert "OUTCOME_UNKNOWN" not in str(read_refusal.value)
    finally:
        server.shutdown()


def test_request_ids_are_unique_per_logical_call():
    ids = []

    def record(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        ids.append(body["id"])
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    origin, server = _serve(record)
    try:
        assert wire_call(origin, "t", "server.hello") == {"ok": True}
        assert wire_call(origin, "t", "server.hello") == {"ok": True}
        assert len(ids) == 2 and ids[0] != ids[1] and all(ids)
    finally:
        server.shutdown()


def test_effectful_write_is_attempted_exactly_once_and_never_retried():
    """The adapter sends an effectful call once; a lost response is not retried."""
    attempts = []

    def write_then_drop(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        attempts.append(body["id"])
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.close_connection = True

    origin, server = _serve(write_then_drop)
    try:
        with pytest.raises(TransportRefused, match="OUTCOME_UNKNOWN"):
            wire_call(origin, "t", "agents.profiles.create", {"requestId": "r1"})
        assert len(attempts) == 1  # exactly one attempt; no automatic retry
    finally:
        server.shutdown()
