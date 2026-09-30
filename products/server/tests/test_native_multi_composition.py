"""One product, independently routed brands. No Agent or model is spawned."""
from pathlib import Path
import shutil

import pytest
from server_plugin_api import WireError
from ordessa_server_product.composition import create_composition


def options(root):
    return dict(plugin_root=Path(__file__).resolve().parents[3] / "plugins/harness",
                harness_id="pi", adapter_command=shutil.which("node"),
                installed_artifact_root="/opt/ordessa/artifacts",
                additional_adapters=({"harnessId": "codex", "command": shutil.which("node"),
                                      "args": ["controlled-codex"]},
                                     {"harnessId": "claude-code", "command": shutil.which("node"),
                                      "args": ["controlled-claude"]}))


def test_multi_native_discovery_profiles_and_launch_routes_restart(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as assembly
    calls = []

    class Transport:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def start(self):
            return self

    monkeypatch.setattr(assembly, "AccessEntryTransport", Transport)
    runtime = create_composition().native_runtime(tmp_path / "data", **options(tmp_path))
    try:
        for _ in range(2):
            runtime.start()
            hello = runtime.wire.dispatch("server.hello", {"clientVersions": ["wire/1"],
                "clientPresentationSupports": []})
            assert [row["id"] for row in hello["acpChannelHarnesses"]] == ["claude-code", "codex", "pi"]
            assert runtime.wire.dispatch("profiles.v2.configuredHarnesses", {}) == {
                "data": ["claude-code", "codex", "pi"]}
            channels = runtime.plugin_host.provided_port("acp.channels")
            for hid, argument in [("pi", []), ("codex", ["controlled-codex"]),
                                  ("claude-code", ["controlled-claude"])]:
                channels._launch(harness_id=hid, cwd=str(tmp_path), on_line=lambda _: None,
                                 on_exit=lambda _: None)
                assert calls[-1]["harness_id"] == hid
                assert calls[-1]["adapter"]["args"] == argument
            runtime.stop()
        assert len(calls) == 6
    finally:
        runtime.stop()


def test_unknown_multi_harness_is_refused_before_launch(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as assembly
    calls = []
    monkeypatch.setattr(assembly, "AccessEntryTransport", lambda **kwargs: calls.append(kwargs))
    runtime = create_composition().native_runtime(tmp_path / "data", **options(tmp_path))
    try:
        runtime.start()
        with pytest.raises(WireError) as refusal:
            runtime.wire.dispatch("acp.channel.open", {"harnessId": "unknown", "projectId": "unused"})
        assert refusal.value.family == "CAPABILITY_UNSUPPORTED"
        assert calls == []
    finally:
        runtime.stop()


def test_multi_channels_do_not_share_ownership_or_accept_changed_identity(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as assembly
    calls = []

    class Transport:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.terminated = 0
            calls.append(self)

        def start(self):
            return self

        def terminate(self):
            self.terminated += 1

    monkeypatch.setattr(assembly, "AccessEntryTransport", Transport)
    runtime = create_composition().native_runtime(tmp_path / "data", **options(tmp_path))
    try:
        runtime.start()
        workspace = runtime.wire.dispatch("workspaces.open", {"requestId": "multi-project-open",
            "environment": {"kind": "local", "host": None, "user": None}, "path": str(tmp_path)})["workspace"]
        opened = {hid: runtime.wire.dispatch("acp.channel.open", {"harnessId": hid,
                  "projectId": workspace["id"]}) for hid in ("pi", "codex", "claude-code")}
        assert len({value["connectionId"] for value in opened.values()}) == 3
        assert len({value["executionId"] for value in opened.values()}) == 3
        again = runtime.wire.dispatch("acp.channel.open", {"harnessId": "pi", "projectId": workspace["id"]})
        assert again == opened["pi"]
        assert len(calls) == 3
        assert [value.kwargs["harness_id"] for value in calls] == ["pi", "codex", "claude-code"]
        assert runtime.wire.dispatch("acp.channel.release", {"connectionId": opened["codex"]["connectionId"]})["released"]
        registry = runtime.plugin_host.provided_port("acp.channels")
        assert registry.get(opened["pi"]["connectionId"]) is not None
        assert registry.get(opened["claude-code"]["connectionId"]) is not None
        assert calls[1].terminated == 1 and calls[0].terminated == calls[2].terminated == 0
        with runtime.database.transaction() as conn:
            conn.execute("UPDATE server_profiles SET archived_at='controlled' WHERE harness_type='claude-code'")
        hello = runtime.wire.dispatch("server.hello", {"clientVersions": ["wire/1"], "clientPresentationSupports": []})
        assert [row["id"] for row in hello["acpChannelHarnesses"]] == ["codex", "pi"]
        with pytest.raises(WireError):
            runtime.wire.dispatch("acp.channel.open", {"harnessId": "claude-code", "projectId": workspace["id"]})
        assert len(calls) == 3
    finally:
        runtime.stop()
    assert all(value.terminated == 1 for value in calls)


@pytest.mark.parametrize("row", [
    {"harnessId": "pi", "command": "/usr/bin/node", "args": []},
    {"harnessId": "codex", "command": "relative", "args": []},
    {"harnessId": "codex", "command": "/usr/bin/node", "args": ["bad\x00arg"]},
    {"harnessId": "codex", "command": "/usr/bin/node", "args": [], "unexpected": True},
])
def test_invalid_additional_adapter_refuses_before_creating_root(tmp_path, row):
    kwargs = {**options(tmp_path), "additional_adapters": (row,)}
    with pytest.raises(RuntimeError, match="NATIVE_ADAPTER|NATIVE_HARNESS"):
        create_composition().native_runtime(tmp_path / "data", **kwargs)
    assert not (tmp_path / "data").exists()


def test_multi_cli_remains_product_owned_and_requires_native_mode():
    import json
    from ordessa_server_product.cli import SERVER_CLI_FLAGS, plan_server_cli
    values = {spec.dest: spec.add.get("default") for spec in SERVER_CLI_FLAGS}
    additions = [{"harnessId": "codex", "command": "/usr/bin/node", "args": ["adapter.js"]}]
    parsed = {**values, "execution_mode": "native", "plugin_root": Path("/opt/harness"),
              "native_harness": "pi", "native_adapter_command": "/usr/bin/node",
              "native_additional_adapters": json.dumps(additions)}
    plan = plan_server_cli(parsed)
    assert plan.method == "native_runtime"
    assert plan.kwargs["additional_adapters"] == tuple(additions)
    assert plan_server_cli({**values, "native_additional_adapters": json.dumps(additions)}).error
    with pytest.raises(SystemExit, match="JSON array"):
        plan_server_cli({**parsed, "native_additional_adapters": "{}"})
