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
        with pytest.raises(WireError):
            runtime.wire.dispatch("profiles.v2.beginTurnApplication", {})
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
