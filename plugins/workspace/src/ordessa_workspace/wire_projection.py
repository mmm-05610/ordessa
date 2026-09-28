"""The Workspace domain's wire/1 record projection.

Moved out of `ordessa_server.wire.projection` by T014-S2c: `workspace_record`
had exactly one consumer in the whole tree — this plugin — and zero host call
sites, so the host file existed only to serve a plugin import. The Workspace row
and its two helpers (`environment`, `accessibility_for`, both used by nothing
else) are workspace's own contract surface, so they live here.

The stored column names are the compatibility-era ones (`env_kind`,
`connection_state`, `remote_user`); this function is the single place that
translates them into the contract's WorkspaceRecord, and `accessibility_for`
states the one honest rule: a connection this deployment cannot attest is
reported as unknown, never assumed.
"""
from __future__ import annotations

from typing import Any, Mapping


def environment(kind: str, host: str | None, user: str | None) -> dict[str, Any]:
    return {"kind": kind, "host": host, "user": user}


def workspace_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a stored workspace row onto the contract's WorkspaceRecord."""
    archived_at = row.get("archived_at")
    return {
        "id": row["id"],
        "version": int(row.get("version") or 1),
        "displayName": row.get("display_name") or row.get("remote_path") or row["id"],
        "normalizedPath": row.get("normalized_path") or row["remote_path"],
        "environment": environment(
            row.get("env_kind") or "wsl", row.get("env_host"), row.get("remote_user"),
        ),
        "accessibility": accessibility_for(row),
        "connection": {"state": "connected"} if row.get("connection_state") == "verified"
        else {"state": "connecting"},
        "archivedAt": archived_at,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def accessibility_for(row: Mapping[str, Any]) -> dict[str, Any]:
    """Readable/writable/executable are independent, per the contract.

    A verified connection is what this deployment can actually attest; whether a
    role can execute is reported as unknown (null) rather than assumed true.
    """
    verified = row.get("connection_state") == "verified"
    reasons = [] if verified else ["connection_state_unverified"]
    return {
        "readable": verified,
        "writable": verified,
        "executableForRole": None,
        "reasons": reasons,
    }
