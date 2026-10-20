"""Loopback fake stdio MCP server for the T03 probe tests (own copy; the
apps/server fixture is reference only, not imported).

Usage: ``python fake_stdio_server.py <mode> [pidfile]``

Modes
  ok            answer initialize with the *echoed* request protocolVersion
                plus a ``tools`` block the probe must ignore
  downgrade     always answer with ``2024-11-05`` (server-side downgrade)
  mismatch      answer with an unsupported ``1999-01-01``
  noresult      answer with a JSON-RPC envelope carrying no result object
  badid         answer with the wrong id
  garbage       answer with a non-JSON line
  oversized     answer with one line far above any probe byte bound
  silent        never answer (probe must time out)
  exit          close immediately without answering
  tree          spawn a child which spawns a grandchild (same process
                group), write their pids, then answer and idle
  treelate      same tree, but never answer (cancellation path)
  leakecho      answer echoing whether ambient/credential env leaked in

The pidfile (when given) receives one pid per line: self, child, grandchild.
"""
import json
import os
import subprocess
import sys
import time

TREE_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree_worker.py")


def _answer(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _initialize_result(protocol_version, name="fake-mcp-t03"):
    return {
        "jsonrpc": "2.0", "id": 1,
        "result": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "serverInfo": {"name": name, "version": "0.1"},
            # A catalog in the handshake answer must never leak into probe
            # facts (FR-02: initialize is not a tool catalog).
            "tools": [{"name": "unseen-tool", "description": "must be ignored"}],
        },
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    pids = sys.argv[2] if len(sys.argv) > 2 else None
    if pids:
        with open(pids, "a") as fh:
            fh.write(str(os.getpid()) + "\n")
            fh.flush()

    if mode == "exit":
        sys.exit(0)
    if mode == "garbage":
        sys.stdin.readline()
        sys.stdout.write("not json at all\n")
        sys.stdout.flush()
        time.sleep(300)
        return
    if mode == "oversized":
        sys.stdin.readline()
        sys.stdout.write("x" * (128 * 1024) + "\n")
        sys.stdout.flush()
        time.sleep(300)
        return
    if mode == "silent":
        sys.stdin.readline()
        time.sleep(300)
        return
    if mode in ("tree", "treelate"):
        subprocess.Popen([sys.executable, TREE_WORKER, "child", pids],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait until the whole tree has registered before going silent or
        # answering: a child killed during interpreter startup never writes
        # its pid, and the cleanup tests must observe all three processes.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with open(pids) as fh:
                if len([line for line in fh if line.strip()]) >= 3:
                    break
            time.sleep(0.02)
        if mode == "treelate":
            time.sleep(300)
            return
    if mode == "leakecho":
        line = sys.stdin.readline()
        _answer({
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "leakecho", "version": json.dumps({
                    "ambient": os.environ.get("ORD_T03_AMBIENT", "absent"),
                    "secretish": os.environ.get("ORD_T03_SECRET_ENV", "absent"),
                    "literal": os.environ.get("ORD_T03_LITERAL", "absent"),
                    "path": os.environ.get("PATH", "absent"),
                })},
                "capabilities": {},
            },
        })
        time.sleep(300)
        return

    line = sys.stdin.readline()
    try:
        request = json.loads(line)
    except ValueError:
        request = {}
    requested = request.get("params", {}).get("protocolVersion", "")

    if mode == "ok" or mode == "tree":
        _answer(_initialize_result(requested or "2024-11-05"))
    elif mode == "downgrade":
        _answer(_initialize_result("2024-11-05"))
    elif mode == "mismatch":
        _answer(_initialize_result("1999-01-01"))
    elif mode == "noresult":
        _answer({"jsonrpc": "2.0", "id": 1})
    elif mode == "badid":
        payload = _initialize_result(requested or "2024-11-05")
        payload["id"] = 999
        _answer(payload)
    else:
        raise SystemExit(f"unknown fake mode {mode!r}")
    time.sleep(300)


if __name__ == "__main__":
    main()
