"""Generic tests for the deployment-declared native driver seam.

A Harness that does not speak ACP is driven by a module the deployment names.
The Server, Core, Worker and bwrap layers carry that declaration as opaque data
and never branch on a Harness name; only the sidecar loads the module, and only
from the deployment area of the same reviewed bundle.

These tests use a controlled fixture driver, so what they prove is the seam:
bundle placement, the generic operation surface, the neutral upward events, the
resumability claim, and the refusals. They do NOT prove any real Harness works -
that is what the per-family production chain gates are for.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import threading

import pytest

from ordessa_server_compat.execution.sidecar import (
    LocalProcessLauncher,
    SidecarEnvelope,
    SidecarError,
    SidecarHarnessPort,
    sidecar_bundle_files,
)


REPO = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
FIXTURE_DRIVER = pathlib.Path(__file__).resolve().parent / "fixtures" / "fixture_native_driver.mjs"
#: The bundle path the sidecar itself loads, relative to a bundle root.
DRIVER_BUNDLE_PATH = "agentbox-sidecar/deployment/fixture-native/driver.mjs"


def node_available() -> bool:
    return bool(shutil.which("node"))


@pytest.fixture
def bundle(tmp_path):
    """A bundle-shaped copy of the sidecar closure, plus one fixture driver.

    The real guest mounts this layout read-only at `/runtime/view`, so the
    seam's placement rule is exercised against the same shape it sees in
    production rather than against a test-only path.
    """
    view = tmp_path / "view"
    sidecar = view / "agentbox-sidecar"
    runtime = sidecar / "runtime"
    runtime.mkdir(parents=True)
    for name in ("worker-entry.mjs", "native-driver.mjs", "profile_extensions.mjs"):
        shutil.copyfile(PLUGIN / "runtime" / name, runtime / name)
    shutil.copytree(PLUGIN / "third_party" / "harness_remote", sidecar / "third_party" / "harness_remote")
    driver = view / DRIVER_BUNDLE_PATH
    driver.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_DRIVER, driver)
    return view


def sidecar_environment(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "AGENTBOX_SIDECAR_ISOLATED": "1",
    }


def launch_for(bundle: pathlib.Path, *, module: str | None = None) -> dict:
    return {
        "command": "/runtime/bin/fixture-native",
        "args": ["run"],
        "environment": {"FIXTURE_MODE": "gate"},
        "driver": {"module": module or str(bundle / DRIVER_BUNDLE_PATH)},
    }


def sidecar_entry(bundle: pathlib.Path) -> str:
    return str(bundle / "agentbox-sidecar" / "runtime" / "worker-entry.mjs")


def open_envelope(bundle: pathlib.Path, tmp_path: pathlib.Path, observed: list) -> SidecarEnvelope:
    launcher = LocalProcessLauncher(["node", sidecar_entry(bundle)])
    return SidecarEnvelope(
        launcher.launch(sidecar_environment(tmp_path)),
        on_event=lambda message: observed.append(message),
    )


pytestmark = pytest.mark.skipif(not node_available(), reason="node is unavailable")


def test_sidecar_routes_generic_operations_to_a_declared_native_driver(bundle, tmp_path):
    observed: list[dict] = []
    envelope = open_envelope(bundle, tmp_path, observed)
    try:
        registered = envelope.request({
            "op": "register", "profile": "fixture-native", "launch": launch_for(bundle),
            "directory": str(tmp_path),
        })
        assert registered["driver"]["module"] == str(bundle / DRIVER_BUNDLE_PATH)
        started = envelope.request({"op": "start"})
        # The capability a product reads as "this Harness can reopen a stored
        # session" is declared by the driver, not guessed by any layer above.
        assert started["sessionCapabilities"] == {"resume": {}, "list": {}}
        created = envelope.request({"op": "create", "title": "execution-1", "model": "fixture-model"})
        assert created["sessionId"] == "fixture-native-1"
        prompted = envelope.request({
            "op": "prompt", "sessionId": created["sessionId"], "text": "hello driver",
        })
        assert prompted["done"] is True
        reported = envelope.request({"op": "status", "sessionId": created["sessionId"]})
        # The driver received the deployment's launch facts: its declared
        # environment, the credential environment name, and a spawn function
        # that injects the credential - never the credential value.
        assert reported["environment"] == {"FIXTURE_MODE": "gate"}
        assert reported["credentialEnvironment"] is None
        assert reported["hasCredential"] is False
        assert reported["hasSpawnProcess"] is True
        assert envelope.request({"op": "close"}) == {"closed": True}
    finally:
        envelope.close()
    kinds = [message.get("event") for message in observed]
    assert "message_delta" in kinds, observed
    assert all("fixture-token" not in json.dumps(message) for message in observed)


def test_port_turns_neutral_driver_deltas_into_product_facts(bundle, tmp_path):
    """A driver delta must arrive as the same fact an ACP chunk becomes."""
    observed: list[tuple[str, str, dict]] = []
    lock = threading.Lock()

    def on_event(execution_id, kind, payload):
        with lock:
            observed.append((execution_id, kind, payload))

    port = SidecarHarnessPort(
        LocalProcessLauncher(["node", sidecar_entry(bundle)]),
        environment=sidecar_environment(tmp_path),
        profile="fixture-native",
        adapter=launch_for(bundle),
        declared_capabilities={"native_continuation": True},
        model="fixture-model",
        state_directory=str(tmp_path / "state"),
        directory=str(tmp_path),
        on_event=on_event,
    )
    try:
        native = port.open_execution("execution-1")
        assert native == "fixture-native-1"
        port.prompt("execution-1", "hello driver")
        state, resumable = port.capture_execution("execution-1")
        assert state['files'] == [] and state['audited']['files'] == 0
        assert resumable is True
    finally:
        port.stop()
    deltas = [item for item in observed if item[1] == "message.delta"]
    assert [item[2]["text"] for item in deltas][:1] == ["created fixture-native-1 for fixture-model"]
    assert any(item[1] == "started" for item in observed)


def test_a_driver_exit_is_reported_as_a_failed_fact(bundle, tmp_path):
    observed: list[tuple[str, str, dict]] = []

    def on_event(execution_id, kind, payload):
        observed.append((execution_id, kind, payload))

    port = SidecarHarnessPort(
        LocalProcessLauncher(["node", sidecar_entry(bundle)]),
        environment=sidecar_environment(tmp_path),
        profile="fixture-native",
        adapter=launch_for(bundle),
        state_directory=str(tmp_path / "state"),
        directory=str(tmp_path),
        on_event=on_event,
    )
    try:
        port.open_execution("execution-1")
        port.prompt("execution-1", "__driver_exit__")
    finally:
        port.stop()
    assert any(item[1] == "failed" and item[2]["code"] == "ADAPTER_EXIT" for item in observed), observed


def test_a_driver_module_outside_the_bundle_deployment_area_is_refused(bundle, tmp_path):
    outside = tmp_path / "outside-driver.mjs"
    shutil.copyfile(FIXTURE_DRIVER, outside)
    envelope = open_envelope(bundle, tmp_path, [])
    try:
        with pytest.raises(SidecarError) as refused:
            envelope.request({
                "op": "register", "profile": "fixture-native",
                "launch": launch_for(bundle, module=str(outside)),
            })
        assert refused.value.code == "DRIVER_MODULE_OUTSIDE_BUNDLE"
    finally:
        envelope.close()


@pytest.mark.parametrize("module", [
    "../../../../etc/passwd",
    "agentbox-sidecar/deployment/fixture-native/driver.mjs",
    "/runtime/view/agentbox-sidecar/deployment/fixture-native/driver.js",
])
def test_a_driver_module_that_is_not_a_bundled_absolute_module_is_refused(bundle, tmp_path, module):
    envelope = open_envelope(bundle, tmp_path, [])
    try:
        with pytest.raises(SidecarError) as refused:
            envelope.request({
                "op": "register", "profile": "fixture-native",
                "launch": launch_for(bundle, module=module),
            })
        assert refused.value.code == "DRIVER_MODULE_OUTSIDE_BUNDLE"
    finally:
        envelope.close()


def test_a_driver_module_without_a_driver_entrypoint_is_refused(bundle, tmp_path):
    empty = bundle / "agentbox-sidecar" / "deployment" / "fixture-empty" / "driver.mjs"
    empty.parent.mkdir(parents=True)
    empty.write_text("export const nothing = true\n", encoding="utf-8")
    envelope = open_envelope(bundle, tmp_path, [])
    try:
        with pytest.raises(SidecarError) as refused:
            envelope.request({
                "op": "register", "profile": "fixture-native",
                "launch": launch_for(bundle, module=str(empty)),
            })
        assert refused.value.code == "DRIVER_ENTRYPOINT_MISSING"
    finally:
        envelope.close()


def test_registering_without_a_driver_still_uses_the_acp_registration(bundle, tmp_path):
    """The driver seam must not displace the ACP path for an undeclared profile."""
    envelope = open_envelope(bundle, tmp_path, [])
    try:
        with pytest.raises(SidecarError) as refused:
            envelope.request({
                "op": "register", "profile": "fixture-native",
                "launch": {"command": "/usr/bin/true", "args": []},
            })
        assert "HARNESS_PROFILE_UNREGISTERED" in refused.value.message
    finally:
        envelope.close()


def test_a_driver_without_every_contract_method_is_refused(bundle, tmp_path):
    """A missing operation is refused at registration, not mid-turn.

    `status` is one of the operations this envelope exposes, so a driver that
    omits it must not register at all - the refusal has to name the operation
    that is missing.
    """
    incomplete = bundle / "agentbox-sidecar" / "deployment" / "fixture-incomplete" / "driver.mjs"
    incomplete.parent.mkdir(parents=True)
    incomplete.write_text(
        "const noop = async () => {}\n"
        "export async function createDriver() {\n"
        "  return { start: noop, create: noop, open: noop, prompt: noop, abort: noop, close: noop }\n"
        "}\n",
        encoding="utf-8",
    )
    envelope = open_envelope(bundle, tmp_path, [])
    try:
        with pytest.raises(SidecarError) as refused:
            envelope.request({
                "op": "register", "profile": "fixture-native",
                "launch": launch_for(bundle, module=str(incomplete)),
            })
        assert refused.value.code == "DRIVER_METHOD_MISSING"
        assert "status" in refused.value.message
    finally:
        envelope.close()


CONFORMANCE_PROBE = r"""
// `node -e` puts no script element in argv, so the first user argument is argv[1].
const [seamPath, ...driverPaths] = process.argv.slice(1)
const seam = await import(new URL("file://" + seamPath).href)
const context = {
  profileID: "contract-probe", command: "/bin/true", args: [], environment: {},
  credentialEnvironment: null, hasCredential: false, directory: process.cwd(),
  stateDirectory: null, emit: () => {}, redact: (value, maximum) => String(value ?? "").slice(0, maximum),
  spawnProcess: () => { throw new Error("the contract probe must not spawn anything") },
}
const missing = {}
for (const driverPath of driverPaths) {
  const module = await import(new URL("file://" + driverPath).href)
  const created = await module.createDriver(context)
  missing[driverPath] = seam.DRIVER_METHODS.filter((name) => typeof created[name] !== "function")
}
process.stdout.write(JSON.stringify({
  methods: seam.DRIVER_METHODS, missing,
}) + "\n")
"""


def test_every_shipped_driver_implements_the_declared_contract():
    """The seam's method list is the contract; both drivers must satisfy it.

    The list is read from the seam module itself (one source of truth), and the
    drivers are asked to construct an instance the same way the sidecar does.
    """
    drivers = [
        FIXTURE_DRIVER,
        PLUGIN / "runtime" / "drivers" / "opencode-native.mjs",
    ]
    result = subprocess.run(
        ["node", "--input-type=module", "-e", CONFORMANCE_PROBE,
         str(PLUGIN / "runtime" / "native-driver.mjs"), *[str(path) for path in drivers]],
        capture_output=True, text=True, timeout=120, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert "status" in payload["methods"], "status is part of the declared contract"
    assert payload["missing"] == {str(path): [] for path in drivers}, payload["missing"]


def test_the_bundle_carries_the_driver_seam_module():
    files = sidecar_bundle_files(PLUGIN)
    assert "agentbox-sidecar/runtime/native-driver.mjs" in files


def test_deployment_carries_a_declared_driver_module_into_the_reviewed_bundle(tmp_path, monkeypatch):
    """The Server carries the declaration; it never interprets the module.

    The normalized module path the sidecar is told to load is inside the same
    reviewed bundle the sidecar itself comes from, and the module bytes travel
    with that bundle - there is nowhere else a deployment could point it.
    """
    source = tmp_path / "driver.mjs"
    source.write_text(
        "export async function createDriver() { return { start: async () => {} } }\n",
        encoding="utf-8",
    )
    captured: dict = {}
    import ordessa_server_compat.composition as runtime_module
    import ordessa_server.bootstrap.runtime as host_module
    import ordessa_server_compat.execution.sidecar as sidecar_module

    monkeypatch.setattr(host_module, "_builtin_connector", lambda _instance_id: object())
    monkeypatch.setattr(
        sidecar_module, "sidecar_bundle_files",
        lambda root, additional_files=None: captured.update({"files": dict(additional_files or {})}) or {},
    )

    class RecordingPort:
        def __init__(self, *_args, **kwargs):
            captured["adapter"] = kwargs.get("adapter")

    monkeypatch.setattr(sidecar_module, "SidecarHarnessPort", RecordingPort)
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({
        "schemaVersion": 1,
        "harnesses": [{
            "id": "fixture-native",
            "adapter": {
                "command": "/runtime/bin/fixture-native", "args": ["run"],
                "environment": {"FIXTURE_MODE": "gate"},
                "driver": {"source": source.name},
            },
        }],
    }), encoding="utf-8")
    # A synthetic seat has no registry entry, so its native home is stubbed to
    # the same shape the real registry returns for the real families.
    monkeypatch.setattr(runtime_module, "_registry_native_homes",
                        lambda: {"fixture-native": ".fixture-native"})
    runtime = runtime_module.build_runtime_from_sidecar_deployment(
        tmp_path / "server", deployment, plugin_root=tmp_path)
    try:
        bundle_path = "agentbox-sidecar/deployment/fixture-native/driver.mjs"
        assert captured["files"][bundle_path] == source.read_bytes()
        frozen = runtime.objects.publish(json.dumps({"execution": {}}).encode())
        runtime.execution.port_factory({
            "harness_type": "fixture-native", "config_object_digest": frozen.digest,
            "distribution": "Ubuntu", "remote_user": os.environ.get("USER", "user"),
            "connection_id": "connection", "remote_path": str(tmp_path),
            "env_kind": "wsl", "profile_id": "profile_driver",
            "profile_name": "fixture-native",
        }, lambda *_args: None)
        assert captured["adapter"]["driver"] == {"module": f"/runtime/view/{bundle_path}"}
        assert captured["adapter"]["command"] == "/runtime/bin/fixture-native"
    finally:
        runtime.stop()


@pytest.mark.parametrize("driver", [
    # A driver declaration names a plugin-relative module, so an absolute path is
    # refused as a host path and a relative escape as a malformed name.
    {"source": "/absolute/driver.mjs"},
    {"source": "../escape.mjs"},
    {"source": "driver.mjs", "extra": True},
    {"module": "driver.mjs"},
    "driver.mjs",
    {"source": "missing-driver.mjs"},
])
def test_deployment_refuses_a_malformed_driver_declaration(tmp_path, monkeypatch, driver):
    source = tmp_path / "driver.mjs"
    source.write_text("export async function createDriver() {}\n", encoding="utf-8")
    import ordessa_server_compat.composition as runtime_module
    import ordessa_server.bootstrap.runtime as host_module

    monkeypatch.setattr(host_module, "_builtin_connector", lambda _instance_id: object())
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({
        "schemaVersion": 1,
        "harnesses": [{
            "id": "fixture-native",
            "adapter": {"command": "/runtime/bin/fixture-native", "args": [], "driver": driver},
        }],
    }), encoding="utf-8")
    with pytest.raises(RuntimeError) as refused:
        runtime_module.build_runtime_from_sidecar_deployment(
            tmp_path / "server", deployment, plugin_root=tmp_path)
    assert str(refused.value).startswith(
        ("SIDECAR_DEPLOYMENT_INVALID", "SIDECAR_DEPLOYMENT_HOST_PATH")
    ), str(refused.value)
