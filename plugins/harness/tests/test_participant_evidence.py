"""T007-01: participant/surface/scope evidence adaptation to the Environment.

Pinned scenarios:

* a valid ``ParticipantEvidence`` roundtrips through the settlement-note
  format used by ``Environment.register_settlement`` (late-object cleanup
  disposition plus stop/scope honesty), deterministically;
* the completeness scale is closed (``complete``/``partial``/``opaque``), the
  exit contract is exactly the ``Environment.mark_object_management`` triple,
  and the evidence digest must be sha256 hex;
* an ``owned`` exit with ``partial``/``opaque`` scope is recorded as
  insufficient evidence (T007-07) instead of being silently upgraded;
* against a real ``Environment`` (pacthold, order 004 gates): install →
  enable → activate → instantiate → ``mark_object_management("owned")`` →
  drain → retire stays ``retire-pending`` without evidence and reaches
  ``retired`` once the settlement notes and closure evidence are registered;
  nothing is deleted — objects turn historical, read-only.

The harness start/connect/close implementation is not exercised here and is
not changed by this module: this file only pins the evidence vocabulary and
its handover to the Environment lifecycle facts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from ordessa_harness_api import (
    ContractError,
    ParticipantEvidence,
    from_settlement_notes,
    to_settlement_notes,
)
from ordessa_environment_api import RequestKey
from ordessa_environment_api.identity import ActivationRef
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord


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


# -- positive: construction + settlement-notes roundtrip -----------------------


@pytest.mark.parametrize("exit_contract", ["owned", "borrowed", "static-projection"])
def test_valid_evidence_roundtrips_through_settlement_notes(exit_contract):
    evidence = _evidence(exit_contract=exit_contract)
    notes = to_settlement_notes(evidence)
    assert all(note.startswith("participant-exit:") for note in notes)
    assert to_settlement_notes(evidence) == notes  # deterministic, ordered
    assert from_settlement_notes(notes) == evidence


def test_evidence_without_surfaces_roundtrips():
    evidence = _evidence(exit_contract="borrowed", surface_ids=())
    assert from_settlement_notes(to_settlement_notes(evidence)) == evidence


def test_scope_evidence_sufficiency_follows_exit_contract():
    assert _evidence(managed_scope="complete").scope_evidence_sufficient is True
    # T007-07: partial/opaque owned instances carry insufficient evidence
    assert _evidence(managed_scope="partial").scope_evidence_sufficient is False
    assert _evidence(managed_scope="opaque").scope_evidence_sufficient is False
    # borrowed only releases, static keeps content — no scope proof owed
    assert _evidence(exit_contract="borrowed", managed_scope="partial").scope_evidence_sufficient is True
    assert _evidence(exit_contract="static-projection", managed_scope="opaque").scope_evidence_sufficient is True
    # and the honesty marker travels into the notes
    notes = to_settlement_notes(_evidence(managed_scope="partial"))
    assert "participant-exit:scope_evidence=insufficient" in notes


# -- negative: closed enums, digest pattern, malformed notes --------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("managed_scope", "full"),
        ("managed_scope", ""),
        ("object_discovery_completeness", "unknown"),
        ("exit_contract", "external"),
        ("exit_contract", "shared"),
    ],
)
def test_closed_enums_refuse_unknown_values(field, value):
    with pytest.raises(ContractError):
        _evidence(**{field: value})


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "A" * 64, "z" * 64, "", 12345],
)
def test_digest_must_be_sha256_hex(digest):
    with pytest.raises(ContractError):
        _evidence(evidence_digest=digest)


def test_surface_ids_are_validated_and_normalized():
    assert _evidence(surface_ids=["a.b", "c.d"]).surface_ids == ("a.b", "c.d")
    for bad in ([""], [" spaced "], "demo.contract", [7]):
        with pytest.raises(ContractError):
            _evidence(surface_ids=bad)


def test_settlement_note_parser_refuses_malformed_notes():
    good = to_settlement_notes(_evidence())
    with pytest.raises(ContractError):
        from_settlement_notes(["env-note:not-ours"])
    with pytest.raises(ContractError):
        from_settlement_notes(good[:-1])  # a partial set is never synthesized
    with pytest.raises(ContractError):
        from_settlement_notes([*good, "participant-exit:surprise=1"])
    with pytest.raises(ContractError):
        from_settlement_notes([*good[:-1], "participant-exit:evidence_digest=short"])
    with pytest.raises(ContractError):
        from_settlement_notes([note for note in good if "exit_disposition" not in note]
                              + ["participant-exit:exit_disposition=release-only"])


# -- Environment handover: owned exit pending without, retired with notes ------


@dataclass(frozen=True)
class _Contract:
    contract_id: str = "demo.contract@1"


def _env_with_participant() -> tuple[Environment, ActivationRef, object, object]:
    env = Environment("env-h")
    env.install(InstallationRecord(installation_id="demo.plugin", manifest_digest="d" * 64))
    env.enable("demo.plugin")
    env.activate("demo.plugin", CoreContributionSet(contracts=(_Contract,)))
    receipt = env.instantiate(
        "demo.contract",
        RequestKey(environment_namespace="env-h", principal_scope="user:local:t", request_id="p-1"),
        instance_id="i-1",
        object_id="o-1",
    )
    obj = receipt.objects[0]
    env.mark_object_management(obj, "owned")  # matches evidence.exit_contract
    activation = ActivationRef(environment="env-h", plugin_id="demo.plugin", generation=1)
    return env, activation, obj, receipt.usages[0]


def test_owned_exit_pending_without_evidence_then_retired_with_settlement_notes():
    env, activation, obj, usage = _env_with_participant()
    env.drain(activation)

    state, blockers = env.retire(activation)  # no closure evidence at all
    assert state == "retire-pending"
    assert any("owned-exit-evidence-missing" in blocker for blocker in blockers)
    # nothing was deleted while pending
    assert env.lookup(obj)["state"] != "deleted"

    evidence = _evidence(surface_ids=("demo.contract",))
    notes = to_settlement_notes(evidence)
    for note in notes:  # late-object cleanup / stop confirmation registration
        env.register_settlement("demo.plugin", 1, note)
    env.release(usage)  # settle our own usage; the owned evidence gap remains
    assert env.retire(activation)[0] == "retire-pending"

    closure_evidence = {
        "exit-contract": evidence.exit_contract,
        "managed-scope": evidence.managed_scope,
        "object-discovery": evidence.object_discovery_completeness,
        "evidence-digest": evidence.evidence_digest,
    }
    state2, blockers2 = env.retire(activation, closure_evidence=closure_evidence)
    assert state2 == "retired" and blockers2 == ()
    assert env.settlements("demo.plugin", 1) == notes
    # retirement is read-only closure: the object turns historical, not gone
    entry = env.lookup(obj, mode="history-read")
    assert entry["historical"] is True
