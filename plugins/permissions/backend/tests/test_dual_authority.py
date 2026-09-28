"""T02 required RED: dual-authority coexistence is observable as a conflict.

Two independent `decide` authorities must never be wired against the same
native request (contracts C3: "禁止两个独立 decide 权威同时接同一 native
request"). This test runs BOTH the legacy `ordessa_server_compat` writer and
the new `ApprovalFacts` against the SAME `server_approvals` row on the real
database and asserts the coexistence surfaces as a typed conflict and that
exactly one settled outcome is ever recorded for one native request.

Retiring the legacy writer (and the `approvals.decide` route migration) is
C0's job under G6 / T08 - this package deliberately does NOT delete or edit
any server-compat file, and keeps the legacy table readable (compat plan).
"""
from __future__ import annotations

import pytest
from ordessa_server_compat.approvals.records import ApprovalRecords
from support import (admin_ceiling, approval_record, append_event, clock_at,
                     make_operation, seeded_database, seed_session, utc)

from ordessa_permissions_backend import ApprovalFacts


@pytest.fixture
def stage(tmp_path):
    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database, append_event=append_event)
    facts.ensure_schema()
    legacy = ApprovalRecords(database, append_event=append_event)
    return database, facts, legacy


def _settled_events(database):
    with database.read() as conn:
        return conn.execute(
            "SELECT data_json FROM server_session_events WHERE kind='approval.settled'"
        ).fetchall()


def test_new_authority_wins_then_legacy_writer_observes_the_conflict(stage):
    """Our `decide` settles first; the legacy writer, still handed the old
    `expected_version`, cannot produce a second settled outcome - it returns
    `invalid` and the ledger still shows exactly one decision."""
    database, facts, legacy = stage
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-dual-1")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    approval_id = record["approvalId"]

    ours = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                        expected_version=1, request_id="ours", now=utc(minutes=1))
    assert ours.kind == "recorded"

    status, body = legacy.decide(approval_id=approval_id, decision="deny",
                                 scope={"kind": "once"}, expected_version=1,
                                 request_id="legacy-race")
    assert status == 200
    assert body == {"outcome": "invalid", "reason": "approval_state:settled"}
    assert len(_settled_events(database)) == 1
    row = facts.get(approval_id)
    assert row["decision"] == "allow" and row["version"] == 2


def test_legacy_writer_settles_first_then_we_refuse_and_keep_one_settled_fact(stage):
    """Symmetric order: the legacy writer settles first; our service refuses
    to produce a second settled outcome for the same native request. A row
    without native correlation is additionally un-decidable by us (Unknown),
    so the two authorities can never both mint decisions."""
    database, facts, legacy = stage
    approval = legacy.request(session_id="session-1", execution_id="turn-1",
                              request={"requestId": "req-1", "tool": "bash",
                                       "summary": "run a command"})
    approval_id = approval["approvalId"]

    # Our service refuses to *start* deciding a legacy row: no native
    # correlation is recorded, so deciding it could never be reconciled.
    refused = facts.decide(approval_id=approval_id, decision="allow",
                           scope={"kind": "once"}, expected_version=1,
                           request_id="ours-first", now=utc())
    assert refused.kind == "unknown"
    assert "correlation" in refused.reason
    assert facts.get(approval_id)["state"] == "open"

    status, body = legacy.decide(approval_id=approval_id, decision="allow",
                                 scope={"kind": "once"}, expected_version=1,
                                 request_id="legacy-settle")
    assert body["outcome"] == "recorded"

    late = facts.decide(approval_id=approval_id, decision="deny", scope={"kind": "once"},
                        expected_version=1, request_id="ours-late", now=utc())
    assert late.kind == "version_conflict"  # CAS caught the moved version
    settled = _settled_events(database)
    assert len(settled) == 1  # exactly one settled outcome for one native request
    assert facts.get(approval_id)["decision"] == "allow"


def test_two_authorities_diverge_on_the_same_row_as_version_conflict(stage):
    """Both authorities captured `expected_version=1`. The first write wins;
    the second is a typed conflict, never a silent overwrite: the row's
    decision and event ledger tell a single story."""
    database, facts, legacy = stage
    operation = make_operation(ceilings=[admin_ceiling()], native_request_id="native-dual-2")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    approval_id = record["approvalId"]

    status, body = legacy.decide(approval_id=approval_id, decision="deny",
                                 scope={"kind": "once"}, expected_version=1,
                                 request_id="legacy-first")
    assert body["outcome"] == "recorded"
    ours = facts.decide(approval_id=approval_id, decision="allow", scope={"kind": "once"},
                        expected_version=1, request_id="ours-second", now=utc())
    assert ours.kind == "version_conflict"
    row = facts.get(approval_id)
    assert row["decision"] == "deny" and row["state"] == "settled"
    assert len(_settled_events(database)) == 1


