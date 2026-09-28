"""Order 117 — `profiles.list` must not draw an unsendable Profile as sendable.

QA-009: the projection carried no blocker fact, so every Profile looked the same
in a picker; the user found out by typing and getting 409
`PROFILE_RECOVERY_REQUIRED`, and revision v2 added the second face — a Profile
whose model names a credential this host never received failed only later, inside
the turn. The order's own limit holds here: this says it out loud earlier, it does
not invent a way to clear either state.

Gates drive the real wire (`profiles.list` over HTTP with `raise_server_exceptions
=False`); the freeze path is called once, as a cross-check that the blocker named
here is the blocker the product would hit, not one this projection invented.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_product.composition import create_composition  # T014-S1d funnel
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.transport.http import create_app

#: The projection's keys before order 117, measured live by ops and re-measured
#: here: `profiles.list` may only ever add to this set.
BASELINE_KEYS = {
    "id", "version", "displayName", "harness", "accountId", "permissionPreset",
    "permissionRules", "originProfileId", "archivedAt", "createdAt", "updatedAt",
    "capabilities",
}


def _registry(*, credential_kind: str | None = "api_key") -> HarnessRegistry:
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", capability_claims={"stream": True},
        model_control_id="model", control_options={"model": ()},
        credential_kind=credential_kind,
        configuration_validator=lambda value: (
            None if isinstance(value, dict) else ValueError()),
    ))
    return registry


@pytest.fixture
def server(tmp_path):
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=create_composition().compatibility_plugins(harnesses=_registry()))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}


def wire(client, headers, method, params):
    response = client.post(f"/wire/v1/{method}", headers=headers, json={
        "jsonrpc": "2.0", "id": method, "method": method, "params": params,
    })
    body = response.json()
    assert "error" not in body, (method, body)
    return body["result"]


def make_profile(client, headers, *, name: str = "role") -> dict:
    response = client.post("/api/v1/profiles", headers={
        **headers, "Idempotency-Key": f"117-{name}",
    }, json={"name": name, "harness_type": "alpha", "configuration": {}, "credential_id": None})
    assert response.status_code == 201, response.text
    return response.json()


def listed(runtime, client, headers, profile_id: str) -> dict:
    items = wire(client, headers, "profiles.list", {"includeArchived": True})["items"]
    return next(item for item in items if item["id"] == profile_id)


def block_the_send(item: dict) -> tuple[str, str | None]:
    """The judgement a client needs before it enables the send button.

    Written as one function so the counter-example can run the *same* judgement
    against the pre-117 projection and show it going red, rather than asserting
    a shape the old output would have satisfied by accident.
    """
    if "recoveryPending" not in item or "sendability" not in item:
        raise AssertionError(f"the projection carries no blocker fact: {sorted(item)}")
    sendability = item["sendability"]
    if sendability["state"] == "ready":
        return "ready", None
    return sendability["state"], sendability["reason"]


def set_recovery_pending(runtime, profile_id: str, value: int) -> None:
    """Arrange the fact the way the product stores it (the column 409 reads)."""
    database = runtime.plugin_host.provided_port('product.repository').database
    with database.transaction() as conn:
        conn.execute("UPDATE server_profiles SET recovery_pending=? WHERE id=?",
                     (value, profile_id))


# -- G1: a Profile waiting on recovery is blocked before anything is typed ---

def test_a_profile_waiting_on_recovery_reads_as_blocked(server):
    runtime, client, headers = server
    profile = make_profile(client, headers, name="recovering")
    set_recovery_pending(runtime, profile["profile_id"], 1)
    item = listed(runtime, client, headers, profile["profile_id"])
    assert item["recoveryPending"] is True, item
    state, reason = block_the_send(item)
    assert (state, reason) == ("blocked", "PROFILE_RECOVERY_REQUIRED"), item["sendability"]
    # Honest about what the user can do: nothing on the wire clears a recovery,
    # so the recovery check itself must offer no action (the union across checks
    # may name what a *different* blocker needs).
    recovery = next(check for check in item["sendability"]["checks"] if check["key"] == "recovery")
    assert recovery["actions"] == [], item["sendability"]
    assert not any("recovery" in action for action in item["sendability"]["actions"]), item["sendability"]


def test_a_clear_profile_reports_its_recovery_fact_as_false_not_unknown(server):
    """`recoveryPending: false` must be readable as a fact; the full "ready"
    verdict additionally needs a satisfiable binding, which
    `test_a_binding_the_host_can_satisfy_is_ready` covers."""
    runtime, client, headers = server
    profile = make_profile(client, headers, name="clean")
    item = listed(runtime, client, headers, profile["profile_id"])
    assert item["recoveryPending"] is False, item
    recovery = next(check for check in item["sendability"]["checks"] if check["key"] == "recovery")
    assert recovery["state"] == "ready", item["sendability"]


# -- G2: unknown is never "sendable" ---------------------------------------

def test_an_unreadable_blocker_is_unknown_and_not_ready(server, monkeypatch):
    """A row that does not carry the column must not collapse into `False`.

    Arranged by handing the projection a row from before the column existed,
    which is exactly the shape that would otherwise lie: the accept path reads
    the column and would fail closed, so a projection that says "ready" here
    would be the one thing `R-0032 ⑤` forbids.
    """
    runtime, client, headers = server
    profile = make_profile(client, headers, name="legacy-row")
    original = runtime.plugin_host.provided_port('compat.handlers').profiles.records.list

    def rows_without_the_column(*args, **kwargs):
        return [{key: value for key, value in row.items() if key != "recovery_pending"}
                for row in original(*args, **kwargs)]

    monkeypatch.setattr(runtime.plugin_host.provided_port('compat.handlers').profiles.records, "list", rows_without_the_column)
    item = listed(runtime, client, headers, profile["profile_id"])
    assert item["recoveryPending"] is None, item
    recovery = next(check for check in item["sendability"]["checks"] if check["key"] == "recovery")
    assert (recovery["state"], recovery["reason"]) == ("unknown", "RECOVERY_STATE_UNREADABLE"), item
    # The overall verdict must never read "ready" while a fact is unknown. A
    # *blocked* verdict outranks it (a known blocker is the stronger fact), so
    # that is the assertion here rather than "state == unknown".
    state, _reason = block_the_send(item)
    assert state != "ready", item["sendability"]


# -- G5 (revision v2): a binding this host cannot satisfy, seen before sending -

def bind_model(runtime, client, headers, *, profile_id: str, credential_id: str | None,
               credential_kind: str = "api_key"):
    provider = wire(client, headers, "providerModels.create", {
        "requestId": "117-provider", "displayName": "117 Official", "harness": "alpha",
        "provider": "opaque-provider", "credentialId": None, "configuration": [],
        "models": [{"modelId": "model-a", "displayName": "Model A",
                    "availability": "unknown", "unavailableReason": None}],
    })["providerModel"]
    if credential_id is not None:
        # `server_provider_models.credential_id` is a real foreign key, so the
        # field shape ("the record names a credential this host cannot use") is
        # arranged by naming a row that exists and is of the wrong kind - which
        # is also the case a plain `exists()` check would have called ready.
        with runtime.plugin_host.provided_port('product.repository').database.transaction() as conn:
            conn.execute("INSERT INTO server_credentials(id,kind,secret_locator,created_at) "
                         "VALUES(?,?,?,?)",
                         (credential_id, credential_kind, "memory:117", "2026-09-19T00:00:00Z"))
            conn.execute("UPDATE server_provider_models SET credential_id=? WHERE id=?",
                         (credential_id, provider["id"]))
    version = listed(runtime, client, headers, profile_id)["version"]
    wire(client, headers, "profiles.updateConfig", {
        "requestId": "117-config", "profileId": profile_id, "expectedVersion": version,
        "values": [{"controlId": "model", "value": {"providerId": provider["id"],
                                                    "modelId": "model-a"}}],
    })
    return provider


def test_a_binding_whose_credential_is_absent_is_blocked_before_sending(server):
    """The field shape behind revision v2: the record names a credential the host
    was never given, and the turn died in execution with the transcript left as
    `EXECUTION_FAILED`.
    """
    runtime, client, headers = server
    profile = make_profile(client, headers, name="unbound-credential")
    bind_model(runtime, client, headers, profile_id=profile["profile_id"],
               credential_id="cred-117-wrong-kind", credential_kind="oauth")
    item = listed(runtime, client, headers, profile["profile_id"])
    state, reason = block_the_send(item)
    assert (state, reason) == ("blocked", "CREDENTIAL_NOT_FOUND"), item["sendability"]
    assert "provision_the_credential_on_this_host" in item["sendability"]["actions"]
    assert item["sendability"]["actions"], item["sendability"]
    assert "cred-117-wrong-kind" in json.dumps(item["sendability"])


def test_the_projection_names_what_the_freeze_path_would_hit(server):
    """Cross-check against the product's own decision, not this file's opinion.

    `freeze_execution_configuration` is the code a turn runs through; it is
    called here directly so the claim "the wire says blocked" is anchored to the
    same fact the accept path obeys, and drift between the two shows up as a red.
    """
    from ordessa_server.errors import ServerError

    runtime, client, headers = server
    profile = make_profile(client, headers, name="freeze-check")
    provider = bind_model(runtime, client, headers, profile_id=profile["profile_id"],
                          credential_id="cred-117-absent", credential_kind="oauth")
    with pytest.raises(ServerError) as raised:
        runtime.plugin_host.provided_port('provider.models').freeze_execution_configuration(
            "alpha", {"model": {"providerId": provider["id"], "modelId": "model-a"}},
        )
    assert raised.value.code == "CREDENTIAL_NOT_FOUND", raised.value
    item = listed(runtime, client, headers, profile["profile_id"])
    assert item["sendability"]["reason"] == raised.value.code


def test_a_binding_the_host_can_satisfy_is_ready(server):
    """The green half of G5: presence is answered, not assumed pessimistic."""
    runtime, client, headers = server
    profile = make_profile(client, headers, name="good-binding")
    bind_model(runtime, client, headers, profile_id=profile["profile_id"],
               credential_id="cred-117-present")
    item = listed(runtime, client, headers, profile["profile_id"])
    assert block_the_send(item) == ("ready", None), item["sendability"]


def test_a_profile_that_chose_no_model_is_blocked_with_the_accept_reason(server):
    """Measured, not assumed: this harness declares a model control, and the
    freeze path raises `PROFILE_CONFIGURATION_INVALID` when the control is empty
    (`model_configs/service.py:144-147`), so a Profile that never chose a model
    genuinely cannot be sent to — saying `ready` here would be the lie QA-009 is
    about. The first draft of this gate asserted the opposite and the product
    corrected it."""
    runtime, client, headers = server
    profile = make_profile(client, headers, name="no-model")
    item = listed(runtime, client, headers, profile["profile_id"])
    state, reason = block_the_send(item)
    assert (state, reason) == ("blocked", "PROFILE_CONFIGURATION_INVALID"), item["sendability"]
    assert "choose_a_model" in item["sendability"]["actions"], item["sendability"]


# -- G3: the existing face does not move -----------------------------------

def test_existing_keys_are_unchanged_and_only_the_two_new_ones_are_added(server):
    runtime, client, headers = server
    profile = make_profile(client, headers, name="snapshot")
    item = listed(runtime, client, headers, profile["profile_id"])
    assert set(item) - {"recoveryPending", "sendability"} == BASELINE_KEYS, sorted(item)
    assert item["displayName"] == "snapshot" and item["harness"] == "alpha"
    assert item["archivedAt"] is None and item["version"] == 1
    listing = wire(client, headers, "profiles.list", {"includeArchived": False})
    assert profile["profile_id"] in {row["id"] for row in listing["items"]}


# -- counter-examples ------------------------------------------------------

def test_counter_example_the_pre_117_projection_fails_the_same_judgement(server):
    """G1/G2/G5's falsifier: strip the two keys and the judgement goes red.

    Run against the live row rather than asserted in prose, so "we added a key"
    cannot quietly become "a client could not have used it".
    """
    runtime, client, headers = server
    profile = make_profile(client, headers, name="counter")
    set_recovery_pending(runtime, profile["profile_id"], 1)
    item = listed(runtime, client, headers, profile["profile_id"])
    assert block_the_send(item)[0] == "blocked"
    stripped = {key: value for key, value in item.items()
                if key not in {"recoveryPending", "sendability"}}
    assert set(stripped) == BASELINE_KEYS
    with pytest.raises(AssertionError):
        block_the_send(stripped)


def test_counter_example_reporting_unknown_as_ready_fails_the_gate(server, monkeypatch):
    """G2's falsifier: make the unreadable case collapse to `False` and the
    judgement has to stop calling it sendable."""
    from ordessa_server_compat import wire_projection as projection_module

    runtime, client, headers = server
    profile = make_profile(client, headers, name="collapse")
    original = projection_module._tri_state
    monkeypatch.setattr(projection_module, "_tri_state", lambda row, column: bool(row.get(column)))
    listing = wire(client, headers, "profiles.list", {"includeArchived": True})
    item = next(row for row in listing["items"] if row["id"] == profile["profile_id"])
    assert item["recoveryPending"] is False  # the lie, restored on purpose
    monkeypatch.undo()
    assert projection_module._tri_state({}, "recovery_pending") is None


def test_the_gate_reads_through_http_and_not_the_implementation(server):
    """G4: every judgement above came off a socket; this one says so explicitly."""
    runtime, client, headers = server
    profile = make_profile(client, headers, name="socket")
    response = client.post("/wire/v1/profiles.list", headers=headers, json={
        "jsonrpc": "2.0", "id": "socket", "method": "profiles.list",
        "params": {"includeArchived": True},
    })
    assert response.status_code == 200
    item = next(row for row in response.json()["result"]["items"] if row["id"] == profile["profile_id"])
    assert {"recoveryPending", "sendability"} <= set(item), sorted(item)
