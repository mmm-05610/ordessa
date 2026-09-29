"""Probe-test fixtures: the one place the T01/T02 side-effect lockdown is
*explicitly* lifted, per test, by requesting ``probe_primitives``.

The package-level autouse guard (``tests/conftest.py``) is untouched - every
test in this directory still runs it first; ``probe_primitives`` only
re-binds the real ``socket.socket`` / ``subprocess`` entry points for the
duration of a requesting test via its own ``monkeypatch``. A probe test that
forgets the fixture simply cannot open sockets or spawn, and fails loudly.

Side effects stay loopback-only by construction: fake HTTP servers bind
``127.0.0.1:0``, fake stdio servers are this directory's test scripts, and no
test talks to anything beyond the machine.
"""
from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from helpers import FAKE_SERVER, HERE  # noqa: F401 (re-exported for tests)

# Captured at import time, before any monkeypatch can be in effect.
_REAL_SOCKET = socket.socket
_REAL_POPEN = subprocess.Popen
_REAL_RUN = subprocess.run
_REAL_CALL = subprocess.call


@pytest.fixture
def probe_primitives(monkeypatch, no_side_effect_primitives):
    """Lift the lockdown *for this test only*; the autouse guard itself stays."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)


# -- loopback fake Streamable-HTTP endpoint --------------------------------------

_INIT_RESULT = {
    "protocolVersion": "2025-11-25",
    "capabilities": {},
    "serverInfo": {"name": "fake-http-mcp", "version": "0.1"},
    # present in the envelope to pin that the probe ignores any catalog (FR-02)
    "tools": [{"name": "unseen-http-tool", "description": "must be ignored"}],
}


class _FakeHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # probe refused and hung up (e.g. timeout path); keep output clean

    def _handle(self):
        server = self.server
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        server.seen.append((dict(self.headers), body))
        mode = server.mode
        if mode == "slow":
            time.sleep(2.0)
        if mode in ("auth401", "auth403"):
            self.send_error(401 if mode == "auth401" else 403)
            return
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/moved")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "oversized":
            payload = b"x" * 8192
            self._send(200, "application/json", payload)
            return
        if mode == "nonjson":
            self._send(200, "application/json", b"\xff not json at all")
            return
        if mode == "html":
            self._send(200, "text/html", b"<html>mcp this is not</html>")
            return
        response = {"jsonrpc": "2.0", "id": 1, "result": dict(_INIT_RESULT)}
        if mode == "downgrade":
            response["result"]["protocolVersion"] = "2024-11-05"
        elif mode == "mismatch":
            response["result"]["protocolVersion"] = "1999-01-01"
        elif mode == "badid":
            response["id"] = 777
        elif mode == "noresult":
            response = {"jsonrpc": "2.0", "id": 1}
        if mode == "sse":
            payload = ("event: message\ndata: " + json.dumps(response) + "\n\n").encode()
            self._send(200, "text/event-stream", payload)
            return
        self._send(200, "application/json", json.dumps(response).encode())

    def _send(self, status, content_type, payload):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # keep pytest output quiet
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode):
        super().__init__(("127.0.0.1", 0), _FakeHTTPHandler)
        self.mode = mode
        self.seen: list = []

    def handle_error(self, request, client_address):
        # A probe that refused an answer hangs up first; the late-write
        # OSError is expected, not a test failure. Anything else stays loud.
        import sys

        exc = sys.exc_info()[1]
        if not isinstance(exc, OSError):
            super().handle_error(request, client_address)


class _HttpEndpoint:
    def __init__(self, mode, tls_cert=None):
        import ssl

        self.server = _Server(mode)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        if tls_cert is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(tls_cert[0], tls_cert[1])
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            self.base_url = f"https://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def seen(self):
        return self.server.seen

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


@pytest.fixture
def http_endpoint():
    """Factory: ``http_endpoint(mode)`` -> loopback endpoint + request log."""
    created = []

    def _make(mode, tls_cert=None):
        endpoint = _HttpEndpoint(mode, tls_cert=tls_cert)
        created.append(endpoint)
        return endpoint

    yield _make
    for endpoint in created:
        endpoint.close()


@pytest.fixture(scope="session")
def self_signed_tls(tmp_path_factory):
    """A throwaway 127.0.0.1 certificate under pytest's tmp root (never in
    the source tree) so TLS *default verification* is proven against a real
    handshake, not asserted from docs. Needs openssl on PATH - environment
    fact registered in reports/t03.md; if absent this fails the tests that
    use it (never skips). Session-scoped, so the subprocess call temporarily
    rebinds the captured original itself rather than depending on the
    function-scoped ``probe_primitives`` lift."""
    cert_dir = tmp_path_factory.mktemp("probe-tls")
    cert = str(cert_dir / "cert.pem")
    key = str(cert_dir / "key.pem")
    blocked = subprocess.run
    subprocess.run = _REAL_RUN
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", key, "-out", cert, "-days", "2",
             "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
            check=True, capture_output=True, timeout=60)
    finally:
        subprocess.run = blocked
    return cert, key
