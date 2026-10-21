"""Current-owner wire successors for Orders 098 and 112.

Every case crosses the real plugin descriptor/host method registry and the
Server's WireService dispatch wall into ModelCatalogService, backed by the
shared temporary App Database fixture. Nothing here invokes the retired
server-compat surface.
"""
from __future__ import annotations

import pytest
from ordessa_server_plugin_api import WireError

from ordessa_model_provider.plugin import PLUGIN_ID, ModelProviderPlugin
from ordessa_model_provider.testing import wire_body
from ordessa_interfaces.system_access.services.invocation import WireService

PROVENANCE = {
    "baseUrl": "https://api.deepseek.com",
    "authStyle": "api_key",
    "wireApi": "chat_completions",
    "fieldsSource": "manual",
}


@pytest.fixture
def rig(stack, credentials, harnesses):
    from ordessa_server.composition.plugin_host.host import ServerPluginHost
    host = ServerPluginHost(host_ports={**stack, "credentials": credentials})
    plugin = ModelProviderPlugin(harnesses=harnesses)
    descriptor = plugin.descriptor()
    host.activate_all([plugin])
    wire = WireService(
        server_id_provider=lambda: "controlled-server",
        cursor_secret=b"p" * 32,
        method_registry=host.methods,
    )
    return {"plugin": plugin, "descriptor": descriptor, "host": host, "wire": wire}


def _create(wire, request_id="prov-wire-create", *, provenance=..., **changes):
    params = {"requestId": request_id, **wire_body()}
    if provenance is not ...:
        params["provenance"] = provenance
    params.update(changes)
    return wire.dispatch("providerModels.create", params)["providerModel"]


def _update(wire, record, request_id, **changes):
    params = {
        "requestId": request_id,
        "providerModelId": record["id"],
        "expectedVersion": record["version"],
        "displayName": record["displayName"],
        "credentialId": record["credentialId"],
        "configuration": wire_body()["configuration"],
        "models": record["models"],
    }
    params.update(changes)
    return wire.dispatch("providerModels.update", params)["providerModel"]


def _read(wire, record_id):
    rows = wire.dispatch("providerModels.list", {"includeArchived": False})["items"]
    return next(row for row in rows if row["id"] == record_id)


def test_real_descriptor_wire_create_and_separate_list_readback(rig):
    descriptor = rig["descriptor"]
    assert descriptor.id == PLUGIN_ID
    assert rig["host"].active(PLUGIN_ID).registration.provided_ports["model_provider.catalog"] is rig["plugin"].catalog

    saved = _create(rig["wire"], provenance=PROVENANCE)
    assert saved["provenance"] == PROVENANCE
    assert _read(rig["wire"], saved["id"])["provenance"] == PROVENANCE


def test_wire_omission_keeps_and_named_null_clears_only_that_fact(rig):
    wire = rig["wire"]
    saved = _create(wire, provenance=PROVENANCE)

    empty = _update(wire, saved, "prov-wire-empty", provenance={})
    assert empty["provenance"] == PROVENANCE

    kept = _update(wire, empty, "prov-wire-keep")
    assert kept["provenance"] == PROVENANCE
    assert _read(wire, saved["id"])["provenance"] == PROVENANCE

    partial = _update(wire, kept, "prov-wire-partial", provenance={"fieldsSource": "pulled"})
    partial_expected = dict(PROVENANCE, fieldsSource="pulled")
    assert partial["provenance"] == partial_expected
    assert _read(wire, saved["id"])["provenance"] == partial_expected

    cleared = _update(wire, partial, "prov-wire-clear", provenance={"baseUrl": None})
    expected = dict(partial_expected, baseUrl=None)
    assert cleared["provenance"] == expected
    assert _read(wire, saved["id"])["provenance"] == expected

    mixed = _update(wire, cleared, "prov-wire-mixed",
                    provenance={"wireApi": None, "authStyle": "oauth"})
    mixed_expected = dict(expected, wireApi=None, authStyle="oauth")
    assert mixed["provenance"] == mixed_expected
    assert _read(wire, saved["id"])["provenance"] == mixed_expected

    cleared_all = _update(wire, mixed, "prov-wire-clear-all",
                          provenance={key: None for key in PROVENANCE})
    assert cleared_all["provenance"] is None
    assert _read(wire, saved["id"])["provenance"] is None


def test_wire_rejects_invalid_provenance_object_field_and_enum_without_create(rig):
    wire = rig["wire"]
    for index, bad in enumerate((
        ["api_key"],
        {"unknown": "x"},
        {"authStyle": "telepathy"},
        {"baseUrl": "https://x" * 600},
    )):
        with pytest.raises(WireError) as caught:
            _create(wire, f"prov-wire-bad-create-{index}", provenance=bad)
        assert caught.value.family == "INVALID_REQUEST"
        assert rig["plugin"].catalog.list() == []


