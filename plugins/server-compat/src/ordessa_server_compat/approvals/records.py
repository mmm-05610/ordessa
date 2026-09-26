"""Atomic approval facts (core-semantics/1 §7).

One approval has one authoritative decision. The first valid decision wins; a
repeat of the same decision is reported as `already_recorded` rather than
re-executed, a contradictory decision is refused, and a decision that arrives
after the approval is no longer actionable is `invalid` — never silently
applied. Rows are only written by this module and events are appended in the
same transaction.
"""
from __future__ import annotations

import json
from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


OPEN = "open"
SETTLED = "settled"
INVALID = "invalid"


class ApprovalRecords:
    def __init__(self, database: Database, *, append_event) -> None:
        self.database = database
        self._append_event = append_event

    def request_in_transaction(
        self, conn, *, session_id: str, execution_id: str, request: dict[str, Any],
    ) -> dict[str, Any]:
        approval_id = opaque_id("approval")
        timestamp = now()
        conn.execute(
            "INSERT INTO server_approvals("
            "id,session_id,execution_id,version,state,decision,scope_json,request_json,created_at,settled_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (approval_id, session_id, execution_id, 1, OPEN, None, None,
             json.dumps(request, ensure_ascii=False, sort_keys=True), timestamp, None),
        )
        body = {
            "approvalId": approval_id, "executionId": execution_id,
            "version": 1, "state": OPEN, "request": request,
        }
        self._append_event(
            conn, session_id, execution_id, "approval.requested",
            {"approval_id": approval_id, "version": 1, "request": request},
        )
        return body

    def request(
        self, *, session_id: str, execution_id: str, request: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a sidecar permission request before publishing it."""
        with self.database.transaction() as conn:
            return self.request_in_transaction(
                conn, session_id=session_id, execution_id=execution_id, request=request,
            )

    def get(self, approval_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_approvals WHERE id=?", (approval_id,),
            ).fetchone()
            if row is None:
                raise ServerError("APPROVAL_NOT_FOUND", "Approval was not found", status=404)
            return self._row(row)

    def decide(
        self, *, approval_id: str, decision: str, scope: dict[str, Any],
        expected_version: int, request_id: str,
    ) -> tuple[int, dict[str, Any]]:
        with self.database.transaction() as conn:
            # Duplicate delivery of the same request is answered from the
            # recorded row; it never applies a second decision.
            prior = conn.execute(
                "SELECT * FROM server_approvals WHERE id=?", (approval_id,),
            ).fetchone()
            if prior is None:
                raise ServerError("APPROVAL_NOT_FOUND", "Approval was not found", status=404)
            recorded = json.loads(prior["request_json"])
            if recorded.get("decideRequestId") == request_id:
                return 200, self._decision_body(prior, "already_recorded")

            if prior["state"] != OPEN:
                body = {
                    "outcome": "invalid",
                    "reason": f"approval_state:{prior['state']}",
                }
                self.idempotency_note(conn, approval_id, body)
                return 200, body
            execution = conn.execute(
                "SELECT state FROM server_turns WHERE id=?", (prior["execution_id"],),
            ).fetchone()
            if execution is None or execution["state"] in {
                "completed", "failed", "cancelled", "unknown",
            }:
                timestamp = now()
                conn.execute(
                    "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                    "WHERE id=? AND state=?",
                    (INVALID, timestamp, approval_id, OPEN),
                )
                self._append_event(
                    conn, prior["session_id"], prior["execution_id"], "approval.settled",
                    {"approval_id": approval_id, "decision": "invalidated"},
                )
                return 200, {
                    "outcome": "invalid", "reason": "execution_not_actionable",
                }
            if int(prior["version"]) != expected_version:
                raise _current_error(ServerError(
                    "APPROVAL_VERSION_CONFLICT",
                    "Approval changed before the decision was applied",
                    status=409,
                ), self._row(prior))

            timestamp = now()
            recorded["decideRequestId"] = request_id
            conn.execute(
                "UPDATE server_approvals SET state=?,decision=?,scope_json=?,version=version+1,"
                "request_json=?,settled_at=? WHERE id=? AND state=? AND version=?",
                (SETTLED, decision, json.dumps(scope, sort_keys=True), json.dumps(recorded, sort_keys=True),
                 timestamp, approval_id, OPEN, expected_version),
            )
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?", (approval_id,)).fetchone()
            self._append_event(
                conn, row["session_id"], row["execution_id"], "approval.settled",
                {"approval_id": approval_id, "decision": decision},
            )
            return 200, self._decision_body(row, "recorded")

    def expire(self, approval_id: str, reason: str) -> None:
        """Close an approval whose execution ended, cancelled, or timed out."""
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM server_approvals WHERE id=?", (approval_id,)).fetchone()
            if row is None or row["state"] != OPEN:
                return
            conn.execute(
                "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                "WHERE id=? AND state=?",
                (INVALID, now(), approval_id, OPEN),
            )

    def invalidate_for_execution(self, execution_id: str, reason: str) -> int:
        """Atomically close every grant route after its execution is terminal."""
        with self.database.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM server_approvals WHERE execution_id=? AND state=?",
                (execution_id, OPEN),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
                    "WHERE id=? AND state=?",
                    (INVALID, now(), row["id"], OPEN),
                )
                self._append_event(
                    conn, row["session_id"], execution_id, "approval.settled",
                    {"approval_id": row["id"], "decision": "invalidated", "reason": reason},
                )
            return len(rows)

    def open_for_execution(self, execution_id: str) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT * FROM server_approvals WHERE execution_id=? AND state=?",
                (execution_id, OPEN),
            ).fetchall()
        return [self._row(row) for row in rows]

    def expire_for_execution(self, conn, execution_id: str, reason: str) -> int:
        del reason
        cursor = conn.execute(
            "UPDATE server_approvals SET state=?,version=version+1,settled_at=? "
            "WHERE execution_id=? AND state=?",
            (INVALID, now(), execution_id, OPEN),
        )
        return cursor.rowcount

    @staticmethod
    def idempotency_note(conn, approval_id: str, body: dict[str, Any]) -> None:
        del conn, approval_id, body

    @staticmethod
    def _row(row) -> dict[str, Any]:
        return {
            "approvalId": row["id"],
            "sessionId": row["session_id"],
            "executionId": row["execution_id"],
            "version": int(row["version"]),
            "state": row["state"],
            "decision": row["decision"],
            "scope": json.loads(row["scope_json"]) if row["scope_json"] else None,
            "request": json.loads(row["request_json"]),
        }

    @staticmethod
    def _decision_body(row, outcome: str) -> dict[str, Any]:
        return {"outcome": outcome, "decision": row["decision"]}


def _current_error(error: ServerError, current: dict[str, Any]) -> ServerError:
    error.current = current  # type: ignore[attr-defined]
    return error
