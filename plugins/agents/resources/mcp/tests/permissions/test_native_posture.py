"""T012 guards: the native permission posture is a display fact, never an
authority (FR-09 / contracts §4 second half).

The posture labels WHICH harness-native permission mechanism actually
governs a native-lane entry while the Ordessa authority is absent —
source, scope, policy id, provenance. The counterexamples here pin the
two prohibitions of the order: a posture can never be read as
authorization, and the snapshot's ``enforcement: "unproven"`` downgrade
and the posture coexist (the label never lifts it).

No network, no spawn (the package-root conftest blocks both); snapshots
are the real ``backend/resolve.py`` shape via ``perms_helpers``.
"""
from __future__ import annotations

import dataclasses

import pytest
from perms_helpers import make_snapshot

from backend.permissions import (
    PERMISSION_ARGS_DIGEST_REQUIRED,
    PERMISSION_AUTHORITY_ABSENT,
    PERMISSION_ENFORCEMENT_UNPROVEN,
    POSTURE_PROVENANCES,
    POSTURE_PROVENANCE_NATIVE_DECLARED,
    POSTURE_PROVENANCE_NATIVE_OBSERVED,
    POSTURE_PROVENANCE_UNATTRIBUTED,
    STATUS_ALLOWED,
    NativePermissionPosture,
    check_tool_callable,
    native_permission_posture,
    native_permission_postures,
    posture_view,
)

DECLARED_FACT = {
    "source": "claude-code native permission rules",
    "scope": "instance",
    "policyRef": "claude-settings-2026-09",
    "provenance": POSTURE_PROVENANCE_NATIVE_DECLARED,
}
OBSERVED_FACT = {
    "source": "codex native policy engine",
    "scope": "session",
    "policyRef": "policy-rev-77",
    "provenance": POSTURE_PROVENANCE_NATIVE_OBSERVED,
}


# -- the labelling surface -------------------------------------------------------

def test_one_posture_per_native_entry_managed_is_never_labelled():
    """A managed-lane entry runs through THIS module's gates; labelling it
    "native-governed" would misstate who decides. Only native entries get
    a posture row."""
    native = make_snapshot(lane="native", enforcement="unproven")
    managed = make_snapshot(definition_id="def2", lane="managed")
    lanes = dict(native.lane_by_definition)
    lanes.update(managed.lane_by_definition)
    both = dataclasses.replace(native, lane_by_definition=lanes)
    postures = native_permission_postures(both, {"def1": DECLARED_FACT})
    assert [p.definition_id for p in postures] == ["def1"]
    assert all(p.provenance == POSTURE_PROVENANCE_NATIVE_DECLARED
               for p in postures)
    # the managed snapshot alone labels nothing
    assert native_permission_postures(managed, {"def2": DECLARED_FACT}) == ()


def test_unattributed_default_never_fabricates_a_policy():
    """Production today: no observer/declarer is composed. The honest row
    says "harness-native mechanism, policy unknown" — an empty display word
    or a guessed policy name would be the lie this pins out."""
    snapshot = make_snapshot(lane="native", enforcement="unproven")
    postures = native_permission_postures(snapshot)
    assert len(postures) == 1
    posture = postures[0]
    assert posture.provenance == POSTURE_PROVENANCE_UNATTRIBUTED
    assert posture.source == "harness-native"
    assert posture.policy_ref == "unknown"
    assert posture.scope == "unknown"


def test_declared_and_observed_facts_carry_their_own_words():
    snapshot = make_snapshot(lane="native", enforcement="unproven")
    for fact in (DECLARED_FACT, OBSERVED_FACT):
        posture = native_permission_postures(snapshot, {"def1": fact})[0]
        assert posture.source == fact["source"]
        assert posture.scope == fact["scope"]
        assert posture.policy_ref == fact["policyRef"]
        assert posture.provenance == fact["provenance"]


def test_posture_provenance_vocabulary_is_closed():
    assert POSTURE_PROVENANCES == frozenset({
        POSTURE_PROVENANCE_NATIVE_OBSERVED, POSTURE_PROVENANCE_NATIVE_DECLARED,
        POSTURE_PROVENANCE_UNATTRIBUTED})
    with pytest.raises(ValueError):
        NativePermissionPosture(definition_id="d", source="s", scope="i",
                                policy_ref="p", provenance="admin-blessed")
    # "unattributed" is the DOMAIN's default word; an injected fact must
    # attribute itself as observed or declared (an attributed claim is
    # never absent)
    with pytest.raises(ValueError):
        native_permission_posture("d", {"provenance": POSTURE_PROVENANCE_UNATTRIBUTED,
                                        "source": "s", "scope": "i",
                                        "policyRef": "p"})
    # blank/absent words fail closed at the DTO
    with pytest.raises(ValueError):
        NativePermissionPosture(definition_id="d", source="", scope="i",
                                policy_ref="p",
                                provenance=POSTURE_PROVENANCE_NATIVE_DECLARED)


