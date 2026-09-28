"""T05 first controlled external distribution through the real product carrier."""
from __future__ import annotations

from importlib import metadata, util
from pathlib import Path
import shutil
import subprocess
import tomllib
from zipfile import ZipFile

import pytest

from ordessa_harness_api import (
    AdapterContext, ErrorCode, Installation, IntentSet, LaunchPlan, LaunchRequest,
    ResumeRequest, RuntimeConfirmed, RuntimeRefused, RuntimeUnknown,
    TargetDescriptor, TargetHandle,
)
from ordessa_server.bootstrap import build_runtime
from server_plugin_api import ContributionOwnerBusyError

RUNTIME_POINT = "harness.runtime-adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"
FIXTURE = Path(__file__).parent / "fixtures" / "external_adapter" / "src" / "ordessa_test_external_adapter" / "__init__.py"
FIXTURE_PROJECT = FIXTURE.parents[2] / "pyproject.toml"


@pytest.fixture(scope="module")
def external_distribution(tmp_path_factory):
    """Build this fixture as a wheel, install it alone, and load those bytes."""
    root = tmp_path_factory.mktemp("t05-external-wheel")
    wheels, site = root / "wheels", root / "site"
    wheels.mkdir()
    site.mkdir()
    builder = shutil.which("python3")
    assert builder is not None, "T05 wheel proof needs Python build tooling"
    built = subprocess.run(
        [builder, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", str(wheels), str(FIXTURE_PROJECT.parent)],
        capture_output=True, text=True, check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel_path, = wheels.glob("ordessa_test_external_adapter-*.whl")
    installed = subprocess.run(
        [builder, "-m", "pip", "install", "--no-deps", "--target", str(site), str(wheel_path)],
        capture_output=True, text=True, check=False,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    package_file = site / "ordessa_test_external_adapter" / "__init__.py"
    assert package_file.is_file() and package_file.resolve() != FIXTURE.resolve()
    distributions = list(metadata.distributions(path=[str(site)]))
    assert len(distributions) == 1
    distribution, = distributions
    assert distribution.metadata["Name"] == "ordessa-test-external-adapter"
    assert distribution.version == "0.1.0"
    assert distribution.locate_file("ordessa_test_external_adapter/__init__.py").resolve() == package_file.resolve()
    with ZipFile(wheel_path) as archive:
        assert package_file.read_bytes() == archive.read("ordessa_test_external_adapter/__init__.py")
    spec = util.spec_from_file_location("ordessa_test_external_adapter", package_file)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == package_file.resolve()
    assert Path(module.__spec__.origin).resolve() == package_file.resolve()
    return module, wheel_path, distribution


def test_external_distribution_declares_real_public_dependencies(external_distribution):
    _, wheel_path, distribution = external_distribution
    declared = tomllib.loads(FIXTURE_PROJECT.read_text())["project"]["dependencies"]
    expected = {"ordessa-harness-api==1.0.0a1", "ordessa-server-plugin-api==0.1.0"}
    assert set(declared) == expected
    assert set(distribution.requires or ()) == expected
    with ZipFile(wheel_path) as archive:
        metadata_file, = (name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        wheel_metadata = archive.read(metadata_file).decode("utf-8")
    assert {line.removeprefix("Requires-Dist: ") for line in wheel_metadata.splitlines()
            if line.startswith("Requires-Dist: ")} == expected


def test_external_adapter_default_product_registration_compile_and_retirement(tmp_path, external_distribution):
    external, _, _ = external_distribution
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        assert host.contributions(RUNTIME_POINT) == ()
        baseline_config = host.contributions(CONFIGURATION_POINT)
        assert len(baseline_config) == 6
        plugin = external.ExternalAdapterPlugin()
        assert plugin.build_count == 0  # descriptor and import have no lifecycle side effect
        assert plugin.configuration_adapter.compile_calls == 0
        assert plugin.runtime_adapter.calls == []
        host.activate(plugin)
        assert plugin.build_count == 1
        assert plugin.configuration_adapter.compile_calls == 0  # stage/commit does not execute adapter work
        assert plugin.runtime_adapter.calls == []
        assert not (tmp_path / "data" / "external-config").exists()
        runtime_views = host.contributions(RUNTIME_POINT)
        config_views = tuple(view for view in host.contributions(CONFIGURATION_POINT)
                             if view.owner == external.OWNER)
        assert len(runtime_views) == len(config_views) == 1
        assert len(host.contributions(CONFIGURATION_POINT)) == len(baseline_config) + 1
        assert runtime_views[0].owner == config_views[0].owner == external.OWNER
        assert runtime_views[0].payload.descriptor.harness_id == "test-external"
        assert config_views[0].payload.descriptor.harness_id == "test-external"
        first_publication = runtime_views[0].publication_token
        with host.use_contribution(RUNTIME_POINT) as held:
            adapter = held.payload
            assert adapter is plugin.runtime_adapter
            assert adapter.describe_installation().harness_id == "test-external"
            assert adapter.describe_targets()[0].handle == adapter.target
            assert adapter.describe_actions() == ()
            launch = adapter.prepare_launch(LaunchRequest(adapter.target, "fixture:snapshot:1"))
            assert isinstance(launch, LaunchPlan)
            started = adapter.start(launch)
            assert isinstance(started, RuntimeConfirmed)
            assert started.evidence_ref == "fixture:started"
            assert adapter.connect(started.instance_ref).kind == "confirmed"
            assert adapter.resume(ResumeRequest(started.instance_ref, started.native_session_identity,
                                                started.runtime_generation)).kind == "confirmed"
            assert adapter.close(started.instance_ref).evidence_ref == "fixture:closed"
            assert adapter.connect(started.instance_ref).kind == "refused"
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate(external.OWNER)
        target = TargetDescriptor(TargetHandle("fixture-target", 1), "file", "json", "instance", (("model",),))
        context = AdapterContext((target,), Installation("test-external", (1, 0, 0), (1, 0, 0), "fixture:native"), "acp", "instance", "fixture:capability")
        with host.use_contribution_exact(CONFIGURATION_POINT, owner=external.OWNER,
                                         publication_token=config_views[0].publication_token) as held:
            assert held.owner == external.OWNER
            adapter = held.payload
            assert adapter.assess(context, {"model": "fixture-model"}).status == "supported"
            plan = adapter.compile(context, {}, {"model": "fixture-model"})
            assert isinstance(plan, IntentSet)
            assert len(plan.intents) == 1 and plan.intents[0].typed_value == "fixture-model"
            assert adapter.compile_calls == 1
            assert not (tmp_path / "data" / "external-config").exists()  # compile is planning only
            assert adapter.verify(context, {"model": "fixture-model"}).kind == "unknown"
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate(external.OWNER)
        assert len(host.contributions(CONFIGURATION_POINT)) == len(baseline_config) + 1
        host.deactivate(external.OWNER)
        assert host.contributions(RUNTIME_POINT) == ()
        assert host.contributions(CONFIGURATION_POINT) == baseline_config
        replacement = external.ExternalAdapterPlugin()
        assert replacement is not plugin and replacement.configuration_adapter is not plugin.configuration_adapter
        host.activate(replacement)
        assert replacement.build_count == 1
        assert replacement.configuration_adapter.compile_calls == 0
        assert replacement.runtime_adapter.calls == []
        assert len(host.contributions(RUNTIME_POINT)) == 1
        assert len(host.contributions(CONFIGURATION_POINT)) == len(baseline_config) + 1
        assert host.contributions(RUNTIME_POINT)[0].payload is replacement.runtime_adapter
        assert host.contributions(RUNTIME_POINT)[0].publication_token != first_publication
        assert next(view for view in host.contributions(CONFIGURATION_POINT)
                    if view.owner == external.OWNER).payload is replacement.configuration_adapter
        host.deactivate(external.OWNER)
    finally:
        runtime.stop()


def test_external_runtime_adapter_refusal_unknown_and_readback_reconcile(tmp_path, external_distribution):
    external, _, _ = external_distribution
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        plugin = external.ExternalAdapterPlugin()
        host.activate(plugin)
        with host.use_contribution(RUNTIME_POINT) as held:
            adapter = held.payload
            wrong_target = adapter.prepare_launch(LaunchRequest(TargetHandle("foreign", 1), "fixture:snapshot:1"))
            assert isinstance(wrong_target, RuntimeRefused)
            assert wrong_target.code is ErrorCode.TARGET_CONFLICT
            stale = adapter.start(LaunchPlan(adapter.target, "fixture:forged", (), None, "fixture:snapshot:1"))
            assert isinstance(stale, RuntimeRefused) and stale.code is ErrorCode.STALE_PLAN
            launch = adapter.prepare_launch(LaunchRequest(adapter.target, "fixture:snapshot:1"))
            adapter.uncertain_start = True
            outcome = adapter.start(launch)
            assert isinstance(outcome, RuntimeUnknown)
            assert adapter.connect(outcome.instance_ref).kind == "unknown"
            assert adapter.reconcile(outcome.instance_ref).kind == "unknown"
            assert adapter.close(outcome.instance_ref).kind == "unknown"
            assert adapter.resume(ResumeRequest(outcome.instance_ref, "wrong-native", 1)).kind == "refused"
            adapter.readback_ready = True  # controlled observation, not a model response
            confirmed = adapter.reconcile(outcome.instance_ref)
            assert isinstance(confirmed, RuntimeConfirmed)
            assert adapter.close(outcome.instance_ref).kind == "confirmed"
            assert adapter.close(outcome.instance_ref).kind == "refused"
        host.deactivate(external.OWNER)
    finally:
        runtime.stop()
