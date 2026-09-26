"""Storage for Workspace records; one private connection per workspace."""
from __future__ import annotations

from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


class WorkspaceRecords:
    def __init__(self, database: Database, idempotency: IdempotentRecords) -> None:
        self.database = database
        self.idempotency = idempotency

    def create(
        self, *, key: str, request_digest: str, distribution: str,
        remote_user: str | None, remote_path: str, connection_id: str,
    ) -> tuple[int, dict[str, Any]]:
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, "POST:/workspaces", key, request_digest)
            if prior:
                return prior
            timestamp = now()
            body = {
                "workspace_id": opaque_id("ws"), "connection_id": connection_id,
                "distribution": distribution, "user": remote_user,
                "path": remote_path, "connection_state": "verified",
            }
            conn.execute(
                "INSERT INTO server_workspaces(id,connection_id,distribution,remote_user,remote_path,connection_state,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (body["workspace_id"], connection_id, distribution, remote_user, remote_path,
                 "verified", timestamp, timestamp),
            )
            self.idempotency.insert(conn, "POST:/workspaces", key, request_digest, 201, body)
            return 201, body

    def list(self) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT * FROM server_workspaces ORDER BY created_at,id"
            ).fetchall()
        return [{
            "workspace_id": row["id"], "connection_id": row["connection_id"],
            "distribution": row["distribution"], "user": row["remote_user"],
            "path": row["remote_path"], "connection_state": row["connection_state"],
        } for row in rows]

    def mark_all_unverified(self) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE server_workspaces SET connection_state='unverified', updated_at=? "
                "WHERE connection_state!='unverified'",
                (now(),),
            )

    def get(self, workspace_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone()
        if row is None:
            raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
        return dict(row)

    def upsert_by_location(
        self, *, env_kind: str, env_host: str | None, remote_user: str | None,
        normalized_path: str, connection_id: str | None,
    ) -> tuple[bool, dict[str, Any]]:
        """Open-or-return a Workspace identified by environment + location.

        The same path string under a different environment is a different
        location (core-semantics/1 §3), so the identity key includes the
        environment; a repeat open returns the existing id with created=False.
        """
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM server_workspaces WHERE env_kind=? AND COALESCE(env_host,'')=COALESCE(?,'') "
                "AND COALESCE(remote_user,'')=COALESCE(?,'') AND normalized_path=?",
                (env_kind, env_host, remote_user, normalized_path),
            ).fetchone()
            if row is not None:
                return False, dict(row)
            timestamp = now()
            workspace_id = opaque_id("ws")
            # A Workspace owns its own logical connection; the connector's
            # environment-scoped id is not the product identity, so two
            # locations in one environment never share this value.
            del connection_id
            # `distribution` is the legacy name of the connector's environment
            # identity and the column is NOT NULL. A local workspace has no
            # remote identity to record, so the placement itself is what the
            # column says - never a host path, never a borrowed WSL name.
            conn.execute(
                "INSERT INTO server_workspaces(id,connection_id,distribution,remote_user,remote_path,"
                "connection_state,display_name,version,archived_at,env_kind,env_host,normalized_path,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (workspace_id, opaque_id("conn"), env_host or "local", remote_user, normalized_path,
                 "verified", normalized_path.rsplit("/", 1)[-1] or normalized_path, 1, None,
                 env_kind, env_host, normalized_path, timestamp, timestamp),
            )
            created = conn.execute(
                "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone()
            return True, dict(created)

    def archive(self, *, workspace_id: str, expected_version: int) -> dict[str, Any]:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone()
            if row is None:
                raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
            if int(row["version"]) != expected_version:
                error = ServerError(
                    "RECORD_VERSION_CONFLICT",
                    "Workspace changed before archiving",
                    status=409,
                )
                error.current = dict(row)  # type: ignore[attr-defined]
                raise error
            if row["archived_at"] is None:
                # Archiving keeps the record and the project files: it is a
                # product metadata change, never a delete or a migration.
                conn.execute(
                    "UPDATE server_workspaces SET archived_at=?,version=version+1,updated_at=? WHERE id=?",
                    (now(), now(), workspace_id),
                )
            updated = conn.execute(
                "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone()
            return dict(updated)

    def list_active(self, *, include_archived: bool) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            if include_archived:
                rows = conn.execute(
                    "SELECT * FROM server_workspaces ORDER BY created_at,id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM server_workspaces WHERE archived_at IS NULL ORDER BY created_at,id"
                ).fetchall()
        return [dict(row) for row in rows]

    def get(self, workspace_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_workspaces WHERE id=?", (workspace_id,),
            ).fetchone()
        if row is None:
            raise ServerError("WORKSPACE_NOT_FOUND", "Workspace was not found", status=404)
        return dict(row)

    def mark_verified(self, workspace_id: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE server_workspaces SET connection_state='verified',updated_at=? WHERE id=?",
                (now(), workspace_id),
            )

    def exists(self, conn, workspace_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM server_workspaces WHERE id=?", (workspace_id,),
        ).fetchone() is not None
