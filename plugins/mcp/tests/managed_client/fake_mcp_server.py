"""Controlled fake MCP server for the T05 managed-client **L2** evidence.

Own copy for ``tests/managed_client`` (the T03 probe fake is a different
fixture and is not imported). stdio, line-delimited JSON-RPC, loopback by
construction (a local subprocess over pipes; nothing binds a port).

Usage: ``python fake_mcp_server.py MODE STATEFILE``

The STATEFILE is the server-side witness: one JSON object per line. Every
received frame, every refusal and every executed ``tools/call`` is booked
there, so the tests can assert the asymmetric fact - "the gate refused,
therefore the *server* saw zero calls" - from the server's own log, not
from the client's account of itself.

Modes
  normal     echo the requested protocolVersion (supported ones), tools
             ``echo`` + ``peek``, ``tools/call`` answers ``<name>:<text>``
  downgrade  always answer ``2024-11-05`` (server-side downgrade to prove
             the client records the ACTUAL negotiated version)
  mismatch   answer ``1999-01-01`` (a version the client must refuse)
  drift      first ``tools/list`` answers ``[echo]``, every later one
             ``[echo, extra]`` (catalog drift)
  slowcall   sleep 1.5 s inside ``tools/call`` (in-flight / timeout tests)
  tree       after a successful initialize spawn a grandchild (same process
             group) and record its pid (process-group reaping evidence)
  stubborn   ignore SIGTERM *and* stdin EOF (only SIGKILL may end it; the
             client's escalation path must reach it)

Protocol guards (deliberate, for the negative evidence):
  * ``tools/list`` / ``tools/call`` before a completed ``initialize`` are
    refused with a JSON-RPC error (``un-negotiated protocol version``) and
    booked as ``refused`` events;
  * an ``initialize`` offering an unsupported version is refused and booked
    as ``version-refused``.
"""
import json
import os
import signal
import subprocess
import sys
import time

SUPPORTED = {"2025-11-25", "2024-11-05"}

TOOL_ECHO = {"name": "echo", "description": "echo the text",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}}}}
TOOL_PEEK = {"name": "peek", "description": "peek",
             "inputSchema": {"type": "object"}}
TOOL_EXTRA = {"name": "extra", "description": "newly appeared tool",
              "inputSchema": {"type": "object", "x": 1}}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    state_path = sys.argv[2] if len(sys.argv) > 2 else "-"
    state = open(state_path, "a", encoding="utf-8")

    def emit(event) -> None:
        state.write(json.dumps(event, sort_keys=True) + "\n")
        state.flush()

    def answer(payload) -> None:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def result(rid, body) -> None:
        answer({"jsonrpc": "2.0", "id": rid, "result": body})

    def error(rid, code, message) -> None:
        answer({"jsonrpc": "2.0", "id": rid,
                "error": {"code": code, "message": message}})

    emit({"event": "pid", "pid": os.getpid(), "pgid": os.getpgid(0),
          "mode": mode})

    if mode == "stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    negotiated = None
    list_count = 0
    call_count = 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            emit({"event": "garbage"})
            continue
        method = request.get("method")
        rid = request.get("id")
        emit({"event": "request", "method": method, "id": rid})

        if method == "initialize":
            requested = (request.get("params") or {}).get("protocolVersion")
            if mode == "mismatch":
                negotiated = "1999-01-01"
                result(rid, {"protocolVersion": "1999-01-01", "capabilities": {},
                             "serverInfo": {"name": "fake-mcp-t05", "version": "0.1"}})
                continue
            if not isinstance(requested, str) or requested not in SUPPORTED:
                emit({"event": "version-refused", "requested": requested})
                error(rid, -32002, "un-negotiated protocol version")
                continue
            negotiated = requested if mode != "downgrade" else "2024-11-05"
            if mode == "tree":
                grandchild = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(300)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                emit({"event": "spawned", "pid": grandchild.pid})
            result(rid, {"protocolVersion": negotiated, "capabilities": {},
                         "serverInfo": {"name": "fake-mcp-t05", "version": "0.1"}})
            continue

        if rid is None:  # any notification (incl. notifications/initialized)
            continue

        if negotiated is None:
            # no completed initialize negotiation: the un-negotiated use is
            # refused and booked so the test can prove the server spoke.
            emit({"event": "refused", "method": method})
            error(rid, -32001, "un-negotiated protocol version")
            continue

        if method == "tools/list":
            list_count += 1
            if mode == "drift" and list_count > 1:
                tools = [TOOL_ECHO, TOOL_EXTRA]
            elif mode == "drift":
                tools = [TOOL_ECHO]
            else:
                tools = [TOOL_ECHO, TOOL_PEEK]
            result(rid, {"tools": tools})
        elif method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            call_count += 1
            emit({"event": "call", "name": name, "seq": call_count})
            arguments = params.get("arguments") or {}
            if mode == "slowcall":
                time.sleep(1.5)
            result(rid, {"content": [
                {"type": "text", "text": f"{name}:{arguments.get('text', '')}"}]})
        else:
            emit({"event": "unknown-method", "method": method})
            error(rid, -32601, "method not found")

    if mode == "stubborn":
        # ignore EOF as well: only the SIGTERM->SIGKILL escalation may end it
        while True:
            time.sleep(0.05)


if __name__ == "__main__":
    main()
