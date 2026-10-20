"""T02 (§C4): unload-while-open must be observable - the host may consult
`busy()` before retiring the plugin. An open approval, or a settled-allow
whose native receipt is still unreconciled, keeps the count non-zero; only a
resolved or denied/invalidated approval lets it drop.
"""
from __future__ import annotations

from contextlib import contextmanager

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


class _ReadFaultProxy:
    """Inject a read failure while preserving the real SQLite schema view."""

    def __init__(self, connection, *, fail_catalog=False, fail_fact_read=False):
        self._connection = connection
        self._fail_catalog = fail_catalog
        self._fail_fact_read = fail_fact_read

    def execute(self, statement, *args):
        if self._fail_catalog and "FROM sqlite_master" in statement:
            raise RuntimeError("controlled schema-catalog failure")
        if (self._fail_fact_read and
                statement.startswith("SELECT state, decision, id FROM server_approvals")):
            raise RuntimeError("controlled fact-query failure")
        return self._connection.execute(statement, *args)


class _ReadFaultDatabase:
    """Wrap a real product DB connection; only the selected read is faulted."""

    def __init__(self, database, *, fail_catalog=False, fail_fact_read=False):
        self._database = database
        self._fail_catalog = fail_catalog
        self._fail_fact_read = fail_fact_read

    @contextmanager
    def read(self):
        with self._database.read() as connection:
            yield _ReadFaultProxy(
                connection, fail_catalog=self._fail_catalog,
                fail_fact_read=self._fail_fact_read)

    def transaction(self):
        return self._database.transaction()


def test_missing_both_fact_tables_is_not_busy(tmp_path):
    """Both fact tables are physically absent in this controlled database."""
    database = seeded_database(tmp_path)
    with database.transaction() as conn:
        conn.execute("DROP TABLE server_approvals")
    with database.read() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"server_approvals", "server_approval_native_receipts"} & tables
    assert ApprovalFacts(database).busy() == 0


def test_missing_receipt_table_with_an_approval_fact_fails_closed(facts):
    instance, database = facts
    _open_approval(instance, database, native="native-partial-no-receipts")
    # Use the production ensure_schema DDL, then remove only one owned table to
    # model a partial schema; do not create test-only replacement table DDL.
    with database.transaction() as conn:
        conn.execute("DROP TABLE server_approval_native_receipts")
    assert instance.busy() == 1


def test_missing_approval_table_with_a_native_receipt_fails_closed(facts):
    instance, database = facts
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_approval_native_receipts(approval_id,native_request_id,"
            "confirmed,observed_at,recorded_at) VALUES (?,?,?,?,?)",
            ("approval-partial", "native-partial", 1, None, "2026-01-01T00:00:00+00:00"))
        conn.execute("DROP TABLE server_approvals")
    assert instance.busy() == 1


def test_schema_catalog_failure_is_unknown_and_busy(tmp_path):
    database = seeded_database(tmp_path)
    # The real fact schema is absent; the wrapper fails only the catalog probe.
    faulty = _ReadFaultDatabase(database, fail_catalog=True)
    assert ApprovalFacts(faulty).busy() == 1


def test_fact_read_failure_with_both_tables_present_is_unknown_and_busy(facts):
    _, database = facts
    faulty = _ReadFaultDatabase(database, fail_fact_read=True)
    assert ApprovalFacts(faulty).busy() == 1


def test_missing_receipt_table_with_a_known_empty_approval_ledger_is_not_busy(tmp_path):
    database = seeded_database(tmp_path)
    with database.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM server_approvals").fetchone()[0] == 0
    assert ApprovalFacts(database).busy() == 0
