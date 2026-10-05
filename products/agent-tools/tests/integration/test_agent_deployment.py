"""Real opt-in Server lifecycle with a temporary data root; no HTTP/models."""
import importlib.util
from pathlib import Path
import sys

import pytest
from ordessa_environment_api import GuaranteeUnavailableError, RequestKey
from ordessa_persistence_sqlite import ProtectedFingerprintHmac
from pacthold.agents.public import agent_services


def deployment_module():
    path = Path(__file__).resolve().parents[2] / "deployment" / "__init__.py"
    spec = importlib.util.spec_from_file_location("agent_tools_deployment_test", path,
                                                submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def deployment():
    return deployment_module()


def fingerprint():
    return ProtectedFingerprintHmac({"fixture": b"isolated-deployment-key"}, active_key_id="fixture")


def test_missing_key_capability_does_not_create_root(deployment, tmp_path):
    root = tmp_path / "untouched"
    config = deployment.AgentServiceConfiguration(root)
    with pytest.raises(GuaranteeUnavailableError):
        deployment.build_agent_runtime(config, fingerprint_port=None)
    assert not root.exists()


def test_factory_requires_current_os_ownership(deployment, tmp_path):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    path = tmp_path / "core.sqlite"
    with pytest.raises(GuaranteeUnavailableError):
        composition.owned_environment_factory(path, lambda: False)
    assert not path.exists()


def test_isolated_runtime_profile_storage_restart_and_empty_plugins(deployment, tmp_path, monkeypatch):
    from ordessa_server_product.composition import ServerProductComposition
    def forbidden(*args, **kwargs):
        raise AssertionError("default Agent/native product assembly must not be called")
    monkeypatch.setattr(ServerProductComposition, "default_plugins", forbidden)
    monkeypatch.setattr(ServerProductComposition, "environment_factory", forbidden)
    configuration = deployment.AgentServiceConfiguration(tmp_path / "isolated")
    runtime = deployment.build_agent_runtime(configuration, fingerprint_port=fingerprint())
    try:
        assert not runtime.started
        assert runtime.plugin_selection == ()
        runtime.start()
        assert runtime.plugin_host.active_ids() == ()
        env = runtime.core_binding.environment
        identity = env.environment_id
        assert env.enabled == () and env.installed == ()
        assert env.registry_snapshot.contract_ids == ()
        profile = agent_services(env).profiles
        request = RequestKey(identity, "local", "isolated-create")
        content = {"harnessDefinitionRef": {"environmentNamespace": identity,
                     "definitionId": "missing", "revision": "1"},
                   "schemaVersion": "1", "declarations": []}
        first = profile.create(profile_id="fixture", display_name="Fixture", manifest=content, request=request)
        assert profile.preview(first.current_manifest_ref)["ready"] is False
        app = deployment.create_agent_app(runtime)
        assert app is not None
        old_method = runtime.plugin_host.methods.lookup("agents.profiles.list")
        assert old_method.handler({})["entries"] == [first.to_dict()]
        runtime.stop()
        assert env._closed
        assert not runtime.owner.acquired
        from server_plugin_api import WireError
        with pytest.raises(WireError) as unavailable:
            old_method.handler({})
        assert unavailable.value.family == "CAPABILITY_UNSUPPORTED"
        runtime.start()
        new_env = runtime.core_binding.environment
        assert new_env is not env and new_env.environment_id == identity
        assert new_env.enabled == ()
        assert runtime.plugin_host.active_ids() == ()
        reopened = agent_services(new_env).profiles
        assert reopened.create(profile_id="fixture", display_name="Fixture", manifest=content, request=request) == first
        assert reopened.read(first.current_manifest_ref).content == content
        assert len(reopened.list()) == 1
    finally:
        runtime.stop()
    # A freshly constructed runtime also reuses the durable namespace.
    fresh = deployment.build_agent_runtime(configuration, fingerprint_port=fingerprint())
    try:
        fresh.start()
        assert fresh.core_binding.environment.environment_id == identity
    finally:
        fresh.stop()


def test_reject_nonempty_unowned_root_without_modification(deployment, tmp_path):
    root = tmp_path / "user-root"
    root.mkdir()
    marker = root / "user-file"
    marker.write_text("untouched")
    with pytest.raises(GuaranteeUnavailableError):
        deployment.build_agent_runtime(deployment.AgentServiceConfiguration(root), fingerprint_port=fingerprint())
    assert list(root.iterdir()) == [marker]
    assert marker.read_text() == "untouched"


def test_policy_has_only_profile_data_authority(deployment, tmp_path):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    env = composition.owned_environment_factory(tmp_path / "core.sqlite", lambda: True)
    try:
        assert env._policy.admit_invoke("local", "pacthold.agents.profiles.create", "reliable")
        for surface in ["agent.configuration-intent", "native.channel-start", "pacthold.agents.nodes.prepare"]:
            assert not env._policy.admit_invoke("local", surface, "reliable")
        assert not env._policy.admit_object_access("local", "foreign:agents.profile:one", "write")
        assert not env._policy.admit_invoke("foreign", "pacthold.agents.profiles.create", "reliable")
    finally:
        env.close()


def test_core_path_symlink_is_refused_before_any_store_write(deployment, tmp_path):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    target = tmp_path / "untouched.sqlite"
    target.write_bytes(b"untouched")
    link = tmp_path / "core.sqlite"
    link.symlink_to(target)
    with pytest.raises(GuaranteeUnavailableError):
        composition.owned_environment_factory(link, lambda: True)
    assert target.read_bytes() == b"untouched"


def test_unrelated_core_database_refused_before_host_initialization(deployment, tmp_path):
    import sqlite3
    from contextlib import closing
    root = tmp_path / "unrelated"
    (root / "state").mkdir(parents=True)
    path = root / "state" / "core.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
        connection.commit()
    before = path.read_bytes()
    with pytest.raises(GuaranteeUnavailableError):
        deployment.build_agent_runtime(deployment.AgentServiceConfiguration(root), fingerprint_port=fingerprint())
    assert path.read_bytes() == before
    assert not (root / "secrets").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
@pytest.mark.parametrize("entry", ["factory", "runtime"])
def test_core_sidecar_link_refused_before_opening_database(deployment, tmp_path, monkeypatch, suffix, entry):
    # First create only this test's own marked Environment database, then close
    # it. Neither the Server nor SQLite may follow the injected sidecar link.
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    root = tmp_path / "isolated"
    path = root / "state" / "core.sqlite"
    env = composition.owned_environment_factory(path, lambda: True)
    env.close()
    before = path.read_bytes()
    target = tmp_path / "untouched-target"
    target.write_bytes(b"must-not-be-opened-as-a-sidecar")
    sidecar = path.with_name(path.name + suffix)
    sidecar.symlink_to(target)
    # A missing guard would attempt a main DB open first. Deny that attempt so
    # the test proves preflight ordering without risking the target contents.
    module = sys.modules[deployment.AgentToolsDeployment.__module__]
    def forbidden_open(*args, **kwargs):
        raise AssertionError("SQLite opened before the sidecar symlink guard")
    monkeypatch.setattr(module.sqlite3, "connect", forbidden_open)
    monkeypatch.setattr(module, "SqliteStorePort", forbidden_open)
    with pytest.raises(GuaranteeUnavailableError, match="sidecars"):
        if entry == "factory":
            composition.owned_environment_factory(path, lambda: True)
        else:
            composition.build_runtime(deployment.AgentServiceConfiguration(root))
    assert target.read_bytes() == b"must-not-be-opened-as-a-sidecar"
    assert path.read_bytes() == before
    assert sidecar.is_symlink()


def test_unknown_contract_refuses_before_creating_root(deployment, tmp_path):
    root = tmp_path / "unselected-contract"
    with pytest.raises(ValueError): deployment.AgentServiceConfiguration(root, agent_contract_version="agent-assembly/999")
    assert not root.exists()


def test_v2_policy_grants_registry_read_only(deployment, tmp_path):
    configuration = deployment.AgentServiceConfiguration(tmp_path / "v2-root", agent_contract_version="agent-assembly/2")
    runtime = deployment.build_agent_runtime(configuration, fingerprint_port=fingerprint())
    try:
        runtime.start()
        env = runtime.core_binding.environment
        assert runtime.plugin_selection == () and env.installed == ()
        assert agent_services(env).providers.list() == ()
        target = env.environment_id + ":agents.runtime"
        assert env._policy.admit_object_access("local", target, "read")
        assert not env._policy.admit_object_access("local", target, "write")
        assert not env._policy.admit_object_access("foreign", target, "read")
        assert not env._policy.admit_object_access("local", target + ":forged", "read")
        assert not env._policy.admit_invoke("local", "pacthold.agents.prepare", "reliable")
    finally:
        runtime.stop()


def test_composition_contract_mismatch_refuses_before_creating_root(deployment, tmp_path):
    root = tmp_path / "mismatched-contract"
    selected = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    with pytest.raises(GuaranteeUnavailableError):
        selected.build_runtime(deployment.AgentServiceConfiguration(root, agent_contract_version="agent-assembly/2"))
    assert not root.exists()