def test_wire_rejects_invalid_provenance_update_without_mutating_record(rig):
    wire = rig["wire"]
    saved = _create(wire, provenance=PROVENANCE)
    for index, bad in enumerate((
        ["api_key"],
        {"unknown": "x"},
        {"authStyle": "telepathy"},
        {"baseUrl": "https://x" * 600},
    )):
        with pytest.raises(WireError) as caught:
            _update(wire, saved, f"prov-wire-bad-update-{index}", provenance=bad)
        assert caught.value.family == "INVALID_REQUEST"
        current = _read(wire, saved["id"])
        assert current["version"] == saved["version"]
        assert current["provenance"] == PROVENANCE


def test_probe_models_uses_real_catalog_probe_and_controlled_loopback(rig):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    wire = rig["wire"]
    with pytest.raises(WireError) as caught:
        wire.dispatch("providerModels.probeModels", {
            "requestId": "prov-probe-invalid",
            "baseUrl": "https://invalid.invalid/v1",
            "provenance": {"unknown": "x"},
        })
    assert caught.value.family == "INVALID_REQUEST"

    seen = []

    class ControlledReject(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            self.send_response(403)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ControlledReject)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        outcome = wire.dispatch("providerModels.probeModels", {
            "requestId": "prov-probe-controlled",
            "baseUrl": base_url,
            "provenance": {"authStyle": "api_key", "fieldsSource": "manual"},
        })
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert outcome == {"status": "failed", "code": "PROBE_AUTH_FAILED", "models": []}
    assert seen == [("/v1/models", None)]


def test_wire_exposes_staticmethod_scope_regression_and_restored_behavior(rig, monkeypatch):
    from ordessa_model_provider import plugin as plugin_module

    handlers = plugin_module._Handlers
    original = handlers._provenance

    def broken(params):
        raw = params.get("provenance")
        if raw is None:
            return None
        # Reintroduces the historical class-scope lookup mistake as a planted
        # counterexample; the real WireService must convert it to typed absence.
        if not set(raw) <= set(_UNBOUND_PROVENANCE_FIELDS):  # noqa: F821
            raise WireError("INVALID_REQUEST", "provenance carries unknown fields")
        return dict(raw)

    monkeypatch.setattr(handlers, "_provenance", staticmethod(broken))
    with pytest.raises(WireError) as caught:
        _create(rig["wire"], "prov-wire-scope-counterexample", provenance=PROVENANCE)
    assert caught.value.family == "UNAVAILABLE"
    assert caught.value.details["internalCode"] == "NameError"

    monkeypatch.setattr(handlers, "_provenance", staticmethod(original))
    assert handlers._provenance is original
    restored = _create(rig["wire"], "prov-wire-scope-restored", provenance=PROVENANCE)
    assert restored["provenance"] == PROVENANCE


def test_wire_exposes_column_keyed_half_fix_as_data_loss_counterexample(rig, monkeypatch):
    from ordessa_model_provider import plugin as plugin_module

    handlers = plugin_module._Handlers
    original = handlers._provenance
    column_names = {
        "baseUrl": "base_url",
        "authStyle": "auth_style",
        "wireApi": "wire_api",
        "fieldsSource": "fields_source",
    }

    def half_fixed(params):
        parsed = original(params)
        if parsed is None:
            return None
        return {column_names[key]: value for key, value in parsed.items()}

    monkeypatch.setattr(handlers, "_provenance", staticmethod(half_fixed))
    record = _create(rig["wire"], "prov-wire-column-counterexample", provenance=PROVENANCE)
    assert record["provenance"] is None
    assert _read(rig["wire"], record["id"])["provenance"] is None


def test_wire_keeps_create_without_provenance_unknown_and_accepts_explicit_nulls(rig):
    wire = rig["wire"]
    absent = _create(wire, "prov-wire-absent")
    assert absent["provenance"] is None
    explicit = _create(
        wire, "prov-wire-explicit-null",
        provenance={"baseUrl": None, "authStyle": "api_key"},
    )
    assert explicit["provenance"] == {
        "baseUrl": None, "authStyle": "api_key", "wireApi": None, "fieldsSource": None,
    }
    assert _read(wire, explicit["id"])["provenance"] == explicit["provenance"]


def test_wire_retains_typed_refusals_for_null_required_fields_and_empty_models(rig):
    wire = rig["wire"]
    saved = _create(wire, "prov-wire-required-shapes", provenance=PROVENANCE)
    for index, (field, changes) in enumerate((
        ("displayName", {"displayName": None}),
        ("configuration", {"configuration": None}),
        ("models", {"models": None}),
        ("models", {"models": []}),
    )):
        with pytest.raises(WireError) as caught:
            _update(wire, saved, f"prov-wire-required-shape-{index}", **changes)
        assert caught.value.family == "INVALID_REQUEST"
        assert field in caught.value.message
        assert _read(wire, saved["id"])["version"] == saved["version"]
    emptied = _update(wire, saved, "prov-wire-empty-configuration", configuration=[])
    assert emptied["configuration"] == []
    assert emptied["provenance"] == PROVENANCE


