"""Q5 first-stage product selection, without a second approval writer.

All host evidence uses a temporary data root and never starts a Server service
or a native model. These adapters remain fail-closed until trusted facts and
the pre-effect authority are composed in a later stage.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tomllib

import pytest

from ordessa_harness.contributions import CONFIGURATION_POINT, HarnessContributionError
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment, ConfigurationAdapterDescriptor,
    ErrorCode, FieldClaim, Installation, ValueSchema, VerificationUnknown,
    VersionRange,
)
from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition
from ordessa_sandbox_adapters import HarnessSandboxConfigurationAdapter
from server_plugin_api import (
    Contribution, ContributionBatch, ContributionPointUnboundError,
    ServerPluginDescriptor, ServerPluginRegistration,
)


EXPECTED_PLUGIN_IDS = (
    "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
    "ordessa.sandbox", "ordessa.sandbox-adapters", "ordessa.permissions-adapters",
)


def test_product_dist_declares_the_three_selected_q5_dependencies():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    dependencies = set(project["project"]["dependencies"])
    assert {"ordessa-sandbox-backend==0.1.0", "ordessa-sandbox-adapters==0.1.0",
            "ordessa-permissions-adapters==0.1.0"} <= dependencies
    assert not any(name.startswith("ordessa-permissions-backend") for name in dependencies)


def test_default_product_selects_three_q5_plugins_without_permissions_writer():
    plugins = create_composition().default_plugins()
    assert tuple(plugin.descriptor().id for plugin in plugins) == EXPECTED_PLUGIN_IDS


def test_explicit_compatibility_selection_has_no_q5_contributions(tmp_path):
    composition = create_composition()
    controlled_execution = object()
    selected = composition.compatibility_plugins(execution=controlled_execution)
    assert tuple(plugin.descriptor().id for plugin in selected) == EXPECTED_PLUGIN_IDS[:3]
    assert selected[1]._execution is controlled_execution
    runtime = build_runtime(tmp_path / "compat-only", server_plugins=selected)
    try:
        assert runtime.plugin_host.active_ids() == EXPECTED_PLUGIN_IDS[:3]
        assert runtime.plugin_host.contributions(CONFIGURATION_POINT) == ()
        assert runtime.plugin_host.contribution_points.point(CONFIGURATION_POINT) is None
    finally:
        runtime.stop()


def test_explicit_plugin_selection_does_not_silently_gain_product_points(tmp_path):
    """The host's explicit selection has no product point declaration.

    Passing the whole default product plugin list as an explicit host-only
    selection must refuse its adapters, never silently discard them.
    """
    root = tmp_path / "explicit-without-points"
    with pytest.raises(ContributionPointUnboundError, match="harness.configuration-adapters"):
        build_runtime(root, server_plugins=create_composition().default_plugins())
    # The failed round released ownership; a genuine selected product can use
    # the same temporary root with both point handlers bound.
    retry = build_runtime(root)
    try:
        assert retry.plugin_host.active_ids() == EXPECTED_PLUGIN_IDS
    finally:
        retry.stop()


def test_real_product_registers_q5_ports_contributions_and_only_legacy_decide(tmp_path):
    runtime = build_runtime(tmp_path / "data")  # constructs only; no service start
    try:
        host = runtime.plugin_host
        assert host.active_ids() == EXPECTED_PLUGIN_IDS
        assert host.provided_port("sandbox.native-configuration@1") is not None
        assert host.provided_port("sandbox.describe@1") is not None
        assert host.provided_port("permissions.authorizer@1") is None
        owners = {method.method_id: method.owner for method in host.methods.descriptors()
                  if method.method_id.endswith("approvals.decide")}
        assert owners == {"approvals.decide": "ordessa.server-compat"}
        assert {view.owner for view in host.contributions(CONFIGURATION_POINT)} == {
            "ordessa.sandbox-adapters", "ordessa.permissions-adapters"}
        assert len(host.contributions(CONFIGURATION_POINT)) == 6
    finally:
        runtime.stop()


def test_q5_callable_c2_remains_unknown_or_refused_without_authority(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    try:
        views = runtime.plugin_host.contributions(CONFIGURATION_POINT)
        by_owner = {view.owner: view.payload for view in views
                    if view.payload.descriptor.harness_id == "codex"}
        assert set(by_owner) == {"ordessa.sandbox-adapters", "ordessa.permissions-adapters"}
        for owner, payload in by_owner.items():
            descriptor = payload.descriptor
            context = AdapterContext((), Installation("codex", descriptor.native_versions.minimum,
                descriptor.adapter_versions.minimum, "controlled:pin"),
                descriptor.entries[0], "instance", "controlled:capability")
            desired = ({"sandbox_mode": "read-only"} if owner == "ordessa.sandbox-adapters"
                       else {"approval_policy": "untrusted"})
            assessment = payload.assess(context, desired)
            assert isinstance(assessment, Assessment) and assessment.status == "unknown"
            refused = payload.compile(context, {}, desired)
            assert isinstance(refused, AdapterRefusal)
            assert refused.code in {ErrorCode.AUTHORIZATION_REFUSED, ErrorCode.CAPABILITY_UNSUPPORTED}
            assert isinstance(payload.verify(context, desired), VerificationUnknown)
    finally:
        runtime.stop()


def test_q5_conflicting_batch_rolls_back_first_staged_entry(tmp_path):
    runtime = build_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        before = host.contributions(CONFIGURATION_POINT)
        first = ConfigurationAdapterDescriptor(
            "test.q5.first", "v1", "test.q5", "v1", "test-q5",
            VersionRange((1, 0, 0)), VersionRange((1, 0, 0)), ("test-entry",),
            ValueSchema("object"), (FieldClaim("file", "test-q5-config", ("mode",)),))
        codex = next(view.payload.descriptor for view in before
                     if view.owner == "ordessa.sandbox-adapters"
                     and view.payload.descriptor.harness_id == "codex")
        collision = replace(codex, adapter_id="test.q5.collision", facet_id="test.q5")

        class Plugin:
            def __init__(self, plugin_id, descriptors):
                self.plugin_id = plugin_id
                self.descriptors = descriptors

            def descriptor(self):
                return ServerPluginDescriptor(self.plugin_id, "Controlled Q5", "1")

            def build(self, _context):
                return ServerPluginRegistration(contributions=ContributionBatch(tuple(
                    Contribution(CONFIGURATION_POINT, "v1",
                        HarnessSandboxConfigurationAdapter(descriptor, object()))
                    for descriptor in self.descriptors),
                    open_points=frozenset({CONFIGURATION_POINT})))

        with pytest.raises(HarnessContributionError, match="claims overlap"):
            host.activate(Plugin("test.q5.failed", (first, collision)))
        assert host.contributions(CONFIGURATION_POINT) == before
        assert not host.is_active("test.q5.failed")
        host.activate(Plugin("test.q5.after-rollback", (first,)))
        assert len(host.contributions(CONFIGURATION_POINT)) == len(before) + 1
        host.deactivate("test.q5.after-rollback")
    finally:
        runtime.stop()
