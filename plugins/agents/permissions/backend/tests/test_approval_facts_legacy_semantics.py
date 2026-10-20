"""T02: the migrated authority keeps the legacy `server_approvals` semantics.

Each negative case has a positive counterpart. Replay is answered from the
recorded row; a version conflict is typed; concurrent different decision ids
against one `expected_version` produce exactly one settled outcome. The table
identity (name + legacy column set) is asserted byte-level against the schema
the current host creates, because live rows must not need a rewrite (FR-10).
"""
from __future__ import annotations

import re
import sqlite3

import pytest
from ordessa_permissions_api import ApprovalDecision, PolicyRefusal
from support import (admin_ceiling, approval_record, make_operation, seeded_database,
                     seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts


@pytest.fixture
def database(tmp_path):
    return seeded_database(tmp_path)


@pytest.fixture
def facts(database):
    instance = ApprovalFacts(database)
    instance.ensure_schema()
    return instance


def _open_approval(facts, database, *, native_request_id="native-1", tool_key="bash"):
    seed_session(database)
    operation = make_operation(ceilings=[admin_ceiling()],
                               native_request_id=native_request_id, tool_key=tool_key)
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    body = facts.request(session_id=operation.session_id,
                         execution_id=operation.execution_id, request=record)
    return record["approvalId"], body


def test_table_name_and_legacy_columns_are_byte_compatible_with_the_host_schema(database):
    """The host creates `server_approvals` (the product storage provider's
    schema, resolved via the composition's `database_type()`); our own
    DDL for a bare database must produce the identical legacy column set."""
    with database.read() as conn:
        host_columns = conn.execute("PRAGMA table_info(server_approvals)").fetchall()
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    ApprovalFacts.create_legacy_table(bare)
    own_columns = bare.execute("PRAGMA table_info(server_approvals)").fetchall()
    legacy_names = [row["name"] for row in host_columns]
    assert [row["name"] for row in own_columns][:len(legacy_names)] == legacy_names
    # Byte-level per-column facts for the legacy set: type, not-null, default, pk.
    own_by_name = {row["name"]: tuple(row) for row in own_columns}
    for row in host_columns:
        assert own_by_name[row["name"]] == tuple(row), row["name"]


def test_correlation_columns_are_nullable_additions(facts, database):
    """New native-correlation columns may only be additive nullable columns:
    a legacy INSERT (the 10-column list) must still succeed on our table."""
    with database.read() as conn:
        added = conn.execute("PRAGMA table_info(server_approvals)").fetchall()
    legacy_columns = {
        "id", "session_id", "execution_id", "version", "state", "decision",
        "scope_json", "request_json", "created_at", "settled_at",
    }
    for row in added:
        if row["name"] not in legacy_columns:
            assert row["notnull"] == 0 and row["dflt_value"] is None, row["name"]


def test_approval_id_keeps_the_legacy_shape(facts, database):
    approval_id, _ = _open_approval(facts, database)
    assert re.fullmatch(r"approval_[0-9a-f]{32}", approval_id)


def test_request_appends_the_legacy_event_name(facts, database):
    approval_id, _ = _open_approval(facts, database)
    with database.read() as conn:
        rows = conn.execute(
            "SELECT kind, data_json FROM server_session_events WHERE kind='approval.requested'"
        ).fetchall()
    assert len(rows) == 1
    assert approval_id in rows[0]["data_json"]


def test_decide_settles_once_and_records_the_decision(facts, database):
    approval_id, _ = _open_approval(facts, database)
    outcome = facts.decide(approval_id=approval_id, decision="allow",
                           scope={"kind": "once"}, expected_version=1,
                           request_id="decide-1", now=utc(minutes=1))
    assert outcome.kind == "recorded"
    assert outcome.decision is ApprovalDecision.ALLOW
    state = facts.get(approval_id)
    assert state["state"] == "settled" and state["decision"] == "allow"
    assert state["version"] == 2


def test_replay_of_the_same_decide_request_id_is_already_recorded_with_no_state_change(
        facts, database):
    approval_id, _ = _open_approval(facts, database)
    facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                 expected_version=1, request_id="decide-1", now=utc(minutes=1))
    before = facts.get(approval_id)
    replay = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                          expected_version=1, request_id="decide-1", now=utc(minutes=2))
    assert replay.kind == "already_recorded"
    after = facts.get(approval_id)
    assert after == before  # no second decision, no version bump
    with database.read() as conn:
        settled_events = conn.execute(
            "SELECT 1 FROM server_session_events WHERE kind='approval.settled'").fetchall()
    assert len(settled_events) == 1


