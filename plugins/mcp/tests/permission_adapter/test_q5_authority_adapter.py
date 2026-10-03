"""T06-wiring proof: the adapter over the REAL Q5 backend serves Q4's gate.

Every expectation states the genuine Q5 outcome the authority produced
(``q5.AllowedOnce`` / ``q5.PendingApproval`` / ``q5.Denied`` carrying
``q5.RefusalCode`` / ``q5.PolicyDenyCode`` members, ``q5.BoundGrant``
bindings, approval ids recomputed through ``q5.approval_id_for`` over an
``OperationRequest`` rebuilt with the lane's own support builders) - never a
string guess about what Q5 "probably" answers.
"""
from __future__ import annotations

import datetime as dt

import pytest

import ordessa_permissions_api as q5
from pa_shared import NOW, default_binding, expected_operation, intent_allowing, \
    snapshot_with, table_provider
from backend.errors import PERMISSION_REFUSED
from backend.permission_adapter import Q5PermissionAuthority, Q5RequestBinding
from backend.permissions import (
    PERMISSION_ARGS_DIGEST_REQUIRED,
    STATUS_ALLOWED,
    STATUS_PENDING_APPROVAL,
    STATUS_REFUSED,
    PermissionAuthority,
    check_tool_callable,
)

HEX64 = "b" * 64
SHA_DIG = "sha256:" + HEX64


def wire(world, *, intent=None, tool_key_map=None, bindings=None):
    authorizer = world.make_authorizer(intent=intent)
    adapter = world.make_adapter(authorizer=authorizer, intent=intent,
                                 tool_key_map=tool_key_map, bindings=bindings)
    return adapter, authorizer


# -- protocol conformance -------------------------------------------------------


def test_the_adapter_satisfies_the_q4_consumer_port():
    built = Q5PermissionAuthority(authorizer=object(), binding_provider=lambda **k: None)
    assert isinstance(built, PermissionAuthority)  # runtime_checkable port


# -- cell: allow -> the Q4 gate passes the call through --------------------------


def test_q5_allow_flows_through_the_double_gate_as_allowed(world):
    intent = intent_allowing(rules=(q5.TypedRule(
        tool=q5.ToolIdentity("read"), action=q5.RuleAction.ALLOW),))
    adapter, authorizer = wire(world, intent=intent, tool_key_map={"fs_read": "read"})

    decision = check_tool_callable(
        snapshot_with(("fs_read",)), adapter, "fs_read", SHA_DIG, NOW.timestamp(),
        principal="user-1", session_ref="session-1", lease_id="lease-1",
        definition_id="def1")
    assert decision.status == STATUS_ALLOWED
    assert decision.basis == "authority"
    assert decision.policy_revision == intent.revision_digest

    inputs, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.AllowedOnce)
    grant = outcome.grant
    assert isinstance(grant, q5.BoundGrant) and grant.single_use
    # the allowed decision carries the REAL grant's expiry, not a local default
    assert decision.expires_at == grant.expires_at.timestamp()
    assert grant.expires_at == NOW + q5.GRANT_TTL
    # the operation the authority actually ruled on is the one the seam implies
    op = expected_operation(ceilings=world.policies.ceilings_current(), intent=intent,
                            tool_key="read", argument_digest=HEX64)
    assert inputs["argument_digest"] == q5.ArgumentDigest(HEX64)
    assert grant.operation_digest == op.operation_digest
    assert grant.ceiling_revision == inputs["ceiling_revision"]
    assert grant.policy_revision == intent.revision_digest


def test_bare_and_prefixed_digests_are_the_same_operation(world):
    intent = intent_allowing(rules=(q5.TypedRule(
        tool=q5.ToolIdentity("read"), action=q5.RuleAction.ALLOW),))
    adapter, authorizer = wire(world, intent=intent, tool_key_map={"fs_read": "read"})
    first = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                        lease_id="l", tool_name="fs_read",
                                        args_digest=SHA_DIG, policy_revision=None)
    second = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                         lease_id="l", tool_name="fs_read",
                                         args_digest=HEX64, policy_revision=None)
    assert (first.status, second.status) == (STATUS_ALLOWED, STATUS_ALLOWED)
    digests = {c[1].grant.operation_digest for c in authorizer.consultations}
    assert len(digests) == 1  # the sha256: prefix is spelling, not a new operation


def test_catalog_gate_refusal_never_consults_q5(world):
    adapter, authorizer = wire(world, tool_key_map={"fs_read": "read"})
    decision = check_tool_callable(snapshot_with(()), adapter, "fs_read", SHA_DIG,
                                   NOW.timestamp(), principal="user-1",
                                   session_ref="session-1", lease_id="lease-1",
                                   definition_id="def1")
    assert decision.status == STATUS_REFUSED
    assert decision.gate == "catalog-subset"
    assert authorizer.consultations == []  # 拒绝先于副作用：Q5 零咨询


