# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_plugin_registration.py, verbatim)
"""G2/G3: single ownership and the absence comparison, against the real host.

The plugin is activated on a real ``ServerPluginHost`` with the same port names
the composition supplies. G2's counterexample is a second plugin claiming
``providerModels.list``: the host must refuse startup, in either activation
order. G3's counterexample is the unloaded plugin still answering: after
``deactivate`` no ``providerModels.*`` row remains while the stored records do.
"""
from __future__ import annotations

import pytest
from server_plugin_api import (
    ServerMethodDescriptor, ServerPluginDescriptor, ServerPluginRegistration,
)

from ordessa_model_provider.plugin import PLUGIN_ID, ModelProviderPlugin
from ordessa_server.plugin_host.host import (
    DuplicateMethodError, ServerPluginHost,
)

from ordessa_model_provider.testing import FakeCredentials, FakeHarnesses, wire_body


# The frozen wire shapes, transcribed from
# specs/002-model-provider/contracts/backend-wire.md (legacy _PARAM_SHAPES).
EXPECTED_SHAPES = {
    "providerModels.list": ({"includeArchived"}, set()),
    "providerModels.create": (
        {"requestId", "displayName", "harness", "provider", "credentialId",
         "configuration", "models"},
        {"provenance"},
    ),
    "providerModels.update": (
        {"requestId", "providerModelId", "expectedVersion", "displayName", "credentialId",
         "configuration", "models"},
        {"provenance"},
    ),
    "providerModels.archive": ({"requestId", "providerModelId", "expectedVersion"}, set()),
    "providerModels.probeModels": ({"requestId", "baseUrl"}, {"credentialId", "provenance"}),
    "providerModels.probeConnection": ({"requestId", "baseUrl"}, {"credentialId"}),
}


class RoguePlugin:
    """A second claimant for one providerModels method (the dual-owner shape)."""

    def descriptor(self):
        return ServerPluginDescriptor(
            id="rogue.provider", display_name="Rogue", version="1", requires=())

    def build(self, context):
        return ServerPluginRegistration(methods=(
            ServerMethodDescriptor(
                method_id="providerModels.list",
                required_params=frozenset({"includeArchived"}),
                optional_params=frozenset(),
                handler=lambda params: {"items": [], "nextCursor": None},
                owner="rogue.provider",
            ),
        ))


@pytest.fixture()
def host(stack, credentials):
    return ServerPluginHost(host_ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })


def _activated_host(host, harnesses):
    host.activate_all([ModelProviderPlugin(harnesses=harnesses)])
    return host


def test_six_methods_registered_with_frozen_shapes(host, harnesses):
    _activated_host(host, harnesses)
    for method_id, (required, optional) in EXPECTED_SHAPES.items():
        descriptor = host.methods.lookup(method_id)
        assert descriptor is not None, method_id
        assert descriptor.owner == PLUGIN_ID
        assert descriptor.required_params == frozenset(required), method_id
        assert descriptor.optional_params == frozenset(optional), method_id
    # exactly the frozen six legacy rows; the Z3 ``modelProvider.*`` additions
    # are pinned by tests/test_next_choice_wire.py (t00-freeze.md §8).
    assert len(host.methods) == 6 + 7


def test_catalog_port_is_exported(host, harnesses):
    _activated_host(host, harnesses)
    active = host.active(PLUGIN_ID)
    assert active.registration.provided_ports["model_provider.catalog"] is not None


def test_g2_second_owner_refuses_activation(host, harnesses):
    host.activate_all([RoguePlugin()])
    with pytest.raises(DuplicateMethodError):
        host.activate_all([ModelProviderPlugin(harnesses=harnesses)])


def test_g2_second_owner_refuses_in_reverse_order(host, harnesses):
    host.activate_all([ModelProviderPlugin(harnesses=harnesses)])
    with pytest.raises(DuplicateMethodError):
        host.activate_all([RoguePlugin()])


def test_g2_dual_claim_in_one_round_refuses_the_round(host, harnesses):
    with pytest.raises(DuplicateMethodError):
        host.activate_all([RoguePlugin(), ModelProviderPlugin(harnesses=harnesses)])
    assert not host.is_active("rogue.provider")


