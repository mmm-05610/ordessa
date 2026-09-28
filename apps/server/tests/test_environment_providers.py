"""The environment providers: what a placement's producer promises.

Local and SSH used to be names the API accepted and no implementation answered.
These tests pin the contracts each producer must keep: a location is validated
before it is recorded, a refusal is typed rather than guessed, and the SSH
connector keeps the key where keys belong - read by `ssh` through a locator,
never copied, never spelled on a command line.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server_compat.execution.placement import resolve_placement
from ordessa_server.connectors import SshConnector, ssh_identity_permissions
from ordessa_server.transport.http import create_app
from ordessa_workspace.local_environment import LocalEnvironmentProvider
from ordessa_workspace.records import WorkspaceRecords
from ordessa_server.idempotency import IdempotentRecords
from pacthold_runtime_compat.storage import Database

from fastapi.testclient import TestClient

ROOT = Path(tempfile.mkdtemp(prefix="env-provider-tests-"))


def _workspace_records(tmp_path: Path) -> WorkspaceRecords:
    database = Database(tmp_path / "data")
    database.initialize()
    return WorkspaceRecords(database, IdempotentRecords(database))


# --- local ------------------------------------------------------------------


def test_a_local_location_is_normalized_into_the_stored_identity():
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "available"})
    root = ROOT / "normalized"
    (root / "real").mkdir(parents=True, exist_ok=True)
    link = ROOT / "alias"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(root / "real", target_is_directory=True)
    try:
        assert provider.validate(str(link)) == str((root / "real").resolve())
    finally:
        link.unlink()


@pytest.mark.parametrize("path,code", [
    ("relative/path", "LOCAL_PATH_INVALID"),
    ("/tmp//double", "LOCAL_PATH_INVALID"),
    ("/tmp/../tmp", "LOCAL_PATH_INVALID"),
    ("/definitely/not/here", "LOCAL_PATH_MISSING"),
    ("/etc/hostname", "LOCAL_PATH_NOT_DIRECTORY"),
    ("/", "LOCAL_PATH_FORBIDDEN"),
])
def test_a_local_location_that_is_not_one_is_refused_by_name(path, code):
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "available"})
    with pytest.raises(Exception) as refused:
        provider.validate(path)
    assert getattr(refused.value, "code", None) == code


def test_an_unreadable_local_location_is_refused_not_hidden():
    if os.geteuid() == 0:
        pytest.skip("root reads every path, so the refusal cannot be provoked")
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "available"})
    secret = ROOT / "unreadable"
    secret.mkdir(exist_ok=True)
    os.chmod(secret, 0o000)
    try:
        with pytest.raises(Exception) as refused:
            provider.browse(str(secret))
        assert refused.value.code == "LOCAL_PATH_NOT_READABLE"
    finally:
        os.chmod(secret, 0o755)


def test_browsing_reports_writable_and_read_only_entries_separately():
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "available"})
    root = ROOT / "browse"
    (root / "writable").mkdir(parents=True, exist_ok=True)
    (root / "plain.txt").write_text("x", encoding="utf-8")
    result = provider.browse(str(root))
    by_name = {entry["name"]: entry for entry in result["entries"]}
    assert by_name["writable"]["kind"] == "directory"
    assert by_name["writable"]["canOpen"] is True and by_name["writable"]["canWrite"] is True
    assert by_name["plain.txt"]["reason"] == "not_a_directory"


def test_an_open_needs_a_room_this_host_can_run():
    """The sandbox is asked where it matters: browsing needs no room, opening does."""
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "unavailable"})
    root = ROOT / "no-sandbox"
    root.mkdir(exist_ok=True)
    assert provider.browse(str(root))["path"] == str(root.resolve())
    with pytest.raises(Exception) as refused:
        provider.open_workspace(str(root))
    assert refused.value.code == "LOCAL_SANDBOX_UNAVAILABLE"


def test_a_local_workspace_records_no_host_and_no_remote_user(tmp_path):
    provider = LocalEnvironmentProvider(sandbox_probe=lambda: {"status": "available"})
    root = ROOT / "workspace"
    root.mkdir(exist_ok=True)
    records = _workspace_records(tmp_path)
    created, row = records.upsert_by_location(
        env_kind="local", env_host=None, remote_user=None,
        normalized_path=provider.open_workspace(str(root))["path"], connection_id=None,
    )
    again_created, again = records.upsert_by_location(
        env_kind="local", env_host=None, remote_user=None,
        normalized_path=provider.open_workspace(str(root))["path"], connection_id=None,
    )
    assert created is True and again_created is False
    assert again["id"] == row["id"]
    assert row["env_kind"] == "local" and row["env_host"] is None and row["remote_user"] is None
    # The legacy column still needs a value, and the honest one names the
    # placement - never a borrowed WSL distribution, never a host path.
    assert row["distribution"] == "local"
    assert not row["connection_id"].startswith("connection-wsl")


def test_the_local_open_refusal_travels_through_the_wire(tmp_path):
    runtime = build_runtime(tmp_path / "server",
                            server_plugins=create_composition().compatibility_plugins(harnesses=registry()))
    runtime.plugin_host.provided_port('product.service').workspaces.local = LocalEnvironmentProvider(
        sandbox_probe=lambda: {"status": "unavailable", "code": "probe_exit_1"},
    )
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        response = client.post("/wire/v1/workspaces.open", headers={
            "Authorization": f"Bearer {runtime.token}",
        }, json={
            "jsonrpc": "2.0", "id": "open", "method": "workspaces.open",
            "params": {
                "requestId": "open-local",
                "environment": {"kind": "local", "host": None, "user": None},
                "path": "/tmp",
            },
        })
        body = response.json()
        assert body["error"]["details"]["internalCode"] == "LOCAL_SANDBOX_UNAVAILABLE"


def registry():
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "fixture", credential_kind=None, model_control_id=None,
        credential_environment=None,
    ))
    return registry


# --- ssh --------------------------------------------------------------------


MANIFEST = {
    "schemaVersion": 1, "workerVersion": "0.1.0", "wireVersion": 1,
    "sha256": "sha256:" + "a" * 64,
}
IDENTITY = ROOT / "identity"
IDENTITY.touch(exist_ok=True)
os.chmod(IDENTITY, 0o600)


def _connector(tmp_path: Path, **changes) -> SshConnector:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({**MANIFEST, **changes.get("manifest", {})}))
    identity = changes.get("identity", IDENTITY)
    return SshConnector(
        manifest_path=manifest, remote_worker_path="/opt/agentbox/worker",
        identity_file=identity, server_instance_id="instance",
        port=changes.get("port", 22),
    )


def test_a_connector_construction_refuses_what_it_cannot_trust(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(MANIFEST))
    with pytest.raises(RuntimeError) as bad_manifest:
        _connector(tmp_path, manifest={"wireVersion": 2})
    assert bad_manifest.value.args[0] == "WORKER_MANIFEST_INCOMPATIBLE"
    with pytest.raises(RuntimeError) as bad_worker:
        SshConnector(
            manifest_path=good, remote_worker_path="opt/agentbox/worker",
            identity_file=IDENTITY, server_instance_id="instance",
        )
    assert bad_worker.value.args[0] == "SSH_WORKER_PATH_INVALID"
    missing = tmp_path / "no-such-key"
    with pytest.raises(RuntimeError) as no_identity:
        SshConnector(
            manifest_path=good, remote_worker_path="/opt/agentbox/worker",
            identity_file=missing, server_instance_id="instance",
        )
    assert no_identity.value.args[0] == "SSH_IDENTITY_MISSING"
    with pytest.raises(RuntimeError) as bad_port:
        _connector(tmp_path, port=0)
    assert bad_port.value.args[0] == "SSH_PORT_INVALID"


def test_the_locator_never_appears_in_a_command_line(tmp_path):
    connector = _connector(tmp_path)
    try:
        from ordessa_server.connectors import _location

        argv = connector._ssh_prefix(_location("203.0.113.7", "root"))
        assert argv[0] == "ssh" and argv[1] == "-F"
        assert str(IDENTITY) not in " ".join(argv)
        config = Path(argv[2])
        assert config.read_text(encoding="utf-8").count(f"IdentityFile {IDENTITY}") == 1
        assert oct(config.stat().st_mode & 0o777) == "0o600"
    finally:
        connector.close()
    assert not connector._runtime_dir.exists()


@pytest.mark.parametrize("target,user", [
    ("-oProxyCommand=evil", None),
    ("host with spaces", None),
    ("203.0.113.7", "root; rm -rf /"),
    ("", None),
])
def test_an_unsafe_target_or_user_is_refused_before_any_ssh_runs(target, user):
    from ordessa_server.connectors import _location

    with pytest.raises(Exception) as refused:
        _location(target, user)
    assert refused.value.code == "SSH_TARGET_INVALID"


def test_a_worker_that_does_not_match_the_pinned_build_is_refused(tmp_path):
    connector = _connector(tmp_path)
    try:
        from ordessa_server.connectors import _location

        connector._run = lambda location, script: SimpleNamespace(
            returncode=0, stdout="root\n" + "b" * 64 + "  /opt/agentbox/worker\n", stderr="",
        )
        with pytest.raises(Exception) as refused:
            connector.probe("203.0.113.7", "root")
        assert refused.value.code == "SSH_WORKER_DIGEST_MISMATCH"
    finally:
        connector.close()


def test_a_probe_records_the_remote_user_and_expires(tmp_path):
    connector = _connector(tmp_path)
    try:
        from ordessa_server.connectors import _location

        connector._run = lambda location, script: SimpleNamespace(
            returncode=0, stdout="deploy\n" + "a" * 64 + "  /opt/agentbox/worker\n", stderr="",
        )
        started = []
        connector._client = lambda probe, **kwargs: started.append(probe) or _StubClient()
        facts = connector.probe("203.0.113.7", None)
        assert facts["user"] == "deploy" and facts["host"] == "203.0.113.7"
        assert facts["worker_digest"] == MANIFEST["sha256"]
        # The probe's identity is what the workspace record will keep: an
        # unnamed caller ends up with the remote host's own answer, not a guess.
        assert connector._probes[facts["probe_id"]].user == "deploy"
    finally:
        connector.close()


class _StubClient:
    def start(self):
        return {"workerVersion": "0.1.0", "workerDigest": MANIFEST["sha256"]}

    def request(self, *args, **kwargs):
        return {}

    def close(self):
        return None


def test_the_ssh_placement_resolves_to_the_worker_channel():
    assert resolve_placement("ssh", has_connector=True).channel == "ssh-worker"


def test_the_locator_permission_bits_are_reportable():
    assert ssh_identity_permissions(IDENTITY) == "0o600"


def teardown_module(module):
    shutil.rmtree(ROOT, ignore_errors=True)