# -- cell: malformed digest is refused BEFORE Q5 is consulted --------------------


def test_unusable_args_digest_refused_before_the_authority(world):
    adapter, authorizer = wire(world)
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest="printenv SECRET",
                                           policy_revision=None)
    assert decision.status == STATUS_REFUSED
    assert decision.code == PERMISSION_ARGS_DIGEST_REQUIRED
    assert authorizer.consultations == []


def test_unattributable_call_refused_before_the_authority(world):
    adapter = Q5PermissionAuthority(
        authorizer=world.make_authorizer(), binding_provider=lambda **k: None,
        ceiling_provider=world.policies.ceilings_current)
    spy = adapter._authorizer
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="no-such",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest=SHA_DIG, policy_revision=None)
    assert decision.status == STATUS_REFUSED
    assert "[unknown]" in decision.reason
    assert spy.consultations == []


# -- cell: pending approval is refused, never allowed unattended -----------------


def test_q5_pending_approval_maps_to_refused_pending(world):
    # No intent at all: Q5's rule 3 - "no matching rule is never an allow".
    adapter, authorizer = wire(world, tool_key_map={"fs_read": "read"})
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest=SHA_DIG, policy_revision=None)
    _, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.PendingApproval)
    assert decision.status == STATUS_PENDING_APPROVAL
    assert decision.code == PERMISSION_REFUSED
    assert "[pending]" in decision.reason
    assert decision.policy_revision == q5.NO_INTENT_REVISION
    # the pending really was recorded by the backend service (its §C1 job):
    op = expected_operation(ceilings=world.policies.ceilings_current(), intent=None,
                            tool_key="read", argument_digest=HEX64)
    approval_id = q5.approval_id_for(operation_digest=op.operation_digest,
                                     native_request_id="native-req-1")
    assert outcome.approval_id == approval_id
    assert world.facts.peek(approval_id)["state"] == "open"
    # and pending is NOT callable through the double gate either
    gated = check_tool_callable(snapshot_with(("fs_read",)), adapter, "fs_read",
                                SHA_DIG, NOW.timestamp(), principal="user-1",
                                session_ref="session-1", lease_id="l",
                                definition_id="def1")
    assert gated.status == STATUS_PENDING_APPROVAL


# -- cell: denials ----------------------------------------------------------------


def test_intent_deny_maps_to_refused_denied(world):
    intent = intent_allowing(rules=(q5.TypedRule(
        tool=q5.ToolIdentity("bash"), action=q5.RuleAction.DENY),))
    adapter, authorizer = wire(world, intent=intent, tool_key_map={"shell": "bash"})
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="shell",
                                           args_digest=SHA_DIG, policy_revision=None)
    _, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.Denied)
    assert outcome.code is q5.PolicyDenyCode.POLICY_DENY
    assert decision.status == STATUS_REFUSED
    assert decision.code == PERMISSION_REFUSED
    assert "[denied]" in decision.reason and q5.POLICY_DENY.value in decision.reason


def test_admin_ceiling_deny_beats_an_intent_allow(world):
    hard = world.store_ceiling_record({
        "policyId": "ceil-hard", "scope": "admin", "revision": 1,
        "source": "signed-admin", "signed": True, "maximumExposure": "full",
        "effectiveFrom": "2020-01-01T00:00:00+00:00",
        "deny": [{"key": "edit", "pattern": "/etc/*"}]})
    intent = intent_allowing(rules=(q5.TypedRule(
        tool=q5.ToolIdentity("edit"), action=q5.RuleAction.ALLOW),))
    adapter, authorizer = wire(world, intent=intent, tool_key_map={"patch": "edit"},
                               bindings={"session-1": default_binding(target="/etc/hosts")})
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="patch",
                                           args_digest=SHA_DIG, policy_revision=None)
    _, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.Denied)
    assert outcome.code is q5.RefusalCode.POLICY_CEILING_VIOLATION
    assert decision.status == STATUS_REFUSED and "[denied]" in decision.reason
    # the ceiling in force is the INTERSECTION (never "last one wins")
    effective = q5.intersect_ceilings(
        [world.policies.ceiling("admin", 1), hard])
    assert effective.blocks("edit", "/etc/hosts")


