"""Order 64: the running-execution inventory - our own runs, nothing else.

The card answers "what is running *from us*", never "what is running on this
machine": every row is explained by our own ledger (a turn in an active state
or a queued item), and the fields we cannot obtain stay `null` with a reason -
a pid is the only such field in practice, and it is `null` unless the side
that runs the turn actually reported it.

Bound and read-only by construction: one keyset-free bounded query, no
cancellation surface, no machine-level process walk, and no host path in any
row (the workspace is named by its record id and display name).
"""
from __future__ import annotations

from typing import Any, Mapping

from pacthold.storage import Database

#: Turn states that mean "an execution of ours is in flight", mapped to the
#: three states the product card shows.
STATE_MAP = {
    "accepted": "queued",
    "dispatching": "running",
    "running": "running",
    "capturing": "running",
}
MAX_EXECUTIONS = 200


class InventoryError(RuntimeError):
    """A typed refusal of one inventory read."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def list_executions(
    database: Database, *, execution_port: Any = None, limit: int = MAX_EXECUTIONS,
) -> list[dict[str, Any]]:
    """Read the in-flight executions from the ledger, pid included if known."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_EXECUTIONS:
        raise InventoryError("INVENTORY_LIMIT_INVALID", f"limit must be 1..{MAX_EXECUTIONS}")
    with database.read() as conn:
        rows = conn.execute(
            "SELECT t.id AS turn_id,t.session_id,t.state,t.created_at,t.stop_requested_at,"
            "t.profile_id,p.name AS profile_name,p.harness_type,"
            "w.id AS workspace_id,w.display_name AS workspace_name,w.env_kind,"
            "q.id AS queue_item_id "
            "FROM server_turns t "
            "JOIN server_sessions s ON s.id=t.session_id "
            "JOIN server_profiles p ON p.id=t.profile_id "
            "JOIN server_workspaces w ON w.id=s.workspace_id "
            "LEFT JOIN server_queue_items q ON q.session_id=t.session_id AND q.state='pending' "
            "WHERE t.state IN ('accepted','dispatching','running','capturing') "
            "ORDER BY t.created_at, t.id",
        ).fetchall()
    if len(rows) > limit:
        raise InventoryError(
            "INVENTORY_LIMIT_EXCEEDED",
            f"more than {limit} executions are in flight; refusing a partial list",
        )
    executions: list[dict[str, Any]] = []
    for row in rows:
        state = STATE_MAP.get(str(row["state"]), "running")
        if row["stop_requested_at"]:
            state = "stopping"
        pid: int | None = None
        pid_reason = "PID_NOT_REPORTED"
        read_pid = getattr(execution_port, "pid_for", None)
        if callable(read_pid):
            pid = read_pid(str(row["turn_id"]))
            if pid is not None:
                pid_reason = None  # type: ignore[assignment]
        executions.append({
            "executionId": row["turn_id"],
            "turnId": row["turn_id"],
            "sessionId": row["session_id"],
            "profileId": row["profile_id"],
            "profile": row["profile_name"],
            "harness": row["harness_type"],
            "placement": str(row["env_kind"] or "wsl"),
            "state": state,
            "startedAt": row["created_at"],
            "workspaceId": row["workspace_id"],
            "workspace": row["workspace_name"] or row["workspace_id"],
            "queueItemId": row["queue_item_id"],
            "pid": pid,
            "pidReason": pid_reason,
            # The order's rule for the rest: only what we actually have.
            "adapterPid": None,
            "adapterPidReason": "ADAPTER_PID_NOT_REPORTED",
        })
    return executions
