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


def test_same_project_scopes_have_independent_owners_and_never_revive(tmp_path, monkeypatch):
    import ordessa_server_compat.composition as assembly
    calls = []

    class Transport:
        def __init__(self, **kwargs):
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
        project = runtime.wire.dispatch("workspaces.open", {"requestId": "scoped-project-open",
            "environment": {"kind": "local", "host": None, "user": None},
            "path": str(tmp_path)})["workspace"]["id"]
        def acquire(scope):
            return runtime.wire.dispatch("acp.channel.open", {"harnessId": "pi",
                "projectId": project, "sessionScopeId": scope})
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(lambda _: acquire("session-a"), range(4)))
        assert all(item == concurrent[0] for item in concurrent)
        a, b = concurrent[0], acquire("session-b")
        assert a["connectionId"] != b["connectionId"]
        assert a["executionId"] != b["executionId"]
        assert acquire("session-a") == a
        assert len(calls) == 2
        runtime.wire.dispatch("acp.channel.release", {"connectionId": a["connectionId"]})
        with pytest.raises(WireError, match="terminal"):
            acquire("session-a")
        assert acquire("session-b") == b
        assert calls[0].terminated == 1 and calls[1].terminated == 0
        for invalid in (" spaced", "bad\nnonce", "x" * 129, 12):
            with pytest.raises(WireError):
                acquire(invalid)
        assert len(calls) == 2
    finally:
        runtime.stop()
    assert all(item.terminated == 1 for item in calls)


@pytest.mark.parametrize('exit_phase', ['launch', 'registered'])
def test_a_scoped_agent_exit_removes_dead_owner_and_refuses_nonce_replay(tmp_path, monkeypatch, exit_phase):
    import ordessa_server_compat.composition as assembly
    calls = []
    class Transport:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            calls.append(self)
        def start(self):
            if exit_phase == 'launch':
                self.kwargs['on_exit'](7)
            return self
        def terminate(self):
            pass
    monkeypatch.setattr(assembly, 'AccessEntryTransport', Transport)
    runtime = create_composition().native_runtime(tmp_path / 'data', **options(tmp_path))
    try:
        runtime.start()
        project = runtime.wire.dispatch('workspaces.open', {'requestId': 'dead-owner-project',
            'environment': {'kind': 'local', 'host': None, 'user': None},
            'path': str(tmp_path)})['workspace']['id']
        request = {'harnessId': 'pi', 'projectId': project, 'sessionScopeId': 'scoped-exit'}
        first = runtime.wire.dispatch('acp.channel.open', request)
        if exit_phase == 'registered':
            calls[0].kwargs['on_exit'](7)
        registry = runtime.plugin_host.provided_port('acp.channels')
        assert registry.get(first['connectionId']) is None
        assert registry._by_pair == {}
        with pytest.raises(WireError, match='terminal'):
            runtime.wire.dispatch('acp.channel.open', request)
        assert len(calls) == 1
    finally:
        runtime.stop()


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
