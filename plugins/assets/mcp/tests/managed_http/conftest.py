"""Fixtures for the T011 managed HTTP-client **L2** tests.

This directory is the managed-lane place that really opens loopback
sockets (client + in-process fake server): the package-level autouse
side-effect lockdown (``plugins/assets/mcp/tests/conftest.py``) is
therefore explicitly lifted for every test here - the same discipline
``tests/probe`` and ``tests/managed_client`` use. The lift only re-binds
the real ``socket``/``subprocess`` entry points; every endpoint is
``127.0.0.1:0`` (or TLS-wrapped on the same address) and the only
subprocess use is ``openssl`` for the throwaway certificate.

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

from fake_http_mcp import FakeStreamableServer

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
    """Lift the lockdown for the HTTP client tests; the autouse guard ran first."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)


@pytest.fixture
def harness(tmp_path):
    from managed_helpers import ManagedHarness

    return ManagedHarness(tmp_path)


@pytest.fixture
def endpoint():
    """Factory: ``endpoint(mode="...", tls=(cert, key))`` -> fake server.

    Every created server is shut down at test end (the remote side the
    client refuses to stop is this fixture's job to stop).
    """
    created: list = []

    def _make(mode: str = "normal", tls: tuple | None = None, expected_secret: str = ""):
        server = FakeStreamableServer(mode, tls=tls, expected_secret=expected_secret)
        created.append(server)
        return server

    yield _make
    for server in created:
        server.close()


@pytest.fixture(scope="session")
def self_signed_tls(tmp_path_factory):
    """Throwaway 127.0.0.1 certificate for the https格 (never in the tree;
    needs openssl on PATH - environment fact registered in reports/t011;
    absent openssl fails loudly, no skip)."""
    cert_dir = tmp_path_factory.mktemp("managed-http-tls")
    cert = str(cert_dir / "cert.pem")
    key = str(cert_dir / "key.pem")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", key, "-out", cert, "-days", "2",
         "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True, timeout=60)
    return cert, key
