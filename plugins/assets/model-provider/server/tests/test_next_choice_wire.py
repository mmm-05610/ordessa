"""Z3 T01 increments: the seven versioned ``modelProvider.*`` methods.

Authored in this line (not migrated): the names are frozen in
``specs/011-z3-model-provider/t00-freeze.md`` §8; the semantics are the design
contracts' Port signatures (``docs/design/model-provider/contracts.md``). The
legacy six ``providerModels.*`` rows are pinned by ``test_plugin_registration``
and are not touched here.

Gates driven here, all red before the implementation lands:
- catalogue failure is a typed error, never an empty page (MP-03);
- chooseForSession only queues a next-turn intent - zero apply calls, zero
  prompts (MP-05), and an explicitly-requested overlay-revision check without
  an overlay port is a fail-closed refusal (REFERENCE_STATE_UNKNOWN);
- CAS on saveProviderConfig answers ``CONFIG_REVISION_CONFLICT`` carrying the
  current projection; the same operation key with a different payload is
  refused (MP-08);
- reconcile never invents a state: no adapter port -> unknown-outcome, a
  verified read-back decides confirmed/refused (MP-07);
- probeProvider probes the *saved* endpoint read-only (MP-04/10).
"""
from __future__ import annotations

import io
import json

import pytest

from ordessa_model_provider.testing import wire_body

#: The seven new shapes, frozen in t00-freeze.md §8.
NEW_SHAPES = {
    "modelProvider.catalogue": (set(), {"includeArchived", "cursor"}),
    "modelProvider.saveProviderConfig": ({"operationKey", "patch"}, {"expectedVersion"}),
    "modelProvider.probeProvider": (
        {"operationKey", "providerConfigId", "expectedVersion"}, set()),
    "modelProvider.inspectChoice": ({"target", "choice"}, set()),
    "modelProvider.chooseForSession": (
        {"target", "choice", "operationKey"}, {"expectedOverlayRevision"}),
    "modelProvider.queryChoice": ({"target"}, set()),
    "modelProvider.reconcileChoice": ({"target", "operationId"}, set()),
}


def _target(harness="pi"):
    return {"serverInstanceId": "srv-1", "harnessId": harness, "acpSessionId": "s-1"}


def _choice(provider_id="p-1", model="m1"):
    return {"providerConfigId": provider_id, "modelId": model}


class ReadyPort:
    """E1 harness-config port: ready for the seeded config, read-back applied."""

    def __init__(self, model="m1"):
        self.applies = 0
        self._model = model

    def describe(self, harness_id):
        return {"format": "test"}

    def eligibility(self, harness_id, config_ref, session_ref):
        return "ready"

    def apply(self, session_ref, choice):
        self.applies += 1
        return {"readBack": {"model": self._model}, "configOptions": {}}

    def read_back(self, session_ref):
        return {"model": self._model}


class UnsupportPort(ReadyPort):
    def eligibility(self, harness_id, config_ref, session_ref):
        return "unsupported"


# -- registration shapes ------------------------------------------------------

@pytest.fixture()
def host(stack, credentials):
    from ordessa_server.plugin_host.host import ServerPluginHost

    return ServerPluginHost(host_ports={
        "database": stack["database"], "objects": stack["objects"],
        "idempotency": stack["idempotency"], "credentials": credentials,
    })


def test_seven_new_methods_registered_with_frozen_shapes(host, harnesses):
    from ordessa_model_provider.plugin import ModelProviderPlugin

    host.activate_all([ModelProviderPlugin(harnesses=harnesses)])
    for method_id, (required, optional) in NEW_SHAPES.items():
        descriptor = host.methods.lookup(method_id)
        assert descriptor is not None, method_id
        from ordessa_model_provider.plugin import PLUGIN_ID

        assert descriptor.owner == PLUGIN_ID
        assert descriptor.required_params == frozenset(required), method_id
        assert descriptor.optional_params == frozenset(optional), method_id
    assert len(host.methods) == 6 + 7


