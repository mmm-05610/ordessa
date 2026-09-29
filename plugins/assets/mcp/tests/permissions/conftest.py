"""T06/T07 test fixtures: fake ports only - sockets and spawns stay sealed.

The package-level lockdown (``tests/conftest.py``) already applies here; per
the dispatch this directory carries its own autouse seal as well, so the
permission/secret tests are honest-by-construction even if the parent file
moves: no test here may open a socket or launch a process. Everything the
double gate and the credential glue touch runs against the fakes in
``helpers.py`` (re-exported below for fixture-style use).
"""
from __future__ import annotations

import socket
import subprocess

import pytest

from perms_helpers import FakeCredentialPort, RecordingAuthority, make_snapshot  # noqa: F401


class _Blocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_side_effect_primitives(monkeypatch):
    def _blocked_socket(*args, **kwargs):
        raise _Blocked("T06/T07 glue must not open sockets")

    def _blocked_popen(*args, **kwargs):
        raise _Blocked("T06/T07 glue must not spawn processes")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(subprocess, "run", _blocked_popen)
    monkeypatch.setattr(subprocess, "call", _blocked_popen)


@pytest.fixture
def allow_authority():
    return RecordingAuthority(make_allowed_decision())


def make_allowed_decision():
    from backend.permissions import ToolCallDecision

    return ToolCallDecision.allowed(basis="authority", gate="authority")


@pytest.fixture
def credential_port():
    return FakeCredentialPort({"cred-1": ("s3cr3t-alpha", "rev-1"),
                               "cred-2": ("s3cr3t-beta", "rev-7")})
