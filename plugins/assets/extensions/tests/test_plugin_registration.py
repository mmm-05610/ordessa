"""EXT-1 — plugin skeleton registration against a bare test host."""
from __future__ import annotations

import pytest
from server_plugin_api import (
    Contribution, ServerPluginContext, ServerPluginDescriptor,
)

from ordessa_extensions import PLUGIN_ID
from ordessa_extensions.plugin import ExtensionsServerPlugin


def build(contribute=True):
    plugin = ExtensionsServerPlugin(
        contribute_harness_adapters=contribute)
    context = ServerPluginContext(plugin_id=PLUGIN_ID,
                                  data_root="/tmp/ext-test-root")
    return plugin, plugin.build(context)


def test_descriptor_has_no_requires_edge():
    descriptor = ExtensionsServerPlugin().descriptor()
    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.id == "ordessa.extensions"
    assert descriptor.requires == ()


def test_registration_carries_methods_ports_and_families():
    plugin, registration = build()
    method_ids = {method.method_id for method in registration.methods}
    assert {"extensions.approvals.list",
            "extensions.approvals.revoke"} <= method_ids
    assert "extensions.service" in registration.provided_ports
    point_ids = {contribution.point_id
                 for contribution in registration.contributions.contributions}
    assert "wire.error-families" in point_ids


def test_harness_adapters_contributed_with_open_point():
    plugin, registration = build()
    rows = [c for c in registration.contributions.contributions
            if c.point_id == "harness.configuration-adapters"]
    assert len(rows) == 2
    adapters = {row.payload.descriptor.harness_id for row in rows}
    assert adapters == {"codex", "claude"}
    assert registration.contributions.open_points == frozenset(
        {"harness.configuration-adapters"})


def test_bare_host_can_skip_adapter_contribution():
    plugin, registration = build(contribute=False)
    assert not [c for c in registration.contributions.contributions
                if c.point_id == "harness.configuration-adapters"]
    # an open declaration with zero rows would be a claim without content
    assert registration.contributions.open_points == frozenset()


def test_provided_service_is_the_single_approval_truth():
    plugin, registration = build()
    service = registration.provided_ports["extensions.service"]
    assert service.loader._ledger is service.ledger


def test_wire_methods_round_trip_through_the_real_handlers():
    from ordessa_extensions.definitions import HookDefinition
    plugin, registration = build()
    methods = {method.method_id: method for method in registration.methods}
    listing = methods["extensions.approvals.list"].handler(
        {"requestId": "r1"})
    assert listing == {"records": []}
    service = registration.provided_ports["extensions.service"]
    definition = HookDefinition(
        hook_id="wired", event="SessionStart", action_kind="command",
        command=("echo", "ok"), handler_ref=None, timeout_seconds=5,
        run_async=False, pin="0.147.0",
        content_sha256="sha256:" + "44" * 32)
    service.ledger.approve(definition, approved_by="op", scope="user")
    listing = methods["extensions.approvals.list"].handler(
        {"requestId": "r2"})
    assert listing["records"][0]["hookId"] == "wired"
    revoked = methods["extensions.approvals.revoke"].handler(
        {"requestId": "r3", "hookId": "wired"})
    assert revoked["record"]["state"] == "revoked"
    from server_plugin_api import ServerError
    with pytest.raises(ServerError) as excinfo:
        methods["extensions.approvals.revoke"].handler(
            {"requestId": "r4", "hookId": "ghost"})
    assert excinfo.value.code == "HOOK_UNKNOWN"
