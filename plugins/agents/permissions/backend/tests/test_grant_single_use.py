"""T02 (FR-04): an approval grant is usable once, bound to the approved object.

"A granted allowance is used exactly once, bound only to the approved
object/scope." The binding is the operation digest (which folds in the target,
session, execution and revisions); the single use is an atomic store-level
consume, not an in-memory flag.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import NativeReceipt
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


def _settled_allow(facts, *, target="/repo/a.py", native_request_id="native-g"):
    operation = make_operation(ceilings=[admin_ceiling()], target=target,
                               native_request_id=native_request_id)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    approval_id = record["approvalId"]
    facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                 expected_version=1, request_id="grant-1", now=utc(minutes=1))
    facts.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=1)))
    return approval_id, operation


def test_grant_is_acquired_once_and_the_second_use_fails(facts):
    approval_id, operation = _settled_allow(facts)
    first = facts.consume_grant(approval_id=approval_id,
                                 operation_digest=operation.operation_digest,
                                 native_request_id=operation.native_request_id,
                                 moment=utc(minutes=2))
    second = facts.consume_grant(approval_id=approval_id,
                                 operation_digest=operation.operation_digest,
                                 native_request_id=operation.native_request_id,
                                 moment=utc(minutes=3))
    assert first is True and second is False


def test_grant_for_one_operation_digest_cannot_be_spent_on_another(facts):
    """Positive/negative pair: the same approval id cannot pay for a different
    object (different operation digest); the stranger consumes nothing."""
    approval_id, _operation = _settled_allow(facts, target="/repo/a.py",
                                             native_request_id="native-g1")
    stranger = make_operation(ceilings=[admin_ceiling()], target="/repo/secret.env",
                              native_request_id="native-g2")
    spent = facts.consume_grant(approval_id=approval_id,
                                operation_digest=stranger.operation_digest,
                                native_request_id=stranger.native_request_id,
                                moment=utc(minutes=2))
    assert spent is False
    # The legitimate digest still succeeds afterwards - the wrong one consumed nothing.
    still_ok = facts.consume_grant(
        approval_id=approval_id,
        operation_digest=make_operation(ceilings=[admin_ceiling()], target="/repo/a.py",
                                        native_request_id="native-g1").operation_digest,
        native_request_id="native-g1", moment=utc(minutes=3))
    assert still_ok is True


def test_consume_grant_requires_a_settled_allowed_approval(facts):
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-open")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    spent = facts.consume_grant(approval_id=record["approvalId"],
                                operation_digest=operation.operation_digest,
                                native_request_id=operation.native_request_id,
                                moment=utc(minutes=1))
    assert spent is False  # still open: nothing was decided, nothing may be spent