def test_valid_admin_authorization_never_widens_a_ceiling_deny(world):
    """Q5's own exception ticket unlocks intent-internal priority only; behind
    this adapter a hard ceiling deny stays denied."""

    def intent_with_ticket_against(ceilings):
        digest = q5.intersect_ceilings(list(ceilings)).revision_digest
        authorization = q5.AdminAuthorization.of(
            issuer="root", subject="edit", target="/etc/hosts",
            ceiling_revision=digest, verified=True,
            expires_at=(NOW + dt.timedelta(hours=1)).isoformat())
        intent = intent_allowing(rules=(q5.TypedRule.of(
            key="edit", action="allow", pattern="/etc/hosts", priority=5,
            scope="session", authorization=authorization),))
        assert intent.rules[0].authorization is not None  # ticket really attached
        return intent

    world.store_ceiling_record({
        "policyId": "ceil-hard", "scope": "admin", "revision": 1,
        "source": "signed-admin", "signed": True, "maximumExposure": "full",
        "effectiveFrom": "2020-01-01T00:00:00+00:00",
        "deny": [{"key": "edit", "pattern": "/etc/*"}]})
    intent = intent_with_ticket_against(world.policies.ceilings_current())
    adapter, authorizer = wire(world, intent=intent, tool_key_map={"patch": "edit"},
                               bindings={"session-1": default_binding(target="/etc/hosts")})
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="patch",
                                           args_digest=SHA_DIG, policy_revision=None)
    _, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.Denied)
    assert outcome.code is q5.RefusalCode.POLICY_CEILING_VIOLATION
    assert decision.status == STATUS_REFUSED
    # asymmetric control: with the SAME ticket but no ceiling entry the intent
    # exception DOES allow - the denial above speaks for the ceiling, not for
    # a broken wiring.
    world2 = world.__class__.build(world.root.parent / "world2")
    intent2 = intent_with_ticket_against(world2.policies.ceilings_current())
    authorizer2 = world2.make_authorizer(intent=intent2)
    adapter2 = world2.make_adapter(authorizer=authorizer2, intent=intent2,
                                   tool_key_map={"patch": "edit"},
                                   bindings={"session-1": default_binding(
                                       target="/etc/hosts")})
    control = adapter2.authorize_tool_call(
        principal="user-1", session_ref="session-1", lease_id="l", tool_name="patch",
        args_digest=SHA_DIG, policy_revision=None)
    assert control.status == STATUS_ALLOWED


def test_unmapped_mcp_tool_name_refused_as_unknown_by_q5_itself(world):
    adapter, authorizer = wire(world)  # no tool_key_map: identity spelling
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="mcp__weird__thing",
                                           args_digest=SHA_DIG, policy_revision=None)
    _, outcome = authorizer.consultations[-1]
    assert isinstance(outcome, q5.Denied)
    assert outcome.code is q5.RefusalCode.PERMISSION_UNKNOWN_TOOL
    assert decision.status == STATUS_REFUSED and "[unknown]" in decision.reason


# -- cell: expiry (stale decision / spent or expired grant) ----------------------


def _settle_allow_with_receipt(world, *, native_request_id="native-req-1",
                               tool_key="read"):
    """Drive the REAL approval loop: pending -> user allow -> native receipt."""
    adapter, authorizer = wire(world, tool_key_map={"fs_read": tool_key},
                               bindings={"session-1": default_binding(
                                   native_request_id=native_request_id)})
    pending = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                          lease_id="l", tool_name="fs_read",
                                          args_digest=SHA_DIG, policy_revision=None)
    assert pending.status == STATUS_PENDING_APPROVAL
    op = expected_operation(ceilings=world.policies.ceilings_current(), intent=None,
                            tool_key=tool_key, argument_digest=HEX64,
                            native_request_id=native_request_id)
    approval_id = q5.approval_id_for(operation_digest=op.operation_digest,
                                     native_request_id=native_request_id)
    recorded = world.facts.decide(approval_id=approval_id, decision="allow",
                                  scope={"kind": "once"}, expected_version=1,
                                  request_id=f"decide-{native_request_id}", now=NOW)
    assert isinstance(recorded, q5.Recorded)
    world.facts.record_native_receipt(approval_id, q5.NativeReceipt.of(
        native_request_id=native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=NOW))
    return adapter, approval_id, op


def test_approved_grant_allows_once_then_expired(world):
    adapter, approval_id, _op = _settle_allow_with_receipt(world)
    first = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                        lease_id="l", tool_name="fs_read",
                                        args_digest=SHA_DIG, policy_revision=None)
    assert first.status == STATUS_ALLOWED
    second = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                         lease_id="l", tool_name="fs_read",
                                         args_digest=SHA_DIG, policy_revision=None)
    assert second.status == STATUS_REFUSED
    assert "[expired]" in second.reason
    assert q5.RefusalCode.APPROVAL_STALE.value in second.reason
    assert world.facts.grant_fields(approval_id)["consumed"] is True


