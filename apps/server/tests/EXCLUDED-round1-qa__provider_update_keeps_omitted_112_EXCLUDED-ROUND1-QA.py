"""Order 112: omission keeps, an explicit null clears - and the two must not be
the same request.

The ticket's stated defect ("omitted fields get written empty") is not what this
tree does: `COALESCE` already kept un-named provenance columns verbatim. What
was actually broken is the other direction - a client that *did* ask to forget
an endpoint fact got 200 and an untouched row, because both the handler
(`if value is None: continue`) and the SQL (`COALESCE(?,col)`) read "null" as
"absent". Every gate below therefore pins one of the two intents against the
other: keep happens when the name is missing, clearing happens when it is
present and null, and a field that may not be emptied still refuses in words.

`configuration`/`models` cannot be omitted on the wire at all - they are in
`providerModels.update`'s required set, and shrinking that set is a contract
change plus a relock (order 113's family), not this order's G4-permitted edit.
The same "omission keeps" rule is asserted one layer down instead, against
`ProviderModelService.update`, which is where an internal caller expresses it.
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server.model_configs.repository import KEEP
from ordessa_server.model_configs import repository as repository_module
from ordessa_server.transport.http import create_app
from ordessa_server.wire import handlers as handlers_module
from test_wire_v1 import Wire, registry

PROVENANCE = {
    "baseUrl": "https://api.deepseek.com",
    "authStyle": "api_key",
    "wireApi": "chat_completions",
    "fieldsSource": "manual",
}
MODEL = {"modelId": "model-a", "displayName": "Model A",
         "availability": "unknown", "unavailableReason": None}
OTHER = {"modelId": "model-b", "displayName": "Model B",
         "availability": "unknown", "unavailableReason": None}
BODY = {"displayName": "Official API", "harness": "alpha", "provider": "opaque-provider",
        "credentialId": None, "configuration": [], "models": [MODEL]}

#: The registered contract copy (order 113 moved it out of `generated/` and named
#: it for its own digest). Read for one thing only: which columns are nullable.
ARTIFACT = (pathlib.Path(__file__).resolve().parents[3]
            / "docs/server-round1/fullstack/contract"
            / "wire-v1.schema.registered-b1eb4762.json")


@pytest.fixture
def api(tmp_path):
    runtime = build_runtime(tmp_path / "data", harnesses=registry())
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield Wire(client, {"Authorization": f"Bearer {runtime.token}"})


def create(api, *, request_id="o112-create-0001", provenance=PROVENANCE):
    params = dict(copy.deepcopy(BODY), requestId=request_id)
    if provenance is not ...:
        params["provenance"] = provenance
    return api.ok("providerModels.create", params)["providerModel"]


def update(api, record, *, request_id, version=None, **changes):
    params = dict(
        copy.deepcopy(BODY), requestId=request_id,
        providerModelId=record["id"],
        expectedVersion=record["version"] if version is None else version,
    )
    params.pop("harness")
    params.pop("provider")
    params.update(changes)
    return params


def stored(api, record_id):
    """Read the row back through a *different* call than the write's reply."""
    listing = api.ok("providerModels.list", {"includeArchived": False})
    for item in listing["items"]:
        if item["id"] == record_id:
            return item
    raise AssertionError("record vanished from providerModels.list")


# -- G1 省略即保留 ---------------------------------------------------------

def test_omitting_provenance_keeps_every_column_verbatim(api):
    record = create(api)
    reply = api.ok("providerModels.update", update(api, record, request_id="o112-keep-all"))
    assert reply["providerModel"]["provenance"] == PROVENANCE
    assert stored(api, record["id"])["provenance"] == PROVENANCE


def test_a_partial_provenance_keeps_the_fields_it_did_not_name(api):
    record = create(api)
    moved = api.ok(
        "providerModels.update",
        update(api, record, request_id="o112-partial",
               provenance={"baseUrl": "https://moved.example"}),
    )["providerModel"]
    assert moved["provenance"] == dict(PROVENANCE, baseUrl="https://moved.example")


def test_an_empty_provenance_object_keeps_everything(api):
    """`{}` names no field, so it must clear nothing. The shape rule and the
    keep rule meet here: an empty mapping is a valid request, not a no-op bug."""
    record = create(api)
    reply = api.ok("providerModels.update",
                   update(api, record, request_id="o112-empty-map", provenance={}))
    assert reply["providerModel"]["provenance"] == PROVENANCE


