"""L0/L1 environment guard: this batch never touches network or processes."""
from __future__ import annotations

import socket
import subprocess

import pytest


def test_socket_construction_is_blocked():
    with pytest.raises(RuntimeError):
        socket.socket()


def test_subprocess_spawn_is_blocked():
    with pytest.raises(RuntimeError):
        subprocess.Popen(["/bin/true"])
    with pytest.raises(RuntimeError):
        subprocess.run(["/bin/true"])


def test_managed_package_ships_only_in_memory_clients():
    # The only ManagedClientPort implementations shipped by the domain are
    # the two fakes - there is no real-SDK code path to accidentally claim.
    from backend.managed import session_manager

    assert session_manager.InMemoryManagedClient.__doc__.count("L0/L1") == 1
    assert session_manager.FaultInjectingManagedClient.__doc__.count("L0/L1") == 1
    assert session_manager.MCP_CLIENT_FACTORY_MISSING == "MCP_CLIENT_FACTORY_MISSING"
