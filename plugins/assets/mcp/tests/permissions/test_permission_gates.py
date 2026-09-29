"""V06 gate: the fail-closed double gate (catalog subset + final authority).

Countersource: ``docs/design/mcp/verification.md`` counterexample 6 - a
model-visible but unauthorised tool must never reach ``tools/call``; every
refusal happens before any side effect, and no UI means no default allow.
"""
from __future__ import annotations

import pytest

from backend.errors import PERMISSION_REFUSED, McpError
from backend.permissions import (
    PERMISSION_ARGS_DIGEST_REQUIRED,
    PERMISSION_AUTHORITY_ABSENT,
    PERMISSION_ENFORCEMENT_UNPROVEN,
    PermissionAuthority,
    ToolCallDecision,
    check_tool_callable,
)

from perms_helpers import RecordingAuthority, make_snapshot

ARGS = "sha256:args-digest-abc"
NOW = 1_000.0


def allowed_decision():
    return ToolCallDecision.allowed(basis="authority", gate="authority")


# -- gate matrix -----------------------------------------------------------------


def test_catalog_pass_authority_refused_stops_the_call():
    authority = RecordingAuthority(ToolCallDecision.refused(
        code=PERMISSION_REFUSED, reason="policy denies this tool", gate="authority"))
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW,
                                   principal="alice", session_ref="sess-1", lease_id="lease-1",
                                   policy_revision="pol-9")
    assert decision.status == "refused"
    assert decision.gate == "authority"
    assert decision.code == PERMISSION_REFUSED
    # the authority was consulted exactly once, with the port's full binding
    assert authority.calls == [{"principal": "alice", "session_ref": "sess-1",
                                "lease_id": "lease-1", "tool_name": "fetch",
                                "args_digest": ARGS, "policy_revision": "pol-9"}]


def test_catalog_refusal_never_reaches_the_authority():
    authority = RecordingAuthority(allowed_decision())
    decision = check_tool_callable(make_snapshot(), authority, "unapproved-tool", ARGS, NOW,
                                   principal="alice")
    assert decision.status == "refused"
    assert decision.gate == "catalog-subset"
    assert authority.calls == []  # gate 1 refused first: no consultation, no side effect


def test_both_gates_pass_is_the_only_allowed_path():
    authority = RecordingAuthority(allowed_decision())
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW,
                                   principal="alice", policy_revision="pol-9")
    assert decision.status == "allowed"
    assert decision.basis == "authority"
    assert decision.policy_revision == "pol-9"
    assert decision.decision_id  # audit references this id, never args or secrets


def test_gate1_pass_alone_is_never_callable():
    """第一门过≠可调用: the catalog says yes, nothing else was asked."""
    decision = check_tool_callable(make_snapshot(), None, "fetch", ARGS, NOW, principal="alice")
    assert decision.status == "refused"  # authority absent -> fail closed


# -- authority absence -------------------------------------------------------------


def test_authority_absent_is_typed_refusal_never_default_allow():
    decision = check_tool_callable(make_snapshot(), None, "fetch", ARGS, NOW)
    assert decision.status == "refused"
    assert decision.code == PERMISSION_AUTHORITY_ABSENT
    assert decision.preauth_misses == ()
    with pytest.raises(McpError) as raised:
        raise decision.as_error()
    assert str(raised.value) == f"{PERMISSION_AUTHORITY_ABSENT}: {decision.gate}: {decision.reason}"


def test_authority_raising_fails_closed():
    authority = RecordingAuthority(error=RuntimeError("boom"))
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW)
    assert decision.status == "refused"
    assert decision.code == PERMISSION_REFUSED
    assert decision.gate == "authority"


def test_authority_nonsense_decision_fails_closed():
    authority = RecordingAuthority(decision="not a decision")
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW)
    assert decision.status == "refused"
    assert "non-decision" in decision.reason


def test_pending_approval_is_not_approval():
    authority = RecordingAuthority(ToolCallDecision.pending(
        reason="interactive approval required", gate="authority"))
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW)
    assert decision.status == "pending-approval"
    assert decision.status != "allowed"
    with pytest.raises(McpError):
        raise decision.as_error()


