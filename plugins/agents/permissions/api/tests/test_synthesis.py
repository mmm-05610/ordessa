"""T01 red/green: adjudication synthesis (data-model 规则合成 1..5).

This is the engine the legacy `resolve()` cannot be: identity/field trust
first, the ceiling is non-widenable, the intent selects *within* the ceiling,
equal-priority conflicts resolve deny > ask > allow, and an approval token
binds to exactly one operation.
"""
from __future__ import annotations

import datetime as dt

import pytest

from ordessa_permissions_api import (
    NO_INTENT_REVISION,
    AdminAuthorization,
    AllowedOnce,
    ApprovalState,
    AuthorizationDecision,
    BoundGrant,
    Denied,
    EffectivePolicySnapshot,
    NativeReceipt,
    PermissionIntent,
    PolicyCeiling,
    PolicyRefusal,
    PolicyRefused,
    PolicySynthesized,
    PendingApproval,
    RuleAction,
    TypedRule,
    evaluate_authorization,
    intersect_ceilings,
    synthesize,
)

NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
HEX = "b" * 64


def ceiling(**overrides: object) -> PolicyCeiling:
    base: dict = {
        "policyId": "admin-default",
        "scope": "admin",
        "revision": 3,
        "source": "signed-admin",
        "signed": True,
        "deny": [{"key": "edit", "pattern": "/etc/*"}],
        "requireApproval": [{"key": "bash"}],
        "maximumExposure": "exec",
        "effectiveFrom": "2026-09-01T00:00:00+00:00",
    }
    base.update(overrides)
    return PolicyCeiling.from_record(base)


def profile(rules: list | None = None, **overrides: object) -> PermissionIntent:
    base: dict = {
        "intentId": "profile-a",
        "revision": 2,
        "harnessId": "claude-code",
        "scope": "user",
        "desiredMode": "default",
        "rules": rules if rules is not None
        else [{"key": "bash", "pattern": None, "action": "allow"}],
    }
    base.update(overrides)
    return PermissionIntent.from_record(base)


def digest_of(*ceilings: PolicyCeiling) -> str:
    return intersect_ceilings(list(ceilings)).revision_digest


def request_for(tool: str = "bash", target: str | None = "git push origin main", *,
                ceilings: tuple[PolicyCeiling, ...] = (),
                intent: PermissionIntent | None = ...,
                **overrides: object):
    from ordessa_permissions_api import OperationRequest
    selected = list(ceilings) or [ceiling()]
    revision = (profile().revision_digest if intent is ...
                else NO_INTENT_REVISION if intent is None else intent.revision_digest)
    base: dict = {
        "principal": "user-1", "serverInstanceId": "srv-1", "sessionId": "sess-1",
        "nativeSessionId": "chan-9", "executionId": "exec-1", "nativeGeneration": "gen-3",
        "toolKey": tool, "target": target, "argumentDigest": HEX,
        "nativeRequestId": "nat-7",
        "ceilingRevision": digest_of(*selected), "policyRevision": revision,
    }
    base.update(overrides)
    return OperationRequest.from_record(base)


def decide(rules: list | None = None, *, ceilings: tuple[PolicyCeiling, ...] = (),
           tool: str = "bash", target: str | None = "git push origin main",
           no_intent: bool = False, **request_overrides: object):
    """Synthesize the default profile (or `rules`) against the default ceiling."""
    selected = list(ceilings) or [ceiling()]
    intent = None if no_intent else profile(rules)
    request = request_for(tool, target, ceilings=tuple(selected),
                          intent=None if no_intent else intent, **request_overrides)
    return synthesize(ceilings=selected, intent=intent, request=request, now=NOW)


def action_of(result) -> RuleAction:
    assert isinstance(result, PolicySynthesized), result
    assert result.action is not None
    return result.action


def code_of(result: PolicyRefused) -> str:
    assert isinstance(result, PolicyRefused)
    return result.denied.code.value


# --- rule 1: identity and field trust come first --------------------------

def test_an_unknown_tool_refuses_with_the_stable_code_and_no_inherited_default() -> None:
    result = decide(tool="rm_all")
    assert code_of(result) == "PERMISSION_UNKNOWN_TOOL"
    assert result.decision is None


def test_a_request_pinned_to_a_stale_policy_revision_refuses() -> None:
    result = decide(policyRevision="profile-a@1")
    assert code_of(result) == "POLICY_CEILING_VIOLATION"


