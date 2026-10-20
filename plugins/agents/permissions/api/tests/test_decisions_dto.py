"""T01 red/green: the §C1 decision/approval DTOs, with no service behind them."""
from __future__ import annotations

import datetime as dt

import pytest

from ordessa_permissions_api import (
    AlreadyRecorded,
    ApprovalDecision,
    ApprovalFact,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
    ApprovalStateKind,
    ArgumentDigest,
    AuthorizationDecision,
    BoundedApprovalScope,
    DecideResult,
    Denied,
    ExecutionState,
    InvalidApproval,
    NativeReceipt,
    OnceApprovalScope,
    OperationRequest,
    PolicyRefusal,
    QueriedApproval,
    QueryUnknown,
    Recorded,
    RuleAction,
    UnknownApproval,
)

NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
DIGEST = "a" * 64


def request_record(**overrides: object) -> dict:
    base: dict = {
        "principal": "user-1",
        "serverInstanceId": "srv-1",
        "sessionId": "sess-1",
        "nativeSessionId": "chan-9",
        "executionId": "exec-1",
        "nativeGeneration": "gen-3",
        "toolKey": "bash",
        "target": "git push origin main",
        "argumentDigest": DIGEST,
        "ceilingRevision": "admin-default@3",
        "policyRevision": "profile-a@2",
        "nativeRequestId": "nat-7",
    }
    base.update(overrides)
    return base


def make_request(**overrides: object) -> OperationRequest:
    return OperationRequest.from_record(request_record(**overrides))


# --- request facts ---------------------------------------------------------

def test_a_complete_request_is_accepted_and_exposes_its_operation_digest() -> None:
    request = make_request()
    assert request.tool_key == "bash"
    assert len(request.operation_digest) == 64
    assert request.operation_digest == make_request().operation_digest
    assert request.operation_digest != make_request(target="git push origin other").operation_digest


def test_argument_digest_holds_a_digest_and_never_the_arguments() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        ArgumentDigest.of("rm -rf / --no-preserve-root")
    assert exc.value.code == "PERMISSION_REQUEST_INVALID"
    assert "rm -rf" not in str(exc.value)


@pytest.mark.parametrize("bad", ["", "a" * 63, "z" * 64, None, 7, DIGEST.upper() + "0"])
def test_a_malformed_argument_digest_is_refused(bad: object) -> None:
    with pytest.raises(PolicyRefusal) as exc:
        ArgumentDigest.of(bad)  # type: arg-type
    assert exc.value.code == "PERMISSION_REQUEST_INVALID"


@pytest.mark.parametrize("field", [
    "principal", "serverInstanceId", "sessionId", "nativeSessionId", "executionId",
    "nativeGeneration", "toolKey", "argumentDigest", "ceilingRevision",
    "policyRevision", "nativeRequestId",
])
def test_a_request_missing_any_trusted_field_fails_closed(field: str) -> None:
    # data-model rule 1: an unreliable field is deny/unknown, never inherited.
    with pytest.raises(PolicyRefusal) as exc:
        make_request(**{field: None})
    assert exc.value.code == "PERMISSION_REQUEST_INVALID"
    assert field in str(exc.value)


def test_an_unknown_request_field_is_refused() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        make_request(preset="full-access")
    assert exc.value.code == "PERMISSION_REQUEST_INVALID"


def test_target_is_the_only_optional_fact_and_a_blank_one_is_not_a_target() -> None:
    assert make_request(target=None).target is None
    with pytest.raises(PolicyRefusal):
        make_request(target="  ")


# --- authorization decision ------------------------------------------------

def test_a_decision_is_bound_to_one_operation_and_carries_an_expiry() -> None:
    decision = AuthorizationDecision.of(
        native_request_id="nat-7", operation_digest=DIGEST, tool="bash",
        target="git push origin main", subject="user-1", action=RuleAction.ASK,
        reason="ceiling requires approval", policy_digest="admin-default@3+profile-a@2",
        expires_at=NOW + dt.timedelta(minutes=2),
    )
    assert decision.action is RuleAction.ASK
    assert decision.expires_at > NOW
    assert decision.alive_at(NOW + dt.timedelta(minutes=1))
    assert not decision.alive_at(NOW + dt.timedelta(minutes=3))


