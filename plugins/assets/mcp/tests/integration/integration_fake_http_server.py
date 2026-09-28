"""Controlled loopback fake Streamable-HTTP MCP server (**L2** witness).

The remote-lane server side of the T10 integration HTTP chain. Own copy for
``tests/integration`` (the managed_http fake is a different fixture and is
not imported; dispatch discipline: 自带 fixture). An in-process
``ThreadingHTTPServer`` on ``127.0.0.1:0`` speaking just enough of the
Streamable-HTTP JSON-RPC shape (POST frames, JSON answer, ``Mcp-Session-Id``
issuance, ``MCP-Protocol-Version`` echo) to hold the real managed HTTP client
honest.

Server-side witnesses (asymmetric proof - the ledger is read from the OTHER
side of the wire, never from the client's self-report):

* ``connections``: TCP connections accepted (keep-alive: one per client);
* ``sessions_issued``: one fresh session id per ``initialize`` - two distinct
  entries prove two independent server-visible sessions (no pooling);
* ``requests``: every processed frame (method, authorization header, body,
  presented session id);
* ``calls``: executed ``tools/call`` records (the side-effect ledger).

Modes
  normal     echo the requested protocolVersion, tools ``echo`` + ``peek``,
             ``tools/call`` answers ``<name>:<text>``
  drift      first ``tools/list`` ``[echo]``, later ``[echo, extra]``
"""
from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUPPORTED = {"2025-11-25", "2024-11-05"}
TOOLS_ECHO = [{"name": "echo",
               "inputSchema": {"type": "object",
                               "properties": {"text": {"type": "string"}}}}]
TOOLS_TWO = TOOLS_ECHO + [{"name": "peek", "inputSchema": {"type": "object"}}]
TOOLS_DRIFT = TOOLS_ECHO + [{"name": "extra", "inputSchema": {"type": "object"}}]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        with self.server.lock:
            self.server.connections += 1

    def do_POST(self):  # noqa: N802
        try:
            self._handle()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # a client that refused/timed out hangs up first: expected

    def log_message(self, *args):  # keep pytest output quiet
        pass

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
            "authorization": self.headers.get("Authorization"),
            "protocol_version_header": self.headers.get("MCP-Protocol-Version"),
            "presented_session": self.headers.get("Mcp-Session-Id"),
            "body": frame,
        }
        with server.lock:
            server.requests.append(record)

        if method == "initialize":
            requested = (frame.get("params") or {}).get("protocolVersion")
            negotiated = requested if requested in SUPPORTED else "2025-11-25"
            session_id = "sess-" + uuid.uuid4().hex
            result = {"jsonrpc": "2.0", "id": frame.get("id"), "result": {
                "protocolVersion": negotiated, "capabilities": {},
                "serverInfo": {"name": "fake-http-integration", "version": "0.1"}}}
            with server.lock:
                server.sessions_issued.append(session_id)
            self._send(200, result, session_id=session_id)
            return

        if rid := frame.get("id"):
            if method == "tools/list":
                with server.lock:
                    server.list_count += 1
                    count = server.list_count
                tools = (TOOLS_DRIFT if server.mode == "drift" and count > 1
                         else TOOLS_TWO if server.mode != "drift" else TOOLS_ECHO)
                self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}})
                return
            if method == "tools/call":
                params = frame.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                with server.lock:
                    server.calls.append({"name": name, "arguments": dict(arguments)})
                self._send(200, {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text",
                                 "text": f"{name}:{arguments.get('text', '')}"}]}})
                return
            self._send(200, {"jsonrpc": "2.0", "id": rid,
                             "error": {"code": -32601, "message": "method not found"}})
            return

        # notification (no id): accepted, no body
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, status, payload, session_id=None):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session_id is not None:
            self.send_header("Mcp-Session-Id", session_id)
        self.end_headers()
        self.wfile.write(body)


class FakeIntegrationHttpServer(ThreadingHTTPServer):
    def __init__(self, mode: str = "normal") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.daemon_threads = True
        self.mode = mode
        self.lock = threading.Lock()
        self.connections = 0
        self.sessions_issued: list = []
        self.requests: list = []
        self.calls: list = []
        self.list_count = 0
        self.base_url = f"http://127.0.0.1:{self.server_address[1]}"
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def handle_error(self, request, client_address):  # noqa: ARG002
        # A client that refused/timed out hangs up first: expected, quiet.
        return

    def methods_seen(self) -> list:
        with self.lock:
            return [r["method"] for r in self.requests]

    def authorization_seen(self) -> list:
        with self.lock:
            return [r.get("authorization") for r in self.requests]

    def close(self) -> None:
        self.shutdown()
        self.server_close()