def test_a_request_pinned_to_another_ceiling_revision_refuses() -> None:
    result = decide(ceilingRevision="admin-default@2")
    assert code_of(result) == "POLICY_CEILING_VIOLATION"


def test_no_ceiling_provider_at_all_is_a_missing_provider_not_an_open_field() -> None:
    result = synthesize(ceilings=[], intent=profile(), request=request_for(), now=NOW)
    assert code_of(result) == "POLICY_ADAPTER_MISSING"


def test_an_unverified_ceiling_refuses_an_enforcement_requiring_decision() -> None:
    # The revision pin is correct here, so the refusal can only come from trust.
    result = decide(ceilings=(PolicyCeiling.unverified("host-observed"),))
    assert code_of(result) == "POLICY_SCOPE_UNVERIFIED"


def test_a_session_record_can_neither_be_a_ceiling_nor_a_user_rule() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record({"policyId": "s", "scope": "session", "revision": 1,
                                   "source": "signed-admin", "signed": True,
                                   "deny": [], "requireApproval": [],
                                   "maximumExposure": "full",
                                   "effectiveFrom": "2026-09-01T00:00:00+00:00"})
    assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"
    with pytest.raises(PolicyRefusal) as exc2:
        profile(scope="session", rules=[{"key": "bash", "pattern": None, "action": "allow",
                                          "scope": "user"}])
    assert exc2.value.code == "POLICY_SCOPE_UNVERIFIED"


# --- rule 2: the ceiling is a non-widenable upper bound -------------------

def test_admin_deny_beats_a_profile_allow() -> None:
    result = decide(ceilings=(ceiling(deny=[{"key": "bash", "pattern": None}],
                                      requireApproval=[]),),
                    target="ls")
    assert action_of(result) is RuleAction.DENY
    assert result.decision.reason.code.value == "POLICY_CEILING_VIOLATION"


def test_a_require_approval_ceiling_never_becomes_allow_even_when_the_intent_allows() -> None:
    assert action_of(decide()) is RuleAction.ASK


def test_two_ceilings_intersect_and_the_stricter_exposure_wins() -> None:
    read_only = ceiling(policyId="ro", maximumExposure="read", deny=[], requireApproval=[])
    exec_ok = ceiling(policyId="exec", revision=5, source="host-trusted",
                      maximumExposure="exec", deny=[], requireApproval=[])
    rules = [{"key": "edit", "pattern": None, "action": "allow"}]
    result = decide(rules, ceilings=(exec_ok, read_only), tool="edit", target="src/app.ts")
    assert action_of(result) is RuleAction.DENY
    assert result.decision.reason.code.value == "POLICY_CEILING_VIOLATION"


def test_an_exposure_ceiling_below_the_tools_implied_exposure_refuses_the_allow() -> None:
    strict = ceiling(maximumExposure="read", requireApproval=[])
    assert action_of(decide(ceilings=(strict,))) is RuleAction.DENY


def test_a_ceiling_can_only_be_relaxed_by_a_higher_exposure_being_still_bounded() -> None:
    permissive = ceiling(maximumExposure="full", requireApproval=[])
    assert action_of(decide(ceilings=(permissive,))) is RuleAction.ALLOW


def test_a_wildcard_allow_in_the_intent_cannot_override_a_ceiling_deny() -> None:
    denies_push = ceiling(deny=[{"key": "bash", "pattern": "git push*"}], requireApproval=[])
    result = decide([{"key": "bash", "pattern": "git*", "action": "allow"}],
                    ceilings=(denies_push,))
    assert action_of(result) is RuleAction.DENY


# --- rule 3: no intent is not allow ---------------------------------------

def test_an_absent_intent_yields_ask_never_allow() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = decide(ceilings=(permissive,), no_intent=True)
    assert action_of(result) is RuleAction.ASK
    assert result.decision.reason.message


def test_an_intent_that_does_not_match_the_tool_still_asks() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = decide([{"key": "read", "pattern": None, "action": "allow"}],
                    ceilings=(permissive,), tool="edit", target="src/app.ts")
    assert action_of(result) is RuleAction.ASK


# --- rule 4: conflicts resolve by strictness, never by list order ---------

def test_a_later_allow_does_not_reverse_an_earlier_deny() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = decide([{"key": "bash", "pattern": None, "action": "deny"},
                     {"key": "bash", "pattern": None, "action": "allow"}],
                    ceilings=(permissive,), target="ls")
    assert action_of(result) is RuleAction.DENY


