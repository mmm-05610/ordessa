"""Native product assembly checks: no Agent process or model is launched."""
from pathlib import Path
import shutil

import pytest

from ordessa_server_product.cli import SERVER_CLI_FLAGS, plan_server_cli
from ordessa_server_product.composition import create_composition
from server_plugin_api import WireError


def values(**overrides):
    defaults = {spec.dest: spec.add.get("default") for spec in SERVER_CLI_FLAGS}
    return {**defaults, **overrides}


def test_installed_root_routes_only_to_native_product():
    native = values(execution_mode="native", plugin_root=Path("/opt/ordessa/harness"),
                    native_harness="pi", native_adapter_command="/usr/bin/node",
                    native_adapter_arg=[], native_installed_artifact_root="/opt/ordessa/artifacts")
    plan = plan_server_cli(native)
    assert plan.method == "native_runtime"
    assert plan.kwargs["installed_artifact_root"] == "/opt/ordessa/artifacts"
    assert plan_server_cli(values(native_installed_artifact_root="/opt/ordessa/artifacts")).error
    assert "installed_artifact_root" not in plan_server_cli(
        {**native, "native_installed_artifact_root": None}).kwargs


def test_native_product_owns_profile_management_without_claiming_application(tmp_path):
    root = Path(__file__).resolve().parents[3]
    node = shutil.which("node")
    assert node, "controlled assembly requires the recorded Node toolchain"
    runtime = create_composition().native_runtime(
        tmp_path / "data", plugin_root=root / "plugins/harness", harness_id="pi",
        adapter_command=node, adapter_args=(),
        installed_artifact_root="/opt/ordessa/artifacts")
    try:
        runtime.start()
        assert runtime.wire.dispatch("profiles.v2.configuredHarnesses", {}) == {"data": ["pi"]}
        profile = runtime.wire.dispatch("profiles.v2.createProfile", {
            "operationKey": "native-profile-create", "realm": "local", "harnessId": "pi",
            "displayName": "Native"})["data"]
        assert runtime.wire.dispatch("profiles.v2.listProfiles", {}) == {"data": [profile]}
        assert runtime.wire.dispatch("skills.list", {"requestId": "skills-native-list"})["items"] == []
        assert "assets.skills" in str(runtime.wire.dispatch("profiles.v2.describeFacets", {}))
        assert "assets.model-provider" in str(runtime.wire.dispatch("profiles.v2.describeFacets", {}))
        with pytest.raises(WireError):
            runtime.wire.dispatch("profiles.v2.beginTurnApplication", {})
    finally:
        runtime.stop()


