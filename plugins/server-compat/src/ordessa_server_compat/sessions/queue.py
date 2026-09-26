"""Authoritative per-Session queue records (core-semantics/1 §6).

A queued item freezes the submitting role, the resolved configuration version,
and the message content at submission time, so a later selection change cannot
rewrite what will be sent. Withdrawal is guarded by the item's own version and
is refused once the item has been dispatched.
"""
from __future__ import annotations

import json
from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


ACTIVE_STATES = ("pending", "dispatched", "paused")


class QueueRecords:
    def __init__(
        self, database: Database, idempotency: IdempotentRecords, *, append_event=None,
        objects=None,
    ) -> None:
        self.database = database
        self.idempotency = idempotency
        self.append_event = append_event
        self.objects = objects

    def enqueue_in_transaction(
        self, conn, *, session_id: str, profile_id: str, config_version: int,
        request_id: str, request_digest: str, message_object_digest: str,
        effective_config_object_digest: str | None = None,
        public_message: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item_id = opaque_id("queue")
        timestamp = now()
        conn.execute(
            "INSERT INTO server_queue_items("
            "id,session_id,version,state,profile_id,config_version,request_id,"
            "request_digest,message_object_digest,effective_config_object_digest,"
            "public_message_json,submitted_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, session_id, 1, "pending", profile_id, config_version,
             request_id, request_digest, message_object_digest,
             effective_config_object_digest,
             json.dumps(public_message, ensure_ascii=False, sort_keys=True)
             if public_message is not None else None,
             timestamp, timestamp),
        )
        item = self._row_to_item(conn.execute(
            "SELECT * FROM server_queue_items WHERE id=?", (item_id,),
        ).fetchone())
        self._append_updated(conn, item)
        return item

    def list(self, session_id: str) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            self._require_session(conn, session_id)
            rows = conn.execute(
                "SELECT * FROM server_queue_items WHERE session_id=? AND state IN (?,?,?) "
                "ORDER BY submitted_at, id",
                (session_id, *ACTIVE_STATES),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def withdraw(
        self, *, session_id: str, item_id: str, expected_version: int,
        request_id: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        scope = f"queue.withdraw:{session_id}:{item_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, request_id, request_digest)
            if prior:
                return prior
            self._require_session(conn, session_id)
            row = conn.execute(
                "SELECT * FROM server_queue_items WHERE id=? AND session_id=?",
                (item_id, session_id),
            ).fetchone()
            if row is None:
                raise ServerError("QUEUE_ITEM_NOT_FOUND", "Queue item was not found", status=404)
            item = self._row_to_item(row)
            if int(row["version"]) != expected_version:
                error = ServerError(
                    "QUEUE_VERSION_CONFLICT",
                    "Queue item changed before the withdrawal was applied",
                    status=409,
                )
                raise _with_current(error, {"item": item})
            if row["state"] != "pending":
                # Already dispatched work is not silently withdrawn: the
                # contract requires an explicit too_late answer.
                body = {
                    "outcome": "too_late",
                    "reason": f"item_state:{row['state']}",
                    "item": item,
                }
                self.idempotency.insert(conn, scope, request_id, request_digest, 200, body)
                return 200, body
            timestamp = now()
            conn.execute(
                "UPDATE server_queue_items SET state='withdrawn',version=version+1,updated_at=? WHERE id=?",
                (timestamp, item_id),
            )
            updated = self._row_to_item(conn.execute(
                "SELECT * FROM server_queue_items WHERE id=?", (item_id,),
            ).fetchone())
            self._append_updated(conn, updated)
            body = {"outcome": "withdrawn", "item": updated}
            self.idempotency.insert(conn, scope, request_id, request_digest, 200, body)
            return 200, body

    def claim_next(self, conn, session_id: str) -> dict[str, Any] | None:
        """Mark the oldest pending item dispatched; returns it or None."""
        row = conn.execute(
            "SELECT * FROM server_queue_items WHERE session_id=? AND state='pending' "
            "ORDER BY submitted_at, id LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE server_queue_items SET state='dispatched',version=version+1,updated_at=? WHERE id=?",
            (now(), row["id"]),
        )
        item = self._row_to_item(conn.execute(
            "SELECT * FROM server_queue_items WHERE id=?", (row["id"],),
        ).fetchone())
        self._append_updated(conn, item)
        return item

    def pause_pending(self, conn, session_id: str, reason: str) -> int:
        """Pause queued work after a failure or user stop (core §6).

        Order 110: the reason is *recorded*, not discarded. A pause must be
        explainable on the wire (`state=paused` + why), so the user can see it and
        choose to withdraw-and-resend. The reason is the terminal that caused it
        (e.g. `cancelled`, or a failure code) supplied by the caller.
        """
        rows = conn.execute(
            "SELECT id FROM server_queue_items WHERE session_id=? AND state='pending' "
            "ORDER BY submitted_at,id", (session_id,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE server_queue_items SET state='paused',pause_reason=?,version=version+1,updated_at=? "
                "WHERE id=?", (reason, now(), row["id"]),
            )
            self._append_updated(conn, self._row_to_item(conn.execute(
                "SELECT * FROM server_queue_items WHERE id=?", (row["id"],),
            ).fetchone()))
        return len(rows)

    def mark_terminal(self, conn, item_id: str, state: str) -> dict[str, Any] | None:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"invalid queue terminal state: {state}")
        cursor = conn.execute(
            "UPDATE server_queue_items SET state=?,version=version+1,updated_at=? "
            "WHERE id=? AND state='dispatched'", (state, now(), item_id),
        )
        if cursor.rowcount != 1:
            return None
        item = self._row_to_item(conn.execute(
            "SELECT * FROM server_queue_items WHERE id=?", (item_id,),
        ).fetchone())
        self._append_updated(conn, item)
        return item

    def _append_updated(self, conn, item: dict[str, Any]) -> None:
        if self.append_event is None:
            return
        public = {
            key: item[key] for key in (
                "itemId", "version", "submittedAt", "message", "profileId",
                "configVersion", "state",
            )
        }
        # Order 110: carry the pause reason on the event only when there is one,
        # so non-paused `queue.updated` frames keep their exact prior shape
        # (FIFO/CAS/withdraw semantics unchanged) while a paused item is
        # explainable on the wire (state=paused + why -> the user can withdraw
        # and resend). This uses the existing event object, not a new method.
        reason = item.get("pauseReason")
        if reason is not None:
            public["pauseReason"] = reason
        self.append_event(
            conn, item["sessionId"], None, "queue.updated", {"item": public},
        )

    @staticmethod
    def _require_session(conn, session_id: str) -> None:
        if conn.execute("SELECT 1 FROM server_sessions WHERE id=?", (session_id,)).fetchone() is None:
            raise ServerError("SESSION_NOT_FOUND", "Session was not found", status=404)

    def _row_to_item(self, row) -> dict[str, Any]:
        item = {
            "itemId": row["id"],
            "sessionId": row["session_id"],
            "version": int(row["version"]),
            "submittedAt": row["submitted_at"],
            "messageText": row["message_object_digest"],
            "profileId": row["profile_id"],
            "state": row["state"],
            "configVersion": int(row["config_version"]),
            "requestId": row["request_id"],
            "pauseReason": row["pause_reason"],
            "_messageObjectDigest": row["message_object_digest"],
            "_effectiveConfigObjectDigest": row["effective_config_object_digest"],
        }
        if row["public_message_json"] is not None:
            item["message"] = json.loads(row["public_message_json"])
        elif self.objects is not None:
            stored = json.loads(self.objects.read(row["message_object_digest"]))
            message = dict(stored.get("message") or stored)
            item["message"] = {
                "text": str(message.get("text", "")),
                "attachments": [
                    {key: attachment[key] for key in ("ref", "displayName", "mediaKind")}
                    for attachment in message.get("attachments", ())
                ],
            }
        return item


def _with_current(error: ServerError, current: dict[str, Any]) -> ServerError:
    error.current = current  # type: ignore[attr-defined]
    return error
