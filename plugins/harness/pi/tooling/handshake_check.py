#!/usr/bin/env python3
"""No-model preflight for the real-Pi desktop acceptance chain.

Spawns the pinned Pi->ACP bridge exactly the way the Server's managed channel
does (absolute command + `--adapter=pi --pi-bin=... --pi-session-dir=...`),
replays the real `initialize` frame observed on the production seam, and shows
the answer.  It stops there: no `session/new`, no `session/prompt`, therefore
no Pi process, no provider contact, no credential read.

Usage: handshake-check.py <bridge> <pi-bin> <out-json> [session-dir]
"""
from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
from pathlib import Path

# The frame the real Server/managed channel sends as id 0 (HD-004 peer log).
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": 1, "clientCapabilities": {}},
}

# HD-002 rule: the Server environment must not carry Pi overlays.
PI_OVERLAYS = (
    "PI_ARGS", "PI_PROVIDER", "PI_MODEL", "PI_BIN", "PI_SESSION_DIR",
    "PI_DISABLE_GATE", "PI_CODING_AGENT_DIR", "PI_MANAGED_INSTALL_ROOT",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def children(pid: int) -> list[int]:
    out: list[int] = []
    for task in Path(f"/proc/{pid}/task").iterdir():
        try:
            text = (task / "children").read_text()
        except OSError:
            continue
        out += [int(v) for v in text.split()]
    return out


def main() -> int:
    bridge, pi_bin, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    session_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else out_path.parent / "handshake-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    env = {k: v for k, v in os.environ.items() if k not in PI_OVERLAYS}
    preflight = {
        "bridgeAbs": str(bridge),
        "bridgeIsFile": bridge.is_file(),
        "bridgeIsExecutable": os.access(bridge, os.X_OK),
        "bridgeSha256": sha256(bridge),
        "piBinAbs": str(pi_bin),
        "piBinIsFile": pi_bin.is_file(),
        "piBinSha256": sha256(pi_bin) if pi_bin.is_file() else None,
        "piOverlaysAbsent": all(k not in os.environ for k in PI_OVERLAYS),
        "modelCallPolicy": "initialize only; no session/new, no session/prompt",
    }
    result = dict(preflight)
    proc = None
    stderr_path = out_path.with_suffix(".stderr")
    try:
        if stderr_path.exists():
            stderr_path.unlink()  # re-runnable preflight; the JSON result is the record
        stderr_fd = os.open(stderr_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        proc = subprocess.Popen(
            [str(bridge), "--adapter=pi", f"--pi-bin={pi_bin}", f"--pi-session-dir={session_dir}"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_fd,
            env=env, text=True, bufsize=1, start_new_session=True,
        )
        os.close(stderr_fd)
        proc.stdin.write(json.dumps(INITIALIZE) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 20.0)
        line = proc.stdout.readline() if ready else ""
        result["answeredWithin"] = "20s" if ready else "timeout"
        result["response"] = json.loads(line) if line.strip() else None
        result["piChildrenAtHandshake"] = children(proc.pid)
        resp = result["response"] or {}
        if "error" in resp:
            result["verdict"] = f"BRIDGE_ERROR {resp['error'].get('code')}"
        elif resp.get("id") == 0 and isinstance(resp.get("result"), dict) and "protocolVersion" in resp["result"]:
            result["verdict"] = "HANDSHAKE_OK_NO_MODEL_CALL"
        else:
            result["verdict"] = "UNEXPECTED_RESPONSE"
    except Exception as exc:  # surfaced verbatim; a failed handshake must not read as success
        result["verdict"] = f"HANDSHAKE_FAILED {type(exc).__name__}: {exc}"
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            try:
                result["exitCode"] = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                result["exitCode"] = proc.wait()
                result["exitNote"] = "killed after SIGTERM timeout"
        try:
            result["bridgeStderr"] = stderr_path.read_text()[-2000:]
        except OSError:
            pass
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("verdict") == "HANDSHAKE_OK_NO_MODEL_CALL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
