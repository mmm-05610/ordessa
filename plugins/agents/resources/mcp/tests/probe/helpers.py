"""Non-fixture helpers for the T03 probe tests (importable by every test in
this directory; pytest puts this directory on ``sys.path``).
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_SERVER = os.path.join(HERE, "fake_stdio_server.py")


def stdio_canonical(mode: str, pids: str | None = None, env=None) -> dict:
    """Canonical v2 definition whose stdio command is the fake server."""
    args = [FAKE_SERVER, mode]
    if pids is not None:
        args.append(pids)
    return {"name": "probe-target",
            "transport": {"stdio": {"command": sys.executable, "args": args, "env": env or {}}}}


def remote_canonical(url: str, headers=None) -> dict:
    return {"name": "probe-target",
            "transport": {"remote": {"url": url, "headers": headers or {}}}}


def read_pids(pids_file: str) -> list:
    with open(pids_file) as fh:
        return [int(line) for line in fh.read().split() if line.strip()]


def pid_alive(pid: int) -> bool:
    """psutil is not installed: ``/proc`` is the authority (psutil-absent
    fallback registered in reports/t03.md)."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            state = fh.read().rsplit(b") ", 1)[1].split()[0]
    except (FileNotFoundError, IndexError, ProcessLookupError):
        # a pid reaped between open() and read() is dead, not an error
        return False
    return state != b"Z"  # zombie = killed, awaiting reaping: not running


def wait_pids_gone(pids_file: str, count: int = 3, timeout: float = 3.0) -> list:
    """Poll until every recorded pid is dead (gone or zombie), no orphans."""
    deadline = time.monotonic() + timeout
    recorded: list = []
    while time.monotonic() < deadline:
        try:
            recorded = read_pids(pids_file)
        except OSError:
            recorded = []
        if len(recorded) >= count and all(not pid_alive(pid) for pid in recorded):
            return recorded
        time.sleep(0.03)
    raise AssertionError(
        f"probe left orphans: {[(p, pid_alive(p)) for p in recorded]} (want >= {count} pids, all dead)")
