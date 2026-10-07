"""T04b — plugin registration via server_plugin_api public types only.

No apps/server branching, no second registry, no host-internal imports; the
Sandbox backend installs and registers with NO Permissions/Harness/compat
dependency (descriptor.requires is empty).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _sandbox_backend_helpers import HARNESSES_TOML
from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_sandbox_api import SandboxApiError, SandboxErrorCode
from ordessa_sandbox_backend import (
    SandboxNativeService,
    SandboxOptionCatalogue,
    build_sandbox_plugin,
)


@pytest.fixture()
def plugin():
    catalogue = SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))
    service = SandboxNativeService(catalogue=catalogue)
    return build_sandbox_plugin(service)


def test_descriptor_declares_no_permissions_or_harness_dependency(plugin):
    descriptor = plugin.descriptor()
    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.requires == ()          # Sandbox installs without Permissions
    assert descriptor.id == "ordessa.sandbox"
    assert descriptor.api_version >= 1


def test_registration_provides_both_ports_and_one_wire_method(plugin):
    context = ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object())
    registration = plugin.build(context)
    assert isinstance(registration, ServerPluginRegistration)
    assert set(registration.provided_ports) == {
        "sandbox.native-configuration@1", "sandbox.describe@1"}
    assert len(registration.methods) == 1     # at most one read-only wire method


def test_wire_method_shape_is_exact_and_read_only(plugin):
    registration = plugin.build(
        ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object()))
    method = registration.methods[0]
    assert isinstance(method, ServerMethodDescriptor)
    assert method.method_id == "sandbox.describe"
    assert method.required_params == frozenset({"harnessId"})
    assert method.optional_params == frozenset(
        {"nativeVersion", "osName", "osVersion", "platformVersion"})


def test_wire_handler_describes_known_pin_without_mutating_state(plugin):
    registration = plugin.build(
        ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object()))
    handler = registration.methods[0].handler
    before = handler({"harnessId": "codex", "nativeVersion": "2.0",
                      "osName": "linux"})
    assert before["status"] == "available"
    assert any(o["optionId"] == "sandbox_mode=workspace-write"
               for o in before["options"])
    # a describe is a query: calling it again returns the same view and does
    # not apply configuration or start side effects
    after = handler({"harnessId": "codex", "nativeVersion": "2.0", "osName": "linux"})
    assert after == before


def test_wire_handler_invents_no_menu_for_unknown_pin(plugin):
    registration = plugin.build(
        ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object()))
    handler = registration.methods[0].handler
    result = handler({"harnessId": "codex", "nativeVersion": "9.9.9", "osName": "linux"})
    assert result["status"] == "unknown"
    assert result["options"] == []


def test_wire_handler_hides_uninstalled_facet(plugin):
    registration = plugin.build(
        ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object()))
    handler = registration.methods[0].handler
    service = registration.provided_ports["sandbox.describe@1"]
    service.repository.save_intent(_codex_intent())
    service.uninstall_facet()
    result = handler({"harnessId": "codex", "nativeVersion": "2.0", "osName": "linux"})
    assert result["visible"] is False
    assert result["options"] == []
    # value retained after uninstall (FR-08)
    assert service.repository.get_intent("sbx-codex-1", 1) is not None


def test_availability_predicate_reflects_busy_state(plugin):
    registration = plugin.build(
        ServerPluginContext(plugin_id="ordessa.sandbox", data_root=object()))
    availability = registration.methods[0].availability
    assert availability() == (True, None)
    service = registration.provided_ports["sandbox.describe@1"]
    service.register_instance("harness-instance-1")
    ok, reason = availability()
    assert ok is False and reason == "PROVIDER_BUSY"


def _codex_intent():
    from _sandbox_backend_helpers import codex_intent
    return codex_intent(revision=1)
