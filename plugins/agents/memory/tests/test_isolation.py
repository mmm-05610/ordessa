"""Boundaries (MB-8): data-root placement, two-profile namespace isolation
through the whole pipeline, service-down absence semantics, and the
no-secrets-in-repo scan."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ordessa_memory import common, llm_wiring
from ordessa_memory.capture import CapturePipeline
from ordessa_memory.plugin import MemoryPlugin
from ordessa_memory.store import MemoryStore

from conftest import FakeClientFactory, build_plugin


def _pipeline(store, client_factory, scope):
    return CapturePipeline(store, (lambda: client_factory.client if client_factory else None),
                           lambda: scope)


def _ready(store, pipeline):
    store.set_extraction_authorized(True)
    pipeline.mark_source_bound(True)


def _turn(profile_id, turn_id):
    from ordessa_memory.events import TurnEvent
    return TurnEvent(profile_id=profile_id, session_id="s1", turn_id=turn_id,
                     user_text=f"{profile_id} 的偏好", assistant_text="收到")


def test_two_profiles_are_isolated_namespaces_through_the_whole_chain(
        store, client_factory, fake_mem0):
    pipeline = _pipeline(store, client_factory, "srv-1")
    _ready(store, pipeline)
    assert pipeline.on_turn(_turn("p1", "t1"), binding={"enabled": True, "boundBrands": ["pi"]})
    assert pipeline.on_turn(_turn("p2", "t1"), binding={"enabled": True, "boundBrands": ["pi"]})
    pipeline.flush()
    mem0_posts = [body for (m, p, h, body) in fake_mem0.requests
                  if m == "POST" and p == "/memories"]
    assert [b["user_id"] for b in mem0_posts] == [
        "ordessa:srv-1:profile:p1", "ordessa:srv-1:profile:p2"]


def test_same_server_scoped_differently_isolates(store, client_factory, fake_mem0):
    """The same profile id on two Servers is two namespaces (server scope)."""
    for scope in ("srv-1", "srv-2"):
        pipeline = _pipeline(store, client_factory, scope)
        _ready(store, pipeline)
        assert pipeline.on_turn(_turn("p1", "t2"), binding={"enabled": True, "boundBrands": ["pi"]})
        pipeline.flush()
    mem0_posts = [body for (m, p, h, body) in fake_mem0.requests
                  if m == "POST" and p == "/memories"]
    assert mem0_posts[-2]["user_id"] == "ordessa:srv-1:profile:p1"
    assert mem0_posts[-1]["user_id"] == "ordessa:srv-2:profile:p1"


def test_namespace_helper_never_collides_on_profile_id_alone():
    assert (common.profile_namespace(None, "p1")
            != common.profile_namespace("srv-1", "p1"))
    assert common.profile_namespace("srv-1", "p1") == "ordessa:srv-1:profile:p1"


def test_service_down_is_absence_not_error(data_root, catalog_openai, fake_runner):
    """Unprovisioned stack: injection empty + health false + capture queued —
    no exception anywhere in the surface."""
    plugin = build_plugin(data_root, catalog=catalog_openai, runner=fake_runner)
    plugin.stack = None
    block = plugin.injection_block_response("p1", "深色", "pi")
    assert block["text"] == "" and "not provisioned" in block["reason"]
    status = plugin.status_snapshot()
    assert status["stack"] == "unprovisioned"
    plugin.store.close()


def test_all_artifacts_stay_under_the_data_root(tmp_path, fake_runner):
    runner = fake_runner
    data_root = tmp_path / "data-root"
    plugin = MemoryPlugin(data_root=data_root, port_plan=None, runner=runner)
    context = SimpleNamespace(plugin_id="t", data_root=data_root,
                              ports={"server.id": "srv-1"})
    plugin.build(context)
    plugin.store.set_binding("p1", {"enabled": True, "budgetTokens": 10,
                                    "extractionModelRef": None, "boundBrands": ["pi"]})
    expected = Path(data_root) / "memory"
    assert (expected / "memory.db").exists()
    plugin.store.close()


def test_provisioned_secrets_never_appear_in_the_package_tree(tmp_path, fake_runner):
    from ordessa_memory import provisioning
    runner = fake_runner
    runner.script = {"docker --version": (0, "d", ""),
                     "docker compose version --short": (0, "v2", "")}
    data_root = tmp_path / "data-root" / "memory"
    data_root.mkdir(parents=True)
    stack = provisioning.MemoryStack(runner, data_root, provisioning.PortPlan(18080, 18432))
    stack.provision({})
    env_text = stack.env_file.read_text()
    secrets = [line.split("=", 1)[1] for line in env_text.splitlines()
               if line.startswith(("ADMIN_API_KEY=", "JWT_SECRET=", "POSTGRES_PASSWORD="))]
    assert all(len(s) >= 24 for s in secrets)
    # scan the package tree for every secret
    package_root = Path(common.__file__).resolve().parents[1]
    for secret in secrets:
        for path in package_root.rglob("*"):
            if path.is_file() and path.name != ".env":
                assert secret not in path.read_text(errors="ignore"), \
                    f"secret leaked into {path}"


def test_uninstall_keeps_data_and_the_env_stays_out_of_the_repo(tmp_path, fake_runner):
    from ordessa_memory import provisioning
    fake_runner.script = {"docker --version": (0, "d", ""),
                          "docker compose version --short": (0, "v2", "")}
    data_root = tmp_path / "data-root" / "memory"
    data_root.mkdir(parents=True)
    stack = provisioning.MemoryStack(fake_runner, data_root, provisioning.PortPlan(18080, 18432))
    stack.provision({})
    stack.uninstall()
    assert stack.env_file.exists()
    assert not any("data-root" in str(p) for p in
                   [Path(common.__file__).resolve()]), "数据只落在 data-root，不在源码树"