def test_posture_view_is_display_shaped_and_claims_nothing():
    view = posture_view(native_permission_posture("def1", DECLARED_FACT))
    assert view == {
        "definitionId": "def1", "source": DECLARED_FACT["source"],
        "scope": "instance", "policyRef": DECLARED_FACT["policyRef"],
        "provenance": POSTURE_PROVENANCE_NATIVE_DECLARED,
        # FR-09: the cross-brand Ordessa-policy claim is pinned False by
        # construction — nothing in the vocabulary can set it True
        "claimsOrdessaAuthority": False,
    }


# -- counterexample 1: the posture is not an authority ----------------------------

def test_counterexample_a_full_posture_still_authorizes_nothing():
    """The strongest-looking posture (runtime-OBSERVED mechanism with a
    policy id) changes no decision: with the authority absent the call is
    still the typed PERMISSION_AUTHORITY_ABSENT refusal — the posture is
    only where the display reads its words from."""
    snapshot = make_snapshot(lane="native", enforcement="proven")
    postures = native_permission_postures(snapshot, {"def1": OBSERVED_FACT})
    assert len(postures) == 1
    decision = check_tool_callable(
        snapshot, None, "fetch", "sha256:args", now=1000.0,
        principal="alice", project_id="proj-1", definition_id="def1")
    assert decision.status != STATUS_ALLOWED
    assert decision.code == PERMISSION_AUTHORITY_ABSENT
    # and the decision never carries posture words into the audit trail
    blob = repr(decision)
    for posture in postures:
        assert posture.policy_ref not in blob
        assert posture.source not in blob


def test_counterexample_the_dto_has_no_authorization_shape():
    """A type that COULD say "allowed" could be mistaken for one. The
    posture is field-for-field a label: no status/basis/decision/code
    vocabulary exists on it."""
    names = {f.name for f in dataclasses.fields(NativePermissionPosture)}
    assert names == {"definition_id", "source", "scope", "policy_ref",
                     "provenance"}
    assert not ({n for n in names if n in
                 ("status", "allowed", "basis", "decision", "code", "gate")})
    public = [m for m in dir(NativePermissionPosture) if not m.startswith("_")]
    assert public == [], f"the label type grew behaviour: {public}"


def test_counterexample_a_snapshot_mapping_without_facts_feeds_no_gate():
    """check_tool_callable does not even accept a posture argument: there
    is no seam where the label could be read as a grant (a digest-less call
    still dies at the catalog gate, posture world or not)."""
    snapshot = make_snapshot(lane="native", enforcement="proven")
    native_permission_postures(snapshot, {"def1": OBSERVED_FACT})
    decision = check_tool_callable(snapshot, None, "fetch", None, now=1000.0)
    assert decision.code == PERMISSION_ARGS_DIGEST_REQUIRED


# -- counterexample 2: unproven enforcement and the posture coexist ---------------

def test_enforcement_unproven_and_posture_coexist_and_never_cancel():
    """contracts §4: a declared mechanism is not a proven per-call
    enforcement. The snapshot keeps its ``enforcement: "unproven"`` word,
    the posture keeps its display words, and the gate still refuses with
    PERMISSION_ENFORCEMENT_UNPROVEN before the authority is consulted —
    the two facts travel side by side, mutually non-exclusive."""
    snapshot = make_snapshot(lane="native", enforcement="unproven")
    posture = native_permission_postures(snapshot, {"def1": DECLARED_FACT})[0]
    view = posture_view(posture)
    # the snapshot itself is untouched by the labelling (same digest words)
    assert snapshot.lane_by_definition["def1"] == {
        "lane": "native", "enforcement": "unproven"}
    assert view["provenance"] == POSTURE_PROVENANCE_NATIVE_DECLARED
    decision = check_tool_callable(
        snapshot, None, "fetch", "sha256:args", now=1000.0,
        principal="alice", project_id="proj-1", definition_id="def1")
    assert decision.status != STATUS_ALLOWED
    assert decision.code == PERMISSION_ENFORCEMENT_UNPROVEN


def test_labelling_touches_no_snapshot_state():
    """The labelling is a pure read of the snapshot: digests, lane words
    and tool subsets are byte-stable before and after postures are built
    (no display pass can smuggle a widening into the frozen set)."""
    snapshot = make_snapshot(lane="native", enforcement="unproven")
    before = snapshot.content_for_digest()
    native_permission_postures(snapshot, {"def1": OBSERVED_FACT})
    native_permission_postures(snapshot)
    assert snapshot.content_for_digest() == before
    assert snapshot.snapshot_digest == "sha256:snapshot"
