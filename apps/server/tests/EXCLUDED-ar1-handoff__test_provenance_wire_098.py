"""EXCLUDED — AR-1/W-1 交接（2026-09-29）

本文件断言的语义已由新 owner 接账，内容**完整保留**（不被收集）：

  接账方：plugins/assets/model-provider/server/tests/test_next_choice_wire.py
  被测语义：provenance 与 wire 形状：返回字典用 wire 名而非 SQL 列名；@staticmethod 不得按裸名读类属性

原由 server-compat 的 model_configs writer 实现；W-1 拆除该 writer 后，
这条链路的 owner 是 model-provider adapters。保留本文件是为了让
"哪条语义去哪了"可追——不是删断言把红藏起来。
按仓库约定（docs/migration/backend-build-test.md §(d)），
`EXCLUDED-*` 前缀使其不被 pytest 收集。
"""

"""Order 098: `provenance` must survive the wire, and refusals must stay typed.

Two defects stack here, and the second is invisible from the first: the
`@staticmethod` read two class attributes by bare name (NameError -> HTTP 500),
and its return dict was keyed by *SQL column names* while the service reads wire
field names - so a fix limited to the scope bug answers 200 and silently stores
nothing. Every assertion below therefore asks about the row that comes back out
of the database, and the counter-examples show each half failing on its own.

The client is built with `raise_server_exceptions=False` on purpose: this order
is about the difference between a 500 and a typed refusal, and a test client
that re-raises server exceptions turns that difference into a Python traceback.

Running this file with `AGENT_BOX_WIRE_SCHEMA` pointed at the generated artifact
fails two cases - `update` and `probeModels` do not declare `provenance` in
their locked `#params`, though the Server accepts it. That is contract drift
(see evidence §9.2, handed to order 102), not a defect in the code under test,
so these gates assert the Server behaviour rather than the stale artifact's.
"""
from __future__ import annotations

import json

import copy

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server.transport.http import create_app
from ordessa_server_compat import core_wire as handlers_module
from test_wire_v1 import Wire, registry

PROVENANCE = {
    "baseUrl": "https://api.deepseek.com",
    "authStyle": "api_key",
    "wireApi": "chat_completions",
    "fieldsSource": "manual",
}
MODEL = {"modelId": "model-a", "displayName": "Model A",
         "availability": "unknown", "unavailableReason": None}
BODY = {"displayName": "Official API", "harness": "alpha", "provider": "opaque-provider",
        "credentialId": None, "configuration": [], "models": [MODEL]}


@pytest.fixture
def api(tmp_path):
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(harnesses=registry()))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield Wire(client, {"Authorization": f"Bearer {runtime.token}"})


def create(api, *, provenance=..., request_id="prov-create-0001"):
    params = copy.deepcopy(BODY)
    params["requestId"] = request_id
    if provenance is not ...:
        params["provenance"] = provenance
    return api.call("providerModels.create", params)


#: The four column names the handler must never hand to the service. Spelled
#: out because "the half-fix stores nothing" is only falsifiable if the test
#: says which keys would give it away.
COLUMN_KEYS = ("base_url", "auth_style", "wire_api", "fields_source")


def test_legal_provenance_is_accepted_and_read_back(api):
    """G1 + G2: 200, and the four fields come back out of the row."""
    status, body = create(api, provenance=PROVENANCE)
    assert status == 200, body
    assert "result" in body, body
    record = body["result"]["providerModel"]
    assert record["provenance"] == PROVENANCE


def test_the_record_is_read_back_from_the_database_not_echoed_from_the_request(api):
    """G2's real bite: a second query, so a handler that keyed its body by
    column names (the half-fix) cannot pass by getting the request handed back.

    `service.create` returns `project(records.get(id))`, so even the create
    response is a read; this asks the question through a *separate* call, which
    is what a client that lists its providers actually does.
    """
    status, body = create(api, provenance=PROVENANCE)
    assert status == 200, body
    listed = api.ok("providerModels.list", {"includeArchived": False})
    assert [item["provenance"] for item in listed["items"]] == [PROVENANCE]


def test_update_writes_the_given_field_and_keeps_the_absent_ones(api):
    """`update` takes one field at a time; absence must not erase what is there."""
    _status, body = create(api, provenance=PROVENANCE, request_id="prov-create-0002")
    record = body["result"]["providerModel"]
    updated = api.ok("providerModels.update", {
        "requestId": "prov-update-0001", "providerModelId": record["id"],
        "expectedVersion": record["version"], "displayName": "Official API",
        "credentialId": None, "configuration": [], "models": [MODEL],
        "provenance": {"fieldsSource": "pulled"},
    })["providerModel"]
    assert updated["provenance"] == {**PROVENANCE, "fieldsSource": "pulled"}


def test_a_record_created_without_provenance_stays_without_provenance(api):
    """The path the order requires unchanged: absent means unknown, not a default."""
    status, body = create(api, request_id="prov-create-0003")
    assert status == 200, body
    assert body["result"]["providerModel"]["provenance"] is None


def test_unknown_provenance_field_is_a_typed_refusal_not_a_500(api):
    """G3, case 1. Before this order the NameError fired on the whitelist line
    itself, so the *refusal* path was as broken as the acceptance path."""
    status, body = create(api, provenance={"unknown": "x"}, request_id="prov-create-0004")
    assert status == 200, f"expected a typed refusal, got http={status}"
    assert body["error"]["code"] == "INVALID_REQUEST", body
    assert "unknown fields" in body["error"]["message"]