def test_ask_beats_a_plain_allow_at_equal_priority() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = decide([{"key": "bash", "pattern": None, "action": "allow"},
                     {"key": "bash", "pattern": None, "action": "ask"}],
                    ceilings=(permissive,), target="ls")
    assert action_of(result) is RuleAction.ASK


def test_a_more_specific_allow_at_equal_priority_still_loses_to_a_broad_deny() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = decide([{"key": "bash", "pattern": "git push origin main", "action": "allow"},
                     {"key": "bash", "pattern": None, "action": "deny"}],
                    ceilings=(permissive,))
    assert action_of(result) is RuleAction.DENY


def test_a_priority_widening_without_verifiable_admin_authority_is_refused() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        profile([{"key": "bash", "pattern": None, "action": "deny"},
                 {"key": "bash", "pattern": "git push origin main", "action": "allow",
                  "priority": 5}])
    assert exc.value.code == "PERMISSION_RULE_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        TypedRule.of(key="bash", action="allow", pattern="ls", priority=5)
    assert exc2.value.code == "PERMISSION_RULE_INVALID"


def authority(**overrides: object) -> AdminAuthorization:
    base: dict = {
        "issuer": "ordessa-settings", "subject": "bash", "target": "git push origin main",
        "ceilingRevision": "admin-default@3", "verified": True,
        "expiresAt": NOW + dt.timedelta(days=1),
    }
    base.update(overrides)
    return AdminAuthorization.from_record(base)


def test_a_priority_exception_with_verifiable_admin_authority_selects_allow() -> None:
    scoped = PermissionIntent.of(
        intent_id="profile-a", revision=2, harness_id="claude-code", scope="user",
        rules=[TypedRule.of(key="bash", action="deny"),
               TypedRule.of(key="bash", action="allow", pattern="git push origin main",
                            priority=5, authorization=authority())])
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = synthesize(ceilings=[permissive], intent=scoped,
                        request=request_for(ceilings=(permissive,), intent=scoped), now=NOW)
    assert action_of(result) is RuleAction.ALLOW


def test_an_expired_admin_authorization_refuses_instead_of_guessing() -> None:
    scoped = PermissionIntent.of(
        intent_id="profile-a", revision=2, harness_id="claude-code", scope="user",
        rules=[TypedRule.of(key="bash", action="deny"),
               TypedRule.of(key="bash", action="allow", pattern="git push origin main",
                            priority=5,
                            authorization=authority(expiresAt=NOW - dt.timedelta(seconds=1)))])
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = synthesize(ceilings=[permissive], intent=scoped,
                        request=request_for(ceilings=(permissive,), intent=scoped), now=NOW)
    assert code_of(result) == "POLICY_SCOPE_UNVERIFIED"


def test_an_authorization_for_another_target_refuses_this_operation() -> None:
    scoped = PermissionIntent.of(
        intent_id="profile-a", revision=2, harness_id="claude-code", scope="user",
        rules=[TypedRule.of(key="bash", action="deny"),
               TypedRule.of(key="bash", action="allow", pattern="git push origin main",
                            priority=5,
                            authorization=authority(target="git push origin other"))])
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    result = synthesize(ceilings=[permissive], intent=scoped,
                        request=request_for(ceilings=(permissive,), intent=scoped), now=NOW)
    assert code_of(result) == "POLICY_SCOPE_UNVERIFIED"


def test_an_unverifiable_authorization_object_cannot_be_constructed() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        authority(verified=False)
    assert exc.value.code == "PERMISSION_AUTHORIZATION_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        authority(issuer="")
    assert exc2.value.code == "PERMISSION_AUTHORIZATION_INVALID"


def test_an_exception_with_a_generic_matcher_is_refused_even_with_authority() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        TypedRule.of(key="bash", action="allow", pattern="git*", priority=5,
                     authorization=authority(target="*"))
    assert exc.value.code in {"PERMISSION_RULE_INVALID", "PERMISSION_PATTERN_INVALID"}


def test_an_exception_can_never_cross_the_ceiling_even_with_authority() -> None:
    scoped = PermissionIntent.of(
        intent_id="profile-a", revision=2, harness_id="claude-code", scope="user",
        rules=[TypedRule.of(key="edit", action="deny"),
               TypedRule.of(key="edit", action="allow", pattern="/etc/passwd", priority=5,
                            authorization=authority(subject="edit", target="/etc/passwd"))])
    result = synthesize(ceilings=[ceiling()], intent=scoped,
                        request=request_for("edit", "/etc/passwd", ceilings=(ceiling(),),
                                            intent=scoped),
                        now=NOW)
    assert action_of(result) is RuleAction.DENY