def test_opposite_decision_after_settle_is_refused(facts, database):
    approval_id, _ = _open_approval(facts, database)
    facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                 expected_version=1, request_id="decide-1", now=utc(minutes=1))
    opposite = facts.decide(approval_id=approval_id, decision="deny",
                            scope={"kind": "once"}, expected_version=2,
                            request_id="decide-2", now=utc(minutes=2))
    assert opposite.kind == "invalid"
    assert facts.get(approval_id)["decision"] == "allow"


def test_concurrent_different_decision_ids_at_one_expected_version_admits_exactly_one(
        facts, database):
    approval_id, _ = _open_approval(facts, database)
    first = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                         expected_version=1, request_id="race-a", now=utc(minutes=1))
    second = facts.decide(approval_id=approval_id, decision="deny", scope={"kind": "once"},
                          expected_version=1, request_id="race-b", now=utc(minutes=1))
    assert first.kind == "recorded"
    # The losing racer never silently overwrites: it is a typed conflict or an
    # invalid-after-settle, and the row carries exactly one decision.
    assert second.kind in {"version_conflict", "invalid"}
    assert facts.get(approval_id)["decision"] == "allow"


def test_missing_approval_is_unknown_never_a_quiet_allow(facts):
    outcome = facts.decide(approval_id="approval_" + "0" * 32, decision="allow",
                           scope={"kind": "once"}, expected_version=1,
                           request_id="ghost-1", now=utc())
    assert outcome.kind == "unknown"
    assert not getattr(outcome, "grants_execution", False)


def test_terminal_execution_makes_a_pending_approval_not_actionable(facts, database):
    from support import set_turn_state
    approval_id, _ = _open_approval(facts, database)
    set_turn_state(database, "turn-1", "cancelled")
    outcome = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                           expected_version=1, request_id="late-1", now=utc(minutes=1))
    assert outcome.kind == "invalid"
    assert outcome.reason == "execution_not_actionable"
    assert facts.get(approval_id)["state"] == "invalid"


def test_decide_refuses_an_expired_approval(facts, database):
    approval_id, _ = _open_approval(facts, database)
    outcome = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                           expected_version=1, request_id="late-window",
                           now=utc(minutes=10))  # expires_at is +5 minutes
    assert outcome.kind == "invalid"
    assert outcome.reason == "approval_expired"


def test_cross_session_decide_is_refused(facts, database):
    approval_id, _ = _open_approval(facts, database)
    outcome = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                           expected_version=1, request_id="other-session",
                           now=utc(minutes=1), session_id="session-OTHER")
    assert outcome.kind == "invalid"
    assert "cross_session" in outcome.reason
    assert facts.get(approval_id)["state"] == "open"  # refusal wrote nothing


def test_scope_is_the_declared_wire_shape_or_nothing(facts, database):
    approval_id, _ = _open_approval(facts, database)
    with pytest.raises(PolicyRefusal):
        facts.decide(approval_id=approval_id, decision="allow",
                     scope={"kind": "always-and-forever"}, expected_version=1,
                     request_id="bad-scope", now=utc(minutes=1))
    assert facts.get(approval_id)["state"] == "open"


def test_invalidate_for_execution_closes_every_open_grant_route(facts, database):
    approval_id, _ = _open_approval(facts, database)
    closed = facts.invalidate_for_execution("turn-1", "turn-cancelled")
    assert closed == 1
    assert facts.get(approval_id)["state"] == "invalid"
    outcome = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                           expected_version=2, request_id="post-invalidate", now=utc())
    assert outcome.kind == "invalid"
