"""Fixtures for the T05 managed-client **L2** tests.

This directory is the one managed-lane place that really spawns the
controlled fake stdio server (the client under test owns a child process):
the package-level autouse side-effect lockdown
(``plugins/assets/mcp/tests/conftest.py``) is therefore explicitly lifted
for every test here - the same discipline ``tests/probe`` uses for its
probe fixtures. Every other directory of the package stays locked, and the
lift is *only* re-binding the real ``Popen``/``socket`` entry points; all
child processes are this directory's fake server script and nothing binds
a non-loopback address (in fact: no socket at all - stdio pipes only).

``sys.path``: the sibling ``tests/managed`` directory is added so the
shared domain doubles (``ManagedHarness``, the ToolCallDecision-shaped
authority fakes) import deterministically whether or not the sibling
suite is collected in the same run.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _directory in (_HERE, _TESTS / "managed"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

# Captured at import time, before any monkeypatch can be in effect.
_REAL_SOCKET = socket.socket
_REAL_POPEN = subprocess.Popen
_REAL_RUN = subprocess.run
_REAL_CALL = subprocess.call


@pytest.fixture(autouse=True)
def client_primitives(monkeypatch, no_side_effect_primitives):
    """Lift the lockdown for the client tests; the autouse guard ran first."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)
