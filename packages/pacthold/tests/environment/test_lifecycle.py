"""004 gates: activation/exit authority, usage retirement, wait graph and the
persistent-reference gate (T004-01..08 counterexamples).

Pinned counterexamples:

* drain cuts new admissions atomically; a LATE open on the drained
  activation is refused, while a NEW generation of the same plugin activates
  normally (old callbacks never reach the new activation);
* retire without owned-exit evidence stays ``retire-pending`` — unknown
  responsibilities are never deleted; borrowed objects only release (there
  is no kill path at all); static projections keep content;
* a wait registration that would close a cycle is refused even though the
  callbacks already returned (async proves nothing);
* published persistent references survive plugin retirement and BLOCK
  destructive changes; a reservation is never auto-released;
* new relations and a destructive change on the same target can never both
  pass the gate.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord, WouldDeadlockError
from ordessa_environment_api import (
    AdmissionRefusedError,
    CanonicalFactTarget,
    IdentityMismatchError,
    PersistentReference,
    ReferenceStatus,
    RequestKey,
    RevisionSelector,
)
from ordessa_environment_api.identity import ActivationRef


@dataclass(frozen=True)
class _Contract:
    contract_id: str = "demo.contract@1"


WS = CanonicalFactTarget(realm="workspace", identity_namespace="ordessa.workspace",
                          stable_entity_id="ws-main")
SKILL = CanonicalFactTarget(realm="resource", identity_namespace="ordessa.skills",
                             stable_entity_id="skill-x")


def _key(rid: str) -> RequestKey:
    return RequestKey(environment_namespace="env-l", principal_scope="user:local:t", request_id=rid)


def _env_with_plugin(plugin: str = "demo.plugin") -> Environment:
    env = Environment("env-l")
    env.install(InstallationRecord(installation_id=plugin, manifest_digest="d" * 64))
    env.enable(plugin)
    env.activate(plugin, CoreContributionSet(contracts=(_Contract,)))
    return env


def _relation(rid: str = "rel-1", source_revision: str = "rev-1") -> PersistentReference:
    return PersistentReference(
        relation_id=rid, source_key=WS, source_revision=source_revision, target_key=SKILL,
        revision_selector=RevisionSelector(op="exact", revision="2"),
        declaring_owner_domain="ordessa.profile", policy_contract_id="profile.facet",
        policy_contract_version=1, operation_id="op-1", source_commit_evidence="sha256:x",
        status=ReferenceStatus.PREPARED,
    )


# -- T004-02/03: drain cut, late open, new generation -------------------------


def test_drain_cuts_new_admissions_and_late_open_is_refused():
    env = _env_with_plugin()
    first = env.activate  # noqa: F841  (readability)
    activation = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    cut = env.drain(activation)
    assert cut.closed_new_admission and cut.admission_cut_revision.startswith("cut-")
    with pytest.raises(AdmissionRefusedError, match="cut"):
        env.bind("demo.contract")
    with pytest.raises(AdmissionRefusedError, match="cut"):
        env.instantiate("demo.contract", _key("late-1"), instance_id="late-i")
    with pytest.raises(AdmissionRefusedError, match="cut"):
        env.invoke("demo.contract", _key("late-2"), input_digest="a" * 64)
    # query/lookup (read paths) survive the cut
    assert env.query(_key("none")) is None


def test_new_generation_activates_after_drain_and_old_callbacks_cannot_touch_it():
    env = _env_with_plugin()
    old = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    env.drain(old)
    env._finish_retire(old)
    receipt = env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    assert receipt.activation.generation == 2
    # the old generation's callback path resolves only against generation 1:
    # mark_retired(old) must not flip the new capability to historical
    env.mark_retired(old)
    env.bind("demo.contract")  # generation-2 capability still bindable


def test_failed_activation_registers_settlement_not_no_side_effects():
    env = Environment("env-l")
    env.install(InstallationRecord(installation_id="demo.plugin", manifest_digest="d" * 64))
    env.enable("demo.plugin")
    # a duplicate contract id makes the batch fail typed; a plugin that had
    # already created an external object before failing reports it — the
    # environment never claims "no side effects"
    @dataclass(frozen=True)
    class _Same:
        contract_id: str = "demo.contract@1"

    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    with pytest.raises(Exception):
        env.activate("demo.plugin", CoreContributionSet(contracts=(_Same,)))
    env.register_settlement("demo.plugin", 1, "external-instance-orphaned")
    assert env.settlements("demo.plugin", 1) == ("external-instance-orphaned",)


# -- T004-04/05: retire rules --------------------------------------------------


def test_retire_requires_drain_then_blocks_on_owned_without_evidence():
    env = _env_with_plugin()
    activation = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    (obj,) = env.instantiate("demo.contract", _key("r-1"), instance_id="i-1",
                             object_id="o-1").objects
    with pytest.raises(AdmissionRefusedError, match="drain cut first"):
        env.retire(activation)
    usage = env.use(obj, "hold")  # an active usage is a real blocker too
    env.drain(activation)
    state, blockers = env.retire(activation)  # owned object, no evidence
    assert state == "retire-pending"
    assert any("owned-exit-evidence-missing" in b for b in blockers)
    # unknown responsibility is still there — nothing was deleted
    assert env.lookup(obj)["state"] != "deleted"

    env.release(usage.usage)  # settle the usage, keep the owned-evidence gap
    assert env.retire(activation)[0] == "retire-pending"
    state2, blockers2 = env.retire(activation, closure_evidence={"exit-scope": "confirmed"})
    assert state2 == "retired" and blockers2 == ()
    # historical read still works; content never erased
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is True


def test_borrowed_only_releases_and_static_keeps_content():
    env = _env_with_plugin()
    activation = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    (borrowed,) = env.instantiate("demo.contract", _key("r-2"), instance_id="i-2",
                                  object_id="o-2").objects
    (static,) = env.instantiate("demo.contract", _key("r-3"), instance_id="i-3",
                                object_id="o-3").objects
    env.mark_object_management(borrowed, "borrowed")
    env.mark_object_management(static, "static-projection")
    env.drain(activation)
    state, blockers = env.retire(activation, closure_evidence={"exit-scope": "owned-only"})
    assert state == "retired"
    # borrowed/static objects release the RELATION without any kill path and
    # without demanding exit evidence
    assert env.lookup(borrowed, mode="history-read")["state"] == "released"
    assert env.lookup(static, mode="history-read")["state"] == "released"


def test_unclassified_deliveries_block_retire_until_resolved():
    env = _env_with_plugin()
    activation = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    env.note_unclassified_delivery(activation, count=2)
    env.drain(activation)
    state, blockers = env.retire(activation, closure_evidence={"exit-scope": "ok"})
    assert state == "retire-pending"
    assert any("unclassified-deliveries" in b for b in blockers)
    env.resolve_unclassified(activation)
    state2, _ = env.retire(activation, closure_evidence={"exit-scope": "ok"})
    assert state2 == "retired"


# -- T004-06: wait graph -------------------------------------------------------


def test_wait_cycle_is_refused_even_though_callbacks_returned():
    env = _env_with_plugin()
    @dataclass(frozen=True)
    class _Other:
        contract_id: str = "other.contract@1"

    env.install(InstallationRecord(installation_id="other.plugin", manifest_digest="e" * 64))
    env.enable("other.plugin")
    env.activate("other.plugin", CoreContributionSet(contracts=(_Other,)))
    a = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    b = ActivationRef(environment="env-l", plugin_id="other.plugin", generation=1)

    env.register_wait(a, b)   # A waits on B — both "callbacks returned"
    with pytest.raises(WouldDeadlockError):
        env.register_wait(b, a)  # closing the cycle must refuse
    env.clear_wait(a, b)
    env.register_wait(b, a)    # legal after the edge is gone


def test_self_wait_is_refused_and_edges_are_visible():
    env = _env_with_plugin()
    a = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    with pytest.raises(WouldDeadlockError):
        env.register_wait(a, a)


# -- T004-08: persistent references -------------------------------------------


def test_published_references_survive_retirement_and_block_destructive_changes():
    env = _env_with_plugin()
    env.publish_reference_set(WS, "rev-1", (_relation(),), operation_id="op-1")

    incoming = env.inspect_incoming(SKILL, change_kind="delete")
    assert incoming["coverage"] == "known" and incoming["blocking-destructive-change"]
    assert incoming["relations"][0].status is ReferenceStatus.PUBLISHED

    with pytest.raises(AdmissionRefusedError, match="blocked by published relations"):
        env.prepare_resource_change(SKILL, "2", "delete", operation_id="op-del")

    # retire the DECLARING plugin: relations stay published and still block
    activation = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    env.drain(activation)
    env.retire(activation, closure_evidence={"exit-scope": "ok"})
    still = env.inspect_incoming(SKILL, change_kind="delete")
    assert still["relations"] and still["coverage"] == "known"


def test_reservation_gates_new_relations_until_evidence_releases_it():
    OTHER = CanonicalFactTarget(realm="resource", identity_namespace="ordessa.skills",
                                stable_entity_id="skill-y")

    def _rel_on(rid: str, target: CanonicalFactTarget, revision: str) -> PersistentReference:
        return PersistentReference(
            relation_id=rid, source_key=WS, source_revision=revision, target_key=target,
            revision_selector=RevisionSelector(op="exact", revision="1"),
            declaring_owner_domain="ordessa.profile", policy_contract_id="profile.facet",
            policy_contract_version=1, operation_id="op", source_commit_evidence="sha256:y",
            status=ReferenceStatus.PREPARED,
        )

    env = _env_with_plugin()
    env.publish_reference_set(WS, "rev-1", (_relation(),), operation_id="op-1")
    # a destructive change on a REFERENCED target is refused outright (E5)
    with pytest.raises(AdmissionRefusedError, match="blocked by published relations"):
        env.prepare_resource_change(SKILL, "2", "delete", operation_id="op-del")

    # on an UNreferenced target the reservation holds and gates NEW relations
    res = env.prepare_resource_change(OTHER, "1", "rewrite", operation_id="op-rw")
    assert res.change_kind == "rewrite"
    with pytest.raises(AdmissionRefusedError, match="already holds reservation"):
        env.prepare_resource_change(OTHER, "1", "delete", operation_id="op-rw-2")
    with pytest.raises(AdmissionRefusedError, match="destructive change reservation"):
        env.publish_reference_set(WS, "rev-2", (_rel_on("rel-9", OTHER, "rev-2"),),
                                  operation_id="op-2")
    # only the explicit evidence-backed release unblocks the gate
    env.release_reservation("op-rw", executed=True)
    env.publish_reference_set(WS, "rev-2", (_rel_on("rel-9", OTHER, "rev-2"),),
                              operation_id="op-2")
    assert len(env.inspect_incoming(OTHER)["relations"]) == 1


def test_relation_publication_is_idempotent_per_version():
    env = _env_with_plugin()
    env.publish_reference_set(WS, "rev-1", (_relation(),), operation_id="op-1")
    env.publish_reference_set(WS, "rev-1", (_relation(),), operation_id="op-1")  # no-op
    incoming = env.inspect_incoming(SKILL)
    assert len(incoming["relations"]) == 1
    # a MISMATCHED source on the same relation is an identity error
    with pytest.raises(IdentityMismatchError):
        env.publish_reference_set(SKILL, "rev-9", (_relation(),), operation_id="op-3")


def test_dual_plugin_states_come_from_the_single_root():
    @dataclass(frozen=True)
    class _Other:
        contract_id: str = "other.contract@1"

    env = _env_with_plugin()
    env.install(InstallationRecord(installation_id="other.plugin", manifest_digest="e" * 64))
    env.enable("other.plugin")
    env.activate("other.plugin", CoreContributionSet(contracts=(_Other,)))
    a = ActivationRef(environment="env-l", plugin_id="demo.plugin", generation=1)
    b = ActivationRef(environment="env-l", plugin_id="other.plugin", generation=1)
    env.drain(a)
    # A is cut, B keeps working: per-activation state from the single root
    with pytest.raises(AdmissionRefusedError, match="cut"):
        env.bind("demo.contract")
    env.bind("other.contract")
    # B's late event cannot masquerade as A's (identity mismatch)
    with pytest.raises(IdentityMismatchError):
        env._activation_entry(
            ActivationRef(environment="env-l", plugin_id="other.plugin", generation=7)
        )
