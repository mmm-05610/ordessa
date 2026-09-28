"""The compatibility core's wire/1 record and event projections.

Moved out of `ordessa_server.wire.projection` by T014-S2c: the measured symbol
table in `specs/010-platform-core/reports/B.md` shows the host contains no call
site for any of these five projectors — they exist for the domains that own the
stored rows — so a plugin importing them from the host was a pure rule-3 breach
with no host reason behind it. Profiles, sessions, executions and event frames
are the compatibility core's records, so they live here now; the workspace
projection went to `ordessa_workspace.wire_projection`, the domain that owns
that row.

Internal storage keeps the 37-era names (`turn`, `connection_state`, internal
event kinds) so retained evidence stays meaningful; this module is the single
place that translates them into the contract's vocabulary (`executionId`,
`version`, `connection`, the wire event kinds). The set is a fact this module
owns, so no sentence here counts it.

No Harness brand is interpreted here; `harness` travels as an opaque data field.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from server_plugin_api.wire_errors import WireError

#: `workspace.connection` is **reserved, with no producer** (order 145, `AUD-B-011`):
#: nothing in the Server appends the kind, so the Server never emits it today.
#: It is not deleted because the blocker is structural, not accidental -
#: `server_session_events.session_id` is NOT NULL and `EventFrame.sessionId` is
#: required, so a session-less browsing phase has no stream that could carry the
#: frame; whether it should be a synchronous result or a second session-free
#: channel is a contract decision (ops: `agent-box-server-round1` status, 需前端在合同层裁决).
#: The gate is `apps/server/tests/test_workspace_connection_reserved_145.py`: it
#: reads a real session's frames and fails if this kind ever appears, and its
#: counter-example writes a row by hand to prove the pipe is live.


WIRE_EVENT_KINDS = frozenset({
    "message.delta",
    "message.final",
    "usage.updated",
    "thought.delta",
    "plan.updated",
    "mode.updated",
    "tool.update",
    "approval.requested",
    "approval.settled",
    "config.changed",
    "execution.state",
    "queue.updated",
    "workspace.connection",
})


# Internal kind -> wire kind. Kinds absent here are internal bookkeeping and are
# not projected onto the event stream at all (for example turn.capture).
_EVENT_KIND_MAP = {
    "turn.accepted": "execution.state",
    "turn.state": "execution.state",
    "message.delta": "message.delta",
    "message.final": "message.final",
    "usage.updated": "usage.updated",
    "thought.delta": "thought.delta",
    "plan.updated": "plan.updated",
    "mode.updated": "mode.updated",
    "tool.update": "tool.update",
    "approval.requested": "approval.requested",
    "approval.settled": "approval.settled",
    "config.changed": "config.changed",
    "queue.updated": "queue.updated",
    "workspace.connection": "workspace.connection",
}


#: The states a stop request can interrupt. A terminal execution that receives a
#: late cancel keeps its terminal state: "stopping" is a fact about an execution
#: that is still running.
_LIVE_EXECUTION_STATES = frozenset({"queued", "dispatched", "running"})


_EXECUTION_STATE_MAP = {
    "accepted": "queued",
    "dispatching": "dispatched",
    "running": "running",
    "capturing": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "stopped",
    "unknown": "unknown",
}


def _tri_state(row: Mapping[str, Any], column: str) -> bool | None:
    """The column as a fact the client can branch on: true, false, or unknown.

    `None` means the row did not carry the column at all. Collapsing that into
    `False` would tell a client "nothing is blocking this Profile" when the
    Server actually does not know (order 117, `C-43`'s `Unknown`).
    """
    if column not in row:
        return None
    return bool(row[column])


def _latest_usage(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The session-level latest usage fact, or None while unknown."""
    try:
        raw = row.get("latest_usage")
    except (AttributeError, KeyError, TypeError):
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def profile_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "version": int(row.get("version") or 1),
        "displayName": row.get("display_name") or row.get("name") or row["id"],
        "harness": row["harness_type"],
        # Order 56: the bound subscription account, or null. The locator and
        # the digest stay server-side; the client needs the reference only.
        "accountId": row.get("account_id"),
        # Order 60: the permission posture and, for a clone, where it came from.
        "permissionPreset": row.get("permission_preset"),
        "permissionRules": (
            json.loads(row["permission_rules_json"])
            if row.get("permission_rules_json") else []
        ),
        "originProfileId": row.get("origin_profile_id"),
        "archivedAt": row.get("archived_at"),
        # Order 117 (QA-009): the send blocker the accept path already obeys
        # (`sessions/repository.py` answers 409 PROFILE_RECOVERY_REQUIRED on it),
        # visible here so a client can grey the Profile out before the user has
        # typed anything. `null` is "unknown", which is not "not blocked".
        "recoveryPending": _tri_state(row, "recovery_pending"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def session_record(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "version": int(row.get("version") or 1),
        "workspaceId": row["workspace_id"],
        "profileId": row.get("profile_id"),
        "displayName": row.get("display_name") or row["id"],
        "pinned": bool(row.get("pinned", False)),
        "archivedAt": row.get("archived_at"),
        # Order 51: the session-level latest usage fact (tokens only), absent
        # while no family on this session has reported one.
        "latestUsage": _latest_usage(row),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def execution_state(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a stored Turn row onto the contract's execution state.

    `stop_requested_at` distinguishes "stop asked for" from "actually stopped",
    which the contract requires not to be conflated.
    """
    state = _EXECUTION_STATE_MAP.get(str(row.get("state")), "unknown")
    if row.get("stop_requested_at") and state == "running":
        state = "stopping"
    body: dict[str, Any] = {"state": state}
    reason = row.get("terminal_reason") or row.get("error_code")
    if reason:
        body["reason"] = str(reason)
    return body


def event_frame(row: Mapping[str, Any], codec: Any) -> dict[str, Any] | None:
    """Project one stored event onto an EventFrame, or None if not wire-visible."""
    kind = _EVENT_KIND_MAP.get(str(row["kind"]))
    if kind is None:
        return None
    normalized = dict(row)
    raw = normalized.get("data_json")
    data = json.loads(raw) if isinstance(raw, str) else dict(normalized.get("data") or {})
    event = _event_body(kind, normalized, data)
    raw_seq = int(normalized["seq"])
    seq = int(normalized.get("wire_seq") or raw_seq)
    return {
        "eventId": normalized["event_id"],
        "sessionId": normalized["session_id"],
        "seq": seq,
        "cursor": codec.encode(normalized["session_id"], raw_seq),
        "emittedAt": normalized["created_at"],
        "event": event,
    }


def _event_body(kind: str, row: Mapping[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
    session_id = row["session_id"]
    if kind == "execution.state":
        state = _EXECUTION_STATE_MAP.get(str(data.get("state")), "unknown")
        if data.get("cancel_requested") and state in _LIVE_EXECUTION_STATES:
            # core v1 §6 keeps three facts apart: a stop was *requested*, it is
            # *being stopped*, and it *stopped*. Only a live execution can be
            # "being stopped": a terminal one keeps its terminal state, because
            # republishing `completed` as `stopping` would tell the client an
            # execution is still in flight when it has already finished.
            state = "stopping"
        body: dict[str, Any] = {
            "kind": kind,
            "sessionId": session_id,
            "executionId": row.get("turn_id"),
            "state": state,
        }
        reason = data.get("error_code")
        if reason:
            body["reason"] = str(reason)
        return body
    if kind in {"message.delta", "message.final"}:
        body = {
            "kind": kind,
            "sessionId": session_id,
            "messageId": str(data.get("message_id") or row.get("turn_id") or "message"),
            "text": str(data.get("text", "")),
        }
        if kind == "message.delta":
            body["role"] = "assistant"
        else:
            body["role"] = str(data.get("role") or "assistant")
            body["displayKind"] = str(data.get("display_kind") or "visible")
        return body
    if kind == "usage.updated":
        usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
        body = {
            "kind": kind,
            "sessionId": session_id,
            "turnId": str(data.get("turn_id") or row.get("turn_id") or "turn"),
            "usage": {
                key: int(usage[key]) for key in sorted(usage)
                if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
            },
        }
        return body
    if kind == "thought.delta":
        return {
            "kind": kind, "sessionId": session_id, "text": str(data.get("text") or ""),
        }
    if kind == "plan.updated":
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        return {
            "kind": kind, "sessionId": session_id,
            "entries": [dict(entry) if isinstance(entry, Mapping) else {}
                        for entry in entries],
        }
    if kind == "mode.updated":
        return {
            "kind": kind, "sessionId": session_id,
            "currentModeId": str(data.get("currentModeId") or ""),
        }
    if kind == "tool.update":
        return {
            "kind": kind,
            "sessionId": session_id,
            "toolCallId": str(data.get("tool_call_id", "tool")),
            "messageId": data.get("message_id"),
            "tool": data.get("tool"),
            "state": str(data.get("state", "requested")),
            **({"summary": str(data["summary"])} if data.get("summary") is not None else {}),
            **({"resultExcerpt": str(data["result_excerpt"])}
               if data.get("result_excerpt") is not None else {}),
        }
    if kind == "approval.requested":
        request = data.get("request") if isinstance(data.get("request"), Mapping) else {}
        operation = request.get("operation") if isinstance(request.get("operation"), Mapping) else None
        if operation is None:
            tool_call = request.get("toolCall") if isinstance(request.get("toolCall"), Mapping) else {}
            tool = request.get("tool") or tool_call.get("name") or tool_call.get("kind")
            detail = []
            for label, value in sorted(request.items()):
                if label in {"requestId", "operation", "expiresAt", "toolCall", "options", "tool", "title"}:
                    continue
                if isinstance(value, (str, int, float, bool)):
                    detail.append({"label": str(label), "value": str(value)})
            operation = {
                "title": str(request.get("title") or tool or "Approval required"),
                "detail": detail,
                "tool": str(tool) if tool is not None else None,
            }
        return {
            "kind": kind,
            "sessionId": session_id,
            "approval": {
                "approvalId": str(data.get("approval_id")),
                "sessionId": session_id,
                "executionId": row.get("turn_id"),
                "version": int(data.get("version") or 1),
                "operation": dict(operation),
                "expiresAt": request.get("expiresAt"),
            },
        }
    if kind == "approval.settled":
        return {
            "kind": kind,
            "sessionId": session_id,
            "approvalId": str(data.get("approval_id")),
            "outcome": {
                "allow": "allowed", "deny": "denied",
                "expired": "expired", "invalidated": "invalidated",
            }.get(str(data.get("decision")), "invalidated"),
        }
    if kind == "config.changed":
        return {
            "kind": kind,
            "sessionId": session_id,
            "effectiveFor": str(data.get("effective_for") or "next_send"),
        }
    if kind == "queue.updated":
        return {
            "kind": kind,
            "sessionId": session_id,
            "item": dict(data["item"]),
        }
    if kind == "workspace.connection":
        return {
            "kind": kind,
            "workspaceId": str(data.get("workspace_id", "")),
            "connection": data.get("connection") or {"state": "connecting"},
        }
    raise WireError("UNAVAILABLE", f"event kind {kind} has no projection")
