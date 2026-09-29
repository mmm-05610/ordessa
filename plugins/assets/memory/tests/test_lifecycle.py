"""Lifecycle (MB-3): provision/up/stop/health/upgrade-backup-first/uninstall
keeps data — all through the recorded fake runner, argv-level assertions."""
from __future__ import annotations

from pathlib import Path

import pytest

from ordessa_memory import common, provisioning
from ordessa_memory.provisioning import ProvisioningUnsupported
from ordessa_memory.provisioning import MemoryStack

from conftest import FakeRunner


def _stack(tmp_path: Path, runner: FakeRunner) -> MemoryStack:
    return MemoryStack(runner, tmp_path / "memory", provisioning.PortPlan(18080, 18432))


def test_lifecycle_requires_provisioning_first(tmp_path):
    stack = _stack(tmp_path, FakeRunner())
    with pytest.raises(ProvisioningUnsupported, match="尚未置备"):
        stack.up()


def test_provision_writes_env_and_compose_and_records_the_docker_facts(tmp_path):
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", "")})
    stack = _stack(tmp_path, runner)
    facts = stack.provision({"OPENAI_API_KEY": "ref://openai-cred"})
    assert facts["compose"] == "v2.39.0"
    env_text = stack.env_file.read_text(encoding="utf-8")
    assert "MEM0_TELEMETRY=false" in env_text
    assert "OPENAI_API_KEY=ref://openai-cred" in env_text
    assert (stack.deploy_dir / provisioning.COMPOSE_FILE_NAME).exists()
    # secrets land only in the data-root env file (0600)
    assert (stack.env_file.stat().st_mode & 0o777) == 0o600


def test_provision_without_docker_is_honest_unsupported(tmp_path):
    stack = _stack(tmp_path, FakeRunner(script={
        "docker --version": (127, "", "command not found")}))
    with pytest.raises(ProvisioningUnsupported):
        stack.provision({})
    assert not stack.env_file.exists()
    assert not (stack.deploy_dir / provisioning.COMPOSE_FILE_NAME).exists()


def test_up_stop_ps_run_through_the_generated_compose_file(tmp_path):
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", "")})
    stack = _stack(tmp_path, runner)
    stack.provision({})
    compose = str(stack.deploy_dir / provisioning.COMPOSE_FILE_NAME)
    stack.up()
    stack.stop()
    stack.ps()
    joined = [" ".join(call) for call in runner.calls]
    assert f"docker compose -f {compose} up -d" in joined
    assert f"docker compose -f {compose} stop" in joined
    assert f"docker compose -f {compose} ps" in joined


def test_upgrade_backs_up_before_touching_the_stack(tmp_path):
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", ""),
        "pg_dumpall": (0, "PG_DMP_ALL_SQL", "")})
    stack = _stack(tmp_path, runner)
    stack.provision({})
    report = stack.upgrade("2026-09-28")
    joined = [" ".join(call) for call in runner.calls]
    dump_index = next(i for i, c in enumerate(joined) if "pg_dumpall" in c)
    stop_index = next(i for i, c in enumerate(joined) if c.endswith("stop"))
    up_index = next(i for i, c in enumerate(joined) if c.endswith("up -d"))
    assert dump_index < stop_index < up_index, "backup must precede stop and upgrade"
    backup = Path(report["backup"])
    assert backup.read_text() == "PG_DMP_ALL_SQL"
    assert "backups" in str(backup)


def test_upgrade_with_a_failed_backup_refuses_to_continue(tmp_path):
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", ""),
        "pg_dumpall": (1, "", "pg_dumpall: connection refused")})
    stack = _stack(tmp_path, runner)
    stack.provision({})
    with pytest.raises(ProvisioningUnsupported, match="不备份不升级"):
        stack.upgrade("2026-09-28")
    joined = [" ".join(call) for call in runner.calls]
    assert not any(c.endswith("up -d") for c in joined)


def test_uninstall_keeps_the_data_root_directories(tmp_path):
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", "")})
    stack = _stack(tmp_path, runner)
    stack.provision({})
    pg_data = tmp_path / "memory" / provisioning.POSTGRES_DATA_DIR_NAME
    pg_data.mkdir(parents=True, exist_ok=True)
    (pg_data / "PG_VERSION").write_text("17")
    stack.uninstall()
    joined = [" ".join(call) for call in runner.calls]
    assert any("down --remove-orphans" in c for c in joined)
    assert (pg_data / "PG_VERSION").exists(), "卸载保留数据"
    assert stack.env_file.exists()


def test_read_admin_key_pulls_the_content_only_from_the_env_file(tmp_path):
    stack = _stack(tmp_path, FakeRunner(script={
        "docker --version": (0, "d", ""), "docker compose version --short": (0, "v2", "")}))
    stack.provision({})
    key = provisioning.read_admin_key(stack.env_file)
    assert len(key) >= 32  # token_urlsafe(32)
    assert key == provisioning.read_admin_key(stack.env_file)


def test_generated_secrets_are_fresh_per_provision(tmp_path):
    stack = _stack(tmp_path, FakeRunner(script={
        "docker --version": (0, "d", ""), "docker compose version --short": (0, "v2", "")}))
    stack.provision({})
    first = provisioning.read_admin_key(stack.env_file)
    (stack.deploy_dir / provisioning.COMPOSE_FILE_NAME).unlink()
    stack.env_file.unlink()
    stack.provision({})
    assert provisioning.read_admin_key(stack.env_file) != first


def test_health_probe_walks_the_client_to_docs(tmp_path):
    """The health path: a provisioned stack builds a client against the
    assigned port; with nothing listening, liveness is honestly false."""
    from ordessa_memory.mem0_client import Mem0Client, Mem0Unreachable
    runner = FakeRunner(script={
        "docker --version": (0, "d", ""), "docker compose version --short": (0, "v2", "")})
    stack = _stack(tmp_path, runner)
    stack.provision({})
    client = Mem0Client(stack.base_url, lambda: provisioning.read_admin_key(stack.env_file),
                        timeout=2.0)
    with pytest.raises(Mem0Unreachable):
        client.docs_liveness()