def test_native_product_skills_edges_follow_restart_round(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(
        tmp_path / "data", plugin_root=root / "plugins/harness", harness_id="pi",
        adapter_command=shutil.which("node"), installed_artifact_root="/opt/ordessa/artifacts")
    try:
        runtime.start()
        original = runtime.plugin_host.provided_port("profile.core")
        skills = runtime.plugin_host.provided_port("skills.service")
        runtime.stop()
        runtime.start()
        assert runtime.plugin_host.provided_port("profile.core") is not original
        assert runtime.plugin_host.provided_port("skills.service") is not skills
        assert runtime.wire.dispatch("skills.list", {"requestId": "skills-restart-list"})["items"] == []
        assert "assets.skills" in str(runtime.wire.dispatch("profiles.v2.describeFacets", {}))
        assert "assets.model-provider" in str(runtime.wire.dispatch("profiles.v2.describeFacets", {}))
        resolved = runtime.wire.dispatch("skills.resolve", {
            "requestId": "skills-restart-resolve", "harnessId": "pi"})
        assert not any(d["kind"] == "mandatory_policy_unavailable" for d in resolved["diagnostics"])
        current_skills = runtime.plugin_host.provided_port("skills.service")
        assert current_skills.mandatory_policy.layer_status()["status"] == "consulted"
    finally:
        runtime.stop()


def test_native_extra_plugin_failure_releases_product_root(tmp_path, monkeypatch):
    import ordessa_server_product.skills as assembly
    real = assembly.ProductSkillsPlugin

    class FailedSkills(real):
        def build(self, context):
            raise ValueError("controlled Skills activation failure")

    root = Path(__file__).resolve().parents[3]
    kwargs = dict(plugin_root=root / "plugins/harness", harness_id="pi",
                  adapter_command=shutil.which("node"), installed_artifact_root="/opt/ordessa/artifacts")
    monkeypatch.setattr(assembly, "ProductSkillsPlugin", FailedSkills)
    with pytest.raises(ValueError, match="controlled Skills activation failure"):
        create_composition().native_runtime(tmp_path / "data", **kwargs)
    monkeypatch.setattr(assembly, "ProductSkillsPlugin", real)
    retry = create_composition().native_runtime(tmp_path / "data", **kwargs)
    try:
        retry.start()
        assert retry.wire.dispatch("skills.list", {"requestId": "skills-retry-list"})["items"] == []
    finally:
        retry.stop()


def test_native_registration_refuses_unobserved_owner_and_client_uid(tmp_path):
    from server_plugin_api import WireError
    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(
        tmp_path / "data", plugin_root=root / "plugins/harness", harness_id="pi",
        adapter_command=shutil.which("node"), installed_artifact_root="/opt/ordessa/artifacts")
    try:
        runtime.start()
        core = runtime.plugin_host.provided_port("profile.core")
        profile = core.profiles.create("wire-profile", realm="local", harness_id="pi", display_name="P")
        params = {"connectionId": "unobserved", "nativeSessionId": "unobserved",
                  "profileId": profile["profile_id"]}
        with pytest.raises(WireError) as refusal:
            runtime.wire.dispatch("profiles.v2.registerNativeSession", params)
        assert refusal.value.details["internalCode"] == "SESSION_NOT_FOUND"
        with pytest.raises(WireError):
            runtime.wire.dispatch("profiles.v2.registerNativeSession", {**params, "sessionUid": "forged"})
        with core.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM profile_sessions").fetchone()[0] == 0
        first = runtime.plugin_host.provided_port("profile.native-sessions")
        runtime.stop()
        assert runtime.plugin_host.provided_port("profile.native-sessions") is None
        runtime.start()
        assert runtime.plugin_host.provided_port("profile.native-sessions") is not first
        assert runtime.plugin_host.provided_port("profile.native-sessions").core is not core
    finally:
        runtime.stop()


def test_native_model_choice_profile_value_survives_restart_without_applying(tmp_path):
    from ordessa_profile.errors import ProfileError

    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(
        tmp_path / "data", plugin_root=root / "plugins/harness", harness_id="pi",
        adapter_command=shutil.which("node"), installed_artifact_root="/opt/ordessa/artifacts")
    choice = {"harnessId": "pi", "providerConfigId": "controlled-provider", "modelId": "m1"}
    try:
        runtime.start()
        core = runtime.plugin_host.provided_port("profile.core")
        profile = core.profiles.create("model-profile-create", realm="local", harness_id="pi", display_name="Model")
        pid = profile["profile_id"]
        saved = runtime.wire.dispatch("profiles.v2.saveProfile", {
            "operationKey": "model-profile-save", "profileId": pid, "expectedVersion": 1,
            "patches": [{"facetId": "assets.model-provider", "itemId": "choice", "op": "set", "value": choice}]})
        assert saved["data"]["profile"]["version"] == 2
        with pytest.raises(ProfileError):
            core.profiles.set_facet_values("model-profile-wrong-harness", profile_id=pid,
                expected_version=core.profiles.get(pid)["version"],
                values=[{"facet_id": "assets.model-provider", "item_id": "choice",
                         "value": {**choice, "harnessId": "codex"}}])
        runtime.stop()
        runtime.start()
        current = runtime.plugin_host.provided_port("profile.core")
        assert current is not core
        stored = current.profiles.facet_values(pid)
        assert [(v["facet_id"], v["item_id"], v["value"], v["quarantined"]) for v in stored] == [
            ("assets.model-provider", "choice", choice, False)]
        assert current.config_port is None  # persistence is not a runtime application receipt
    finally:
        runtime.stop()


def test_native_product_passes_installed_root_to_harness_startup_only(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as composition

    captured = []

    class ControlledTransport:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def start(self):
            return self

    monkeypatch.setattr(composition, "AccessEntryTransport", ControlledTransport)
    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(tmp_path / "data",
        plugin_root=root / "plugins/harness", harness_id="pi",
        adapter_command=shutil.which("node"), installed_artifact_root="/opt/ordessa/artifacts")
    try:
        runtime.plugin_host.provided_port("acp.channels")._launch(
            harness_id="pi", cwd=str(tmp_path), on_line=lambda _: None, on_exit=lambda _: None)
        assert len(captured) == 1
        assert captured[0]["installed_artifact_root"] == "/opt/ordessa/artifacts"
        assert "installed_artifact_root" not in captured[0]["adapter"]
        assert "controlled_test_peer" not in captured[0]
    finally:
        runtime.stop()


@pytest.mark.parametrize("invalid", ["relative", "//opt/ordessa", "/opt/../opt/ordessa", "/opt/ordessa\x00"])
def test_invalid_installed_root_refuses_before_creating_data(tmp_path, invalid):
    with pytest.raises(RuntimeError, match="NATIVE_INSTALLED_ROOT_INVALID"):
        create_composition().native_runtime(tmp_path / "data", plugin_root=tmp_path,
            harness_id="pi", adapter_command="/usr/bin/node", installed_artifact_root=invalid)
    assert not (tmp_path / "data").exists()


def test_enhanced_pi_flag_routes_to_native_product_only():
    native = values(execution_mode="native", plugin_root=Path("/opt/ordessa/harness"),
                    native_harness="pi", native_adapter_command="/usr/bin/node",
                    native_adapter_arg=[], native_pi_profile_bridge=True,
                    native_installed_artifact_root="/opt/ordessa/artifacts")
    assert plan_server_cli(native).kwargs["pi_profile_bridge"] is True
    assert plan_server_cli(values(native_pi_profile_bridge=True)).error


def test_native_profile_flags_route_to_explicit_native_product_only():
    native = values(execution_mode='native', plugin_root=Path('/opt/ordessa/harness'),
                    native_harness='codex', native_adapter_command='/usr/bin/node',
                    native_profile_harness=['codex', 'claude-code'])
    assert plan_server_cli(native).kwargs['native_profile_harnesses'] == ('codex', 'claude-code')
    assert plan_server_cli(values(native_profile_harness=['codex'])).error


@pytest.mark.parametrize('brands', [['codex'], ('pi',), ('codex', 'codex'), ({},), ('claude-code',)])
def test_native_profile_selection_refuses_before_data_creation(tmp_path, brands):
    root = Path(__file__).resolve().parents[3]
    with pytest.raises(RuntimeError, match='NATIVE_PROFILE_SELECTION_INVALID'):
        create_composition().native_runtime(tmp_path / 'data', plugin_root=root / 'plugins/harness',
            harness_id='codex', adapter_command=shutil.which('node'),
            installed_artifact_root='/opt/ordessa/artifacts', native_profile_harnesses=brands)
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('brand', ['codex', 'claude-code'])
def test_native_profile_launch_and_factory_are_explicit_and_instance_scoped(tmp_path, monkeypatch, brand):
    import ordessa_server_compat.composition as composition
    captured = []
    class ControlledTransport:
        def __init__(self, **kwargs):
            captured.append(kwargs)
        def start(self):
            return self
    monkeypatch.setattr(composition, 'AccessEntryTransport', ControlledTransport)
    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(tmp_path / 'data',
        plugin_root=root / 'plugins/harness', harness_id=brand,
        adapter_command=shutil.which('node'), installed_artifact_root='/opt/ordessa/enhanced',
        native_profile_harnesses=(brand,))
    try:
        port = runtime.plugin_host.provided_port('profile.core').config_port
        assert port.supported_harnesses == {brand}
        launch = runtime.plugin_host.provided_port('acp.channels')._launch
        for _ in range(2):
            launch(harness_id=brand, cwd=str(tmp_path), on_line=lambda _: None, on_exit=lambda _: None)
        paths = [Path(row['instance_directory']) for row in captured]
        assert paths[0] != paths[1]
        assert all(row['native_profile_bridge'] is True and row['harness_id'] == brand for row in captured)
        assert all('pi_profile_bridge' not in row for row in captured)
        assert all(path.exists() and path.stat().st_mode & 0o077 == 0 for path in paths)
        assert all('instance_directory' not in row['adapter'] for row in captured)
    finally:
        runtime.stop()


def test_enhanced_pi_launch_allocates_per_process_not_per_profile(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as composition
    captured = []

    class ControlledTransport:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def start(self):
            return self

    monkeypatch.setattr(composition, "AccessEntryTransport", ControlledTransport)
    root = Path(__file__).resolve().parents[3]
    runtime = create_composition().native_runtime(tmp_path / "data",
        plugin_root=root / "plugins/harness", harness_id="pi", adapter_command=shutil.which("node"),
        installed_artifact_root="/opt/ordessa/artifacts", pi_profile_bridge=True)
    try:
        launch = runtime.plugin_host.provided_port("acp.channels")._launch
        for _ in range(2):
            launch(harness_id="pi", cwd=str(tmp_path), on_line=lambda _: None, on_exit=lambda _: None)
        paths = [Path(row["instance_directory"]) for row in captured]
        assert paths[0] != paths[1]
        assert all(row["pi_profile_bridge"] is True for row in captured)
        assert all(item.exists() and item.stat().st_mode & 0o077 == 0 for item in paths)
        assert all("instance_directory" not in row["adapter"] for row in captured)
    finally:
        runtime.stop()
    assert all(item.exists() for item in paths), "recovery state must not be deleted on stop"
