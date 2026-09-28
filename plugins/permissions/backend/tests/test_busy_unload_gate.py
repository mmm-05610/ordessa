"""T02 (§C4): unload-while-open must be observable - the host may consult
`busy()` before retiring the plugin. An open approval, or a settled-allow
whose native receipt is still unreconciled, keeps the count non-zero; only a
resolved or denied/invalidated approval lets it drop.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import NativeReceipt
from support import (admin_ceiling, approval_record, make_operation, seeded_database,
                     seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts


@pytest.fixture
def facts(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    instance = ApprovalFacts(database)
    instance.ensure_schema()
    return instance, database


def _open_approval(facts, database, *, native="native-busy"):
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id=native)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    return record["approvalId"], operation


def test_no_activity_is_not_busy(facts):
    instance, _ = facts
    assert instance.busy() == 0


def test_an_open_approval_makes_the_service_busy(facts):
    instance, database = facts
    _open_approval(instance, database)
    assert instance.busy() == 1
    assert instance.open_count() == 1


def test_a_settled_allow_without_reconciled_receipt_stays_busy(facts):
    instance, database = facts
    approval_id, _ = _open_approval(instance, database, native="native-busy-2")
    instance.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                    expected_version=1, request_id="busy-d", now=utc(minutes=1))
    assert instance.open_count() == 0
    assert instance.busy() == 1  # unreconciled native grant: not unloadable


def test_reconciled_or_denied_activity_clears_busy(facts):
    instance, database = facts
    approval_id, operation = _open_approval(instance, database, native="native-busy-3")
    instance.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                    expected_version=1, request_id="busy-3", now=utc(minutes=1))
    instance.record_native_receipt(approval_id, NativeReceipt.of(
        native_request_id=operation.native_request_id, approval_id=approval_id,
        confirmed=True, observed_at=utc(minutes=2)))
    assert instance.busy() == 0

    denied_id, _ = _open_approval(instance, database, native="native-busy-4")
    instance.decide(approval_id=denied_id, decision="deny", scope={"kind": "once"},
                    expected_version=1, request_id="busy-4", now=utc(minutes=1))
    assert instance.busy() == 0  # a recorded denial needs no native reconciliation
