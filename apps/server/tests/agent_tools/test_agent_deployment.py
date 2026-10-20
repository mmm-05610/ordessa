"""Real opt-in Server lifecycle with a temporary data root; no HTTP/models."""
from ordessa_server.composition.agent_tools.owner_ports import OwnerAssemblyRefused
from ordessa_execution_agents.profiles import encode_content
from ordessa_execution_agents.profiles import encode_profile
import importlib.util
from pathlib import Path
import sys

import pytest
from ordessa_infrastructure.identifiers import RequestKey
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from ordessa_units.public import unit_services


def deployment_module():
    from ordessa_server.composition import agent_tools
    return agent_tools


@pytest.fixture
def deployment():
    return deployment_module()


@pytest.fixture
def owned_root():
    from ordessa_server.composition.runtime import DataRootOwner
    owners = []
    def acquire(root):
        owner = DataRootOwner(root)
        owner.acquire()
        owners.append(owner)
        return owner
    yield acquire
    for owner in reversed(owners):
        owner.release()


def fingerprint():
    return ProtectedFingerprintHmac({"fixture": b"isolated-deployment-key"}, active_key_id="fixture")


def test_missing_key_capability_does_not_create_root(deployment, tmp_path):
    root = tmp_path / "untouched"
    config = deployment.AgentServiceConfiguration(root)
    with pytest.raises(OwnerAssemblyRefused):
        deployment.build_agent_runtime(config, fingerprint_port=None)
    assert not root.exists()


@pytest.mark.parametrize("probe", [True, False])
def test_factory_requires_current_os_ownership(deployment, tmp_path, probe):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    path = tmp_path / "unowned" / "state" / "core.sqlite"
    with pytest.raises(OwnerAssemblyRefused):
        composition.owned_environment_factory(path, lambda: probe)
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
        profile = unit_services(env).profiles
        request = RequestKey(identity, "local", "isolated-create")
        content = {"harnessDefinitionRef": {"environmentNamespace": identity,
                     "definitionId": "missing", "revision": "1"},
                   "schemaVersion": "1", "declarations": []}
        first = profile.create(profile_id="fixture", name="Fixture", content=content, request=request)
        assert profile.preview(first.current_revision)["ready"] is False
        app = deployment.create_agent_app(runtime)
        assert app is not None
        old_method = runtime.plugin_host.methods.lookup("agents.profiles.list")
        assert old_method.handler({})["entries"] == [encode_profile(first)]
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
        reopened = unit_services(new_env).profiles
        assert reopened.create(profile_id="fixture", name="Fixture", content=content, request=request) == first
        assert encode_content(reopened.get_revision(first.current_revision).content) == content
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
    with pytest.raises(OwnerAssemblyRefused):
        deployment.build_agent_runtime(deployment.AgentServiceConfiguration(root), fingerprint_port=fingerprint())
    assert list(root.iterdir()) == [marker]
    assert marker.read_text() == "untouched"


def test_policy_has_only_profile_data_authority(deployment, tmp_path, owned_root):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    owner = owned_root(tmp_path / "policy-root")
    env = composition.owned_environment_factory(owner.root / "state" / "core.sqlite", owner)
    try:
        assert env._policy.admit_invoke("local", "pacthold.agents.profiles.create", "reliable")
        for surface in ["agent.configuration-intent", "native.channel-start", "pacthold.agents.nodes.prepare"]:
            assert not env._policy.admit_invoke("local", surface, "reliable")
        assert not env._policy.admit_object_access("local", "foreign:agents.profile:one", "write")
        assert not env._policy.admit_invoke("foreign", "pacthold.agents.profiles.create", "reliable")
    finally:
        env.close()


