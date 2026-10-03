"""T007-07 (verification half): retirement evidence gates for participant exits.

Pins the handover from participant exit evidence to Environment retirement:

* an ``owned`` instance whose managed scope was only ``partial``/``opaque``
  carries insufficient scope evidence: the adapter never turns it into closure
  proof, and the Environment keeps the activation ``retire-pending`` with the
  ``owned-exit-evidence-missing`` blocker — nothing is deleted while pending;
* a ``complete`` ``owned`` exit is sufficient and reaches ``retired`` once the
  closure evidence is handed over;
* ``borrowed``/``static-projection`` exits never owe scope evidence: a
  partial/opaque scope is still sufficient and retirement succeeds without
  owned evidence, releasing the relation while history stays readable;
* a borrowed object shared by two activations is not misfired: a retirement
  attempt never silently settles the other side's live usage (the gate stays
  pending), each side releases its OWN usage, and after the borrower's exit the
  owner's object is still available, non-historical, bindable and usable;
* malformed digests/enums and settlement notes that try to launder
  insufficient scope into ``sufficient`` are refused.

The Environment's owned gate is presence-based (``retire`` asks only whether a
closure-evidence mapping was handed over, not what it says); ``_closure_evidence``
below models the documented adapter handover decision, so an insufficient
record yields no mapping and the Environment reports the owned gap.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from ordessa_environment_api import AdmissionRefusedError, RequestKey
from ordessa_environment_api.identity import ActivationRef
from ordessa_harness_api import (
    ContractError,
    ParticipantEvidence,
    from_settlement_notes,
    to_settlement_notes,
)
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord

ENVIRONMENT = "env-retire"


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _evidence(**overrides) -> ParticipantEvidence:
    base = dict(
        managed_scope="complete",
        object_discovery_completeness="complete",
        exit_contract="owned",
        surface_ids=("demo.contract",),
        evidence_digest=_digest("participant-evidence-bundle"),
    )
    base.update(overrides)
    return ParticipantEvidence(**base)


def _closure_evidence(evidence: ParticipantEvidence) -> dict[str, str] | None:
    """The documented handover: only sufficient scope evidence becomes closure
    proof.  An insufficient record yields nothing, so the Environment keeps the
    owned gap visible instead of accepting an unbacked mapping."""
    if not evidence.scope_evidence_sufficient:
        return None
    return {
        "exit-contract": evidence.exit_contract,
        "managed-scope": evidence.managed_scope,
        "object-discovery": evidence.object_discovery_completeness,
        "evidence-digest": evidence.evidence_digest,
    }


@dataclass(frozen=True)
class _Contract:
    contract_id: str = "demo.contract@1"


@dataclass(frozen=True)
class _OtherContract:
    contract_id: str = "other.contract@1"


def _key(request_id: str) -> RequestKey:
    return RequestKey(
        environment_namespace=ENVIRONMENT,
        principal_scope="user:local:t",
        request_id=request_id,
    )


def _activate(env: Environment, plugin_id: str, *contracts) -> ActivationRef:
    env.install(InstallationRecord(installation_id=plugin_id, manifest_digest="d" * 64))
    env.enable(plugin_id)
    env.activate(plugin_id, CoreContributionSet(contracts=tuple(contracts)))
    return ActivationRef(environment=env.environment_id, plugin_id=plugin_id, generation=1)


def _single_participant(management: str):
    """One installed participant owning one object of the given management kind."""
    env = Environment(ENVIRONMENT)
    activation = _activate(env, "demo.plugin", _Contract)
    receipt = env.instantiate(
        "demo.contract", _key("r-1"), instance_id="i-1", object_id="o-1"
    )
    obj = receipt.objects[0]
    env.mark_object_management(obj, management)
    return env, activation, obj, receipt.usages[0]


def _register_notes(env: Environment, notes: tuple[str, ...]) -> None:
    for note in notes:
        env.register_settlement("demo.plugin", 1, note)


# -- insufficient owned evidence stays pending ---------------------------------


@pytest.mark.parametrize("managed_scope", ["partial", "opaque"])
def test_insufficient_owned_scope_evidence_stays_retire_pending(managed_scope):
    env, activation, obj, handover = _single_participant("owned")
    evidence = _evidence(managed_scope=managed_scope, exit_contract="owned")
    assert evidence.scope_evidence_sufficient is False

    notes = to_settlement_notes(evidence)
    assert "participant-exit:scope_evidence=insufficient" in notes
    _register_notes(env, notes)

    env.drain(activation)
    env.release(handover)
    # the same retire call shape as the sufficient case, but the insufficient
    # record yields no closure evidence at all
    closure = _closure_evidence(evidence)
    assert closure is None
    state, blockers = env.retire(activation, closure_evidence=closure)
    assert state == "retire-pending"
    assert "owned-exit-evidence-missing:i-1" in blockers

    # pending is honest, not destructive: the object is still available
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is False
    assert entry["state"] == "available"
    # the registered notes still parse back to the same insufficient record
    registered = env.settlements("demo.plugin", 1)
    assert registered == notes
    assert from_settlement_notes(registered) == evidence
    assert from_settlement_notes(registered).scope_evidence_sufficient is False


# -- sufficient owned evidence reaches retired ---------------------------------


def test_sufficient_owned_scope_evidence_reaches_retired():
    env, activation, obj, handover = _single_participant("owned")
    evidence = _evidence(managed_scope="complete", exit_contract="owned")
    assert evidence.scope_evidence_sufficient is True

    notes = to_settlement_notes(evidence)
    assert "participant-exit:scope_evidence=sufficient" in notes
    _register_notes(env, notes)

    env.drain(activation)
    env.release(handover)
    closure = _closure_evidence(evidence)
    assert closure is not None
    state, blockers = env.retire(activation, closure_evidence=closure)
    assert state == "retired" and blockers == ()
    assert env.settlements("demo.plugin", 1) == notes

    # owned closure is read-only: object retained as history, admissions cut
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is True
    assert entry["state"] == "available"
    with pytest.raises(AdmissionRefusedError):
        env.bind("demo.contract")


# -- borrowed / static-projection never owe scope evidence ---------------------


@pytest.mark.parametrize(
    "exit_contract,management,managed_scope,disposition",
    [
        ("borrowed", "borrowed", "partial", "release-only"),
        ("static-projection", "static-projection", "opaque", "content-preserved"),
    ],
)
def test_borrowed_and_static_exits_owe_no_scope_evidence(
    exit_contract, management, managed_scope, disposition
):
    env, activation, obj, handover = _single_participant(management)
    evidence = _evidence(exit_contract=exit_contract, managed_scope=managed_scope)
    # only an owned exit demands a complete scope
    assert evidence.scope_evidence_sufficient is True

    notes = to_settlement_notes(evidence)
    assert "participant-exit:scope_evidence=sufficient" in notes
    assert f"participant-exit:exit_disposition={disposition}" in notes
    _register_notes(env, notes)

    env.drain(activation)
    env.release(handover)
    state, blockers = env.retire(activation)  # no owned evidence handed over
    assert state == "retired" and blockers == ()

    # relation closed, content/history never deleted
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is True
    assert entry["state"] == "released"
    with pytest.raises(AdmissionRefusedError):
        env.use(obj, "late")


# -- shared borrowed relation: one side's exit does not misfire the other ------


def test_retiring_one_side_does_not_misfire_the_shared_borrowed_relation():
    env = Environment(ENVIRONMENT)
    owner = _activate(env, "demo.owner", _Contract)
    borrower = _activate(env, "demo.borrower", _OtherContract)
    receipt = env.instantiate(
        "demo.contract", _key("r-1"), instance_id="i-1", object_id="o-1"
    )
    shared = receipt.objects[0]
    env.mark_object_management(shared, "borrowed")
    owner_handover = receipt.usages[0]  # owner's own handover usage
    owner_usage = env.use(shared, "owner-keep")
    borrower_usage = env.use(shared, "borrower-hold")
    before = dict(env.lookup(shared))
    assert before["owner_activation"] == owner

    # the borrower's exit is refused while any usage is live: nobody's usage is
    # silently settled by the other side's retirement attempt
    env.drain(borrower)
    state, blockers = env.retire(borrower)
    assert state == "retire-pending"
    for usage in (owner_handover, owner_usage.usage, borrower_usage.usage):
        assert f"active-usage:{usage.usage_id}" in blockers
    assert env.lookup(shared) == before

    # each side releases its OWN usage; only then does the borrower retire
    env.release(owner_usage.usage)
    env.release(borrower_usage.usage)
    env.release(owner_handover)
    state2, blockers2 = env.retire(borrower)
    assert state2 == "retired" and blockers2 == ()

    # the owner's side of the shared relation is untouched: same lookup, still
    # usable, capability bindable and new admissions possible
    assert env.lookup(shared) == before
    fresh = env.use(shared, "owner-after-borrower-exit")
    assert fresh.state == "active"
    env.bind("demo.contract")
    with pytest.raises(AdmissionRefusedError):
        env.bind("other.contract")  # only the borrower's own capability is cut


# -- missing preconditions: malformed construction and note laundering ---------


@pytest.mark.parametrize(
    "field,value",
    [("managed_scope", "full"), ("exit_contract", "shared")],
)
def test_invalid_evidence_enums_are_refused(field, value):
    with pytest.raises(ContractError):
        _evidence(**{field: value})


@pytest.mark.parametrize("digest", ["a" * 63, "A" * 64])
def test_invalid_evidence_digest_is_refused(digest):
    with pytest.raises(ContractError):
        _evidence(evidence_digest=digest)


def test_settlement_notes_cannot_launder_insufficient_scope():
    notes = list(
        to_settlement_notes(_evidence(managed_scope="partial", exit_contract="owned"))
    )
    doctored = [
        note.replace("scope_evidence=insufficient", "scope_evidence=sufficient")
        for note in notes
    ]
    assert doctored != notes  # the doctoring really happened
    with pytest.raises(ContractError):
        from_settlement_notes(doctored)
