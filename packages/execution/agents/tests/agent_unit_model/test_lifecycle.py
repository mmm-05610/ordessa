"""Lifecycle coordination counterexamples: stop, release, recover (C only).

Real temporary SQLite store, real Core/Node publication/Issuer with controlled
provider and owner ports. No native process, no model. The coordinator never
fabricates outcomes, never auto-releases unknown holds and never re-dispatches
a claimed step; recover must return the original Node binding identity.
"""
from __future__ import annotations

import json
import pytest
from ordessa_infrastructure.identifiers import RequestKey

from ordessa_units.errors import UnitGuaranteeUnavailable, UnitIdentityMismatch, UnitOperationUnknown
from ordessa_units.definitions.operations import OperationRevisionConflict, node_holder
from ordessa_units.definitions.admission_identity import AgentNodeRef

from agent_tools_fixtures.assembly import (
    Authority, CurrentState, Policy, source, Environment, InstallationRecord,
    AgentContributionSet, DirectoryBindingRef, InvocationIssuer, ProfileService,
    NodePublication, NodePublicationEvidence, AgentAssembly, PreparationContext,
    PreparationObservation, SqliteStorePort, ProtectedFingerprintHmac,
    UsageMutation, operation_holder, decode_node_ref, Provider, ContextOwner, Owner,
)
from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION, RuntimeProviderDescriptor
from ordessa_units.lifecycle.service import AgentLifecycle, LifecycleObservation


