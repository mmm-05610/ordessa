#!/usr/bin/env python3
"""Controlled real-Pi-CLI probe for the managed bridge lane (T10 promotion).

NOT a pytest module - run explicitly, from the repository root, e.g.:

    .venv/bin/python plugins/assets/mcp/tests/pi_bridge/real_pi_probe.py

Discipline (specs/011-q4-mcp prompt + AGENTS rules):
* the pi process runs with an ISOLATED HOME (fresh mktemp dir), never the
  user's; nothing under ~/.pi is read or written by this probe;
* every pi invocation is timeout-bounded; no network except this probe's
  own loopback control channel (PI_OFFLINE=1, PI_SKIP_VERSION_CHECK=1);
* the "MCP server" behind the double gate is the in-memory fake client
  (echo semantics) - NO real model and NO real MCP server is involved;
* each cell prints OBSERVED vs UNKNOWN with the concrete evidence; the
  probe never upgrades a cell it did not literally see.

Cells: A load/lifecycle, B registered-catalog-visible-inside-pi,
C tool call through the gate, D refusal path, E close/cleanup.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent.parent                     # plugins/assets/mcp
REPO = PACKAGE_ROOT.parent.parent.parent             # worktree root
sys.path.insert(0, str(PACKAGE_ROOT))
sys.path.insert(0, str(PACKAGE_ROOT / "tests" / "managed"))

from managed_helpers import TOOLS_TWO, ALLOWING, ManagedHarness  # noqa: E402
from backend.managed.pi_bridge import bind_bridge  # noqa: E402

EXTENSION = PACKAGE_ROOT / "adapters" / "pi" / "ordessa-mcp-bridge.ts"
PI_TIMEOUT = 60


def cell(name: str, status: str, evidence: str) -> None:
    print(f"[{name}] {status.upper()} :: {evidence}", flush=True)


def which_pi() -> str | None:
    from shutil import which
    return which("pi")


def build_bridge(tmp: Path):
    harness = ManagedHarness(tmp / "state")
    revision = harness.install_remote()
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_TWO)
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, _catalog, client = harness.bring_up(manager, caller, "srv-a", revision)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    server = bind_bridge(
        manager=manager, caller=caller, owner_id=lease.owner_id,
        lease_id=lease.lease_id,
        tools=[dict(t) for t in TOOLS_TWO if t["name"] == "echo"],
        bridge_id="pib-real-probe")
    return harness, manager, caller, lease, client, server


class RpcDriver:
    """Minimal newline-JSON driver of `pi --mode rpc` (stdin commands,
    stdout events). stdout of pi is the protocol; stderr captured."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.events: list = []
        self.raw_lines: list = []

    def send(self, frame: dict) -> None:
        line = json.dumps(frame, separators=(",", ":"))
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def pump(self, seconds: float, predicate=lambda e: False) -> list:
        """Read stdout lines for up to `seconds` (wall clock)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            line = None
            if self.proc.stdout is not None:
                import select
                ready, _, _ = select.select([self.proc.stdout], [], [], 0.2)
                if ready:
                    line = self.proc.stdout.readline()
            if line == "" or line is None:  # EOF
                break
            if not line:
                continue
            text = line.strip()
            if not text:
                continue
            self.raw_lines.append(text)
            try:
                frame = json.loads(text)
            except json.JSONDecodeError:
                continue
            self.events.append(frame)
            if predicate(frame):
                break
        return self.events


def main() -> int:
    pi_bin = which_pi()
    version = "?"
    if pi_bin:
        version = subprocess.run([pi_bin, "--version"], capture_output=True,
                                 text=True, timeout=PI_TIMEOUT).stdout.strip()
    print(f"pi binary: {pi_bin} version: {version}", flush=True)
    if not pi_bin:
        cell("A", "unknown", "no pi on PATH")
        return 1
    if not EXTENSION.is_file():
        cell("A", "unknown", f"extension source missing: {EXTENSION}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="ordessa-pi-probe-"))
    home = tmp / "home"
    home.mkdir()
    workdir = tmp / "work"
    workdir.mkdir()
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
    })
    env.pop("PI_CODING_AGENT_DIR", None)
    harness, manager, caller, lease, client, server = build_bridge(tmp)
    good_env = dict(server.extension_env())
    proc = None
    rc = 0
    try:
        # -- Cell D (first, while the token is still unspent): a pi launched
        # with a WRONG token must die at the channel gate before anything
        # binds; a refused hello does not consume the registration.
        bad_env = dict(good_env, ORDESSA_PI_BRIDGE_TOKEN="f" * 32)
        bad_proc = subprocess.Popen(
            [pi_bin, "--mode", "rpc", "--no-session", "-e", str(EXTENSION)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(workdir), env=bad_env)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and server.state.hellos_refused == 0:
            time.sleep(0.2)
        bad_proc.stdin and bad_proc.stdin.close()
        try:
            bad_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            bad_proc.kill()
            bad_proc.wait(timeout=10)
        cell("D0", "observed" if (server.state.hellos_refused >= 1
                                 and not server.state.bound) else "unknown",
             f"wrong-token pi: hellosRefused={server.state.hellos_refused} "
             f"bound={server.state.bound} reasons={server.state.refusal_reasons[:2]} "
             "client_executed=" + str(len(client.executed_calls)))

        # -- Cell A: the real pi CLI loads the managed extension -------------
        env.update(good_env)
        proc = subprocess.Popen(
            [pi_bin, "--mode", "rpc", "--no-session", "-e", str(EXTENSION)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=str(workdir), env=env,
            bufsize=1)
        bound = server.wait_for_bound(timeout=25)
        ready_seen = server.state.hellos_accepted
        cell("A", "observed" if bound else "unknown",
             f"pi(pid={proc.pid}) hello_accepted={ready_seen} bound={bound}; "
             f"isolated HOME={home}")
        if not bound:
            err = proc.stderr.read(4000) if proc.stderr else ""
            print(f"--- pi stderr head ---\n{err}\n---", flush=True)

        driver = RpcDriver(proc)
        if bound:
            # -- Cell B: the Server-validated catalog is live INSIDE pi ------
            driver.send({"id": "s-1", "type": "prompt",
                         "message": "/ordessa_mcp_status"})
            deadline = time.monotonic() + 20

            def wants_status(frame):
                return (frame.get("type") == "extension_ui_request"
                        and frame.get("method") == "notify")
            while time.monotonic() < deadline and not any(
                    wants_status(e) for e in driver.events):
                driver.pump(1.0, predicate=wants_status)
            notes = [e for e in driver.events if wants_status(e)]
            text = " ".join(str(e.get("message", "")) for e in notes)
            ok = "bound=true" in text and "echo" in text
            cell("B", "observed" if ok else "unknown",
                 f"notify frames={len(notes)} text={text[:220]!r}")

            # -- Cell C: a real tools/call dispatched by pi ------------------
            # requires the agent loop (a provider); without model credentials
            # the honest answer is unknown - recorded, never faked.
            executed_before = len(client.executed_calls)
            cell("C", "unknown",
                 "no model provider in this probe; the LLM tool-dispatch leg "
                 "needs credentials (real model calls require prior user "
                 f"authorisation). in-memory client calls so far: {executed_before}")

            # -- Cell D1: refusal on the live server ---------------------------
            # a second real pi launched with the (already consumed) token
            # must be refused at the gate while the first channel stays the
            # only bound one - and zero calls may have reached the client.
            rival = subprocess.Popen(
                [pi_bin, "--mode", "rpc", "--no-session", "-e", str(EXTENSION)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=str(workdir), env=env)
            refusals_before = len(server.state.refusal_reasons)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and len(
                    server.state.refusal_reasons) == refusals_before:
                time.sleep(0.2)
            rival.stdin and rival.stdin.close()
            try:
                rival.wait(timeout=10)
            except subprocess.TimeoutExpired:
                rival.kill()
                rival.wait(timeout=10)
            refused = (any(("already consumed" in r or "another live channel" in r)
                           for r in server.state.refusal_reasons)
                       and server.state.bound
                       and not client.executed_calls)
            cell("D1", "observed" if refused else "unknown",
                 f"re-bind attempt: reasons={server.state.refusal_reasons[-2:]} "
                 f"firstChannelStillBound={server.state.bound} "
                 f"client_executed={len(client.executed_calls)}")

        # -- Cell E: close/cleanup ------------------------------------------
        proc.stdin and proc.stdin.close()
        try:
            proc.wait(timeout=15)
            exit_code = proc.returncode
            how = f"exited {exit_code}"
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                exit_code = proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait(timeout=10)
            how = f"terminated (exit {exit_code})"
        time.sleep(0.4)
        deadline = time.monotonic() + 3.0
        while server.state.bound and time.monotonic() < deadline:
            time.sleep(0.05)
        still = server.state.bound
        gone = not still
        snap = server.close()
        cell("E", "observed" if gone else "unknown",
             f"pi {how}; bridge.bound={still}; server close snapshot "
             f"closed={snap['closed']} hellosAccepted={snap['hellosAccepted']} "
             f"callsRefused={snap['callsRefused']} "
             f"client_executed={len(client.executed_calls)}")
        if not gone:
            rc = 2
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        server.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print("probe done", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