def test_service_update_keeps_all_facts_its_body_omits(rig):
    saved = _create(rig["wire"], "prov-service-sparse", provenance=PROVENANCE)
    renamed = rig["plugin"].catalog.update(
        saved["id"], saved["version"], "prov-service-sparse-update",
        {"displayName": "Renamed only"},
    )
    assert renamed["displayName"] == "Renamed only"
    assert renamed["models"] == saved["models"]
    assert renamed["credentialId"] is None
    assert renamed["provenance"] == PROVENANCE
    assert renamed["version"] == saved["version"] + 1


def test_wire_stale_version_stays_typed_and_idempotent_replay_does_not_bump_twice(rig):
    wire = rig["wire"]
    saved = _create(wire, "prov-wire-cas", provenance=PROVENANCE)
    changed = _update(wire, saved, "prov-wire-cas-first", displayName="Changed")
    with pytest.raises(WireError) as caught:
        _update(wire, saved, "prov-wire-cas-stale", displayName="Stale")
    assert caught.value.family == "CONFLICT_VERSION"
    assert caught.value.current["version"] == changed["version"]

    params = {
        "requestId": "prov-wire-replay",
        "providerModelId": changed["id"],
        "expectedVersion": changed["version"],
        "displayName": changed["displayName"],
        "credentialId": changed["credentialId"],
        "configuration": wire_body()["configuration"],
        "models": changed["models"],
        "provenance": {"baseUrl": None},
    }
    first = wire.dispatch("providerModels.update", params)["providerModel"]
    replay = wire.dispatch("providerModels.update", params)["providerModel"]
    assert replay["version"] == first["version"]
    assert replay["provenance"] == dict(PROVENANCE, baseUrl=None)


def test_wire_shape_still_refuses_each_missing_required_update_field(rig):
    wire = rig["wire"]
    saved = _create(wire, "prov-wire-missing-required")
    complete = {
        "requestId": "prov-wire-missing-required-update",
        "providerModelId": saved["id"],
        "expectedVersion": saved["version"],
        "displayName": saved["displayName"],
        "credentialId": saved["credentialId"],
        "configuration": wire_body()["configuration"],
        "models": saved["models"],
    }
    for index, field in enumerate(("displayName", "credentialId", "configuration", "models")):
        params = dict(complete, requestId=f"prov-wire-missing-required-{index}")
        params.pop(field)
        with pytest.raises(WireError) as caught:
            wire.dispatch("providerModels.update", params)
        assert caught.value.family == "INVALID_REQUEST"
        assert field in caught.value.message


def test_wire_handler_drop_nulls_counterexample_would_swallow_clear(rig, monkeypatch):
    from ordessa_model_provider import plugin as plugin_module

    handlers = plugin_module._Handlers
    original = handlers._provenance

    def dropping(params):
        parsed = original(params)
        if parsed is None:
            return None
        return {key: value for key, value in parsed.items() if value is not None}

    monkeypatch.setattr(handlers, "_provenance", staticmethod(dropping))
    wire = rig["wire"]
    saved = _create(wire, "prov-wire-drop-null", provenance=PROVENANCE)
    result = _update(
        wire, saved, "prov-wire-drop-null-update",
        provenance={key: None for key in PROVENANCE},
    )
    assert result["provenance"] == PROVENANCE
    assert _read(wire, saved["id"])["provenance"] == PROVENANCE


def test_wire_credential_null_unbind_uses_real_records_and_controlled_secret_port(stack):
    from ordessa_model_provider.plugin import ModelProviderPlugin
    from ordessa_model_provider.testing import FakeHarnesses, harness_descriptor
    from ordessa_server.composition.plugin_host.host import ServerPluginHost
    from ordessa_server.configuration.credentials import CredentialRecords

    class ControlledSecretStore:
        def __init__(self):
            self.reads = []

        def read(self, locator):
            self.reads.append(locator)
            return b"controlled-test-secret"

    credentials = CredentialRecords(stack["database"])
    credentials.register("cred-wire-unbind", "api_key", "controlled://cred-wire-unbind")
    secret_store = ControlledSecretStore()
    harnesses = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind="api_key")},
        protocols={"pi": {"openai-chat": ""}},
    )
    host = ServerPluginHost(data_root=stack["root"], host_ports={
        **stack, "credentials": credentials,
    })
    plugin = ModelProviderPlugin(harnesses=harnesses, secret_store=secret_store)
    host.activate_all([plugin])
    wire = WireService(
        server_id_provider=lambda: "controlled-server",
        cursor_secret=b"c" * 32,
        method_registry=host.methods,
    )

    bound = _create(wire, "prov-credential-bound", provenance=PROVENANCE,
                    credentialId="cred-wire-unbind")
    assert bound["credentialId"] == "cred-wire-unbind"
    assert credentials.get("cred-wire-unbind", kind="api_key")["secret_locator"] == \
        "controlled://cred-wire-unbind"

    detached = _update(wire, bound, "prov-credential-detached", credentialId=None)
    assert detached["credentialId"] is None
    assert _read(wire, bound["id"])["credentialId"] is None
    assert detached["provenance"] == PROVENANCE
    assert secret_store.reads == []


def test_current_keep_sentinel_identity_and_repr_are_pinned():
    from ordessa_model_provider.records import KEEP

    assert KEEP is not None
    assert repr(KEEP) == "<KEEP>"