from agent_tools_fixtures.lifecycle import LifecycleProvider, LifecycleOwner, lifecycle
def test_stop_concludes_with_owner_termination_proof_and_replays_idempotently(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    view = coordinator.stop(request, node_ref, {})
    assert view["action"] == "stop" and view["status"] == "running"
    step = store.read_operation_step(request, "stop")
    assert step.outcome == "concluded"
    assert step.evidence["termination"]["state"] == "confirmed"
    assert provider.lifecycle_calls.count("stop") == 1
    # replay of the same request returns the original operation, never a resend
    replay = coordinator.stop(request, node_ref, {})
    assert replay == view
    assert provider.lifecycle_calls.count("stop") == 1


def test_failed_effect_records_unknown_and_never_resends(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    provider.fail_lifecycle = "stop"
    view = coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"
    assert view["status"] == "unknown"  # the operation honestly reports unknown
    assert provider.lifecycle_calls.count("stop") == 1
    coordinator.stop(request, node_ref, {})
    assert provider.lifecycle_calls.count("stop") == 1  # possibly-dispatched, never resent


def test_wrong_receipt_identity_records_unknown_not_concluded(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    owner.wrong_correlation = True
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"
    request = RequestKey("env", "principal", "stop-2")
    owner.wrong_correlation = False
    owner.wrong_unit = True
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"


def test_new_explicit_stop_reconciles_unknown_before_release(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, first, provider_ref, current = lifecycle
    provider.fail_lifecycle = "stop"
    coordinator.stop(first, node_ref, {})
    assert store.read_operation_step(first, "stop").outcome == "unknown"
    release = RequestKey("env", "principal", "release-before-reconciliation")
    with pytest.raises(UnitOperationUnknown, match="unresolved effect claim"):
        coordinator.release(release, node_ref, {})
    assert store.read_operation_step(release, "release") is None
    provider.fail_lifecycle = None
    second = RequestKey("env", "principal", "explicit-reconcile-stop")
    coordinator.stop(second, node_ref, {})
    evidence = store.read_operation_step(second, "stop").evidence
    assert evidence["termination"]["state"] == "confirmed"
    assert store.read_operation_step(first, "stop").outcome == "unknown"
    coordinator.release(RequestKey("env", "principal", "release-after-reconciliation"), node_ref, {})
    assert store.read_operation_step(first, "stop").outcome == "unknown"
    assert provider.lifecycle_calls.count("stop") == 2
    assert provider.lifecycle_calls.count("release") == 1


def test_older_concluded_stop_cannot_reconcile_later_unknown_stop(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, first, provider_ref, current = lifecycle
    coordinator.stop(first, node_ref, {})
    assert store.read_operation_step(first, "stop").outcome == "concluded"
    provider.fail_lifecycle = "stop"
    unknown = RequestKey("env", "principal", "later-unknown-stop")
    coordinator.stop(unknown, node_ref, {})
    assert store.read_operation_step(unknown, "stop").outcome == "unknown"
    with pytest.raises(UnitOperationUnknown, match="unresolved effect claim"):
        coordinator.release(RequestKey("env", "principal", "release-after-later-unknown"), node_ref, {})
    assert provider.lifecycle_calls.count("release") == 0


def test_unconfirmed_termination_records_unknown_step(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    owner.terminal = "unknown"
    coordinator.stop(request, node_ref, {})
    assert store.read_operation_step(request, "stop").outcome == "unknown"


def test_release_requires_exact_active_publication_set(lifecycle):
    from ordessa_units.definitions.operations import node_holder
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    holder = node_holder("env", node_ref.instance_id, node_ref.generation)
    rows_before = store.read_usages("env", holder)
    assert rows_before and all(row["state"] == "active" for row in rows_before)
    assert {row["usageId"] for row in rows_before} == {item["usageId"] for item in node["resourceUsageRefs"]}
    # happy path: the exact active set releases and the step concludes
    view = coordinator.release(request, node_ref, {})
    step = store.read_operation_step(request, "release")
    assert step.outcome == "concluded"
    rows_after = store.read_usages("env", holder)
    assert [row["state"] for row in rows_after] == ["released"] * len(rows_after)
    assert provider.lifecycle_calls.count("release") == 1
    # replay of the same request is idempotent
    assert coordinator.release(request, node_ref, {}) == view
    assert provider.lifecycle_calls.count("release") == 1
    # a NEW release request sees a non-active set and is refused before dispatch
    with pytest.raises(UnitGuaranteeUnavailable, match="active publication Usages"):
        coordinator.release(RequestKey("env", "principal", "release-again"), node_ref, {})
    assert provider.lifecycle_calls.count("release") == 1


def test_recover_requires_original_binding_identity(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    forged = dict(node["binding"])
    forged["nativeSessionRefs"] = [source(provider_ref, "recent-session")]
    owner.binding = forged
    coordinator.recover(request, node_ref, {})
    assert store.read_operation_step(request, "recover").outcome == "unknown"
    request = RequestKey("env", "principal", "recover-2")
    owner.binding = dict(node["binding"])
    view = coordinator.recover(request, node_ref, {})
    assert store.read_operation_step(request, "recover").outcome == "concluded"
    assert view["action"] == "recover"


def test_recover_refuses_after_original_node_usages_are_released(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    coordinator.release(request, node_ref, {})
    assert store.read_operation_step(request, "release").outcome == "concluded"
    before = list(provider.lifecycle_calls)
    recover = RequestKey("env", "principal", "recover-after-release")
    with pytest.raises(UnitGuaranteeUnavailable, match="recover requires the exact original Node Usage set"):
        coordinator.recover(recover, node_ref, {})
    assert store.read_operation_step(recover, "recover") is None
    assert provider.lifecycle_calls == before


def test_unknown_node_usage_refuses_recover_before_reservation(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, _, provider_ref, current = lifecycle
    rows = store.read_usages("env", node_holder("env", node_ref.instance_id, node_ref.generation))
    assert rows and all(row["state"] == "active" for row in rows)
    store._conn.execute("UPDATE env_usages SET state='unknown' WHERE usage_id=?",
                        (rows[0]["usageId"],))
    store._conn.commit()
    request = RequestKey("env", "principal", "recover-unknown-held-usage")
    with pytest.raises(UnitGuaranteeUnavailable,
                       match="recover requires the exact original Node Usage set"):
        coordinator.recover(request, node_ref, {})
    assert store.read_operation(request) is None
    assert provider.lifecycle_calls == []


@pytest.mark.parametrize("change", ("target", "rights", "revision"))
def test_first_held_snapshot_change_before_reservation_cannot_dispatch(lifecycle, change):
    coordinator, owner, provider, node_ref, node, env, store, _, provider_ref, current = lifecycle
    request = RequestKey("env", "principal", "recover-first-held-snapshot-" + change)
    rows = store.read_usages("env", node_holder("env", node_ref.instance_id, node_ref.generation))
    assert rows and all(row["state"] == "active" for row in rows)
    usage_id = rows[0]["usageId"]
    original_reserve = store.reserve_operation
    def mutate_after_original_owner_validation(key, digest, intent, writes=(), usages=()):
        if key == request:
            if change == "target":
                changed_target = dict(rows[0]["targetRef"])
                changed_target["controlledMutation"] = "after-first-validation"
                store._conn.execute("UPDATE env_usages SET target_ref=? WHERE usage_id=?",
                                    (json.dumps(changed_target), usage_id))
            elif change == "rights":
                store._conn.execute("UPDATE env_usages SET rights=? WHERE usage_id=?",
                                    ('["use","read"]', usage_id))
            else:
                store._conn.execute("UPDATE env_usages SET revision=revision+1 WHERE usage_id=?",
                                    (usage_id,))
            store._conn.commit()
        return original_reserve(key, digest, intent, writes, usages)
    store.reserve_operation = mutate_after_original_owner_validation
    with pytest.raises(OperationRevisionConflict, match="Usage set changed before claim"):
        coordinator.recover(request, node_ref, {})
    assert store.read_operation_step(request, "recover") is None
    assert provider.lifecycle_calls == []


def test_preconditions_shape_and_unknown_keys_are_refused(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    for bad in ("string", 5, {"unknownKey": 1}):
        with pytest.raises(UnitIdentityMismatch, match="preconditions"):
            coordinator.stop(RequestKey("env", "principal", "bad-" + str(type(bad).__name__)), node_ref, bad)
    assert provider.lifecycle_calls == []


def test_lifecycle_requires_composed_authorities(lifecycle):
    coordinator, owner, provider, node_ref, node, env, store, request, provider_ref, current = lifecycle
    bare = AgentLifecycle(env, coordinator._nodes, invocation_issuer=coordinator._issuer)
    assert bare.capabilities() == {"nodeLifecycle": False}
    with pytest.raises(UnitGuaranteeUnavailable, match="lifecycle authorities"):
        bare.stop(RequestKey("env", "principal", "bare"), node_ref, {})
    assert coordinator.capabilities() == {"nodeLifecycle": True}


def test_draining_exact_owner_can_stop_release_then_retire_without_new_admission(lifecycle):
    from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef
    from ordessa_units.definitions.operations import node_holder
    from ordessa_units.errors import UnitAdmissionRefused
    coordinator, owner, provider, node_ref, node, env, store, request, pin, current = lifecycle
    activation = pin["ownerActivationRef"]
    ref = HarnessActivationRef("env", activation["pluginId"], activation["generation"])
    state, blockers = env.retire_activation(ref)
    assert state == "retire-pending" and any(value.startswith("agent-unit-usage:") for value in blockers)
    current.active = False  # current-state port reports ordinary admission closed
    with pytest.raises(UnitAdmissionRefused):
        env.agent_runtime_contribution(provider.descriptor.definition_ref)
    with pytest.raises(UnitAdmissionRefused):
        coordinator.recover(RequestKey("env", "principal", "recover-draining"), node_ref, {})
    assert store.read_operation(RequestKey("env", "principal", "recover-draining")) is None
    stopped = coordinator.stop(request, node_ref, {})
    assert stopped["action"] == "stop"
    assert store.read_operation_step(request, "stop").outcome == "concluded"
    release_request = RequestKey("env", "principal", "release-draining")
    released = coordinator.release(release_request, node_ref, {})
    assert released["action"] == "release"
    assert store.read_operation_step(release_request, "release").outcome == "concluded"
    holder = node_holder("env", node_ref.instance_id, node_ref.generation)
    assert all(row["state"] == "released" for row in store.read_usages("env", holder))
    assert coordinator.release(release_request, node_ref, {}) == released
    assert provider.lifecycle_calls.count("release") == 1
    assert env.retire_activation(ref) == ("retired", ())