def test_new_methods_are_single_owner_too(host, harnesses):
    from server_plugin_api import (
        ServerMethodDescriptor, ServerPluginDescriptor, ServerPluginRegistration,
    )
    from ordessa_server.plugin_host.host import DuplicateMethodError
    from ordessa_model_provider.plugin import ModelProviderPlugin

    class Rogue:
        def descriptor(self):
            return ServerPluginDescriptor(
                id="rogue.2", display_name="Rogue", version="1", requires=())

        def build(self, context):
            return ServerPluginRegistration(methods=(
                ServerMethodDescriptor(
                    method_id="modelProvider.catalogue",
                    required_params=frozenset(), optional_params=frozenset(),
                    handler=lambda params: {"items": [], "nextCursor": None},
                    owner="rogue.2",
                ),
            ))

    with pytest.raises(DuplicateMethodError):
        host.activate_all([ModelProviderPlugin(harnesses=harnesses), Rogue()])


# -- catalogue ----------------------------------------------------------------

def test_catalogue_returns_page(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses)
    handlers = plugin.activate_locally(stack, credentials)
    handlers["providerModels.create"]({"requestId": "req-cat-001", **wire_body()})
    page = handlers["modelProvider.catalogue"]({})
    assert [item["displayName"] for item in page["items"]] == ["My API"]
    assert page["nextCursor"] is None


def test_catalogue_failure_is_typed_error_never_empty_page(stack, harnesses, credentials, monkeypatch):
    plugin = ModelProviderPluginShim(harnesses)
    handlers = plugin.activate_locally(stack, credentials)
    from ordessa_server.wire.errors import WireError

    def broken_list(*a, **k):
        raise RuntimeError("store offline")
    monkeypatch.setattr(plugin.catalog.records, "list", broken_list)
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.catalogue"]({})
    assert excinfo.value.details["internalCode"] == "OPERATION_UNKNOWN"


# -- saveProviderConfig -------------------------------------------------------

def test_save_provider_config_create_then_cas_conflict(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses)
    handlers = plugin.activate_locally(stack, credentials)
    saved = handlers["modelProvider.saveProviderConfig"](
        {"operationKey": "op-save-001", "patch": wire_body()})
    revision = saved["providerModel"]
    assert revision["version"] == 1
    # CAS: a stale expectedVersion is a typed revision conflict with current.
    from ordessa_server.wire.errors import WireError
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.saveProviderConfig"]({
            "operationKey": "op-save-002", "expectedVersion": 99,
            "patch": {"providerConfigId": revision["id"], **wire_body()},
        })
    assert excinfo.value.details["internalCode"] == "CONFIG_REVISION_CONFLICT"
    assert excinfo.value.current is not None
    assert excinfo.value.current["version"] == 1


def test_save_provider_config_same_key_different_payload_refused(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses)
    handlers = plugin.activate_locally(stack, credentials)
    handlers["modelProvider.saveProviderConfig"](
        {"operationKey": "op-duplicate-key", "patch": wire_body()})
    from ordessa_server.wire.errors import WireError
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.saveProviderConfig"]({
            "operationKey": "op-duplicate-key",
            "patch": wire_body(displayName="Different"),
        })
    assert excinfo.value.details["internalCode"] == "IDEMPOTENCY_CONFLICT"


# -- probeProvider ------------------------------------------------------------

def test_probe_provider_reads_saved_endpoint_read_only(
        stack, harnesses, credentials, monkeypatch):
    from ordessa_model_provider import probe as probe_module
    from ordessa_model_provider.testing import FakeHarnesses, harness_descriptor

    # a harness seat that accepts api-key credentials, so the saved record can
    # carry a credential reference (the secret itself stays in the store)
    credential_harnesses = FakeHarnesses(
        descriptors={"pi": harness_descriptor(credential_kind="api_key")},
        protocols={"pi": {"openai-chat": ""}},
    )
    from ordessa_model_provider.testing import seed_credential_row

    seed_credential_row(stack["database"], "cred-1")
    plugin = ModelProviderPluginShim(credential_harnesses)
    handlers = plugin.activate_locally(stack, credentials)
    created = handlers["providerModels.create"]({
        "requestId": "req-cat-002",
        **wire_body(credentialId="cred-1", provenance={
            "baseUrl": "https://127.0.0.1/v1", "authStyle": "api_key",
            "wireApi": "chat_completions", "fieldsSource": "manual",
        }),
    })
    record = created["providerModel"]
    payload = json.dumps({"data": [{"id": "m1"}]}).encode()
    monkeypatch.setattr(
        probe_module, "_open_request",
        lambda request, timeout: _FakeResponse(payload))
    fact = handlers["modelProvider.probeProvider"]({
        "operationKey": "op-probe-001", "providerConfigId": record["id"],
        "expectedVersion": record["version"],
    })
    assert fact["status"] == "ok"
    assert fact["models"] == ["m1"]
    assert fact["providerConfigId"] == record["id"]
    assert fact["observedAt"]
    after = handlers["providerModels.list"]({"includeArchived": True})
    assert after["items"][0]["version"] == record["version"]  # read-only probe


