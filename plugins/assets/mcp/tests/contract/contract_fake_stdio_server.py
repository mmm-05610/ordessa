"""Millisecond-level fake MCP stdio server for the contract probe cells.

Spawned by the REAL ``backend.probe.probe_stdio`` transport (composition-
injected command/args): reads exactly one newline-delimited JSON-RPC line and
answers the initialize handshake. It stuffs a ``tools`` array into the result
on purpose — the probe must ignore it (FR-02: a handshake proves the
handshake, never a catalog), and the calling cell asserts the fact shape has
no catalog. No network, no sleeps, exits right after answering.
"""
import json
import sys

line = sys.stdin.readline()
try:
    request = json.loads(line)
except ValueError:
    sys.exit(1)
answer = {
    "jsonrpc": "2.0",
    "id": request.get("id", 1),
    "result": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "serverInfo": {"name": "contract-fake-stdio", "version": "0.1"},
        "tools": [{"name": "unseen-stdio-tool"}],  # must be ignored by the probe
    },
}
sys.stdout.write(json.dumps(answer) + "\n")
sys.stdout.flush()