def test_grant_past_its_expiry_is_expired_not_allow(world):
    adapter, _approval_id, _op = _settle_allow_with_receipt(
        world, native_request_id="native-req-clock")
    world.clock.advance(q5.GRANT_TTL + dt.timedelta(minutes=1))
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest=SHA_DIG, policy_revision=None)
    assert decision.status == STATUS_REFUSED
    assert "[expired]" in decision.reason
    assert q5.RefusalCode.APPROVAL_STALE.value in decision.reason


# -- cell: a grant never travels to another principal or session ------------------


def test_cross_principal_cannot_spend_another_users_approval(world):
    adapter, approval_id, _op = _settle_allow_with_receipt(
        world, native_request_id="native-req-xp")
    other_binding = default_binding(native_request_id="native-req-xp-other")
    other_adapter = world.make_adapter(
        authorizer=world.make_authorizer(), tool_key_map={"fs_read": "read"},
        bindings={"session-1": other_binding})
    foreign = other_adapter.authorize_tool_call(
        principal="user-2", session_ref="session-1", lease_id="l", tool_name="fs_read",
        args_digest=SHA_DIG, policy_revision=None)
    assert foreign.status != STATUS_ALLOWED  # its own pending, never user-1's yes
    assert world.facts.grant_fields(approval_id)["consumed"] is False
    # user-1's grant is untouched and still spends for user-1
    mine = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                       lease_id="l", tool_name="fs_read",
                                       args_digest=SHA_DIG, policy_revision=None)
    assert mine.status == STATUS_ALLOWED


def test_cross_session_cannot_spend_another_sessions_approval(world):
    adapter, approval_id, _op = _settle_allow_with_receipt(
        world, native_request_id="native-req-xs")
    session_two = Q5RequestBinding(
        server_instance_id="srv-1", session_id="session-2",
        native_session_id="native-session-session-2", execution_id="turn-2",
        native_generation="gen-1", native_request_id="native-req-xs-s2")
    other_adapter = world.make_adapter(
        authorizer=world.make_authorizer(), tool_key_map={"fs_read": "read"},
        bindings={"session-2": session_two})
    foreign = other_adapter.authorize_tool_call(
        principal="user-1", session_ref="session-2", lease_id="l2",
        tool_name="fs_read", args_digest=SHA_DIG, policy_revision=None)
    assert foreign.status != STATUS_ALLOWED
    assert world.facts.grant_fields(approval_id)["consumed"] is False
    mine = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                       lease_id="l", tool_name="fs_read",
                                       args_digest=SHA_DIG, policy_revision=None)
    assert mine.status == STATUS_ALLOWED


# -- cell: the Q5 service breaking is a refusal, never a crash or an allow --------


def test_q5_service_raising_fails_closed_through_the_double_gate(world):
    adapter, _authorizer = wire(world, tool_key_map={"fs_read": "read"})
    # Break the REAL store underneath the real Authorizer: the exception must
    # travel through Q5 and land as a typed refusal (fault injection without
    # mocking Q5's semantics).
    with world.database.transaction() as conn:
        conn.execute("DROP TABLE server_approvals")
    decision = check_tool_callable(snapshot_with(("fs_read",)), adapter, "fs_read",
                                   SHA_DIG, NOW.timestamp(), principal="user-1",
                                   session_ref="session-1", lease_id="l",
                                   definition_id="def1")
    assert decision.status == STATUS_REFUSED
    assert decision.code == PERMISSION_REFUSED
    assert "[unknown]" in decision.reason


def test_missing_ceiling_provider_refuses_without_consulting(world):
    spy = world.make_authorizer()
    adapter = Q5PermissionAuthority(
        authorizer=spy, binding_provider=table_provider(
            {"session-1": default_binding()}))
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest=SHA_DIG, policy_revision=None)
    assert decision.status == STATUS_REFUSED and "[unknown]" in decision.reason
    assert spy.consultations == []


def test_empty_ceiling_set_refuses_as_adapter_missing(world):
    spy = world.make_authorizer()
    adapter = Q5PermissionAuthority(
        authorizer=spy, binding_provider=table_provider(
            {"session-1": default_binding()}),
        ceiling_provider=lambda: ())
    decision = adapter.authorize_tool_call(principal="user-1", session_ref="session-1",
                                           lease_id="l", tool_name="fs_read",
                                           args_digest=SHA_DIG, policy_revision=None)
    assert decision.status == STATUS_REFUSED
    assert q5.RefusalCode.POLICY_ADAPTER_MISSING.value in decision.reason
    assert spy.consultations == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
