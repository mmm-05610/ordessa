"""tests/integration: the Q4 T10 cross-domain controlled chain.

This directory runs the REAL composition end to end, so the package-level
side-effect lockdown (``plugins/assets/mcp/tests/conftest.py``) is
explicitly lifted here — the same discipline ``tests/probe``,
``tests/managed_client`` and ``tests/managed_http`` use: the lift only
re-binds the real ``socket``/``subprocess`` entry points, every endpoint is
loopback (stdio pipes or ``127.0.0.1``), and the only children are the
directory's own fake server script. Teardown reaps any child process that a
test forgot to close (process-tree guarantee, no stray survivors).

``sys.path``: the sibling helper directories are added so the chain reuses
the REAL factories/in-process doubles from other batches where they are
importable helper modules (``tests/adapters`` native_helpers,
``tests/harness_wiring`` wiring_helpers) — the managed_client/managed_http
fixtures are NOT imported; per the dispatch this directory carries its own
copies (``integration_fake_stdio_server.py`` / ``integration_fake_http_server``).
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _directory in (_HERE, _TESTS / "adapters", _TESTS / "harness_wiring",
                  _TESTS / "service"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

# Captured at import time, before any monkeypatch can be in effect.
_REAL_SOCKET = socket.socket
_REAL_POPEN = subprocess.Popen
_REAL_RUN = subprocess.run
_REAL_CALL = subprocess.call

from integration_helpers import (  # noqa: E402,F401  (re-export fixtures)
    FakeCredentialRecords,
    FakeSecretStore,
    FakeSubmissionGate,
    IntegrationStack,
    Q5World,
    SENTINEL,
    TransportRouter,
    args_digest_for,
    intent_allowing,
    make_plan_stack,
    make_stack,
    plan_full_setup,
    read_allow_intent,
    wire_q5,
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@pytest.fixture(autouse=True)
def chain_primitives(monkeypatch, no_side_effect_primitives):
    """Lift the package seal for the chain tests; the autouse guard ran first."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)


@pytest.fixture(autouse=True)
def chain_process_cleanup(tmp_path):
    """Process-tree guard: reap any fake-server child this test left behind.

    Tests assert on the witness pid lines themselves; this fixture is the
    belt: at teardown every pid booked in a ``witness-*.jsonl`` file under
    the tmp dir must be gone - if it is not, it is killed here and the
    process-tree claim would be false (the test that forgot to close fails
    its own assertion before this ever matters).
    """
    yield
    for state in tmp_path.glob("**/witness-*.jsonl"):
        import json
        for line in state.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") != "pid":
                continue
            pgid = int(event["pgid"])
            if _pid_alive(int(event["pid"])) or _pid_alive(pgid):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.fixture
def stack(tmp_path):
    """The L2 chain stack: real plugin activation + real client router."""
    composed = make_stack(tmp_path)
    yield composed
    composed.close_service()


@pytest.fixture
def world(tmp_path) -> Q5World:
    """The REAL Q5 permissions backend over a seeded throwaway database."""
    return Q5World.build(tmp_path / "q5")