def test_g3_deactivate_removes_methods_but_keeps_records(host, harnesses, stack):
    plugin = ModelProviderPlugin(harnesses=harnesses)
    host.activate_all([plugin])
    handlers = {mid: host.methods.lookup(mid).handler for mid in EXPECTED_SHAPES}
    created = handlers["providerModels.create"]({
        "requestId": "req-create-01", **wire_body(),
    })
    record_id = created["providerModel"]["id"]
    assert len(handlers["providerModels.list"]({"includeArchived": False})["items"]) == 1

    host.deactivate(PLUGIN_ID)

    for method_id in EXPECTED_SHAPES:
        assert host.methods.lookup(method_id) is None, method_id
    with stack["database"].read() as conn:
        row = conn.execute(
            "SELECT id FROM server_provider_models WHERE id=?", (record_id,)).fetchone()
    assert row is not None  # unload never deletes the user's records


def test_handlers_keep_provenance_and_projection_semantics(host, harnesses):
    _activated_host(host, harnesses)
    handler = host.methods.lookup("providerModels.create").handler
    created = handler({
        "requestId": "req-create-02",
        **wire_body(credentialId=None, provenance={
            "baseUrl": "https://127.0.0.1/v1", "wireApi": "chat_completions",
            "fieldsSource": "manual",
        }),
    })
    record = created["providerModel"]
    assert record["provenance"]["baseUrl"] == "https://127.0.0.1/v1"
    assert record["provenance"]["wireApi"] == "chat_completions"  # stored as declared

    update = host.methods.lookup("providerModels.update").handler
    # un-named provenance keeps its stored value
    kept = update({
        "requestId": "req-update-01", "providerModelId": record["id"],
        "expectedVersion": record["version"], "displayName": "Renamed",
        "credentialId": None,
        "configuration": wire_body()["configuration"],
        "models": wire_body()["models"],
    })["providerModel"]
    assert kept["displayName"] == "Renamed"
    assert kept["provenance"]["baseUrl"] == "https://127.0.0.1/v1"
    # named null clears
    cleared = update({
        "requestId": "req-update-02", "providerModelId": record["id"],
        "expectedVersion": kept["version"], "displayName": "Renamed",
        "credentialId": None,
        "configuration": wire_body()["configuration"],
        "models": wire_body()["models"],
        "provenance": {"baseUrl": None},
    })["providerModel"]
    # only the named field clears; the others are untouched facts
    assert cleared["provenance"]["baseUrl"] is None
    assert cleared["provenance"]["wireApi"] == "chat_completions"


def test_update_version_conflict_maps_to_wire_error_with_current(host, harnesses):
    from ordessa_server.wire.errors import WireError

    _activated_host(host, harnesses)
    create = host.methods.lookup("providerModels.create").handler
    record = create({"requestId": "req-create-03", **wire_body()})["providerModel"]
    update = host.methods.lookup("providerModels.update").handler
    update({"requestId": "req-update-03", "providerModelId": record["id"],
            "expectedVersion": record["version"], "displayName": "v2",
            "credentialId": None,
            "configuration": wire_body()["configuration"],
            "models": wire_body()["models"]})
    with pytest.raises(WireError) as excinfo:
        update({"requestId": "req-update-04", "providerModelId": record["id"],
                "expectedVersion": record["version"], "displayName": "v3",
                "credentialId": None,
                "configuration": wire_body()["configuration"],
                "models": wire_body()["models"]})
    assert getattr(excinfo.value, "current", None) is not None
    assert excinfo.value.current["version"] == record["version"] + 1


def test_archive_reference_conflict_rides_the_wire_error_details(host, harnesses):
    from ordessa_server.wire.errors import WireError

    class ReferencingPort:
        def references_of(self, provider_config_id):
            return ["profile-9"]

    host.activate_all([ModelProviderPlugin(harnesses=harnesses, reference_port=ReferencingPort())])
    create = host.methods.lookup("providerModels.create").handler
    record = create({"requestId": "req-create-04",
                     **wire_body(credentialId=None)})["providerModel"]
    archive = host.methods.lookup("providerModels.archive").handler
    with pytest.raises(WireError) as excinfo:
        archive({"requestId": "req-archive-01", "providerModelId": record["id"],
                 "expectedVersion": record["version"]})
    assert excinfo.value.details["referenceIds"] == ["profile-9"]