def test_probe_provider_stale_version_and_archived_refusals(stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    class UnreferencedPort:
        def references_of(self, provider_config_id):
            return []

    plugin = ModelProviderPluginShim(harnesses, reference_port=UnreferencedPort())
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"]({
        "requestId": "req-cat-003", **wire_body(),
    })["providerModel"]
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.probeProvider"]({
            "operationKey": "op-probe-002", "providerConfigId": record["id"],
            "expectedVersion": 42,
        })
    assert excinfo.value.details["internalCode"] == "CONFIG_REVISION_CONFLICT"
    handlers["providerModels.archive"]({
        "requestId": "req-arch-001", "providerModelId": record["id"],
        "expectedVersion": record["version"],
    })
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.probeProvider"]({
            "operationKey": "op-probe-003", "providerConfigId": record["id"],
            "expectedVersion": record["version"] + 1,
        })
    assert excinfo.value.details["internalCode"] == "PROVIDER_ARCHIVED"


# -- inspectChoice ------------------------------------------------------------

def test_inspect_choice_supported_when_port_ready(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses, harness_config_port=ReadyPort())
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-004", **wire_body()})["providerModel"]
    verdict = handlers["modelProvider.inspectChoice"](
        {"target": _target(), "choice": _choice(record["id"])})
    assert verdict["verdict"] == "supported"


def test_inspect_choice_without_port_is_unknown_never_supported(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses)  # no harness_config_port
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-005", **wire_body()})["providerModel"]
    verdict = handlers["modelProvider.inspectChoice"](
        {"target": _target(), "choice": _choice(record["id"])})
    assert verdict["verdict"] == "unknown"


def test_inspect_choice_unsupported_and_missing_facts(stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    plugin = ModelProviderPluginShim(harnesses, harness_config_port=UnsupportPort())
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-006", **wire_body()})["providerModel"]
    verdict = handlers["modelProvider.inspectChoice"](
        {"target": _target(), "choice": _choice(record["id"])})
    assert verdict["verdict"] == "unsupported"
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.inspectChoice"](
            {"target": _target(), "choice": _choice(record["id"], model="nope")})
    assert excinfo.value.details["internalCode"] == "MODEL_NOT_FOUND"
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.inspectChoice"](
            {"target": _target(), "choice": _choice("p-missing")})
    assert excinfo.value.details["internalCode"] == "PROVIDER_NOT_FOUND"


# -- chooseForSession / queryChoice -------------------------------------------

def test_choose_for_session_queues_pending_zero_apply(stack, harnesses, credentials):
    port = ReadyPort()
    plugin = ModelProviderPluginShim(harnesses, harness_config_port=port)
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-007", **wire_body()})["providerModel"]
    pending = handlers["modelProvider.chooseForSession"](
        {"target": _target(), "choice": _choice(record["id"]),
         "operationKey": "op-queue-001"})
    assert pending["outcome"] == "pending-next-turn"
    assert pending["sequence"]
    assert port.applies == 0  # queueing never applies, never prompts
    state = handlers["modelProvider.queryChoice"]({"target": _target()})
    assert state["desired"]["providerConfigId"] == record["id"]
    assert state["desired"]["modelId"] == "m1"
    assert state["lastConfirmed"] is None