def test_legacy_table_stays_readable_by_the_new_authority(stage):
    """Compat plan: our store reads legacy rows (the 10 original columns)
    without rewriting them - retiring the legacy writer is C0's job (G6)."""
    database, facts, legacy = stage
    approval = legacy.request(session_id="session-1", execution_id="turn-1",
                              request={"requestId": "req-readable"})
    row = facts.get(approval["approvalId"])
    assert row["sessionId"] == "session-1"
    assert row["state"] == "open"
    assert row["nativeRequestId"] is None  # honest absence, never fabricated


# -- T019: even the DELEGATED old route joined to a live legacy writer cannot
# -- produce two settled outcomes: the single authority is the authorizer.


@pytest.fixture
def delegated_stage(tmp_path):
    """Same database, both handlers wired: the legacy `ApprovalRecords.decide`
    AND the delegated old-wire route served by `PermissionsBackendPlugin(
    approval_route="legacy-delegated")`. A hazard registration, used here to
    prove two settled outcomes stay impossible on every row ordering."""
    from server_plugin_api import ServerPluginContext
    from ordessa_permissions_backend import PermissionsBackendPlugin

    database = seeded_database(tmp_path)
    seed_session(database)
    facts = ApprovalFacts(database, append_event=append_event)
    facts.ensure_schema()
    legacy = ApprovalRecords(database, append_event=append_event)
    registration = PermissionsBackendPlugin(approval_route="legacy-delegated").build(
        ServerPluginContext(plugin_id="permissions-backend", data_root=tmp_path,
                            ports={"database": database}))
    authorizer = registration.provided_ports["permissions.authorizer@1"]
    authorizer.policies.store_ceiling(admin_ceiling())
    authorizer.clock = clock_at(utc())
    old_route = {m.method_id: m.handler for m in registration.methods}[
        "approvals.decide"]
    return database, facts, legacy, old_route


def _legacy_params(approval_id, *, request_id, decision, expected_version=1):
    # the OLD wire shape exactly (core_wire.py:327-329): no sessionId field
    return {"requestId": request_id, "approvalId": approval_id,
            "expectedVersion": expected_version, "decision": decision,
            "scope": {"kind": "once"}}


def test_delegated_route_settles_first_and_the_legacy_writer_cannot_second(
        delegated_stage):
    database, facts, legacy, old_route = delegated_stage
    operation = make_operation(ceilings=[admin_ceiling()],
                               native_request_id="native-deleg-dual-1")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    body = old_route(_legacy_params(record["approvalId"], request_id="deleg",
                                    decision="allow"))
    assert body["outcome"] == "recorded"
    status, second = legacy.decide(approval_id=record["approvalId"], decision="deny",
                                   scope={"kind": "once"}, expected_version=1,
                                   request_id="legacy-second")
    assert second == {"outcome": "invalid", "reason": "approval_state:settled"}
    assert len(_settled_events(database)) == 1
    assert facts.get(record["approvalId"])["decision"] == "allow"


def test_legacy_writer_settles_first_and_the_delegated_route_refuses(
        delegated_stage):
    """The mirrored order. A row the legacy writer minted carries no native
    operation/session/generation facts, so the delegated route refuses it
    typed (unknown) and never writes a second settled outcome; a fully
    correlated row is caught by the CAS instead."""
    database, facts, legacy, old_route = delegated_stage
    approval = legacy.request(session_id="session-1", execution_id="turn-1",
                              request={"requestId": "req-1", "tool": "bash"})
    status, first = legacy.decide(approval_id=approval["approvalId"], decision="allow",
                                  scope={"kind": "once"}, expected_version=1,
                                  request_id="legacy-first")
    assert first["outcome"] == "recorded"
    refused = old_route(_legacy_params(approval["approvalId"], request_id="deleg-late",
                                       decision="deny", expected_version=2))
    assert refused["outcome"] == "unknown"  # missing native facts: never a decision
    assert len(_settled_events(database)) == 1
    assert facts.get(approval["approvalId"])["decision"] == "allow"

    operation = make_operation(ceilings=[admin_ceiling()],
                               native_request_id="native-deleg-dual-2")
    record = approval_record(operation, requested_at=utc(), expires_at=utc(minutes=5))
    facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                  request=record)
    first_new = old_route(_legacy_params(record["approvalId"], request_id="deleg-a",
                                         decision="allow", expected_version=1))
    assert first_new["outcome"] == "recorded"
    late = old_route(_legacy_params(record["approvalId"], request_id="deleg-race",
                                    decision="deny", expected_version=1))
    assert late["outcome"] == "version_conflict"
    assert len(_settled_events(database)) == 2  # one per approval, never two per row
