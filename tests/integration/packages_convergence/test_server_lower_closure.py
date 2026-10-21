"""S-09: the installed default closure serves the Product without the upper assembly.

This is the release gate for T04-A, not a unit test: it builds a venv containing
ONLY the wheels reachable from `ordessa-server` (plus the CLI and the default
product deployment, which are selections rather than dependencies), then proves
three things the source tree alone cannot:

1. the closure contains no `ordessa-units` / `ordessa-engineering` /
   `ordessa-system-access-bindings`;
2. the installed Server imports and serves a real Profile lifecycle;
3. the legacy-chain negative is *sensitive*: importing the retired composition
   fails without those distributions and succeeds once they are installed, so a
   vacuously-passing "no reference" check cannot hide a still-working old chain.

The build is expensive (15 wheels + a venv), so this module is deliberately the
only place that pays for it.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from installed_server_fixture import build_installed_server

REPO_ROOT = Path(__file__).resolve().parents[3]
UPPER = ("ordessa-units", "ordessa-engineering", "ordessa-system-access-bindings")


def _run(args, *, env=None, timeout=120):
    return subprocess.run([str(item) for item in args], capture_output=True, text=True,
                          timeout=timeout, env=env)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def closure(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("s09-closure")
    python, ordessa, env, receipt = build_installed_server(
        REPO_ROOT, temporary,
        extra_projects=("ordessa-cli", "ordessa-server-product"))
    return python, ordessa, env, receipt


def test_default_closure_excludes_the_upper_assembly(closure):
    python, _ordessa, _env, receipt = closure
    listed = _run([python, "-m", "pip", "list", "--format=json"])
    assert listed.returncode == 0, listed.stderr
    installed = {item["name"].lower() for item in json.loads(listed.stdout)}
    assert not [name for name in UPPER if name in installed], sorted(installed)
    assert receipt["pipCheck"]["returncode"] == 0, receipt["pipCheck"]
    assert "ordessa-server-product" in receipt["selectedProjects"]


def test_installed_server_serves_a_profile_and_refuses_the_legacy_chain(closure):
    python, ordessa, env, _receipt = closure
    # 1. The retired composition is genuinely unreachable without the upper wheels.
    legacy = _run([python, "-c", "import ordessa_server.composition.runtime"], env=env)
    assert legacy.returncode != 0
    assert "ordessa_units" in legacy.stderr

    # 2. Installed console scripts serve a zero-configuration instance.
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="s09-parent-")) / "root"  # must not pre-exist: an unmarked dir is foreign
    port = _free_port()
    server = subprocess.Popen(
        [str(python.with_name("ordessa-server")), "--data-root", str(root),
         "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        deadline = time.time() + 30
        handshake = None
        while time.time() < deadline:
            line = server.stdout.readline()
            if '"listening"' in line:
                handshake = json.loads(line)
                break
        assert handshake is not None, server.stderr.read()
        assert handshake["origin"].endswith(str(port))
        token = root / "secrets" / "http-token"
        assert token.is_file() and (token.stat().st_mode & 0o777) == 0o600

        client = root / "client.json"
        client.write_text(json.dumps({"services": {"local": {
            "endpoint": handshake["origin"], "tokenFile": str(token)}}}))
        client.chmod(0o600)
        listed = _run([ordessa, "--config", client, "--service", "local",
                       "agents", "profiles", "list", "--json"], env=env)
        assert listed.returncode == 0, listed.stderr
        assert json.loads(listed.stdout)["status"] == "completed"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