def test_choose_for_session_unsupported_selection_refused(stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    plugin = ModelProviderPluginShim(harnesses, harness_config_port=UnsupportPort())
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-008", **wire_body()})["providerModel"]
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.chooseForSession"](
            {"target": _target(), "choice": _choice(record["id"]),
             "operationKey": "op-queue-002"})
    assert excinfo.value.details["internalCode"] == "SELECTION_UNSUPPORTED"


def test_choose_for_session_overlay_revision_without_port_fail_closed(
        stack, harnesses, credentials):
    from ordessa_server.wire.errors import WireError

    plugin = ModelProviderPluginShim(harnesses, harness_config_port=ReadyPort())
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-009", **wire_body()})["providerModel"]
    with pytest.raises(WireError) as excinfo:
        handlers["modelProvider.chooseForSession"](
            {"target": _target(), "choice": _choice(record["id"]),
             "operationKey": "op-queue-003", "expectedOverlayRevision": "rev-7"})
    assert excinfo.value.details["internalCode"] == "REFERENCE_STATE_UNKNOWN"


# -- reconcileChoice ----------------------------------------------------------

def test_reconcile_confirmed_by_readback(stack, harnesses, credentials):
    port = ReadyPort()
    plugin = ModelProviderPluginShim(harnesses, harness_config_port=port)
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-010", **wire_body()})["providerModel"]
    pending = handlers["modelProvider.chooseForSession"](
        {"target": _target(), "choice": _choice(record["id"]),
         "operationKey": "op-recon-001"})
    result = handlers["modelProvider.reconcileChoice"](
        {"target": _target(), "operationId": pending["sequence"]})
    assert result["outcome"] == "confirmed"
    assert result["turnFact"]["modelId"] == "m1"
    state = handlers["modelProvider.queryChoice"]({"target": _target()})
    assert state["lastConfirmed"]["modelId"] == "m1"
    assert state["desired"] is None  # consumed by the confirmed reconcile


def test_reconcile_mismatch_is_refused(stack, harnesses, credentials):
    port = ReadyPort()
    plugin = ModelProviderPluginShim(harnesses, harness_config_port=port)
    handlers = plugin.activate_locally(stack, credentials)
    record = handlers["providerModels.create"](
        {"requestId": "req-cat-011", **wire_body()})["providerModel"]
    pending = handlers["modelProvider.chooseForSession"](
        {"target": _target(), "choice": _choice(record["id"]),
         "operationKey": "op-recon-002"})
    port._model = "something-else"  # the session drifted from the intent
    result = handlers["modelProvider.reconcileChoice"](
        {"target": _target(), "operationId": pending["sequence"]})
    assert result["outcome"] == "refused"


def test_reconcile_without_port_is_unknown_never_confirmed(stack, harnesses, credentials):
    plugin = ModelProviderPluginShim(harnesses)  # no port
    handlers = plugin.activate_locally(stack, credentials)
    result = handlers["modelProvider.reconcileChoice"](
        {"target": _target(), "operationId": 17})
    assert result["outcome"] == "unknown-outcome"
    assert result["reason"] == "ADAPTER_MISSING"


# -- helpers -------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._consumed = False

    def read(self, size=-1):
        # one-shot body: the probe's read loop stops at the first empty read
        if self._consumed:
            return b""
        self._consumed = True
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ModelProviderPluginShim:
    """Activates the real plugin against the fixture stack without a host,
    exposing the handler table directly (the same shape the host would bind)."""

    def __init__(self, harnesses, harness_config_port=None, reference_port=None):
        from ordessa_model_provider.plugin import ModelProviderPlugin

        self._plugin = ModelProviderPlugin(
            harnesses=harnesses, harness_config_port=harness_config_port,
            reference_port=reference_port)
        self.catalog = None

    def activate_locally(self, stack, credentials):
        from types import SimpleNamespace

        context = SimpleNamespace(ports={
            "database": stack["database"], "objects": stack["objects"],
            "idempotency": stack["idempotency"], "credentials": credentials,
        })
        registration = self._plugin.build(context)
        self.catalog = self._plugin.catalog
        handlers = {
            descriptor.method_id: descriptor.handler
            for descriptor in registration.methods
        }
        return handlers
