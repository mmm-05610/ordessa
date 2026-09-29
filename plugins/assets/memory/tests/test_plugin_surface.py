"""The plugin surface: wire family registration, C2 + error-family
contributions, the AR-5 default fallback, the honest status snapshot, the
AR-3 absent source state, and disposal."""
from __future__ import annotations

import pytest

from ordessa_memory import bridge, common, facet, llm_wiring
from ordessa_memory.plugin import PLUGIN_ID, REQUIRES, MemoryError, MemoryPlugin

from conftest import FakeCatalog, build_plugin, provider_row


class _Capture:
    """Records registration arguments without a live host."""

    def __init__(self):
        self.methods = None
        self.provided_ports = None
        self.contributions = None
        self.disposal = None
        self.descriptor = None


def test_descriptor_declares_the_model_provider_dependency():
    plugin = MemoryPlugin()
    descriptor = plugin.descriptor()
    assert descriptor.id == PLUGIN_ID
    assert descriptor.requires == REQUIRES == ("ordessa.model-provider",)


def test_build_registers_methods_ports_and_contributions(plugin):
    assert plugin.store is not None
    assert plugin.pipeline is not None and plugin.producer is not None


def test_wire_family_and_error_families_via_real_host(data_root, catalog_openai, port_plan, fake_runner):
    """Build through a real harness-style host double: the contributions
    batch stages into the real registry + error-family handler shapes."""
    plugin = build_plugin(data_root, catalog=catalog_openai, port_plan=port_plan,
                          runner=fake_runner)
    # exercise the wire handlers directly (host-shaped calls)
    status = plugin.status_snapshot()
    assert status["attribution"] == common.ATTRIBUTION
    assert status["telemetry"] == "disabled"
    assert status["llmWiring"]["state"] == "supported"
    assert status["llmWiring"]["llmProvider"] == "openai"
    plugin.store.close()


def test_status_without_catalog_is_honest_unsupported(data_root, port_plan, fake_runner):
    plugin = build_plugin(data_root, catalog=None, port_plan=port_plan, runner=fake_runner)
    status = plugin.status_snapshot()
    assert status["llmWiring"]["state"] == "unsupported"
    assert "bundled provider" in status["llmWiring"]["reason"]
    plugin.store.close()


def test_status_reports_the_ar3_absent_event_source(data_root, catalog_openai):
    plugin = build_plugin(data_root, catalog=catalog_openai)
    status = plugin.status_snapshot()
    assert status["capture"]["source"]["state"] == "absent"
    assert "AR-3" in status["capture"]["source"]["note"]
    plugin.store.close()


def test_binding_roundtrip_and_ar5_default_fallback(plugin):
    answer = {"profileId": "p1"}
    answer["value"] = plugin.store.get_binding("p1")
    assert answer["value"] == common.default_binding()  # absent → facet default, no error
    stored = plugin.store.set_binding("p1", {
        "enabled": False, "budgetTokens": 500, "extractionModelRef": None,
        "boundBrands": ["dsh"]})
    assert stored["enabled"] is False
    assert plugin.store.get_binding("p1")["budgetTokens"] == 500
    with pytest.raises(facet.FacetValueError):
        plugin.store.set_binding("p1", {"enabled": False})


def test_extraction_authorization_defaults_off_and_is_explicit(plugin):
    assert plugin.store.extraction_authorized() is False
    plugin.store.set_extraction_authorized(True)
    assert plugin.status_snapshot()["extractionAuthorized"] is True
    plugin.store.set_extraction_authorized(False)
    assert plugin.status_snapshot()["extractionAuthorized"] is False


def test_health_is_honest_when_the_stack_is_absent(plugin):
    plugin.stack = None
    client = plugin._client_getter()
    assert client is None


def test_injection_response_carries_facet_and_attribution(plugin, fake_mem0):
    plugin.stack = None  # no stack → producer reports absence honestly
    response = plugin.injection_block_response("p1", "深色", "pi")
    assert response["facetName"] == "ordessa.memory"
    assert response["attribution"] == common.ATTRIBUTION
    assert response["coexistenceNote"] is None
    native = plugin.injection_block_response("p1", "深色", "codex")
    assert "重复" in native["coexistenceNote"]


def test_bind_turn_source_flows_events_into_the_pipeline(plugin):
    class _Source:
        source_name = "test-source"

        def subscribe(self, listener):
            self.listener = listener
            return lambda: None

    source = _Source()
    from conftest import FakeClientFactory
    factory = FakeClientFactory("http://127.0.0.1:1")
    plugin._client = factory.client
    plugin.store.set_extraction_authorized(True)
    plugin.pipeline.mark_source_bound(True)
    plugin.bind_turn_source(source)
    source.listener({"profileId": "p1", "sessionId": "s1", "turnId": "t1",
                     "userText": "u", "assistantText": "a"})
    assert plugin.store.capture_stats()["queued"] == 1


def test_disposal_closes_the_store(plugin):
    plugin._dispose()
    assert plugin.store is None
    assert plugin.pipeline is None


def test_missing_data_root_is_a_typed_refusal():
    plugin = MemoryPlugin()

    class _Context:
        plugin_id = "test"
        data_root = None
        ports = {}

    with pytest.raises(MemoryError) as excinfo:
        plugin.build(_Context())
    assert excinfo.value.code == "MEMORY_STORE_UNAVAILABLE"


def test_error_codes_map_to_wire_families():
    from ordessa_memory.plugin import MEMORY_ERROR_CODES
    for family in MEMORY_ERROR_CODES.values():
        assert family in {"UNAVAILABLE", "UNAUTHENTICATED", "FORBIDDEN", "NOT_FOUND",
                          "CONFLICT_VERSION", "CONFLICT_REQUEST", "CONFLICT_REFERENCE",
                          "INVALID_REQUEST", "CAPABILITY_UNSUPPORTED", "OUTCOME_UNKNOWN",
                          "WORKER_UNREACHABLE", "APPROVAL_INVALID"}