def test_the_service_keeps_every_field_its_body_omits(api, tmp_path):
    """The ticket's "only displayName" case, asserted one layer down where it is
    expressible: before this order `update()` read `body["configuration"]` and
    died with a `KeyError`, which is an unhandled-exception shape, not a rule."""
    runtime = build_runtime(tmp_path / "svc", harnesses=registry())
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        wired = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        record = create(wired)
        kept = runtime.plugin_host.provided_port('provider.models').update(
            record["id"], record["version"], "o112-service-0001",
            {"displayName": "Renamed only"},
        )
    assert kept["displayName"] == "Renamed only"
    assert kept["models"] == [MODEL]
    assert kept["credentialId"] is None
    assert kept["provenance"] == PROVENANCE
    assert kept["version"] == record["version"] + 1


# -- G2 显式即清空 ---------------------------------------------------------

@pytest.mark.parametrize("nulls,expected", [
    ({"baseUrl": None, "authStyle": None, "wireApi": None, "fieldsSource": None}, None),
    ({"baseUrl": None}, dict(PROVENANCE, baseUrl=None)),
    ({"fieldsSource": None}, dict(PROVENANCE, fieldsSource=None)),
])
def test_an_explicit_null_clears_only_the_field_it_names(api, nulls, expected):
    record = create(api)
    reply = api.ok("providerModels.update",
                   update(api, record, request_id="o112-n-" + next(iter(nulls)),
                          provenance=nulls))["providerModel"]
    assert reply["provenance"] == expected
    # ...and it is the row that changed, not the echo.
    assert stored(api, record["id"])["provenance"] == expected


def test_clearing_all_four_reads_back_as_unknown_not_as_a_guessed_default(api):
    record = create(api)
    api.ok("providerModels.update", update(
        api, record, request_id="o112-clear",
        provenance={key: None for key in PROVENANCE}))
    row = stored(api, record["id"])
    assert row["provenance"] is None
    assert row["displayName"] == BODY["displayName"]  # the rest survived


def test_keep_and_clear_happen_in_the_same_request(api):
    """One request, both intents: clear `wireApi`, rewrite `authStyle`, leave the
    other two alone. Only possible if the two states are distinguishable."""
    record = create(api)
    reply = api.ok("providerModels.update", update(
        api, record, request_id="o112-both",
        provenance={"wireApi": None, "authStyle": "oauth"}))["providerModel"]
    assert reply["provenance"] == dict(
        PROVENANCE, wireApi=None, authStyle="oauth")


# -- G2b 不允许清空者仍然说得出话 -----------------------------------------

def test_display_name_still_refuses_null_rather_than_keeping_quietly(api):
    record = create(api)
    error = api.err("providerModels.update",
                    update(api, record, request_id="o112-display-null", displayName=None))
    assert error["code"] == "INVALID_REQUEST"


def test_models_refuse_to_be_emptied(api):
    """`models: []` is an explicit value, and the protocol refuses it; the point
    of pinning it is that 112 must not turn "explicit" into "silently ignored"."""
    record = create(api)
    error = api.err("providerModels.update",
                    update(api, record, request_id="o112-empty-models", models=[]))
    assert error["code"] == "INVALID_REQUEST"


def test_configuration_may_be_emptied_on_purpose(api):
    record = create(api, provenance=PROVENANCE)
    reply = api.ok("providerModels.update", update(
        api, record, request_id="o112-cfg",
        configuration=[{"controlId": "model",
                        "value": {"providerId": record["id"], "modelId": "model-a"}}],
    ))["providerModel"]
    assert len(reply["configuration"]) == 1
    emptied = api.ok("providerModels.update",
                     update(api, reply, request_id="o112-cfg2", configuration=[]))
    assert emptied["providerModel"]["configuration"] == []
    assert emptied["providerModel"]["provenance"] == PROVENANCE


# -- G3 不退化 ------------------------------------------------------------

def test_a_stale_expected_version_is_still_a_typed_conflict(api):
    record = create(api)
    api.ok("providerModels.update", update(api, record, request_id="o112-version-a"))
    error = api.err("providerModels.update", update(
        api, record, request_id="o112-version-b", version=record["version"]))
    assert error["code"] == "CONFLICT_VERSION"
    assert error["current"]["provenance"] == PROVENANCE


def test_replaying_one_request_id_does_not_bump_the_version_twice(api):
    record = create(api)
    params = update(api, record, request_id="o112-replay",
                    provenance={"baseUrl": None})
    first = api.ok("providerModels.update", params)["providerModel"]
    replay = api.ok("providerModels.update", params)["providerModel"]
    assert replay["version"] == first["version"]
    assert replay["provenance"] == dict(PROVENANCE, baseUrl=None)