def test_a_decision_without_expiry_or_reason_is_refused() -> None:
    for bad in ({"expires_at": None}, {"reason": None}, {"reason": "  "}):
        kwargs = {
            "native_request_id": "nat-7", "operation_digest": DIGEST, "tool": "bash",
            "target": None, "subject": "user-1", "action": RuleAction.ASK,
            "reason": "x", "policy_digest": "p@1", "expires_at": NOW,
        } | bad
        with pytest.raises(PolicyRefusal) as exc:
            AuthorizationDecision.of(**kwargs)  # type: ignore[arg-type]
        assert exc.value.code == "PERMISSION_DECISION_INVALID"


# --- approval DTOs ---------------------------------------------------------

def approval_record(**overrides: object) -> dict:
    base: dict = {
        "approvalId": "approval_1",
        "sessionId": "sess-1",
        "executionId": "exec-1",
        "nativeRequestId": "nat-7",
        "operationDigest": DIGEST,
        "toolKey": "bash",
        "target": "git push origin main",
        "ceilingRevision": "admin-default@3",
        "policyRevision": "profile-a@2",
        "nativeGeneration": "gen-3",
        "requestedAt": NOW,
        "expiresAt": NOW + dt.timedelta(minutes=3),
        "version": 1,
    }
    base.update(overrides)
    return base


def test_an_approval_request_is_bound_to_the_operation_and_expires() -> None:
    approval = ApprovalRequest.from_record(approval_record())
    assert approval.version == 1
    assert approval.expires_at > approval.requested_at
    assert approval.bound_to(operation_digest=DIGEST, policy_revision="profile-a@2",
                             native_generation="gen-3", ceiling_revision="admin-default@3")
    assert not approval.bound_to(operation_digest="b" * 64, policy_revision="profile-a@2",
                                 native_generation="gen-3", ceiling_revision="admin-default@3")


def test_an_approval_request_shape_is_strict() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        ApprovalRequest.from_record(approval_record(autoApprove=True))
    assert exc.value.code == "PERMISSION_APPROVAL_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        ApprovalRequest.from_record(approval_record(expiresAt=None))
    assert exc2.value.code == "PERMISSION_APPROVAL_INVALID"


def test_approval_states_keep_the_persisted_vocabulary() -> None:
    # `server_approvals` stores open/settled/invalid; the DTO must not rename it.
    assert {kind.value for kind in ApprovalStateKind} == {"open", "settled", "invalid"}
    assert ApprovalDecision.ALLOW.value == "allow"
    assert ApprovalDecision.DENY.value == "deny"


def state(**overrides: object) -> ApprovalState:
    base: dict = {
        "approvalId": "approval_1", "sessionId": "sess-1", "executionId": "exec-1",
        "version": 2, "state": "open", "decision": None, "scope": None,
        "requestId": "dec-1", "nativeRequestId": "nat-7",
    } | overrides
    return ApprovalState.from_record(base)


def test_an_approval_state_reports_actionability_and_version() -> None:
    assert state().is_open
    assert state().version == 2
    assert not state(state="settled", decision="allow",
                    scope={"kind": "once"}).is_open
    assert not state(state="invalid").is_open


def test_a_settled_state_without_a_decision_is_a_shape_error() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        state(state="settled", decision=None)
    assert exc.value.code == "PERMISSION_APPROVAL_INVALID"


def test_approval_scope_keeps_the_wire_vocabulary_and_refuses_extra_keys() -> None:
    once = ApprovalScope.from_record({"kind": "once"})
    assert once == OnceApprovalScope()
    bounded = ApprovalScope.from_record(
        {"kind": "bounded", "until": "session_end", "environmentId": "env-1"})
    assert isinstance(bounded, BoundedApprovalScope)
    with pytest.raises(PolicyRefusal) as exc:
        ApprovalScope.from_record({"kind": "once", "until": "forever"})
    assert exc.value.code == "PERMISSION_APPROVAL_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        ApprovalScope.from_record({"kind": "always"})
    assert exc2.value.code == "PERMISSION_APPROVAL_INVALID"


