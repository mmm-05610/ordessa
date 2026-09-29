"""L2 helpers: real stdio client factory + server-side witness readers.

The in-memory doubles of ``tests/managed`` stay there (**L0/L1**); this
directory drives the real :mod:`backend.managed.client_stdio` client
against ``fake_mcp_server.py`` (**L2**, controlled loopback stdio). The
witness is the fake's own statefile: counts of executed ``tools/call``,
refusals and the pids of the whole owned process tree - so "the gate
refused, the server saw nothing" is proven from the server side.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from backend.managed.client_stdio import (
    StdioClientPolicy,
    make_stdio_client_factory,
)
from managed_helpers import ManagedHarness

HERE = Path(__file__).resolve().parent
FAKE = str(HERE / "fake_mcp_server.py")

#: generous for functional tests; the teardown graces stay short so a
#: broken reaping fails the test instead of hanging the suite.
FAST = StdioClientPolicy(request_timeout=6.0, initialize_timeout=6.0,
                         exit_grace=0.5, kill_grace=0.8)
#: for the timeout / unknown-outcome path against the slowcall fake.
BRIEF = StdioClientPolicy(request_timeout=0.3, initialize_timeout=3.0,
                          exit_grace=0.5, kill_grace=0.8)


class RealClientFactory:
    """Wraps the production factory and records every produced client.

    One fresh client per lease (the manager asks once per lease); the
    ``produced`` list is the no-pooling witness.
    """

    def __init__(self, definitions, *, policy: StdioClientPolicy = FAST,
                 secret_resolver=None) -> None:
        self._inner = make_stdio_client_factory(
            definitions, policy=policy, secret_resolver=secret_resolver)
        self.policy = policy
        self.produced: list = []

    def __call__(self, lease):
        client = self._inner(lease)
        self.produced.append(client)
        return client


def build_harness(tmp_path, *, mode: str = "normal", definition_id: str = "srv-real",
                  policy: StdioClientPolicy = FAST):
    """ManagedHarness wired to the real client factory and one fake mode.

    Returns ``(harness, revision, statefile)``; ``harness.factory`` is the
    :class:`RealClientFactory` and ``harness.bring_up`` works unchanged.
    """
    harness = ManagedHarness(tmp_path)
    harness.factory = RealClientFactory(harness.definitions, policy=policy)
    statefile = tmp_path / f"{definition_id}.server.jsonl"
    revision = harness.install_stdio(
        definition_id=definition_id, command=sys.executable,
        args=[FAKE, mode, str(statefile)])
    return harness, revision, statefile


# -- server-side witness ---------------------------------------------------------

def events(statefile) -> list:
    path = Path(statefile)
    if not path.is_file():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def call_events(statefile) -> list:
    return [event for event in events(statefile) if event.get("event") == "call"]


def methods_seen(statefile) -> list:
    return [event.get("method") for event in events(statefile)
            if event.get("event") == "request"]


def recorded_pids(statefile) -> list:
    """The fake's own pid plus every pid it spawned (the owned tree)."""
    pids = []
    for event in events(statefile):
        if event.get("event") in ("pid", "spawned"):
            pids.append(int(event["pid"]))
    return pids


def pid_running(pid: int) -> bool:
    """``/proc`` is the authority (psutil absent): gone or zombie = not running."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            state = handle.read().rsplit(b")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    except ProcessLookupError:
        # reaped between open() and read(): dead, not running
        return False
    except OSError:
        return True
    return state != b"Z"


def wait_pids_gone(statefile, *, timeout: float = 5.0) -> list:
    """Block until every recorded pid of the owned tree is not running."""
    pids = recorded_pids(statefile)
    assert pids, "the fake never registered its pid - the witness is empty"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(pid_running(pid) for pid in pids):
            return pids
        time.sleep(0.02)
    alive = [pid for pid in pids if pid_running(pid)]
    raise AssertionError(f"process(es) {alive} of the owned tree still running")
