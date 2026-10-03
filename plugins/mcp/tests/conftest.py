"""Shared fixtures: T01/T02 storage must never touch the network or spawn.

The gate is honest-by-construction: instead of mocking a transport we block
the primitives themselves for every test in this package, so any accidental
``socket`` use or child process launch fails the suite.
"""
import socket
import subprocess

import pytest


class _Blocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_side_effect_primitives(monkeypatch):
    def _blocked_socket(*args, **kwargs):
        raise _Blocked("T01/T02 storage must not open sockets")

    def _blocked_popen(*args, **kwargs):
        raise _Blocked("T01/T02 storage must not spawn processes")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(subprocess, "run", _blocked_popen)
    monkeypatch.setattr(subprocess, "call", _blocked_popen)
