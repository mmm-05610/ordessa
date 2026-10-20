"""The old Worker driver loader is gone; OpenCode owns its retained driver bytes."""
from __future__ import annotations

from pathlib import Path
import tomllib

from ordessa_harness_opencode.acp_resources import acp_resources
from ordessa_harness_opencode.production import DRIVER_TEMPLATE


ROOT = Path(__file__).resolve().parents[2]


def test_retired_agents_driver_loader_and_unconsumed_worker_fixture_are_absent():
    assert not (ROOT / "packages/execution/agents/src/ordessa_execution_agents/harness/providers/native_driver.mjs").exists()
    assert not (ROOT / "apps/server/tests/fixtures/fixture_native_driver.mjs").exists()
    metadata = tomllib.loads((ROOT / "packages/execution/agents/pyproject.toml").read_text())
    members = metadata["tool"]["setuptools"]["package-data"]["ordessa_execution_agents"]
    assert "harness/providers/native_driver.mjs" not in members


def test_opencode_own_driver_and_public_resource_port_still_publish_original_capability():
    resources = dict(acp_resources())
    assert "acp/opencode_native.mjs" in resources
    assert resources["acp/opencode_native.mjs"] == DRIVER_TEMPLATE
    assert DRIVER_TEMPLATE.is_file()
    source = DRIVER_TEMPLATE.read_text()
    assert "export async function createDriver" in source
    for method in ("start", "create", "open", "prompt", "abort", "status", "close"):
        assert f"async function {method}(" in source
    for name in ("opencode_driver_tail.test.mjs", "opencode_control_leg_audit.test.mjs",
                 "opencode_stream_framing.test.mjs", "opencode_subscriber_attribution.test.mjs",
                 "opencode_abort_outcome_halfb.test.mjs", "opencode_pump_attribution_x20.test.mjs"):
        assert (ROOT / "plugins/harness/opencode/tests" / name).is_file()