def test_value_outside_the_enum_is_a_typed_refusal_naming_the_field(api):
    """G3, case 2 - and the vocabulary itself is untouched by this order."""
    status, body = create(api, provenance={"authStyle": "telepathy"},
                          request_id="prov-create-0005")
    assert status == 200, f"expected a typed refusal, got http={status}"
    assert body["error"]["code"] == "INVALID_REQUEST", body
    assert "provenance.authStyle" in body["error"]["message"]


def test_a_provenance_that_is_not_an_object_is_refused_without_500(api):
    """The whitelist guard also answers for a non-Mapping payload."""
    status, body = create(api, provenance=["api_key"], request_id="prov-create-0006")
    assert status == 200, f"expected a typed refusal, got http={status}"
    assert body["error"]["code"] == "INVALID_REQUEST", body


def test_probe_models_with_provenance_does_not_500(api):
    """The third call site, which the order did not name: `probeModels` also
    declares `provenance` as optional and also validated it through `_provenance`.

    The base URL is a local discard port, so the probe fails honestly without
    any provider being reached - what is asserted is only that the failure is
    typed, not a 500.
    """
    status, body = api.call("providerModels.probeModels", {
        "requestId": "prov-probe-0001", "baseUrl": "http://127.0.0.1:9/v1",
        "provenance": {"authStyle": "api_key", "fieldsSource": "manual"},
    })
    assert status == 200, f"expected a typed probe outcome, got http={status}"
    assert "result" in body, body
    assert body["result"]["status"] in {"failed", "unreachable"}, body


def test_the_handler_speaks_wire_field_names_to_the_service(api):
    """The second defect, asserted on its own terms.

    `_provenance` is the only place that used to translate to columns, and the
    service never looked at those keys. This pins the direction of the contract:
    the handler validates wire vocabulary and hands wire vocabulary over.
    """
    parsed = handlers_module.CoreWireHandlers._provenance({"provenance": dict(PROVENANCE)})
    assert parsed == PROVENANCE
    assert not set(parsed) & set(COLUMN_KEYS), parsed


def test_counter_example_the_scope_bug_returns_the_500(api, monkeypatch):
    """The gate must bite on the original defect: restore a `_provenance` that
    reads the constants by bare name inside a `@staticmethod`, and the same call
    that now answers 200 has to fall back to 500.

    Nothing on disk changes; the attribute is put back by `monkeypatch`, and the
    restoration is asserted rather than assumed.
    """
    original = handlers_module.CoreWireHandlers._provenance

    def broken(params):
        raw = params.get("provenance")
        if raw is None:
            return None
        # Bare name, exactly as at the baseline. The name is undefined at module
        # scope because it is a class attribute - which is the whole defect.
        if not set(raw) <= set(_PROVENANCE_COLUMNS):  # noqa: F821  (deliberate)
            raise handlers_module.WireError("INVALID_REQUEST", "provenance carries unknown fields")
        return dict(raw)

    monkeypatch.setattr(handlers_module.CoreWireHandlers, "_provenance", staticmethod(broken))
    status, text = _raw_create(api, {"authStyle": "api_key"}, "prov-counter-01")
    # Superseded by order 115, which closed the family this defect used to escape
    # through: a `NameError` inside a handler can no longer leave as a bare 500.
    # The gate still bites, one level honest - the request must not succeed, and
    # the crash has to be named in the body rather than hidden behind a status.
    assert status == 200, f"unexpected transport failure: http={status} {text!r}"
    body = json.loads(text)
    assert "error" in body, body
    assert body["error"]["code"] == "UNAVAILABLE", body
    assert body["error"]["details"]["internalCode"] == "NameError", body
    assert "authStyle" not in text or body["error"]["code"] == "UNAVAILABLE", text

    monkeypatch.undo()
    assert handlers_module.CoreWireHandlers._provenance == original
    #: Same request, same client, only the patch removed - so the failure above
    #: is attributed to the defect and not to the payload.
    fixed_status, fixed_text = _raw_create(api, {"authStyle": "api_key"}, "prov-counter-01b")
    assert fixed_status == 200, fixed_status
    assert "result" in json.loads(fixed_text), fixed_text


def _raw_create(api, provenance, request_id):
    """POST past the shared helper, which asserts a JSON-RPC envelope.

    A real 500 answers `Internal Server Error` as plain text, so the helper's
    own `response.json()` would raise before this test could state the defect.
    """
    params = copy.deepcopy(BODY)
    params.update({"requestId": request_id, "provenance": provenance})
    response = api.client.post(
        "/wire/v1/providerModels.create", headers=api.headers,
        json={"jsonrpc": "2.0", "id": request_id,
              "method": "providerModels.create", "params": params},
    )
    return response.status_code, response.text


def test_counter_example_the_half_fix_stores_nothing(api, monkeypatch):
    """And it must bite on the tempting one-line fix.

    Repairing only the scope bug yields a 200 whose provenance is empty: a gate
    that checked the status code alone would call that green. This is the
    counter-example that makes the read-back assertions worth having.
    """
    original = handlers_module.CoreWireHandlers._provenance
    to_column = dict(zip(("baseUrl", "authStyle", "wireApi", "fieldsSource"), COLUMN_KEYS))

    def column_keyed(cls, params):
        parsed = original.__func__(cls, params)
        if parsed is None:
            return None
        return {to_column[field]: value for field, value in parsed.items()}

    monkeypatch.setattr(handlers_module.CoreWireHandlers, "_provenance",
                        classmethod(column_keyed))
    status, body = create(api, provenance=PROVENANCE, request_id="prov-counter-02")
    assert status == 200, body
    assert body["result"]["providerModel"]["provenance"] is None, (
        "the half-fix was supposed to lose the data; if this is not None the "
        "read-back assertions below are not doing their job")
    monkeypatch.undo()
    assert handlers_module.CoreWireHandlers._provenance == original