def test_illegal_provenance_values_stay_typed_refusals(api):
    """098's rules, unchanged: the only thing 112 added is the `null` branch."""
    record = create(api)
    for bad in ({"authStyle": "magic"}, {"baseUrl": "https://x" * 600}):
        error = api.err("providerModels.update",
                        update(api, record, request_id="o112-bad", provenance=bad))
        assert error["code"] == "INVALID_REQUEST"


def test_create_is_neutral_to_the_null_change(api):
    """`create` must not shift under this order: writing NULL over a
    NULL-defaulted column is the same row, so the projection is identical."""
    mixed = api.ok("providerModels.create", dict(
        copy.deepcopy(BODY), requestId="o112-create-nullmix",
        provenance={"baseUrl": None, "authStyle": "api_key"}))["providerModel"]
    assert mixed["provenance"] == {
        "baseUrl": None, "authStyle": "api_key",
        "wireApi": None, "fieldsSource": None}


# -- 修订 v2 的逐字段登记：可空性由合同决定，不是由实现决定 ----------------

#: Read from the locked contract (`providerModels.update#params.properties`),
#: and asserted against it below - so the table cannot quietly disagree with the
#: artifact it claims to describe.
NULLABLE_PER_CONTRACT = {
    "credentialId": True,     # anyOf [string, null]
    "displayName": False,     # string
    "configuration": False,   # array
    "models": False,          # array
}

#: A divergence, named rather than smoothed over: the contract puts no length
#: bound on `models`, while the Server refuses an empty list. It is still honest
#: (a typed refusal, never a silent keep), which is the test R-0032 ⑤ sets.
CONTRACT_ALLOWS_EMPTY_BUT_SERVER_REFUSES = ("models",)


def _credential_capable_registry():
    """`registry()`'s alpha declares no `credential_kind`, so the service refuses
    any binding on it - which is why the unbind leg below needs its own harness."""
    from ordessa_server.execution import HarnessDescriptor, HarnessRegistry

    reg = HarnessRegistry()
    reg.register(HarnessDescriptor(
        "alpha", credential_kind="api-key", capability_claims={"stream": True},
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
    ))
    return reg


def test_the_contract_nullable_column_really_unbinds(tmp_path):
    """The revision's other half: `credentialId` is `anyOf [string, null]` in the
    contract, so a null means *detach this* - and it must actually detach, and an
    omitted `credentialId` at the service layer must leave it attached."""
    from ordessa_server.credentials import CredentialRecords

    runtime = build_runtime(tmp_path / "cred", harnesses=_credential_capable_registry())
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        # the database file exists only after the app's lifespan opens it
        CredentialRecords(runtime.database).register("cred-o112", "api-key", "/locator/never-read")
        api = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        params = dict(copy.deepcopy(BODY), requestId="o112-cred-create",
                      credentialId="cred-o112", provenance=PROVENANCE)
        bound = api.ok("providerModels.create", params)["providerModel"]
        assert bound["credentialId"] == "cred-o112"

        detached = api.ok("providerModels.update", update(
            api, bound, request_id="o112-cred-null", credentialId=None))["providerModel"]
        assert detached["credentialId"] is None

        kept = runtime.plugin_host.provided_port('provider.models').update(
            detached["id"], detached["version"], "o112-cred-keep",
            {"displayName": "只改名字，凭据保持"},
        )
        assert kept["displayName"] == "只改名字，凭据保持"
    # re-attach and omit the column on the wire: the required set refuses by name
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        api = Wire(client, {"Authorization": f"Bearer {runtime.token}"})
        again = api.ok("providerModels.update", update(
            api, kept, request_id="o112-cred-reattach", credentialId="cred-o112"))["providerModel"]
        params = update(api, again, request_id="o112-cred-omit")
        params.pop("credentialId")
        error = api.err("providerModels.update", params)
        assert error["code"] == "INVALID_REQUEST" and "credentialId" in error["message"]
        assert again["credentialId"] == "cred-o112"


def test_the_three_non_nullable_columns_refuse_null_by_name(api):
    """`displayName`/`configuration`/`models` are not nullable in the contract,
    so a null has to be answered with the field's own name - not a silent keep."""
    record = create(api)
    for field in ("displayName", "configuration", "models"):
        error = api.err("providerModels.update",
                        update(api, record, request_id="o112-null-" + field, **{field: None}))
        assert error["code"] == "INVALID_REQUEST", (field, error)
        assert field in error["message"], (field, error)


def _contract_update_properties():
    schema = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    return schema["providerModels.update#params"]["properties"]


