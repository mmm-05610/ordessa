"""V06 gate: bounded preauthorization - the only path an unattended call may
take without a live UI (contracts §4: 无人值守不等于默认批准).

Every counterexample from verification.md #6 is pinned: expired grants,
cross-principal, cross-project, tool/schema changes, unknown side effects,
and "no approval UI available" must all refuse - never default-allow.
"""
from __future__ import annotations

import pytest

from backend.permissions import (
    PERMISSION_AUTHORITY_ABSENT,
    BoundedPreAuthorization,
    ToolCallDecision,
    check_tool_callable,
)

from perms_helpers import RecordingAuthority, make_snapshot

ARGS = "sha256:args-digest-abc"
NOW = 150.0  # inside the default window [100, 200]


def grant(**over):
    params = dict(
        preauth_id="preauth-1", principal="alice", definition_id="def1",
        definition_revision=1, tool_name="fetch", project_id="proj-1",
        not_before=100.0, expires_at=200.0,
        allowed_side_effect_levels=frozenset({"read-only"}),
        audit_policy="audit-basic", args_digest=ARGS, session_ref="sess-1",
        definition_digest="sha256:def1-r1",
    )
    params.update(over)
    return BoundedPreAuthorization(**params)


def call(snapshot=None, *, preauths=(), now=NOW, tool="fetch", args_digest=ARGS,
         principal="alice", project_id="proj-1", session_ref="sess-1",
         definition_id="def1", side_effect_level="read-only"):
    return check_tool_callable(
        snapshot if snapshot is not None else make_snapshot(), None, tool, args_digest, now,
        principal=principal, project_id=project_id, session_ref=session_ref,
        definition_id=definition_id, side_effect_level=side_effect_level,
        preauthorizations=preauths)


# -- the covering path -----------------------------------------------------------------


def test_exact_bound_and_live_reverified_grant_allows_without_ui():
    decision = call(preauths=(grant(),))
    assert decision.status == "allowed"
    assert decision.basis == "preauthorized"
    assert decision.preauth_id == "preauth-1"
    assert decision.expires_at == 200.0  # the audit record cites the bound window


def test_grant_is_consulted_only_after_the_catalog_gate_passed():
    authority = RecordingAuthority(ToolCallDecision.allowed(basis="authority", gate="authority"))
    decision = check_tool_callable(make_snapshot(), authority, "ghost-tool", ARGS, NOW,
                                   principal="alice", definition_id="def1",
                                   project_id="proj-1", session_ref="sess-1",
                                   side_effect_level="read-only", preauthorizations=(grant(),))
    assert decision.status == "refused"
    assert decision.gate == "catalog-subset"
    assert authority.calls == []  # a grant never overrules the frozen subset


def test_authority_present_authority_decides_grants_do_not_bypass_it():
    # a perfectly bound grant must NOT smuggle the call past a refusing authority
    authority = RecordingAuthority(ToolCallDecision.refused(
        code=PERMISSION_AUTHORITY_ABSENT, reason="denied", gate="authority"))
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW,
                                   principal="alice", preauthorizations=(grant(),))
    assert decision.status == "refused"


# -- the negative re-verifications --------------------------------------------------------

NEGATIVES = [
    ("expired", dict(now=201.0), "grant expired"),
    ("not-yet-valid", dict(now=50.0), "grant not yet valid"),
    ("cross-principal", dict(principal="mallory"), "cross-principal"),
    ("cross-project", dict(project_id="proj-2"), "cross-project"),
    ("cross-session", dict(session_ref="sess-9"), "cross-session"),
    ("cross-tool", dict(tool="write_file"), "tool name is outside"),
    ("args-changed", dict(args_digest="sha256:other"), "args digest differs"),
    ("unknown-side-effect", dict(side_effect_level=None), "unknown side-effect level"),
    ("side-effect-escalated", dict(side_effect_level="external-write"),
     "side-effect level outside the bound set"),
    ("definition-not-in-snapshot", dict(definition_id="def-z"),
     "cross-definition"),
]


@pytest.mark.parametrize("label,over,needle", NEGATIVES, ids=[n[0] for n in NEGATIVES])
def test_negative_case_refuses_before_side_effects(label, over, needle):
    kwargs = dict(preauths=(grant(),))
    kwargs.update(over)
    decision = call(**kwargs)
    assert decision.status == "refused"
    assert decision.code == PERMISSION_AUTHORITY_ABSENT
    assert any(needle in reason for _id, reason in decision.preauth_misses), (label, decision.preauth_misses)


def test_schema_change_refuses_revision_move():
    snapshot = make_snapshot(revision=2)  # snapshot froze a newer definition revision
    decision = call(snapshot=snapshot, preauths=(grant(),))
    assert decision.status == "refused"
    assert any("revision changed" in reason for _id, reason in decision.preauth_misses)


def test_schema_change_refuses_canonical_digest_move():
    snapshot = make_snapshot(canonical_digest="sha256:def1-r1-remodelled")
    decision = call(snapshot=snapshot, preauths=(grant(),))
    assert decision.status == "refused"
    assert any("canonical digest changed" in reason for _id, reason in decision.preauth_misses)


def test_unattributed_call_cannot_be_covered():
    decision = call(principal=None, project_id=None, definition_id=None)
    assert decision.status == "refused"
    assert decision.code == PERMISSION_AUTHORITY_ABSENT


def test_no_covering_grant_and_no_ui_is_refused_not_pending_allow():
    decision = call(preauths=())
    assert decision.status == "refused"
    assert decision.code == PERMISSION_AUTHORITY_ABSENT
    # nothing in the refusal promises a later allow
    assert decision.basis is None


def test_constraint_digest_grant_matches_prefix_bound_args():
    g = grant(args_digest=None, args_constraint_digest="sha256:args-digest")
    decision = call(preauths=(g,))
    assert decision.status == "allowed"


def test_allow_any_args_needs_explicit_declaration():
    g = grant(args_digest=None, allow_any_args=True)
    decision = call(args_digest="sha256:whatever", preauths=(g,))
    assert decision.status == "allowed"
    with pytest.raises(ValueError):
        grant(args_digest=None)  # unbounded args, no declaration -> not a bounded grant


# -- construction bounds -------------------------------------------------------------------


def test_grant_without_audit_policy_is_not_a_grant():
    with pytest.raises(ValueError):
        grant(audit_policy="")


def test_grant_window_must_be_forward_and_numeric():
    with pytest.raises(ValueError):
        grant(expires_at=90.0, not_before=100.0)
    with pytest.raises(ValueError):
        grant(expires_at="later")


def test_grant_levels_must_be_a_nonempty_frozen_set():
    with pytest.raises(ValueError):
        grant(allowed_side_effect_levels=frozenset())
    with pytest.raises(ValueError):
        grant(allowed_side_effect_levels=["read-only"])  # not a frozenset


def test_grant_bindings_must_be_named():
    for field in ("principal", "definition_id", "tool_name", "project_id", "preauth_id"):
        with pytest.raises(ValueError):
            grant(**{field: ""})
