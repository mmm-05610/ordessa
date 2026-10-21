"""Current-owner successor coverage for Order 092 compatibility facts.

Uses the real ModelCatalogService/records, the fixture's App Database and its
same-connection IdempotentRecords port. Read projections are checked against
selected public C2 descriptors; the retained freeze method is separately
checked at its current service boundary.
"""
from __future__ import annotations

import pytest

from ordessa_server_plugin_api.internal_errors import ServerError

from ordessa_model_provider.harness_declarations import ModelConfigurationCatalog
from ordessa_model_provider.testing import harness_descriptor, wire_body


def _row(catalog, key: str, *, protocols=...):
    body = wire_body(harness=None, configuration=[])
    if protocols is not ...:
        body["protocols"] = protocols
    return catalog.create(key, body)


def _selected_c2(protocols: dict[str, dict[str, str]]):
    """Build the current projection from real selected brand C2 descriptors."""
    from ordessa_harness_claude_code.configuration.c2 import descriptor as claude_descriptor
    from ordessa_harness_codex.configuration.c2 import descriptor as codex_descriptor
    from ordessa_harness_pi.configuration.c2 import descriptor as pi_descriptor

    descriptors = (claude_descriptor(), codex_descriptor(), pi_descriptor())
    ports = {
        harness_id: (lambda value=protocols.get(harness_id, {}): dict(value))
        for harness_id in ("claude-code", "codex", "pi")
    }
    from ordessa_harness_claude_code.configuration.c2 import declared_model_control as claude_control
    from ordessa_harness_codex.configuration.c2 import declared_model_control as codex_control
    from ordessa_harness_pi.configuration.c2 import declared_model_control as pi_control
    controls = dict(zip((descriptor.harness_id for descriptor in descriptors),
                        (claude_control, codex_control, pi_control)))
    return ModelConfigurationCatalog(descriptors, protocol_ports=ports,
        model_control_ports=controls)


def _set_freeze_declarations(catalog, selected):
    """Freeze uses the same actual selected declaration projection as reads."""
    catalog.harnesses = selected


def _freeze(catalog, harness_id: str, record):
    return catalog.freeze_execution_configuration(
        harness_id,
        {"model": {"providerId": record["id"], "modelId": "m1"}},
    )


def test_catalog_projection_derives_sorted_compatibility_and_rederives_live(catalog):
    record = _row(catalog, "compat-projection", protocols=["openai-chat", "anthropic-messages"])
    selected = _selected_c2({
        "codex": {"openai-chat": "declared", "openai-responses": "declared"},
        "claude-code": {"anthropic-messages": "declared"},
        "pi": {"openai-chat": "declared"},
    })
    catalog.harnesses = selected

    first = next(item for item in catalog.list() if item["id"] == record["id"])
    assert first["compatibility"] == [
        {"harness": "claude-code", "protocol": "anthropic-messages"},
        {"harness": "codex", "protocol": "openai-chat"},
        {"harness": "pi", "protocol": "openai-chat"},
    ]
    assert first["protocolsDeclared"] is True
    assert first["protocols"] == ["openai-chat", "anthropic-messages"]

    # A new selected declaration snapshot changes the next read projection;
    # no compatibility value is stored with the record.
    catalog.harnesses = _selected_c2({
        "codex": {"openai-chat": "declared"},
        "claude-code": {},
        "pi": {},
    })
    second = next(item for item in catalog.list() if item["id"] == record["id"])
    assert second["compatibility"] == [{"harness": "codex", "protocol": "openai-chat"}]
    assert second["protocols"] == first["protocols"]


def test_catalog_projection_keeps_undeclared_record_unknown_and_empty(catalog):
    record = _row(catalog, "compat-unknown")
    catalog.harnesses = _selected_c2({
        "codex": {"openai-chat": "declared"},
        "claude-code": {"anthropic-messages": "declared"},
        "pi": {},
    })

    projected = next(item for item in catalog.list() if item["id"] == record["id"])
    assert projected["protocolsDeclared"] is False
    assert projected["protocols"] is None
    assert projected["compatibility"] == []


def test_freeze_rejects_declared_disjoint_protocols_and_accepts_overlap(catalog):
    record = _row(catalog, "freeze-disjoint", protocols=["openai-chat"])
    _set_freeze_declarations(catalog, _selected_c2({
        "codex": {"openai-chat": "declared"},
        "claude-code": {"anthropic-messages": "declared"},
    }))

    with pytest.raises(ServerError) as caught:
        _freeze(catalog, "claude-code", record)
    assert caught.value.code == "PROTOCOL_INCOMPATIBLE"
    assert _freeze(catalog, "codex", record)["model"] == "m1"


def test_freeze_adding_declared_protocol_makes_same_reference_pass(catalog):
    record = _row(catalog, "freeze-add-protocol", protocols=["openai-chat"])
    _set_freeze_declarations(catalog, _selected_c2({
        "claude-code": {"anthropic-messages": "declared"},
    }))
    with pytest.raises(ServerError) as caught:
        _freeze(catalog, "claude-code", record)
    assert caught.value.code == "PROTOCOL_INCOMPATIBLE"

    catalog.update(record["id"], record["version"], "freeze-add-protocol-update", {
        "protocols": ["openai-chat", "anthropic-messages"],
    })
    assert _freeze(catalog, "claude-code", record)["model"] == "m1"


def test_freeze_does_not_treat_undeclared_harness_protocols_as_incompatible(catalog):
    record = _row(catalog, "freeze-unknown-harness", protocols=["openai-chat"])
    _set_freeze_declarations(catalog, _selected_c2({"claude-code": {}}))
    assert _freeze(catalog, "claude-code", record)["model"] == "m1"


def test_freeze_passes_through_declared_protocol_and_endpoint_facts(catalog):
    body = wire_body(
        harness=None, configuration=[], protocols=["openai-chat"],
        endpoints={"openai-chat": "http://127.0.0.1:9/v1"},
    )
    record = catalog.create("freeze-facts", body)
    _set_freeze_declarations(catalog, _selected_c2({"codex": {"openai-chat": "declared"}}))

    frozen = _freeze(catalog, "codex", record)
    assert frozen["protocols"] == ["openai-chat"]
    assert frozen["endpoints"] == {"openai-chat": "http://127.0.0.1:9/v1"}


def test_freeze_without_protocol_facts_adds_no_projection_keys(catalog):
    record = _row(catalog, "freeze-no-facts")
    _set_freeze_declarations(catalog, _selected_c2({"codex": {"openai-chat": "declared"}}))

    frozen = _freeze(catalog, "codex", record)
    assert "protocols" not in frozen and "endpoints" not in frozen
    assert set(frozen) == {
        "providerModelId", "providerModelVersion", "provider", "model",
        "credentialId", "configuration",
    }


def test_selected_public_c2_declaration_rejects_unknown_protocol_and_orders_known_values():
    from ordessa_harness_codex.configuration.c2 import descriptor, declared_model_control

    with pytest.raises(ServerError) as caught:
        ModelConfigurationCatalog(
            [descriptor()],
            protocol_ports={"codex": lambda: {"martian-wire": "declared"}},
            model_control_ports={"codex": declared_model_control},
        )
    assert caught.value.code == "PROTOCOL_UNKNOWN"

    selected = ModelConfigurationCatalog(
        [descriptor()],
        protocol_ports={"codex": lambda: {
            "openai-responses": "declared", "openai-chat": "declared",
        }},
        model_control_ports={"codex": declared_model_control},
    )
    assert tuple(selected.wire_protocols("codex")) == ("openai-chat", "openai-responses")
    assert selected.get("codex").id == "codex"
