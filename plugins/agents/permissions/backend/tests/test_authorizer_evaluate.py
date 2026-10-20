"""T02: the §C1 authorizer service rulings — fail-closed everywhere.

`evaluate` delegates the ruling to `evaluate_authorization`/`synthesize` and
the record-keeping to `ApprovalFacts`/`PolicyRepository`. Missing ceiling
provider, unknown tool, forged grant, unresolved execution, missing native
receipt — each refuses with the stable §C4 codes and never with a quiet allow;
each negative has a positive counterpart in this file.

The real pre-effect execution gate is NOT wired here: that seam is C0-owned
and still blocked (api-requests G1). These tests prove the ruling surface;
they do not claim a tool side-effect was intercepted end to end.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import (NativeReceipt, RefusalCode, approval_id_for)
from support import (admin_ceiling, approval_record, clock_at, effective_digest,
                     make_operation, seeded_database, seed_session, set_turn_state, utc)

from ordessa_permissions_backend import ApprovalFacts, Authorizer, PolicyRepository


@pytest.fixture
def wired(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    policies.store_ceiling(admin_ceiling())
    authorizer = Authorizer(facts=facts, policies=policies,
                            ceiling_provider=policies.ceilings_current,
                            intent_provider=lambda: None,
                            clock=clock_at(utc()))
    return database, facts, policies, authorizer


def _evaluate(authorizer, *, ceilings_holder=None, tool_key="bash", target=None,
              native_request_id="native-e", session_id="session-1",
              execution_id="turn-1", revisions=None, intent=None):
    ceilings = ceilings_holder if ceilings_holder is not None else ()
    digest = effective_digest(ceilings) if ceilings else "none"
    policy_revision = "no-intent" if intent is None else intent.revision_digest
    if revisions is not None:
        digest, policy_revision = revisions
    operation = make_operation(ceilings=ceilings or [admin_ceiling()], intent=intent,
                               tool_key=tool_key,
                               target=target, native_request_id=native_request_id,
                               session_id=session_id, execution_id=execution_id)
    # The pins the caller carries are what `evaluate` must re-check, not the
    # ones the helper used to build the digest, when the caller means to forge.
    return operation, authorizer.evaluate(
        principal=operation.principal,
        session_ref={"serverInstanceId": operation.server_instance_id,
                     "sessionId": operation.session_id,
                     "nativeSessionId": operation.native_session_id},
        execution_ref=operation.execution_id,
        native_generation=operation.native_generation,
        tool_identity=operation.tool_key,
        target_facts={"target": operation.target},
        argument_digest=operation.argument_digest.value,
        ceiling_revision=digest,
        policy_revision=policy_revision,
        native_request_id=operation.native_request_id,
    )


def test_ask_produces_a_pending_approval_backed_by_a_recorded_fact(wired):
    database, facts, policies, authorizer = wired
    operation, outcome = _evaluate(authorizer, ceilings_holder=policies.ceilings_current())
    assert outcome.outcome == "pending_approval"
    row = facts.get(outcome.approval_id)
    assert row["state"] == "open"
    assert row["operationDigest"] == operation.operation_digest
    assert outcome.approval_id == approval_id_for(
        operation_digest=operation.operation_digest,
        native_request_id=operation.native_request_id)


def test_allow_within_a_permissive_ceiling_is_allowed_once(wired):
    from ordessa_permissions_api import PermissionIntent
    database, facts, policies, authorizer = wired
    intent = PermissionIntent.from_record({
        "intentId": "profile", "revision": 1, "harnessId": "pi", "scope": "project",
        "rules": [{"key": "read", "action": "allow"}],
    })
    policies.store_intent(intent)
    authorizer.intent_provider = lambda: policies.intent_current("profile")
    operation, outcome = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                                   tool_key="read", intent=intent)
    assert outcome.outcome == "allowed_once"
    assert outcome.grant.operation_digest == operation.operation_digest


def test_missing_ceiling_provider_denies_with_policy_adapter_missing(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    policies = PolicyRepository(database)
    policies.ensure_schema()
    authorizer = Authorizer(facts=facts, policies=policies,
                            ceiling_provider=lambda: (), intent_provider=lambda: None,
                            clock=clock_at(utc()))
    _, outcome = _evaluate(authorizer)
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.POLICY_ADAPTER_MISSING


def test_ceiling_provider_raising_fails_closed(wired):
    database, facts, policies, authorizer = wired

    def broken_provider():
        raise RuntimeError("provider is down")

    authorizer.ceiling_provider = broken_provider
    _, outcome = _evaluate(authorizer)
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.POLICY_ADAPTER_MISSING


def test_unknown_tool_denies_with_permission_unknown_tool(wired):
    database, facts, policies, authorizer = wired
    _, outcome = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                           tool_key="teleport")
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.PERMISSION_UNKNOWN_TOOL


def test_terminal_execution_denies_approval_not_actionable(wired):
    database, facts, policies, authorizer = wired
    set_turn_state(database, "turn-1", "completed")
    _, outcome = _evaluate(authorizer, ceilings_holder=policies.ceilings_current())
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.APPROVAL_NOT_ACTIONABLE


def test_unresolved_execution_denies_approval_result_unknown(wired):
    database, facts, policies, authorizer = wired
    _, outcome = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                           execution_id="turn-does-not-exist")
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.APPROVAL_RESULT_UNKNOWN


def test_forged_grant_without_any_approval_record_is_denied(wired):
    """A client cannot mint `allow`: without a recorded approval, even a
    well-shaped grant token reads as APPROVAL_RESULT_UNKNOWN, never as yes."""
    database, facts, policies, authorizer = wired
    operation, pending = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                                   native_request_id="native-f")
    forged_id = approval_id_for(operation_digest=operation.operation_digest,
                                native_request_id="native-f")
    outcome = authorizer.evaluate_with_grant(
        operation=operation,
        grant_fields={"approvalId": forged_id,
                      "operationDigest": operation.operation_digest,
                      "target": operation.target,
                      "ceilingRevision": operation.ceiling_revision,
                      "policyRevision": operation.policy_revision,
                      "nativeGeneration": operation.native_generation,
                      "expiresAt": utc(minutes=4).isoformat(), "consumed": False})
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.APPROVAL_RESULT_UNKNOWN
    # positive counterpart: the recorded-pending state is still just pending.
    assert pending.outcome == "pending_approval"


def test_missing_native_receipt_never_resolves_to_allow(wired):
    database, facts, policies, authorizer = wired
    operation, pending = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                                   native_request_id="native-r")
    settled = authorizer.decide(approval_id=pending.approval_id, expected_version=1,
                                 decision="allow", scope={"kind": "once"},
                                 operation_key="ui-1", session_id="session-1")
    assert settled.kind == "recorded"
    _, after = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                         native_request_id="native-r")
    # settled allow but no receipt: unknown, not allowed.
    assert after.outcome == "denied"
    assert after.code is RefusalCode.APPROVAL_RESULT_UNKNOWN
    # positive counterpart: once the native receipt lands, the same operation
    # resolves to AllowedOnce (exactly once - see test_wire_and_single_use).
    facts.record_native_receipt(pending.approval_id, NativeReceipt.of(
        native_request_id="native-r", approval_id=pending.approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    _, allowed = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                           native_request_id="native-r")
    assert allowed.outcome == "allowed_once"
    _, second = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                          native_request_id="native-r")
    assert second.outcome == "denied"
    assert second.code is RefusalCode.APPROVAL_STALE  # used is used


def test_ceiling_tightened_between_request_and_decide_stales_the_decide(wired):
    database, facts, policies, authorizer = wired
    operation, pending = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                                   native_request_id="native-t")
    tightened = admin_ceiling(revision=2, maximumExposure="none")
    policies.store_ceiling(tightened)
    outcome = authorizer.decide(approval_id=pending.approval_id, expected_version=1,
                                decision="allow", scope={"kind": "once"},
                                operation_key="ui-late", session_id="session-1")
    assert outcome.kind == "invalid"
    assert "APPROVAL_STALE" in outcome.reason or "revision" in outcome.reason
    # re-evaluating under the new ceiling: the ask path can no longer settle to
    # an allow - the operation is now denied outright (exposure none).
    _, after = _evaluate(authorizer, ceilings_holder=policies.ceilings_current(),
                         native_request_id="native-t")
    assert after.outcome in {"denied", "pending_approval"}
    assert not getattr(after, "grant", None)


def test_evaluate_with_missing_trusted_fields_fails_closed(wired):
    database, facts, policies, authorizer = wired
    outcome = authorizer.evaluate(
        principal="user-1",
        session_ref={"serverInstanceId": "srv-1", "sessionId": "session-1"},  # no native id
        execution_ref="turn-1", native_generation="gen-1", tool_identity="bash",
        target_facts={}, argument_digest="a" * 64, ceiling_revision="admin@1",
        policy_revision="no-intent", native_request_id="native-x")
    assert outcome.outcome == "denied"
    assert outcome.code is RefusalCode.POLICY_SCOPE_UNVERIFIED