# --- rule 5: the approval token binds to exactly one operation ------------

def open_state(**overrides: object) -> ApprovalState:
    base: dict = {
        "approvalId": "approval_1", "sessionId": "sess-1", "executionId": "exec-1",
        "version": 1, "state": "open", "decision": None, "scope": None,
        "requestId": "dec-1", "nativeRequestId": "nat-7",
    }
    base.update(overrides)
    return ApprovalState.from_record(base)


def grant_for(request, **overrides: object) -> BoundGrant:
    base: dict = {
        "approval_id": "approval_1", "request": request,
        "expires_at": NOW + dt.timedelta(minutes=2),
    }
    base.update(overrides)
    return BoundGrant.of(**base)  # type: ignore[arg-type]


def receipt_for(request, **overrides: object) -> NativeReceipt:
    return NativeReceipt.of(native_request_id=request.native_request_id,
                            approval_id="approval_1", confirmed=True,
                            observed_at=NOW)


def test_an_asking_decision_without_a_token_is_a_pending_approval() -> None:
    result = evaluate_authorization(ceilings=[ceiling()], intent=profile(),
                                    request=request_for(), now=NOW)
    assert isinstance(result, PendingApproval)
    assert result.outcome == "pending_approval"
    assert result.approval_id.startswith("approval_")


def test_a_forged_allow_cannot_replace_the_pending_approval() -> None:
    # The DTO layer has no field a client could assert an action through, and
    # `evaluate` never returns `AllowedOnce` for a required-approval ceiling.
    result = evaluate_authorization(ceilings=[ceiling()], intent=profile(),
                                    request=request_for(), now=NOW)
    assert isinstance(result, PendingApproval)
    # Nothing in the DTO surface can carry a client-asserted action, so the only
    # way to an `AllowedOnce` here is a token that binds this exact operation.
    assert not hasattr(result, "grant")
    assert not any(name == "action" for name in vars(result))


def test_a_matching_token_lets_the_operation_through_once() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(request), approval=open_state(), receipt=receipt_for(request),
        execution_state="running", now=NOW)
    assert isinstance(result, AllowedOnce)
    assert result.grant.single_use
    assert result.grant.valid_for(request, NOW)
    assert not result.grant.consume().valid_for(request, NOW)


def test_a_token_bound_to_a_different_operation_digest_refuses_instead_of_rebinding() -> None:
    request = request_for()
    other = request_for(target="git push origin other")
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(other), approval=open_state(), receipt=receipt_for(request),
        execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_STALE"


def test_a_token_bound_to_another_native_generation_refuses() -> None:
    request = request_for()
    stale = request_for(nativeGeneration="gen-2")
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(stale), approval=open_state(), receipt=receipt_for(request),
        execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_STALE"


def test_a_token_bound_to_another_ceiling_revision_refuses() -> None:
    request = request_for()
    foreign = request_for(ceilingRevision="admin-default@9")
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(foreign), approval=open_state(), receipt=receipt_for(request),
        execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_STALE"


def test_an_expired_token_refuses_with_stale() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(request, expires_at=NOW - dt.timedelta(seconds=1)),
        approval=open_state(), receipt=receipt_for(request), execution_state="running",
        now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_STALE"


def test_a_token_without_a_recorded_approval_stays_unknown() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request, grant=grant_for(request),
        receipt=receipt_for(request), execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_RESULT_UNKNOWN"


def test_a_terminal_execution_makes_the_approval_not_actionable() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request, grant=grant_for(request),
        approval=open_state(state="settled", decision="allow", scope={"kind": "once"}),
        receipt=receipt_for(request), execution_state="completed", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_NOT_ACTIONABLE"


def test_an_invalid_approval_is_not_actionable_even_while_the_execution_runs() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request, grant=grant_for(request),
        approval=open_state(state="invalid"), receipt=receipt_for(request),
        execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_NOT_ACTIONABLE"


def test_an_unconfirmed_native_result_is_never_reported_as_allowed() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request, grant=grant_for(request),
        approval=open_state(state="settled", decision="allow", scope={"kind": "once"}),
        receipt=NativeReceipt.unknown(native_request_id=request.native_request_id,
                                      approval_id="approval_1"),
        execution_state="running", now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_RESULT_UNKNOWN"


def test_an_unknown_execution_state_is_unknown_not_a_silent_allow() -> None:
    request = request_for()
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request, grant=grant_for(request),
        approval=open_state(), receipt=receipt_for(request), execution_state="unknown",
        now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "APPROVAL_RESULT_UNKNOWN"