def test_missing_args_digest_refused_before_everything():
    authority = RecordingAuthority(allowed_decision())
    for bad in (None, "", 123):
        decision = check_tool_callable(make_snapshot(), authority, "fetch", bad, NOW)
        assert decision.status == "refused"
        assert decision.code == PERMISSION_ARGS_DIGEST_REQUIRED
    assert authority.calls == []  # an unattributed call never even asks


def test_consumer_port_shape_is_protocol_checkable():
    assert isinstance(RecordingAuthority(allowed_decision()), PermissionAuthority)


# -- annotations are untrusted -------------------------------------------------------


def test_annotations_read_only_hint_never_opens_either_gate():
    """contracts §4 / FR 非目标: readOnlyHint 等 annotations 不构成放行输入."""
    hints = {"readOnlyHint": True, "openWorldHint": False, "idempotentHint": True}
    authority = RecordingAuthority(ToolCallDecision.refused(
        code=PERMISSION_REFUSED, reason="untrusted annotation only", gate="authority"))
    decision = check_tool_callable(make_snapshot(), authority, "fetch", ARGS, NOW,
                                   annotations=hints)
    assert decision.status == "refused"
    # same call without the hints decides identically (the glue never reads them)
    plain = check_tool_callable(make_snapshot(), RecordingAuthority(
        ToolCallDecision.refused(code=PERMISSION_REFUSED, reason="untrusted annotation only",
                                 gate="authority")), "fetch", ARGS, NOW)
    assert (plain.status, plain.code, plain.gate) == (decision.status, decision.code, decision.gate)
    absent = check_tool_callable(make_snapshot(), None, "fetch", ARGS, NOW, annotations=hints)
    assert absent.code == PERMISSION_AUTHORITY_ABSENT


def test_annotations_source_code_never_reads_them_for_a_decision():
    import ast
    import inspect

    import backend.permissions as module

    tree = ast.parse(inspect.getsource(module.check_tool_callable))
    reads = [node for node in ast.walk(tree)
             if isinstance(node, ast.Name) and node.id == "annotations"
             and isinstance(node.ctx, ast.Load)]
    assert reads == []  # only the `del annotations` store exists - never a load


# -- native-lane enforcement ----------------------------------------------------------


def test_unproven_native_enforcement_refused_before_authority():
    snapshot = make_snapshot(lane="native", enforcement="unproven")
    authority = RecordingAuthority(allowed_decision())
    decision = check_tool_callable(snapshot, authority, "fetch", ARGS, NOW,
                                   principal="alice", definition_id="def1")
    assert decision.status == "refused"
    assert decision.code == PERMISSION_ENFORCEMENT_UNPROVEN
    assert authority.calls == []  # hiding behind UI is not enforcement: no consultation


def test_proven_native_lane_proceeds_to_the_authority():
    snapshot = make_snapshot(lane="native", enforcement="proven")
    authority = RecordingAuthority(allowed_decision())
    decision = check_tool_callable(snapshot, authority, "fetch", ARGS, NOW,
                                   principal="alice", definition_id="def1")
    assert decision.status == "allowed"
    assert len(authority.calls) == 1


# -- decision hygiene -------------------------------------------------------------------


def test_refusal_shape_is_code_colon_message():
    decision = check_tool_callable(make_snapshot(), None, "fetch", ARGS, NOW)
    error = decision.as_error()
    assert isinstance(error, McpError)
    assert error.code == PERMISSION_AUTHORITY_ABSENT
    assert error.message == f"{decision.gate}: {decision.reason}"
    assert str(error) == f"{error.code}: {error.message}"


def test_decision_never_carries_the_args_digest_or_raw_args():
    raw_args = {"password": "hunter2"}
    decision = check_tool_callable(make_snapshot(), None, "fetch", ARGS, NOW,
                                   annotations=raw_args)
    assert ARGS not in repr(decision)  # digests are pointers; even they stay out of audit
    assert "hunter2" not in repr(decision)


def test_allowed_decision_requires_a_basis_and_refusals_a_code():
    with pytest.raises(ValueError):
        ToolCallDecision(status="allowed", reason="oops", basis="vibes")
    with pytest.raises(ValueError):
        ToolCallDecision(status="refused", reason="no code")