def test_the_nullability_table_is_read_from_the_contract_and_not_typed_in():
    """The table above claims which columns are nullable; this checks the claim
    against the artifact, so a relock that changes nullability turns this red
    instead of letting a behavior claim quietly age into an assumption."""
    properties = _contract_update_properties()
    derived = {
        field: any(item.get("type") == "null" for item in schema.get("anyOf", []))
        for field, schema in properties.items()
    }
    assert derived.keys() == set(properties), "every column must be accounted for"
    assert NULLABLE_PER_CONTRACT == {
        field: nullable for field, nullable in derived.items()
        if field in NULLABLE_PER_CONTRACT
    }, (NULLABLE_PER_CONTRACT, derived)
    # and the columns this file reasons about are exactly the ones update accepts
    # `provenance` is excluded by name: it is the Order 112 provenance *object*,
    # not a column, so it has no row in the nullability table above. LNX-002
    # declared it in the contract at the generation source because the Server's
    # own `_PARAM_SHAPES["providerModels.update"]` already accepts it (pinned by
    # `test_the_locked_param_shape_for_update_is_untouched` below) — excluding it
    # here keeps the column claim exact instead of widening it to hide the change.
    assert set(properties) - {"provenance"} == {
        "requestId", "providerModelId", "expectedVersion", "displayName",
        "credentialId", "configuration", "models"}


@pytest.mark.parametrize("field", CONTRACT_ALLOWS_EMPTY_BUT_SERVER_REFUSES)
def test_an_empty_list_the_contract_allows_is_still_a_typed_refusal(api, field):
    """Registered as a divergence, not fixed here: refusing an empty model list
    is stricter than the contract, but it speaks - which is what AQ-0007 is about."""
    schema = _contract_update_properties()[field]
    assert "minItems" not in schema, "the contract grew a bound; re-read this gate"
    record = create(api)
    error = api.err("providerModels.update",
                    update(api, record, request_id="o112-empty-" + field, **{field: []}))
    assert error["code"] == "INVALID_REQUEST"


def test_the_locked_param_shape_for_update_is_untouched():
    required, optional = handlers_module._PARAM_SHAPES["providerModels.update"]
    assert required == {
        "requestId", "providerModelId", "expectedVersion", "displayName",
        "credentialId", "configuration", "models"}
    assert optional == {"provenance"}


@pytest.mark.parametrize("field", ["displayName", "credentialId", "configuration", "models"])
def test_omitting_a_required_field_is_still_a_typed_shape_refusal(api, field):
    """The honest face of "partial update is not expressible on this contract":
    it refuses by name instead of guessing. Loosening this is a contract change
    plus a relock (handed to 113), not a side effect of 112."""
    record = create(api)
    params = update(api, record, request_id="o112-shape-" + field)
    params.pop(field)
    error = api.err("providerModels.update", params)
    assert error["code"] == "INVALID_REQUEST"
    assert field in error["message"]


# -- 反例：两个吞 null 的位置，各自被一条断言逮住 --------------------------

def test_the_handler_that_drops_nulls_would_swallow_the_clear(api, monkeypatch):
    """Counter-example, executed: put 098's `if value is None: continue` back and
    the same request answers 200 with the old fact still in the row - the exact
    behavior this order exists to remove."""
    original = handlers_module.WireService._provenance

    def dropping(cls, params):
        parsed = original.__func__(cls, params)
        if parsed is None:
            return None
        return {key: value for key, value in parsed.items() if value is not None}

    monkeypatch.setattr(handlers_module.WireService, "_provenance",
                        classmethod(dropping))
    record = create(api)
    reply = api.ok("providerModels.update", update(
        api, record, request_id="o112-counter-handler",
        provenance={key: None for key in PROVENANCE}))["providerModel"]
    assert reply["provenance"] == PROVENANCE  # swallowed: the bug, reproduced


def test_a_none_default_in_the_repository_would_make_clear_and_keep_identical():
    """Counter-example in the other layer: with `None` as the parameter default
    (the old `COALESCE` shape) the repository cannot tell the two intents apart,
    so this signature pin is what keeps the fix from rotting back."""
    parameters = inspect.signature(repository_module.ProviderModelRecords.update).parameters
    for column in repository_module.PROVENANCE_COLUMNS:
        assert parameters[column].default is KEEP
    source = inspect.getsource(repository_module.ProviderModelRecords.update)
    assert "COALESCE" not in source


def test_the_keep_sentinel_is_not_none():
    """If `KEEP` were ever aliased to `None`, G1 and G2 collapse into each other
    and every gate above still passes. This one would not."""
    assert KEEP is not None
    assert repr(KEEP) == "<KEEP>"
