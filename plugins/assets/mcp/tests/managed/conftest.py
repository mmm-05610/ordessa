"""Fixtures for the T05 managed-domain tests (**L0/L1**, no network, no spawn).

The package-level autouse lockdown (``plugins/assets/mcp/tests/conftest.py``)
stays in force for every test in this directory and is **never lifted** by
any fixture here: the managed batch contains no real SDK client, so it
needs no sockets and no subprocesses (see test_environment_guard.py).

Everything client-shaped is one of the two in-memory fakes from
``backend.managed.session_manager`` via :class:`managed_helpers.FakeClientFactory`.
"""
from __future__ import annotations

import socket
import subprocess

import pytest

from managed_helpers import ManagedHarness


@pytest.fixture
def harness(tmp_path) -> ManagedHarness:
    return ManagedHarness(tmp_path)


@pytest.fixture(autouse=True)
def guard_stays_locked(no_side_effect_primitives):
    """Explicit dependency on the package lockdown fixture.

    This directory has **no** primitive-lifting fixture (unlike tests/probe):
    if the autouse guard is ever weakened, the assertions here and the guard
    test fail.
    """
    assert socket.socket.__name__ == "_blocked_socket"
    assert subprocess.Popen.__name__ == "_blocked_popen"
    yield
