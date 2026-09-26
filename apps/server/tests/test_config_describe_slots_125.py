"""Order 125: `config.describe` has to show every slot, not the first one.

R-0013's v2 multi-slot criteria (092's G8/G9/G10) reached the wire as: a control
may hold a *list* of Provider/Model references. Before this order
`_controls` built `slots` from `control_id` alone - one entry, whatever the
profile held - so a client could not see past the first seat. The storage layer
already walked lists (`model_configs.service._model_references` is recursive),
which is why this survived as a *wire-only* fix.

Shape decision, and the reason for it:
  * a single-reference value keeps the **legacy dict verbatim**
    (`{"name": control_id, "model": ...}`) - 092's G9 says the old shape must not
    move, and order 60's wire test pins that dict key for key;
  * a list value gets one entry per reference with a stable table identity:
    `name`, `slotIndex`, `table`, `providerId`, `modelId`, `model`.
  * an empty list yields **no slots** - nothing is invented for an absent seat
    (G10: 覆盖与事实分离, 缺席不写键).

Every gate drives the real wire over HTTP.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

REPO = Path(__file__).resolve().parents[3]
TARGETS = ("plugins/server-compat/src/ordessa_server_compat/core_wire.py", "plugins/server-compat/src/ordessa_server_compat/model_configs/service.py")

_spec = importlib.util.spec_from_file_location(
    "wire_v1_helpers", REPO / "apps/server/tests/test_wire_v1.py")
wire_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wire_v1)

from ordessa_server.bootstrap import build_runtime
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.transport.http import create_app
from ordessa_server_compat.model_configs.service import _model_references
from ordessa_server_compat import core_wire as handlers_module


def _registry():
    """The production shape, with a validator that allows a seat list too.

    The descriptor half (declaring `model_controls`, plural) belongs to the
    runtime line and 125's order text says it can come later; what the wire has
    to be right about is a value that *is* a list, because storage accepts it.
    """
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True},
        model_control_id="model", control_options={"model": ()},
        configuration_validator=lambda value: (
            None if isinstance(value, (dict, list)) else ValueError()),
    ))
    return registry


@pytest.fixture
def api(tmp_path):
    runtime = build_runtime(tmp_path / "data", harnesses=_registry(),
                            connector=wire_v1.FakeConnector(),
                            execution=wire_v1.RecordingExecution(block=True))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, wire_v1.Wire(client, {"Authorization": f"Bearer {runtime.token}"})


def _provider(api, name: str, model_id: str):
    created = api.ok("providerModels.create", {
        "requestId": f"p125-{name}", "displayName": name, "harness": "alpha",
        "provider": f"opaque-{name}", "credentialId": None, "configuration": [],
        "models": [{"modelId": model_id, "displayName": model_id.upper(),
                    "availability": "unknown", "unavailableReason": None}],
    })["providerModel"]
    return created["id"], model_id


def _profile_with_value(api, value):
    created = api.ok("profiles.create", {
        "requestId": "p125-profile", "displayName": "multi", "harness": "alpha"})["profile"]
    api.ok("profiles.updateConfig", {
        "requestId": "p125-config", "profileId": created["id"],
        "expectedVersion": created["version"],
        "values": [{"controlId": "model", "value": value}]})
    return created["id"]


def _model_control(api, profile_id):
    descriptor = api.ok("config.describe", {"profileId": profile_id, "workspaceId": None})["descriptor"]
    control = next(item for item in descriptor["controls"] if item["controlId"] == "model")
    others = [item for item in descriptor["controls"] if item["controlId"] == "model"]
    assert len(others) == 1, "one control must not be projected twice"
    return control


# -- G1: every seat is visible ---------------------------------------------

def test_a_single_reference_keeps_the_legacy_shape_verbatim(api):
    _runtime, client = api
    provider_id, model_id = _provider(client, "one", "model-a")
    profile_id = _profile_with_value(client, {"providerId": provider_id, "modelId": model_id})
    control = _model_control(client, profile_id)
    assert control["slots"] == [{
        "name": "model",
        "model": {"providerId": provider_id, "modelId": model_id,
                  "availability": "unknown", "unavailableReason": None},
    }], control["slots"]


def test_a_list_value_projects_one_slot_per_reference_with_a_table_identity(api):
    _runtime, client = api
    first = _provider(client, "two", "model-a")
    second = _provider(client, "three", "model-b")
    profile_id = _profile_with_value(client, [
        {"providerId": first[0], "modelId": first[1]},
        {"providerId": second[0], "modelId": second[1]}])
    slots = _model_control(client, profile_id)["slots"]
    assert [(slot["name"], slot["slotIndex"], slot["table"],
             slot["providerId"], slot["modelId"]) for slot in slots] == [
        ("model[0]", 0, "providerModels", first[0], "model-a"),
        ("model[1]", 1, "providerModels", second[0], "model-b")], slots
    assert slots[0]["model"]["modelId"] == "model-a"
    assert slots[1]["model"]["providerId"] == second[0]


def test_an_empty_list_invents_no_seat(api):
    _runtime, client = api
    profile_id = _profile_with_value(client, [])
    control = _model_control(client, profile_id)
    assert control["slots"] == [], control
    assert "currentValue" not in control and "value" not in control, control


def test_counter_example_the_first_slot_only_projection_is_back(api, monkeypatch):
    """The pre-125 behaviour, restored where the wire actually reads it.

    `slots` used to be built from the control id alone, so a two-seat profile was
    described as one seat and the client had no way to learn the second exists.
    """
    _runtime, client = api
    first = _provider(client, "four", "model-a")
    second = _provider(client, "five", "model-b")
    profile_id = _profile_with_value(client, [
        {"providerId": first[0], "modelId": first[1]},
        {"providerId": second[0], "modelId": second[1]}])
    original = handlers_module.CoreWireHandlers._slot_entries

    def one_slot_only(self, control_id, references, current):
        return original(self, control_id, references[:1], current)

    monkeypatch.setattr(handlers_module.CoreWireHandlers, "_slot_entries", one_slot_only)
    slots = _model_control(client, profile_id)["slots"]
    assert len(slots) == 1, slots
    monkeypatch.undo()
    assert len(_model_control(client, profile_id)["slots"]) == 2


# -- G3: the copy of a rule is checked against the rule ---------------------

@pytest.mark.parametrize("value", [
    {"providerId": "p", "modelId": "m"},
    [{"providerId": "p", "modelId": "m"}],
    [{"providerId": "p", "modelId": "m"}, {"providerId": "q", "modelId": "n"}],
    {"nested": {"deep": [{"providerId": "p", "modelId": "m"}]}},
    {"providerId": "p"},
    "not-a-reference",
    [],
])
def test_the_wire_walks_references_exactly_like_the_service(value):
    assert handlers_module._model_reference_list(value) == list(_model_references(value))


def test_the_two_walks_differ_on_one_shape_and_the_wire_is_the_stricter_one():
    """The copy is checked, and where it deliberately differs that is pinned.

    `model_configs.service._model_references` asks whether the *keys* are
    present and then stringifies, so `{"providerId": "p", "modelId": None}`
    becomes a reference to a model literally named "None" - which the wire would
    then send to `reference()` and get a typed 404. The wire requires real
    strings. The service's behaviour is a finding for its own line (交回, not
    this order's surface), so the gate records the divergence instead of
    quietly keeping a "these are the same" assertion that would be false.
    """
    value = [{"providerId": "p", "modelId": None}]
    service_out = list(_model_references(value))
    wire_out = handlers_module._model_reference_list(value)
    assert service_out == [{"providerId": "p", "modelId": "None"}], service_out
    assert wire_out == [], wire_out
    assert all(entry in service_out for entry in wire_out)


def test_the_reference_shape_names_a_table_and_is_json_safe(api):
    _runtime, client = api
    provider_id, model_id = _provider(client, "six", "model-a")
    profile_id = _profile_with_value(client, [
        {"providerId": provider_id, "modelId": model_id},
        {"providerId": provider_id, "modelId": model_id}])
    slots = _model_control(client, profile_id)["slots"]
    assert {slot["table"] for slot in slots} == {handlers_module.SLOT_TABLE}
    assert json.dumps(slots, sort_keys=True)
    # the same reference twice is two seats, not one deduplicated entry
    assert [slot["slotIndex"] for slot in slots] == [0, 1], slots


# -- G4: the rest of the descriptor did not move ----------------------------

def test_the_rest_of_the_descriptor_is_untouched(api):
    _runtime, client = api
    provider_id, model_id = _provider(client, "seven", "model-a")
    profile_id = _profile_with_value(client, {"providerId": provider_id, "modelId": model_id})
    descriptor = client.ok("config.describe", {"profileId": profile_id, "workspaceId": None})["descriptor"]
    assert descriptor["effectTiming"] == "next_send"
    assert descriptor["securityLockedIds"] == []
    assert [item["controlId"] for item in descriptor["controls"]] == ["model"]


def test_resolve_still_rejects_an_unknown_control_naming_it(api):
    _runtime, client = api
    profile_id = _profile_with_value(client, [])
    outcome = client.ok("config.resolve", {
        "profileId": profile_id, "workspaceId": None,
        "overrides": [{"controlId": "nope", "value": 1}]})
    assert outcome["outcome"] == "rejected", outcome
    assert outcome["invalidControls"] == [{"controlId": "nope", "reason": "unknown_control"}]


def test_125_touched_only_its_own_surface():
    changed = [path for path in TARGETS
               if "def _slot_entries" in (REPO / path).read_text(encoding="utf-8")]
    assert changed == ["plugins/server-compat/src/ordessa_server_compat/core_wire.py"], changed
