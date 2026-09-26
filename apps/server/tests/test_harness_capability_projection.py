"""One canonical capability view for ACP and for a native driver.

The two routes reach the Server through different transports - an ACP
registration and a deployment-declared driver module - but a client must not be
able to tell them apart in the capability view. This test gives both routes the
same static declaration and the same native abilities, then demands the same
canonical projection: same ids, same scopes, same declared/observed/supported
values and the same reasons. Only `nativeEvidence` may differ, because it names
where the observation came from and that genuinely differs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from ordessa_server_compat.execution.sidecar import (
    LocalProcessLauncher,
    SidecarHarnessPort,
    sidecar_bundle_files,
)


REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
ACP_PEER = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"
FIXTURE_DRIVER = Path(__file__).resolve().parent / "fixtures" / "fixture_native_driver.mjs"
DRIVER_BUNDLE_PATH = "agentbox-sidecar/deployment/fixture-native/driver.mjs"
#: Identical static ceiling on both routes: the comparison is about the
#: projection, not about who declared more.
DECLARED = {"start": True, "observe": True, "finish": True, "stream": True,
            "attach": True, "native_continuation": True}
COMPARED_FIELDS = ("id", "scope", "declared", "observed", "supported", "reason")


def node_available() -> bool:
    return bool(shutil.which("node"))


def sidecar_environment(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
            "AGENTBOX_SIDECAR_ISOLATED": "1"}


@pytest.fixture
def bundle(tmp_path):
    """A bundle-shaped copy, so the driver module resolves the way it does in the guest."""
    view = tmp_path / "view"
    sidecar = view / "agentbox-sidecar"
    runtime = sidecar / "runtime"
    runtime.mkdir(parents=True)
    for name in ("worker-entry.mjs", "native-driver.mjs", "profile_extensions.mjs"):
        shutil.copyfile(PLUGIN / "runtime" / name, runtime / name)
    shutil.copytree(PLUGIN / "third_party" / "harness_remote",
                    sidecar / "third_party" / "harness_remote")
    driver = view / DRIVER_BUNDLE_PATH
    driver.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_DRIVER, driver)
    return view


def acp_port(tmp_path: Path) -> SidecarHarnessPort:
    return SidecarHarnessPort(
        LocalProcessLauncher(["node", str(PLUGIN / "runtime" / "worker-entry.mjs")]),
        environment=sidecar_environment(tmp_path), profile="pi",
        adapter={"command": "node", "args": [str(ACP_PEER)]},
        declared_capabilities=dict(DECLARED),
        state_directory=str(tmp_path / "state"), directory=str(tmp_path),
    )


def driver_port(tmp_path: Path, bundle: Path) -> SidecarHarnessPort:
    return SidecarHarnessPort(
        LocalProcessLauncher(["node", str(bundle / "agentbox-sidecar" / "runtime" / "worker-entry.mjs")]),
        environment=sidecar_environment(tmp_path), profile="fixture-native",
        adapter={"command": "/runtime/bin/fixture-native", "args": ["run"],
                 "driver": {"module": str(bundle / DRIVER_BUNDLE_PATH)}},
        declared_capabilities=dict(DECLARED),
        state_directory=str(tmp_path / "state"), directory=str(tmp_path),
    )


def comparable(view: dict) -> list[tuple]:
    return [tuple(item[field] for field in COMPARED_FIELDS) for item in view["capabilities"]]


pytestmark = pytest.mark.skipif(not node_available(), reason="node is unavailable")


def test_an_acp_harness_and_a_native_driver_project_the_same_capabilities(tmp_path, bundle):
    """Same declaration + same native abilities => the same canonical view."""
    acp = acp_port(tmp_path / "acp")
    driver = driver_port(tmp_path / "driver", bundle)
    try:
        acp.open_execution("execution-acp")
        driver.open_execution("execution-driver")
        acp.prompt("execution-acp", "capability projection")
        driver.prompt("execution-driver", "capability projection")
        acp_view = acp.effective_capabilities("execution-acp")
        driver_view = driver.effective_capabilities("execution-driver")
    finally:
        acp.stop()
        driver.stop()

    assert acp_view["schemaVersion"] == driver_view["schemaVersion"]
    assert comparable(acp_view) == comparable(driver_view), (
        json.dumps({"acp": acp_view, "driver": driver_view}, indent=1)[:1500])

    by_id = {item["id"]: item for item in acp_view["capabilities"]}
    # The abilities both routes really have are observed and supported.
    for capability_id in ("start", "observe", "finish", "stream", "native_continuation", "attach"):
        assert by_id[capability_id]["observed"] is True, capability_id
        assert by_id[capability_id]["supported"] is True, capability_id
    # Nothing declared as unsupported may be promoted by the runtime.
    assert by_id["steer"]["supported"] is False
    assert by_id["steer"]["reason"] == "CAPABILITY_NOT_DECLARED"


def test_an_undeclared_native_ability_cannot_raise_the_product_capability(tmp_path, bundle):
    """A native claim the static declaration rejects stays unsupported (fail closed)."""
    declared = dict(DECLARED)
    declared["native_continuation"] = False
    port = SidecarHarnessPort(
        LocalProcessLauncher(["node", str(PLUGIN / "runtime" / "worker-entry.mjs")]),
        environment=sidecar_environment(tmp_path), profile="pi",
        adapter={"command": "node", "args": [str(ACP_PEER)]},
        declared_capabilities=declared,
        state_directory=str(tmp_path / "state"), directory=str(tmp_path),
    )
    try:
        port.open_execution("execution-conflict")
        view = port.effective_capabilities("execution-conflict")
    finally:
        port.stop()
    entry = next(item for item in view["capabilities"] if item["id"] == "native_continuation")
    assert entry["declared"] is False
    assert entry["observed"] is True
    assert entry["supported"] is False
    assert entry["reason"] == "CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION"