def test_a_native_receipt_records_corroboration_without_inventing_it() -> None:
    confirmed = NativeReceipt.of(native_request_id="nat-7", approval_id="approval_1",
                                 confirmed=True, observed_at=NOW)
    assert confirmed.confirmed
    unconfirmed = NativeReceipt.unknown(native_request_id="nat-7", approval_id="approval_1")
    assert not unconfirmed.confirmed
    assert unconfirmed.observed_at is None
    with pytest.raises(PolicyRefusal) as exc:
        NativeReceipt.of(native_request_id=None, approval_id="approval_1",
                         confirmed=True, observed_at=NOW)
    assert exc.value.code == "PERMISSION_APPROVAL_INVALID"


def test_an_approval_fact_is_the_queryable_union_of_the_above() -> None:
    fact = ApprovalFact.of(
        request=ApprovalRequest.from_record(approval_record()),
        state=state(state="settled", decision="allow", scope={"kind": "once"}),
        receipt=NativeReceipt.unknown(native_request_id="nat-7", approval_id="approval_1"),
    )
    assert fact.approval_id == "approval_1"
    assert fact.settled
    assert not fact.native_confirmed
    assert fact.operation_digest == DIGEST


def test_a_fact_must_have_matching_identity_fields() -> None:
    request = ApprovalRequest.from_record(approval_record())
    with pytest.raises(PolicyRefusal) as exc:
        ApprovalFact.of(request=request, state=state(approvalId="approval_other"),
                        receipt=None)
    assert exc.value.code == "PERMISSION_APPROVAL_INVALID"


# --- decide / query result unions -----------------------------------------

def test_decide_results_are_four_distinct_outcomes() -> None:
    outcomes = [
        Recorded(version=3, decision=ApprovalDecision.ALLOW),
        AlreadyRecorded(version=3, decision=ApprovalDecision.ALLOW, request_id="dec-1"),
        InvalidApproval(reason="APPROVAL_NOT_ACTIONABLE"),
        UnknownApproval(reason="transport closed before an answer arrived"),
    ]
    assert {result.kind for result in outcomes} == {
        "recorded", "already_recorded", "invalid", "unknown"}
    assert all(isinstance(result, DecideResult) for result in outcomes)


def test_unknown_is_never_folded_into_invalid_or_into_allow() -> None:
    unknown = UnknownApproval(reason="no answer")
    assert not isinstance(unknown, InvalidApproval)
    assert unknown.kind == "unknown"
    assert not unknown.grants_execution
    assert Recorded(version=2, decision=ApprovalDecision.DENY).grants_execution is False
    assert Recorded(version=2, decision=ApprovalDecision.ALLOW).grants_execution is True


def test_query_results_keep_the_state_and_receipt_apart() -> None:
    queried = QueriedApproval(
        state=state(), receipt=NativeReceipt.unknown(native_request_id="nat-7",
                                                     approval_id="approval_1"))
    assert queried.state.is_open
    assert not queried.native_confirmed
    missing = QueryUnknown(reason="APPROVAL_RESULT_UNKNOWN")
    assert missing.kind == "unknown"
    assert not isinstance(missing, QueriedApproval)


def test_denied_carries_a_stable_code_and_an_evidence_reference() -> None:
    denied = Denied.of(code="APPROVAL_STALE", evidence_ref="evid_1",
                       reason="the grant no longer refers to this operation")
    assert denied.code.value == "APPROVAL_STALE"
    assert denied.evidence_ref == "evid_1"
    assert denied.outcome == "denied"
    with pytest.raises(PolicyRefusal) as exc:
        Denied.of(code="MY_OWN_CODE", evidence_ref="evid_1")
    assert exc.value.code == "PERMISSION_DECISION_INVALID"


def test_execution_state_vocabulary_is_closed_and_terminal_states_are_known() -> None:
    assert ExecutionState.of("running").actionable
    for terminal in ("completed", "failed", "cancelled"):
        assert not ExecutionState.of(terminal).actionable
    assert ExecutionState.of("unknown").outcome_is_resolved is False
    with pytest.raises(PolicyRefusal) as exc:
        ExecutionState.of("paused")
    assert exc.value.code == "PERMISSION_REQUEST_INVALID"
