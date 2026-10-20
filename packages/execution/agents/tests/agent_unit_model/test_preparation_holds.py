"""Real SQLite reservation holds; no native process or model evidence."""
import json

import pytest

from ordessa_units.bindings.publication import NodePublication, IDENTITIES
from pacthold.public import Environment, InstallationRecord
from agent_tools_fixtures.node_publication import Provider
from ordessa_execution_agents.harness.providers.registry.contributions import AgentContributionSet
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitIdentityMismatch, UnitAdmissionRefused
from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from pacthold.adapters.sqlite.environment.store import SqliteStorePort




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

class Policy:
    def admit_object_access(self, *args): return True
    def admit_invoke(self, *args): return True


@pytest.fixture
def reservation(tmp_path):
    path = tmp_path / "preparation.sqlite"
    store = SqliteStorePort(path)
    env = Environment("env", store=store, policy=Policy(), principal_scope="principal", resource_extension_snapshot=_test_resource_snapshot)
    # Register a real RuntimeProvider activation so the reservation pin is the
    # provider_ref the Environment actually admitted. publication.py refuses
    # intents whose pinned_provider_ref is not an admitted contribution.
    env.install(InstallationRecord("fixture.plugin", "a" * 64))
    env.enable("fixture.plugin")
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    provider = env.agent_runtime_contribution(Provider.descriptor.definition_ref).provider_ref
    request = RequestKey("env", "principal", "prepare")
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
    with pytest.raises(UnitIdentityMismatch):
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
        cold = NodePublication(Environment("env", store=cold_store, policy=Policy(), principal_scope="principal", resource_extension_snapshot=_test_resource_snapshot))
        replay = cold.reserve(request, "digest", intent, usages=(hold,))
        assert replay.status == "unknown"
        assert not cold_store.claim_operation_step(request, "digest", step).claimed
        assert held(cold_store) == before
    finally:
        cold_store.close()


def test_reserve_refuses_pin_that_was_never_admitted(tmp_path):
    """A new reservation must reject a pin with no admitted RuntimeProvider.

    The exact-pin comparison stays strict: a hand-written subset of the real
    provider_ref is not an admitted contribution and must be refused, not
    silently accepted or compared field-by-field with tolerance.
    """
    store = SqliteStorePort(tmp_path / "unadmitted.sqlite")
    try:
        env = Environment("env", store=store, policy=Policy(), principal_scope="principal", resource_extension_snapshot=_test_resource_snapshot)
        request = RequestKey("env", "principal", "prepare")
        unadmitted = {"environmentNamespace": "env", "providerId": "fixed-provider", "generation": 1}
        intent = OperationIntent("prepare-operation", "prepare",
            {"environmentNamespace": "env", "profileId": "profile", "manifestRevision": 1,
             "contentDigest": "sha256:" + "b" * 64},
            {"environmentNamespace": "env"},
            (StepIntent("prepare", unadmitted, "step-digest", "original-correlation"),),
            {"environmentNamespace": "env", "instanceId": "node", "generation": 1})
        with pytest.raises(UnitAdmissionRefused):
            NodePublication(env).reserve(request, "digest", intent)
        assert store.read_operation(request) is None
        assert store.read_domain("env", IDENTITIES, "node") is None
        assert held(store) == []
    finally:
        store.close()


def test_reserve_refuses_pin_after_provider_is_drained(tmp_path):
    """Draining the activation must make new reservations of that pin fail.

    The drained-state exclusion is exactly what keeps the strict comparison
    meaningful after registration; it is not relaxed to a best-effort check.
    """
    store = SqliteStorePort(tmp_path / "drained.sqlite")
    try:
        env = Environment("env", store=store, policy=Policy(), principal_scope="principal", resource_extension_snapshot=_test_resource_snapshot)
        env.install(InstallationRecord("fixture.plugin", "a" * 64))
        env.enable("fixture.plugin")
        receipt = env.activate("fixture.plugin",
                               AgentContributionSet(agent_runtime_providers=(Provider(),)))
        provider = env.agent_runtime_contribution(Provider.descriptor.definition_ref).provider_ref
        assert any(safe_json(item.provider_ref) == safe_json(provider)
                   for item in env.agent_runtime_contributions())
        env.drain(receipt.activation)
        request = RequestKey("env", "principal", "prepare")
        intent = OperationIntent("prepare-operation", "prepare",
            {"environmentNamespace": "env", "profileId": "profile", "manifestRevision": 1,
             "contentDigest": "sha256:" + "b" * 64},
            {"environmentNamespace": "env"},
            (StepIntent("prepare", provider, "step-digest", "original-correlation"),),
            {"environmentNamespace": "env", "instanceId": "node", "generation": 1})
        hold = UsageMutation("provider-hold", 0, None,
                             operation_holder(request, intent.operation_ref),
                             provider, ("use",), "active")
        with pytest.raises(UnitAdmissionRefused):
            NodePublication(env).reserve(request, "digest", intent, usages=(hold,))
        assert store.read_operation(request) is None
        assert store.read_domain("env", IDENTITIES, "node") is None
        assert held(store) == []
    finally:
        store.close()