def test_core_path_symlink_is_refused_before_any_store_write(deployment, tmp_path, owned_root):
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    target = tmp_path / "untouched.sqlite"
    target.write_bytes(b"untouched")
    owner = owned_root(tmp_path / "symlink-root")
    link = owner.root / "state" / "core.sqlite"
    link.parent.mkdir()
    link.symlink_to(target)
    with pytest.raises(OwnerAssemblyRefused):
        composition.owned_environment_factory(link, owner)
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
    with pytest.raises(OwnerAssemblyRefused):
        deployment.build_agent_runtime(deployment.AgentServiceConfiguration(root), fingerprint_port=fingerprint())
    assert path.read_bytes() == before
    assert not (root / "secrets").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
@pytest.mark.parametrize("entry", ["factory", "runtime"])
def test_core_sidecar_link_refused_before_opening_database(deployment, tmp_path, monkeypatch, suffix, entry, owned_root):
    # First create only this test's own marked Environment database, then close
    # it. Neither the Server nor SQLite may follow the injected sidecar link.
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    root = tmp_path / "isolated"
    path = root / "state" / "core.sqlite"
    owner = owned_root(root)
    env = composition.owned_environment_factory(path, owner)
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
    with pytest.raises(OwnerAssemblyRefused, match="sidecars"):
        if entry == "factory":
            composition.owned_environment_factory(path, owner)
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
    configuration = deployment.AgentServiceConfiguration(tmp_path / "v2-root", agent_contract_version="agent-assembly/3")
    runtime = deployment.build_agent_runtime(configuration, fingerprint_port=fingerprint())
    try:
        runtime.start()
        env = runtime.core_binding.environment
        assert runtime.plugin_selection == () and env.installed == ()
        assert unit_services(env).providers.list() == ()
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
    with pytest.raises(OwnerAssemblyRefused):
        selected.build_runtime(deployment.AgentServiceConfiguration(root, agent_contract_version="agent-assembly/3"))
    assert not root.exists()


@pytest.mark.parametrize("kind", ["lookalike", "unissued", "override", "foreign", "released", "path-replaced"])
def test_factory_rejects_unissued_or_expired_bindings_before_database_io(
    deployment, tmp_path, owned_root, monkeypatch, kind,
):
    from server_plugin_api.root_ownership import OwnedRootBinding
    from types import SimpleNamespace
    root = tmp_path / "proof-root"
    owner = owned_root(root)
    path = root / "state" / "core.sqlite"
    child = root / "plugins" / "profile" / "native-configuration.sqlite"
    binding = owner.bind_owned_root(root_path=root, store_path=path, child_path=child)
    if kind == "lookalike":
        binding = SimpleNamespace(validate_for=lambda **kwargs: None)
    elif kind == "unissued":
        binding = object.__new__(OwnedRootBinding)
    elif kind == "override":
        class Counterfeit(OwnedRootBinding):
            def validate_for(self, **kwargs):
                return None
        binding = object.__new__(Counterfeit)
    elif kind == "foreign":
        other = owned_root(tmp_path / "foreign-root")
        binding = other.bind_owned_root(root_path=other.root,
            store_path=other.root / "state" / "core.sqlite",
            child_path=other.root / "plugins" / "profile" / "native-configuration.sqlite")
    elif kind == "released":
        owner.release()
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "state").symlink_to(outside, target_is_directory=True)
    port = SimpleNamespace(bind_owned_root=lambda **kwargs: binding,
                           validate_owned_root=owner.validate_owned_root)
    module = sys.modules[deployment.AgentToolsDeployment.__module__]
    def forbidden(*args, **kwargs):
        raise AssertionError("database opened before validating issued root proof")
    monkeypatch.setattr(module.sqlite3, "connect", forbidden)
    monkeypatch.setattr(module, "SqliteStorePort", forbidden)
    composition = deployment.AgentToolsDeployment(fingerprint_port=fingerprint())
    with pytest.raises(OwnerAssemblyRefused):
        composition.owned_environment_factory(path, port)
    assert not path.exists()
    assert not child.exists()
    if kind == "path-replaced":
        assert tuple(outside.iterdir()) == ()
