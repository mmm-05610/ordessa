"""T02: native correlation and the lost-contact reconcile path (§C1, FR-04, G2).

`Unknown` is its own outcome and never resolves to allow. The receipt plumbing
into the real ACP channel is still C0-owned (api-requests G2): these tests
feed the receipts through the store's public record/reconcile surface only.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import (ApprovalStateKind, NativeReceipt, PolicyRefusal,
                                     approval_id_for)
from support import (admin_ceiling, approval_record, make_operation, seeded_database,
                     seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts


@pytest.fixture
def database(tmp_path):
    db = seeded_database(tmp_path)
    seed_session(db)
    return db


@pytest.fixture
def facts(database):
    instance = ApprovalFacts(database)
    instance.ensure_schema()
    return instance


@pytest.fixture
def approved(facts):
    """One settled-allow approval with full native correlation."""
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-9")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    approval_id = record["approvalId"]
    facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                 expected_version=1, request_id="d-1", now=utc(minutes=1))
    return approval_id, operation


def test_correlation_fields_are_stored_with_the_fact(facts, database):
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-42",
                               tool_key="edit", target="/repo/a.py")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    state = facts.get(record["approvalId"])
    assert state["nativeRequestId"] == "native-42"
    assert state["operationDigest"] == operation.operation_digest
    assert state["ceilingRevision"] == operation.ceiling_revision
    assert state["policyRevision"] == operation.policy_revision
    assert state["nativeGeneration"] == operation.native_generation


def test_reconcile_without_a_receipt_is_unknown_and_never_resolves_to_allow(
        facts, approved):
    approval_id, operation = approved
    outcome = facts.reconcile(approval_id, operation.native_request_id)
    assert outcome.kind == "unknown"  # its own outcome, not `resolved`
    assert not getattr(outcome, "grants_execution", False)
    assert "native_receipt_unobserved" in outcome.reason
    # positive counterpart: once the receipt arrives, the same query resolves.
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    resolved = facts.reconcile(approval_id, operation.native_request_id)
    assert resolved.kind == "resolved"
    assert resolved.state.state is ApprovalStateKind.SETTLED
    assert resolved.native_confirmed


def test_reconcile_with_a_foreign_native_request_id_stays_unknown(facts, approved):
    approval_id, operation = approved
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    forged = facts.reconcile(approval_id, "native-of-another-owner")
    assert forged.kind == "unknown"
    assert "correlation" in forged.reason
    assert not getattr(forged, "grants_execution", False)


def test_reconcile_of_an_unknown_approval_is_unknown(facts):
    outcome = facts.reconcile("approval_" + "f" * 32, "native-ghost")
    assert outcome.kind == "unknown"


def test_receipt_correlated_to_another_approval_is_refused(facts, approved):
    approval_id, _ = approved
    with pytest.raises(PolicyRefusal):
        facts.record_native_receipt(approval_id, NativeReceipt.of(
            native_request_id="completely-elsewhere", approval_id="approval_" + "e" * 32,
            confirmed=True, observed_at=utc(minutes=2)))


def test_unknown_receipt_never_overwrites_a_confirmed_one(facts, approved):
    approval_id, operation = approved
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    facts.record_native_receipt(approval_id, NativeReceipt.unknown(
        native_request_id=operation.native_request_id, approval_id=approval_id))
    resolved = facts.reconcile(approval_id, operation.native_request_id)
    assert resolved.kind == "resolved" and resolved.native_confirmed


def test_legacy_shaped_rows_without_correlation_reconcile_to_unknown(facts, database):
    """A row written by the old authority (no correlation columns) can never be
    reconciled into an allow: absence of provenance is Unknown, not assent."""
    seed_session(database)
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="legacy-1")
    stamp = utc().isoformat()
    ghost_id = approval_id_for(operation_digest=operation.operation_digest,
                               native_request_id="legacy-1")
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_approvals(id,session_id,execution_id,version,state,decision,"
            "scope_json,request_json,created_at,settled_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ghost_id, "session-1", "turn-1", 1, "open", None, None,
             '{"requestId": "old-shape"}', stamp, None),
        )
    outcome = facts.reconcile(ghost_id, "legacy-1")
    assert outcome.kind == "unknown"
    assert not getattr(outcome, "grants_execution", False)
