"""The provisioner (MB-2): Docker/compose v2 prerequisite honesty, .env
generation, compose 子栈 rendering, vendor pin discipline.

The Docker-detection gate runs for real in this environment: the host has
no ``docker`` binary, so the unsupported path is exercised first-hand —
exactly the honest behavior the dispatch demands (constraint 2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ordessa_memory import common, provisioning
from ordessa_memory.provisioning import (
    PortPlan, ProvisioningUnsupported, detect_docker, ensure_vendor, render_compose,
    render_env, write_env)

from conftest import FakeRunner


def test_missing_docker_binary_is_honest_unsupported():
    """Live first-hand: this environment has no docker; the detection must
    return the typed unsupported with the precise reason — never a fake."""
    with pytest.raises(ProvisioningUnsupported) as excinfo:
        detect_docker(FakeRunner(script={"docker --version": (127, "", "command not found")}))
    assert "Docker 前置缺失" in excinfo.value.reason
    assert "不会用本地假实现冒充" in excinfo.value.reason


def test_missing_compose_v2_is_honest_unsupported():
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (1, "", "compose is not a docker command")})
    with pytest.raises(ProvisioningUnsupported) as excinfo:
        detect_docker(runner)
    assert "Compose v2" in excinfo.value.reason


def test_detected_docker_reports_both_facts():
    runner = FakeRunner(script={
        "docker --version": (0, "Docker version 27.0.0", ""),
        "docker compose version --short": (0, "v2.39.0", "")})
    facts = detect_docker(runner)
    assert facts == {"docker": "Docker version 27.0.0", "compose": "v2.39.0"}


def test_port_plan_requires_explicit_product_assigned_ports():
    # no defaults: the upstream documentation numbers are never silently used
    import inspect
    params = inspect.signature(PortPlan.__init__).parameters
    assert all(params[name].default is inspect.Parameter.empty
               for name in ("server_port", "postgres_port"))
    with pytest.raises(ValueError):
        PortPlan(server_port=0, postgres_port=5432)
    with pytest.raises(ValueError):
        PortPlan(server_port=70000, postgres_port=5432)


def test_env_generation_is_random_telemetry_off_and_honors_the_port_plan():
    ports = PortPlan(server_port=18080, postgres_port=18432)
    one = render_env(ports, {"POSTGRES_PASSWORD": "pw-1", "ADMIN_API_KEY": "key-1",
                             "JWT_SECRET": "jwt-1"}, {})
    two = render_env(ports, {"POSTGRES_PASSWORD": "pw-2", "ADMIN_API_KEY": "key-2",
                             "JWT_SECRET": "jwt-2"}, {})
    assert one != two
    assert "MEM0_TELEMETRY=false" in one
    assert "AUTH_DISABLED=false" in one
    assert "ADMIN_API_KEY=key-1" in one
    assert "JWT_SECRET=jwt-1" in one
    assert "POSTGRES_PASSWORD=pw-1" in one
    assert f"server={ports.server_port}" in one
    assert f"postgres={ports.postgres_port}" in one
    # the pinned upstream default is telemetry ON (F7); the generated file
    # must not carry a bare `MEM0_TELEMETRY=true` anywhere.
    assert "MEM0_TELEMETRY=true" not in one


def test_env_generation_embeds_provider_references_only():
    text = render_env(PortPlan(18080, 18432),
                      {"POSTGRES_PASSWORD": "p", "ADMIN_API_KEY": "a", "JWT_SECRET": "j"},
                      {"OPENAI_API_KEY": "ref://openai-cred"})
    assert "OPENAI_API_KEY=ref://openai-cred" in text
    assert "ANTHROPIC_API_KEY=" in text
    assert "GOOGLE_API_KEY=" in text


def test_env_generation_is_byte_stable_for_identical_inputs():
    ports = PortPlan(18080, 18432)
    secrets_in = {"POSTGRES_PASSWORD": "p", "ADMIN_API_KEY": "a", "JWT_SECRET": "j"}
    assert render_env(ports, secrets_in, {}) == render_env(ports, secrets_in, {})


def test_env_write_is_0600_under_the_data_root_and_never_in_the_source_tree(tmp_path):
    deploy = tmp_path / "data-root" / "memory" / "deploy"
    env_path = write_env(deploy, "ADMIN_API_KEY=x\n")
    assert env_path == deploy / ".env"
    assert (env_path.stat().st_mode & 0o777) == 0o600
    source_tree = Path(common.__file__).resolve().parents[2]
    with pytest.raises(ProvisioningUnsupported):
        write_env(source_tree / "nowhere", "ADMIN_API_KEY=x\n")


def test_compose_substack_has_exactly_two_services_and_no_dashboard():
    ports = PortPlan(server_port=18080, postgres_port=18432)
    text = render_compose(ports, Path("/data-root/memory"))
    assert "services:" in text
    assert "  mem0:" in text
    assert "  postgres:" in text
    assert "dashboard" not in text.lower()
    assert common.MEM0_GIT_SHA not in text  # the pin lives in the vendor checkout, not the compose
    assert "pgvector/pgvector:pg17" in text
    assert "127.0.0.1:18080:8000" in text
    assert "127.0.0.1:18432:5432" in text
    assert "MEM0_TELEMETRY=false" in text
    # all state stays under the data root
    assert "/data-root/memory/postgres-data" in text
    assert "/data-root/memory/history" in text


def test_compose_render_is_byte_stable():
    ports = PortPlan(18080, 18432)
    assert (render_compose(ports, Path("/data-root/memory"))
            == render_compose(ports, Path("/data-root/memory")))


def test_vendor_checkout_is_cloned_at_the_pinned_sha_and_recorded(tmp_path):
    runner = FakeRunner()
    target = ensure_vendor(runner, tmp_path)
    assert (target / "VENDOR_SHA").read_text().strip() == common.MEM0_GIT_SHA
    joined = [" ".join(call) for call in runner.calls]
    assert any(common.MEM0_REPO_URL in call for call in joined)
    assert any(common.MEM0_GIT_SHA in call for call in joined)
    # idempotent: a checkout at the pin is reused, not recloned
    runner2 = FakeRunner()
    assert ensure_vendor(runner2, tmp_path) == target
    assert runner2.calls == []


def test_vendor_checkout_at_a_foreign_sha_refuses_instead_of_repinning(tmp_path):
    target = provisioning.vendor_dir(tmp_path)
    target.mkdir(parents=True)
    (target / "VENDOR_SHA").write_text("deadbeef" + "0" * 56)
    with pytest.raises(ProvisioningUnsupported) as excinfo:
        ensure_vendor(FakeRunner(), tmp_path)
    assert "不静默换版" in excinfo.value.reason


def test_upstream_pin_matches_the_first_hand_download():
    """The pin recorded in common.py is the SHA this package verified
    first-hand (server/main.py sha256 from the pinned checkout)."""
    import hashlib
    pinned_main = Path("/tmp/mem0-probe/mem0-git/server/main.py")
    if not pinned_main.exists():
        pytest.skip("first-hand checkout not present in this environment")
    assert hashlib.sha256(pinned_main.read_bytes()).hexdigest() == common.MEM0_SERVER_MAIN_SHA256
