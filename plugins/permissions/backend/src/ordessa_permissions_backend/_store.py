"""The storage seam: a small local Protocol for the injected host database.

The backend never imports the host's storage class; the host hands over an
object that provides `transaction()` and `read()` context managers yielding a
connection-like with `execute()`. Timestamps and opaque ids keep the exact
shape the existing product writes, so migrated rows are indistinguishable.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import typing
import uuid
from typing import Any

__all__ = [
    "ApprovalDatabase",
    "WIRE_VISIBLE_EVENT_KINDS",
    "append_session_event",
    "now_stamp",
    "opaque_id",
    "parse_stamp",
]


class ApprovalDatabase(typing.Protocol):
    """What the injected database object must provide (host-owned lifetime)."""

    def transaction(self) -> contextlib.AbstractContextManager[Any]: ...

    def read(self) -> contextlib.AbstractContextManager[Any]: ...


def now_stamp() -> str:
    """The product's record timestamp spelling: aware ISO-8601 UTC."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_stamp(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def opaque_id(prefix: str) -> str:
    """The product's opaque id shape: `{prefix}_{32 lowercase hex}`."""
    return f"{prefix}_{uuid.uuid4().hex}"


#: The event kinds the public session stream renders; identical to the spelling
#: the current host already assigns wire sequence numbers for, so approval
#: events keep their wire position after the migration.
WIRE_VISIBLE_EVENT_KINDS = frozenset({
    "turn.accepted", "turn.state", "message.delta", "message.final", "tool.update",
    "approval.requested", "approval.settled", "config.changed", "queue.updated",
    "workspace.connection",
})


def append_session_event(conn, session_id: str, turn_id: str | None, kind: str,
                         data: dict[str, Any]) -> dict[str, Any]:
    """Default session-event writer, column-for-column the host's own shape.

    A host that already owns an event writer injects it instead; this default
    exists so the approval ledger is never silently eventless.
    """
    seq = int(conn.execute(
        "SELECT COALESCE(MAX(seq),0)+1 FROM server_session_events WHERE session_id=?",
        (session_id,),
    ).fetchone()[0])
    created_at = now_stamp()
    wire_seq = None
    if kind in WIRE_VISIBLE_EVENT_KINDS:
        wire_seq = int(conn.execute(
            "SELECT COALESCE(MAX(wire_seq),0)+1 FROM server_session_events"
            " WHERE session_id=?", (session_id,),
        ).fetchone()[0])
    conn.execute(
        "INSERT INTO server_session_events(session_id,seq,wire_seq,event_id,turn_id,kind,"
        "schema_version,data_json,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, seq, wire_seq, opaque_id("event"), turn_id, kind, 1,
         json.dumps(data, ensure_ascii=False, sort_keys=True), created_at),
    )
    return {"session_id": session_id, "seq": seq, "wire_seq": wire_seq, "kind": kind,
            "data": data, "created_at": created_at}
