"""Controlled loopback fake Streamable-HTTP MCP server (**L2** witness).

The server side of every test in this directory. It is deliberately
branded as a fake: an in-process ``ThreadingHTTPServer`` on
``127.0.0.1:0`` that speaks just enough of the Streamable-HTTP JSON-RPC
shape (POST frames, JSON or SSE answers, ``Mcp-Session-Id`` issuance,
``MCP-Protocol-Version`` echo) to hold the client honest.

Server-side witnesses the tests assert against (verification.md
counterexample 3 discipline - "no pooling" and "the gate refused" are
proven from the OTHER side of the wire, not from client self-reports):

* ``connections``: TCP connections accepted (keep-alive: one per client);
* ``sessions_issued``: one fresh session id per ``initialize`` - two
  distinct entries prove two independent server-visible sessions;
* ``requests``: every processed frame (method, headers snapshot, body,
  presented session id, connection index);
* ``calls``: executed ``tools/call`` count (the side-effect ledger);
* ``refusals``: 401s, redirect answers and other scripted rejections.

Modes are switchable at runtime (``server.mode = "..."``) so a test can
bring a session up normally and then drive exactly one pathological
request.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS_ECHO = [{"name": "echo",
               "inputSchema": {"type": "object",
                               "properties": {"text": {"type": "string"}}}}]
TOOLS_DRIFT = TOOLS_ECHO + [{"name": "extra", "inputSchema": {"type": "object"}}]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        server = self.server
        with server.state_lock:
            server.connections += 1
            self._conn_index = server.connections

    def do_POST(self):  # noqa: N802
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # a client that refused/timed out hangs up first: expected
            pass

    def log_message(self, *args):  # keep pytest output quiet
        pass

    # -- one request ---------------------------------------------------------------

    def _handle(self):
        server = self.server
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            frame = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            frame = {"method": "<nonjson>"}
        method = frame.get("method")
        record = {
            "method": method,
            "path": self.path,
            "body": frame,
            "presented_session": self.headers.get("Mcp-Session-Id"),
            "protocol_version_header": self.headers.get("Mcp-Protocol-Version"),
            "authorization": self.headers.get("Authorization"),
            "connection": self._conn_index,
        }
        mode = server.mode
        # the request REACHED the server: ledger first (the witness of
        # "received at most once" must not depend on the scripted delay)
        with server.state_lock:
            server.requests.append(record)

        if mode == "redirect":
            with server.state_lock:
                server.refusals.append("redirect")
            self.send_response(302)
            self.send_header("Location", "/moved")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if mode == "require-auth" and record["authorization"] != server.expected_secret:
            with server.state_lock:
                server.refusals.append("401")
            self.send_error(401)
            return

        if mode == "slow" and method == "initialize":
            time.sleep(1.5)
        if mode in ("slow-call", "hang-call") and method == "tools/call":
            time.sleep(2.0)

        with server.state_lock:
            answer = self._answer_for(server, mode, frame, method)
        if answer is None:
            # notifications/initialized: accepted, no body
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status, payload = answer
        if status >= 500:
            self.send_error(status)
            return
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        if mode == "badjson" and method in ("tools/list", "tools/call", "initialize"):
            body = b"\xff this is not json"
        if mode == "oversized-list" and method == "tools/list":
            body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                               "result": {"tools": [
                                   {"name": "x" * 8192, "pad": "y" * 8192}]}}).encode()
        if mode == "sse-list" and method == "tools/list":
            self._send_sse(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if payload.get("result") and method == "initialize":
            self.send_header("Mcp-Session-Id", server.sessions_issued[-1])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _answer_for(self, server, mode, frame, method):
        """Decide the reply under the server lock (mutating witnesses too)."""
        request_id = frame.get("id")
        if method == "initialize":
            if mode == "init_error":
                server.refusals.append("initialize-error")
                return 200, {"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32600, "message": "unsupported offer"}}
            version = {"downgrade": "2024-11-05", "mismatch": "1999-01-01"}.get(
                mode, "2025-11-25")
            server.sessions_issued.append(str(uuid.uuid4()))
            return 200, {"jsonrpc": "2.0", "id": request_id,
                         "result": {"protocolVersion": version, "capabilities": {},
                                    "serverInfo": {"name": "fake-streamable-mcp",
                                                   "version": "t011"}}}
        if method == "notifications/initialized":
            server.initialized_notifications += 1
            return None
        if method == "tools/list":
            tools = TOOLS_DRIFT if server.drift and len(
                [r for r in server.requests if r["method"] == "tools/list"]) >= 1 else TOOLS_ECHO
            return 200, {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        if method == "tools/call":
            if mode == "call_error":
                server.refusals.append("call-error")
                return 200, {"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32603, "message": "tool execution failed"}}
            if mode == "http500-call":
                return 500, None
            server.calls.append(frame.get("params"))
            params = frame.get("params") or {}
            return 200, {"jsonrpc": "2.0", "id": request_id,
                         "result": {"content": [
                             {"type": "text",
                              "text": "echoed " + str(params.get("arguments"))}]}}
        return 200, {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32601, "message": "method not found"}}

    def _send_sse(self, body: bytes) -> None:
        payload = b"event: message\ndata: " + body + b"\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class FakeStreamableServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode: str = "normal", tls: tuple | None = None,
                 expected_secret: str = "") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.expected_secret = expected_secret
        self.state_lock = threading.Lock()
        self.connections = 0
        self.requests: list = []
        self.calls: list = []
        self.refusals: list = []
        self.sessions_issued: list = []
        self.initialized_notifications = 0
        self.drift = False
        self.base_url = f"http://127.0.0.1:{self.server_address[1]}"
        if tls is not None:
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(tls[0], tls[1])
            self.socket = context.wrap_socket(self.socket, server_side=True)
            self.base_url = f"https://127.0.0.1:{self.server_address[1]}"
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def handle_error(self, request, client_address):
        # a client that refused/timed out hangs up first: late OSErrors are
        # expected; anything else stays loud
        import sys

        exc = sys.exc_info()[1]
        if not isinstance(exc, OSError):
            super().handle_error(request, client_address)

    # -- witnesses -----------------------------------------------------------------

    def methods_seen(self) -> list:
        with self.state_lock:
            return [record["method"] for record in self.requests]

    def requests_for(self, method: str) -> list:
        with self.state_lock:
            return [dict(r) for r in self.requests if r["method"] == method]

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=3)