def test_a_hard_denied_operation_cannot_be_unlocked_by_a_token() -> None:
    scoped = profile([{"key": "edit", "pattern": None, "action": "allow"}])
    request = request_for("edit", "/etc/passwd", ceilings=(ceiling(),), intent=scoped)
    result = evaluate_authorization(
        ceilings=[ceiling()], intent=scoped, request=request, grant=grant_for(request),
        approval=open_state(), receipt=receipt_for(request), execution_state="running",
        now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "POLICY_CEILING_VIOLATION"


def test_a_profile_stated_deny_is_reported_as_a_policy_statement_not_a_ceiling_violation() -> None:
    # The stable codes must say which layer refused: a user's own deny is not
    # dressed up as an administrator-ceiling violation.
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    scoped = profile([{"key": "bash", "pattern": None, "action": "deny"}])
    result = evaluate_authorization(ceilings=[permissive], intent=scoped,
                                    request=request_for(ceilings=(permissive,), intent=scoped),
                                    now=NOW)
    assert isinstance(result, Denied)
    assert result.code.value == "policy_deny"
    assert result.code.value != "POLICY_CEILING_VIOLATION"


def test_an_allow_path_still_issues_a_single_use_grant() -> None:
    permissive = ceiling(maximumExposure="full", deny=[], requireApproval=[])
    request = request_for(ceilings=(permissive,))
    result = evaluate_authorization(ceilings=[permissive], intent=profile(),
                                    request=request, now=NOW)
    assert isinstance(result, AllowedOnce)
    assert result.grant.valid_for(request, NOW)
    assert not result.grant.valid_for(request_for(ceilings=(permissive,),
                                                   target="something else"), NOW)


def test_a_snapshot_bound_to_another_runtime_generation_is_stale() -> None:
    request = request_for()
    elsewhere = request_for(nativeGeneration="gen-4")
    foreign = synthesize(ceilings=[ceiling()], intent=profile(), request=elsewhere, now=NOW)
    assert isinstance(foreign, PolicySynthesized)
    assert foreign.snapshot.runtime_generation == "gen-4"
    evaluated = evaluate_authorization(
        ceilings=[ceiling()], intent=profile(), request=request,
        grant=grant_for(request), approval=open_state(), receipt=receipt_for(request),
        execution_state="running", snapshot=foreign.snapshot, now=NOW)
    assert isinstance(evaluated, Denied)
    assert evaluated.code.value == "APPROVAL_STALE"


# --- what comes out of a synthesis ---------------------------------------

def test_a_synthesis_result_carries_a_snapshot_bound_to_every_input_identity() -> None:
    request = request_for()
    result = synthesize(ceilings=[ceiling()], intent=profile(), request=request, now=NOW)
    assert isinstance(result, PolicySynthesized)
    snapshot = result.snapshot
    assert isinstance(snapshot, EffectivePolicySnapshot)
    assert snapshot.covers(server_instance_id=request.server_instance_id,
                           session_id=request.session_id,
                           native_session_id=request.native_session_id,
                           runtime_generation=request.native_generation,
                           principal=request.principal,
                           ceiling_revision=snapshot.ceiling_revision,
                           intent_revision=snapshot.intent_revision,
                           issued_at=snapshot.issued_at, expires_at=snapshot.expires_at)
    assert snapshot.ceiling_revision == digest_of(ceiling())
    assert snapshot.intent_revision == profile().revision_digest


def test_the_decision_is_bound_to_the_native_request_and_operation_digest() -> None:
    request = request_for()
    result = synthesize(ceilings=[ceiling()], intent=profile(), request=request, now=NOW)
    assert isinstance(result, PolicySynthesized)
    decision = result.decision
    assert isinstance(decision, AuthorizationDecision)
    assert decision.native_request_id == "nat-7"
    assert decision.operation_digest == request.operation_digest
    assert decision.subject == "user-1"
    assert decision.tool == "bash"
    assert decision.policy_digest == f"{digest_of(ceiling())}+{profile().revision_digest}"


def test_an_expired_now_makes_the_issued_decision_itself_stale() -> None:
    request = request_for()
    result = synthesize(ceilings=[ceiling()], intent=profile(), request=request, now=NOW)
    assert isinstance(result, PolicySynthesized)
    assert result.decision.alive_at(NOW)
    assert not result.decision.alive_at(NOW + dt.timedelta(hours=1))
    assert not result.snapshot.valid_at(NOW + dt.timedelta(hours=1))
