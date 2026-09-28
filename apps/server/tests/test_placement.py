"""The placement decides the channel - and nothing else does.

A workspace record says where a turn belongs (`env_kind`). That fact resolves to
exactly one channel implementation; a placement with no implementation is
refused in typed terms rather than quietly running on another machine, and a
missing connector is the placement's refusal to give, not a construction gate.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
from ordessa_server_compat.execution.local_channel import LocalSidecarLauncher
from ordessa_server_compat.execution.placement import PlacementUnsupported, resolve_placement

PLUGIN = Path(__file__).resolve().parents[3] / "plugins"  / "harness"


def test_a_wsl_workspace_needs_a_connector_and_says_so():
    assert resolve_placement("wsl", has_connector=True).channel == "wsl-worker"
    with pytest.raises(PlacementUnsupported) as refused:
        resolve_placement("wsl", has_connector=False)
    assert refused.value.code == "WSL_CONNECTOR_UNAVAILABLE"


def test_an_ssh_workspace_resolves_once_its_connector_is_composed():
    assert resolve_placement("ssh", has_connector=True).channel == "ssh-worker"
    with pytest.raises(PlacementUnsupported) as refused:
        resolve_placement("ssh", has_connector=False)
    assert refused.value.code == "SSH_CONNECTOR_UNAVAILABLE"


def test_a_local_workspace_needs_no_connector():
    placement = resolve_placement("local", has_connector=False)
    assert (placement.kind, placement.channel) == ("local", "local-process")


def test_every_named_placement_has_an_implementation_so_none_is_downgraded():
    """No placement is named without being served, and no unknown one is served.

    The historic failure this guards against is a name that resolves into
    "whatever channel happens to exist": a workspace whose record says `ssh` must
    never quietly become a local turn because that was the easier machine.
    """
    assert {resolve_placement(kind, has_connector=True).kind for kind in ("local", "wsl", "ssh")} == {
        "local", "wsl", "ssh",
    }
    with pytest.raises(PlacementUnsupported) as unknown:
        resolve_placement("serial", has_connector=True)
    assert unknown.value.code == "PLACEMENT_UNKNOWN"
    # A workspace that names no placement at all is refused too: the historic
    # "assume WSL" default is exactly what this resolution removes.
    with pytest.raises(PlacementUnsupported) as unnamed:
        resolve_placement(None, has_connector=True)
    assert unnamed.value.code == "PLACEMENT_UNKNOWN"


def _deployment(tmp_path: Path) -> Path:
    document = tmp_path / "deployment.json"
    document.write_text(json.dumps({
        "schemaVersion": 1,
        "harnesses": [{
            # A seat the registry knows: only a declared native home may run.
            "id": "pi",
            "adapter": {"command": "/usr/bin/node", "args": []},
        }],
    }), encoding="utf-8")
    return document


def _channel_for(tmp_path, monkeypatch, env_kind: str, *, ssh_connector: bool = False,
                 host_os: str | None = None) -> str:
    """Which channel the product's own port factory builds for one placement.

    ``host_os`` fakes the Server's own platform (`"nt"` = Windows control plane)
    so a guest placement's routing can be checked on a Linux test host - the exact
    condition order 090 broke under.
    """
    import ordessa_server.bootstrap.runtime as runtime_module
    # T014-S2b: the built-in connector builders moved to the workspace
    # plugin; patching them now happens on their owning module, and the
    # os.name patch below still reaches the same shared os module the
    # builders read.
    import ordessa_workspace.connectors as ws_connectors_module
    import ordessa_server_compat.execution.local_channel as local_module
    import ordessa_server_compat.execution.sidecar as sidecar_module

    chosen: dict = {}

    class RecordingWorker:
        def __init__(self, connector, *_args, **_kwargs) -> None:
            # The launcher must be handed the connector of the placement it is
            # about to run on, not whichever one the composition happens to have.
            chosen["channel"] = "worker"
            chosen["connector"] = connector

    class RecordingLocal:
        def __init__(self, *_args, **_kwargs) -> None:
            chosen["channel"] = "local-process"

    wsl = object() if env_kind == "wsl" else None
    ssh = object() if ssh_connector else None
    monkeypatch.setattr(ws_connectors_module, "_builtin_connector", lambda _id: wsl)
    monkeypatch.setattr(ws_connectors_module, "_builtin_ssh_connector", lambda _id: ssh)
    monkeypatch.setattr(
        sidecar_module, "sidecar_bundle_files",
        lambda root, additional_files=None: dict(additional_files or {}),
    )
    monkeypatch.setattr(sidecar_module, "WorkerSidecarLauncher", RecordingWorker)
    # The builder imports both launchers at call time, so patching the source
    # module's attributes is what the product path actually reads.
    monkeypatch.setattr(local_module, "LocalSidecarLauncher", RecordingLocal)

    runtime = build_runtime_from_sidecar_deployment(
        tmp_path / "server", _deployment(tmp_path), plugin_root=PLUGIN,
    )
    frozen = runtime.objects.publish(json.dumps({"execution": {}}).encode())

    def call_port_factory():
        runtime.plugin_host.provided_port('execution.port').port_factory({
            "harness_type": "pi", "distribution": "Ubuntu", "remote_user": "tester",
            "connection_id": "connection", "remote_path": "/workspace",
            "env_kind": env_kind, "env_host": "Ubuntu", "normalized_path": "/workspace",
            "profile_id": "profile_test", "profile_name": "Pi Test",
            "config_object_digest": frozen.digest,
        }, lambda *_args: None)

    try:
        if host_os is not None:
            # Scope the fake host platform to just the resolution, so runtime.stop()
            # still runs under the real one (its lock release is os-specific).
            with monkeypatch.context() as scoped:
                scoped.setattr(runtime_module.os, "name", host_os)
                call_port_factory()
        else:
            call_port_factory()
    finally:
        runtime.stop()
    return chosen["channel"]


def test_the_placement_picks_the_channel_through_the_product_path(tmp_path, monkeypatch):
    assert _channel_for(tmp_path, monkeypatch, "wsl") == "worker"


def test_the_ssh_placement_runs_on_its_own_connector(tmp_path, monkeypatch):
    chosen_channel = _channel_for(tmp_path, monkeypatch, "ssh", ssh_connector=True)
    assert chosen_channel == "worker"


def test_the_ssh_placement_is_refused_without_its_connector(tmp_path, monkeypatch):
    import ordessa_workspace.connectors as runtime_module

    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _id: object())
    monkeypatch.setattr(runtime_module, "_builtin_ssh_connector", lambda _id: None)
    runtime = build_runtime_from_sidecar_deployment(
        tmp_path / "server", _deployment(tmp_path), plugin_root=PLUGIN,
    )
    try:
        frozen = runtime.objects.publish(json.dumps({"execution": {}}).encode())
        with pytest.raises(PlacementUnsupported) as refused:
            runtime.plugin_host.provided_port('execution.port').port_factory({
                "harness_type": "pi", "distribution": "203.0.113.7",
                "remote_user": "root", "connection_id": "connection",
                "remote_path": "/workspace", "env_kind": "ssh", "env_host": "203.0.113.7",
                "normalized_path": "/workspace",
                "profile_id": "profile_test", "profile_name": "Pi Test",
                "config_object_digest": frozen.digest,
            }, lambda *_args: None)
    finally:
        runtime.stop()
    assert refused.value.code == "SSH_CONNECTOR_UNAVAILABLE"


def test_a_local_workspace_runs_through_the_local_channel(tmp_path, monkeypatch):
    assert _channel_for(tmp_path, monkeypatch, "local") == "local-process"


def test_the_local_channel_is_the_one_that_runs_a_command_it_is_handed():
    """Its contract, stated as an attribute of the class: no host paths, no
    isolation mechanics, no Harness knowledge - it stages, runs, captures."""
    source = Path(LocalSidecarLauncher.__module__.replace(".", "/") + ".py")
    # the implementation moved with the execution domain (core-cleanup stage 3)
    root = ("plugins/server-compat/src"
            if source.parts[0] == "ordessa_server_compat" else "apps/server/src")
    text = (Path(__file__).resolve().parents[3] / root / source).read_text()
    assert "compile_remote_sidecar_bwrap_argv" not in text
    assert "bwrap" not in text.replace("agent_box_sandbox_bwrap", "")


def test_the_sandbox_default_follows_the_placement_not_the_host(monkeypatch):
    """G1 (order 090): the room is composed for the guest the turn runs in, not
    the machine hosting the Server. A WSL/SSH placement is Linux even under a
    Windows control plane; only a native local placement may use the Windows
    sandbox, and an explicit deployment provider still wins."""
    from ordessa_server_compat import composition as runtime_module
    monkeypatch.delenv("AGENT_BOX_SANDBOX_PROVIDER", raising=False)
    choose = runtime_module._sandbox_provider_name
    monkeypatch.setattr(runtime_module.os, "name", "nt")   # Windows control plane
    assert choose({}, "wsl") == "sandbox-bwrap"
    assert choose({}, "ssh") == "sandbox-bwrap"
    assert choose({}, "local") == "sandbox-windows"
    assert choose({"sandboxProvider": "sandbox-special"}, "wsl") == "sandbox-special"
    monkeypatch.setattr(runtime_module.os, "name", "posix")
    assert choose({}, "wsl") == "sandbox-bwrap"
    assert choose({}, "local") == "sandbox-bwrap"


def test_a_wsl_turn_still_routes_to_the_worker_from_a_windows_host(tmp_path, monkeypatch):
    """G1 end-to-end (the trial's exact host condition): a WSL-workspace turn on a
    Server reporting `nt` must reach the WSL worker channel, not fall back to the
    host `sandbox-windows` (which unresolved made it an ambiguous dispatch). Without
    the placement-aware default the port factory raises and this errors, so the
    gate only passes with the fix."""
    assert _channel_for(tmp_path, monkeypatch, "wsl", host_os="nt") == "worker"
