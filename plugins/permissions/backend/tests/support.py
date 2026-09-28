"""Shared helpers for the permissions-backend tests.

Everything runs against the REAL product storage provider — the very class
`ordessa_server_product.composition.ServerProductComposition.database_type()`
hands the composition (resolved through the product accessor, not a hardcoded
module path), the same object the legacy approvals tests wire into
`ApprovalRecords` — inside pytest tmp dirs only: no models, no network, no
`$HOME`, no user configs.
"""
from __future__ import annotations

import datetime as dt
import json

from ordessa_permissions_api import (
    OperationRequest,
    PolicyCeiling,
    approval_id_for,
    build_operation_request,
    intersect_ceilings,
)
from ordessa_server_product.composition import ServerProductComposition

#: The product's storage provider class, obtained the way the composition
#: obtains it. `database_type()` is idempotent and opens no database.
Database = ServerProductComposition().database_type()

UTC = dt.timezone.utc
ARG_DIGEST = "a" * 64
ADMIN_CEILING_RECORD = {
    "policyId": "admin",
    "scope": "admin",
    "revision": 1,
    "source": "signed-admin",
    "signed": True,
    "maximumExposure": "full",
    "effectiveFrom": "2020-01-01T00:00:00+00:00",
}


def seeded_database(tmp_path) -> Database:
    """The real product database, schema-initialized, in a temp dir."""
    database = Database(tmp_path / "data")
    database.initialize()
    return database


def seed_session(database: Database, *, session_id: str = "session-1",
                 execution_id: str = "turn-1", turn_state: str = "running",
                 profile_id: str = "profile-1", workspace_id: str = "ws-1") -> None:
    """Insert the FK chain a real approval row needs: workspace/profile/session/turn."""
    stamp = "2026-01-01T00:00:00+00:00"
    with database.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO server_workspaces(id,connection_id,distribution,"
            "remote_path,connection_state,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (workspace_id, f"{workspace_id}-conn", "local", "/tmp/ws", "connected",
             stamp, stamp),
        )
        conn.execute(
            "INSERT OR IGNORE INTO server_profiles(id,name,harness_type,config_revision,"
            "config_object_digest,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (profile_id, "p", "pi", 1, "0" * 64, stamp, stamp),
        )
        conn.execute(
            "INSERT OR IGNORE INTO server_sessions(id,workspace_id,profile_id,created_at,"
            "updated_at) VALUES (?,?,?,?,?)",
            (session_id, workspace_id, profile_id, stamp, stamp),
        )
        conn.execute(
            "INSERT OR IGNORE INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (execution_id, session_id, profile_id, 1, 1, turn_state, "pending", "pending",
             "0" * 64, stamp, stamp),
        )


def set_turn_state(database: Database, execution_id: str, state: str) -> None:
    with database.transaction() as conn:
        conn.execute("UPDATE server_turns SET state=? WHERE id=?", (state, execution_id))


def admin_ceiling(revision: int = 1, **overrides) -> PolicyCeiling:
    record = {**ADMIN_CEILING_RECORD, "revision": revision, **overrides}
    return PolicyCeiling.from_record(record)


def effective_digest(ceilings) -> str:
    return intersect_ceilings(list(ceilings)).revision_digest


def make_operation(*, tool_key: str = "bash", target: str | None = None,
                   ceilings, intent=None, session_id: str = "session-1",
                   execution_id: str = "turn-1", native_request_id: str = "native-1",
                   principal: str = "user-1", native_generation: str = "gen-1",
                   argument_digest: str = ARG_DIGEST) -> OperationRequest:
    return build_operation_request(
        principal=principal, server_instance_id="srv-1", session_id=session_id,
        native_session_id=f"native-session-{session_id}", execution_id=execution_id,
        native_generation=native_generation, tool_key=tool_key, target=target,
        argument_digest=argument_digest, native_request_id=native_request_id,
        ceilings=list(ceilings), intent=intent,
    )


def approval_record(operation: OperationRequest, *, requested_at: dt.datetime,
                    expires_at: dt.datetime, approval_id: str | None = None,
                    version: int = 1) -> dict:
    """The stored request record, in the API's declared wire spelling."""
    return {
        "approvalId": approval_id or approval_id_for(
            operation_digest=operation.operation_digest,
            native_request_id=operation.native_request_id),
        "sessionId": operation.session_id,
        "executionId": operation.execution_id,
        "nativeRequestId": operation.native_request_id,
        "operationDigest": operation.operation_digest,
        "toolKey": operation.tool_key,
        "target": operation.target,
        "ceilingRevision": operation.ceiling_revision,
        "policyRevision": operation.policy_revision,
        "nativeGeneration": operation.native_generation,
        "requestedAt": requested_at.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "version": version,
    }


def utc(*, minutes: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC) + dt.timedelta(minutes=minutes)


def clock_at(moment: dt.datetime):
    def _clock() -> dt.datetime:
        return moment
    return _clock


WIRE_VISIBLE_EVENT_KINDS = {
    "turn.accepted", "turn.state", "message.delta", "message.final", "tool.update",
    "approval.requested", "approval.settled", "config.changed", "queue.updated",
    "workspace.connection",
}


def append_event(conn, session_id: str, turn_id, kind: str, data: dict) -> dict:
    """Mirror of the host's session-event writer (same table, same columns)
    so BOTH authorities' ledgers are directly comparable in the dual test."""
    seq = int(conn.execute(
        "SELECT COALESCE(MAX(seq),0)+1 FROM server_session_events WHERE session_id=?",
        (session_id,),
    ).fetchone()[0])
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    wire_seq = None
    if kind in WIRE_VISIBLE_EVENT_KINDS:
        wire_seq = int(conn.execute(
            "SELECT COALESCE(MAX(wire_seq),0)+1 FROM server_session_events"
            " WHERE session_id=?", (session_id,),
        ).fetchone()[0])
    conn.execute(
        "INSERT INTO server_session_events(session_id,seq,wire_seq,event_id,turn_id,kind,"
        "schema_version,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, seq, wire_seq, f"event_{seq:08d}", turn_id, kind, 1,
         json.dumps(data, ensure_ascii=False, sort_keys=True), created_at),
    )
    return {"session_id": session_id, "seq": seq, "kind": kind}
