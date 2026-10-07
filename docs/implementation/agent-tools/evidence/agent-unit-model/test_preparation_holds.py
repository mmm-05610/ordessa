"""Real SQLite reservation holds; no native process or model evidence."""
import json

import pytest

from pacthold.agents.nodes.publication import NodePublication, IDENTITIES
from pacthold.public import Environment
from ordessa_environment_api import RequestKey, IdentityMismatchError
from ordessa_environment_api.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
from ordessa_persistence_sqlite import SqliteStorePort


class Policy:
    def admit_object_access(self, *args): return True
    def admit_invoke(self, *args): return True


@pytest.fixture
def reservation(tmp_path):
    path = tmp_path / "preparation.sqlite"
    store = SqliteStorePort(path)
    env = Environment("env", store=store, policy=Policy(), principal_scope="principal")
    request = RequestKey("env", "principal", "prepare")
    provider = {"environmentNamespace": "env", "providerId": "fixed-provider", "generation": 1}
    intent = OperationIntent("prepare-operation", "prepare",
        {"environmentNamespace": "env", "profileId": "profile", "manifestRevision": 1,
         "contentDigest": "sha256:" + "b" * 64},
        {"environmentNamespace": "env"},
        (StepIntent("prepare", provider, "step-digest", "original-correlation"),),
        {"environmentNamespace": "env", "instanceId": "node", "generation": 1})
    hold = UsageMutation("provider-hold", 0, None, operation_holder(request, intent.operation_ref),
                         provider, ("use",), "active")
    cleanup = [store.close]
    yield path, store, NodePublication(env), request, intent, hold, cleanup
    for close in cleanup:
        close()


def held(store):
    return [dict(row) for row in store._conn.execute("SELECT * FROM env_usages ORDER BY usage_id")]


def test_reservation_holds_provider_before_any_dispatch(reservation):
    _, store, nodes, request, intent, hold, _ = reservation
    operation = nodes.reserve(request, "digest", intent, usages=(hold,))
    assert operation.status == "reserved"
    assert store.read_operation_step(request, "prepare") is None
    rows = held(store)
    assert len(rows) == 1 and rows[0]["revision"] == 1 and rows[0]["state"] == "active"
    assert json.loads(rows[0]["holder_ref"]) == dict(hold.holder_ref)
    assert json.loads(rows[0]["target_ref"]) == dict(hold.target_ref)


@pytest.mark.parametrize("foreign", ["holder", "target"])
def test_invalid_hold_rolls_back_operation_and_node_identity(reservation, foreign):
    _, store, nodes, request, intent, hold, _ = reservation
    holder, target = dict(hold.holder_ref), dict(hold.target_ref)
    if foreign == "holder": holder["operationRef"] = "another-operation"
    else: target["environmentNamespace"] = "other"
    invalid = UsageMutation("provider-hold", 0, None, holder, target, ("use",), "active")
    with pytest.raises(IdentityMismatchError):
        nodes.reserve(request, "digest", intent, usages=(invalid,))
    assert store.read_operation(request) is None
    assert store.read_domain("env", IDENTITIES, "node") is None
    assert held(store) == []
    assert nodes.reserve(request, "digest", intent, usages=(hold,)).status == "reserved"


def test_replay_cannot_acquire_additional_hold(reservation):
    _, store, nodes, request, intent, hold, _ = reservation
    original = nodes.reserve(request, "digest", intent, usages=(hold,))
    extra = UsageMutation("extra", 0, None, hold.holder_ref, hold.target_ref, ("use",), "active")
    assert nodes.reserve(request, "digest", intent, usages=(extra,)) == original
    assert [row["usage_id"] for row in held(store)] == ["provider-hold"]
    assert held(store)[0]["revision"] == 1


def test_unknown_and_cold_replay_retain_original_hold(reservation):
    path, store, nodes, request, intent, hold, cleanup = reservation
    nodes.reserve(request, "digest", intent, usages=(hold,))
    step = intent.steps[0]
    assert store.claim_operation_step(request, "digest", step).claimed
    store.record_operation_step(request, "digest", step.step_id, step.input_digest, 1,
                                "unknown", {"evidenceRef": "original-timeout"})
    before = held(store)
    cleanup.pop()()
    cold_store = SqliteStorePort(path)
    try:
        cold = NodePublication(Environment("env", store=cold_store, policy=Policy(), principal_scope="principal"))
        replay = cold.reserve(request, "digest", intent, usages=(hold,))
        assert replay.status == "unknown"
        assert not cold_store.claim_operation_step(request, "digest", step).claimed
        assert held(cold_store) == before
    finally:
        cold_store.close()
