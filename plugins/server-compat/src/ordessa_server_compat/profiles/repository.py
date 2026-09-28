"""Storage for Profile role records; capability claims are not stored here.

Stored rows carry configuration identity only. Any capability statement in
a response is joined by the use case from the registered Harness descriptor,
so an unregistered or unverified Harness can never look capable.
"""
from __future__ import annotations

import json

from typing import Any

from server_plugin_api import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold_runtime_compat.storage import Database


class ProfileRecords:
    def __init__(self, database: Database, idempotency: IdempotentRecords) -> None:
        self.database = database
        self.idempotency = idempotency

    def create(
        self, *, key: str, request_digest: str, name: str, harness_type: str,
        config_digest: str, credential_id: str | None,
    ) -> tuple[int, dict[str, Any]]:
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, "POST:/profiles", key, request_digest)
            if prior:
                return prior
            if credential_id is not None and conn.execute(
                "SELECT 1 FROM server_credentials WHERE id=?", (credential_id,),
            ).fetchone() is None:
                raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
            timestamp = now()
            body = {
                "profile_id": opaque_id("profile"), "name": name,
                "harness_type": harness_type, "config_revision": 1,
                "native_generation": 0, "credential_id": credential_id,
                "run_state": "idle",
            }
            conn.execute(
                "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,native_generation,config_object_digest,credential_id,display_name,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (body["profile_id"], 1, name, harness_type, 1, 0, config_digest,
                 credential_id, name,
                 timestamp, timestamp),
            )
            self.idempotency.insert(conn, "POST:/profiles", key, request_digest, 201, body)
            return 201, body

    def get(self, profile_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone()
        if row is None:
            raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
        return dict(row)

    def exists(self, conn, profile_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM server_profiles WHERE id=?", (profile_id,),
        ).fetchone() is not None

    def list(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            if include_archived:
                rows = conn.execute("SELECT * FROM server_profiles ORDER BY created_at,id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM server_profiles WHERE archived_at IS NULL ORDER BY created_at,id"
                ).fetchall()
        return [dict(row) for row in rows]

    def update_display_name(
        self, *, profile_id: str, expected_version: int, display_name: str,
        key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._mutate(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=request_digest, operation="update",
            assignments={"name": display_name, "display_name": display_name},
        )

    def update_configuration(
        self, *, profile_id: str, expected_version: int, config_digest: str,
        key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._mutate(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=request_digest, operation="updateConfig",
            assignments={"config_object_digest": config_digest}, bump_config=True,
        )

    def archive(
        self, *, profile_id: str, expected_version: int, key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        return self._mutate(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=request_digest, operation="archive",
            assignments={"archived_at": now()},
        )

    def clone_from(
        self, *, source_id: str, name: str, harness_type: str,
        report: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Write the clone row from a plan computed by the caller.

        Only what the plan says travels: the family, the configuration object
        (same family), the credential/account references (same family), the
        permission posture, and the origin (source id + time). Native session
        material is not in this list by construction.
        """
        source = self.get(source_id)
        same_family = str(source["harness_type"]) == harness_type
        timestamp = now()
        profile_id = opaque_id("profile")
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
                "native_generation,config_object_digest,credential_id,account_id,"
                "permission_preset,permission_rules_json,origin_profile_id,cloned_at,"
                "display_name,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (profile_id, 1, name, harness_type, 1, 0,
                 source["config_object_digest"] if same_family else "",
                 source.get("credential_id") if same_family else None,
                 source.get("account_id") if same_family else None,
                 source.get("permission_preset"),
                 source.get("permission_rules_json"),
                 source_id, timestamp, name, timestamp, timestamp),
            )
            return dict(conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone())

    def grant_subagent(self, *, parent_id: str, child_id: str) -> dict[str, Any]:
        """Grant one delegation edge (idempotent; nothing is granted by default)."""
        if parent_id == child_id:
            raise ServerError("SUBAGENT_CYCLE", "a Profile cannot call itself", status=409)
        timestamp = now()
        with self.database.transaction() as conn:
            for profile_id in (parent_id, child_id):
                if conn.execute(
                    "SELECT 1 FROM server_profiles WHERE id=?", (profile_id,),
                ).fetchone() is None:
                    raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            # A grant that would close a cycle is refused here rather than at
            # call time: A→B→A never becomes representable.
            if conn.execute(
                "SELECT 1 FROM server_subagent_grants WHERE parent_profile_id=? "
                "AND child_profile_id=?", (child_id, parent_id),
            ).fetchone() is not None:
                raise ServerError(
                    "SUBAGENT_CYCLE",
                    "that grant would close a delegation cycle", status=409,
                )
            conn.execute(
                "INSERT OR IGNORE INTO server_subagent_grants("
                "parent_profile_id,child_profile_id,created_at) VALUES (?,?,?)",
                (parent_id, child_id, timestamp),
            )
            return {"parentProfileId": parent_id, "childProfileId": child_id}

    def revoke_subagent(self, *, parent_id: str, child_id: str) -> None:
        with self.database.transaction() as conn:
            removed = conn.execute(
                "DELETE FROM server_subagent_grants WHERE parent_profile_id=? "
                "AND child_profile_id=?", (parent_id, child_id),
            )
            if removed.rowcount != 1:
                raise ServerError(
                    "SUBAGENT_GRANT_NOT_FOUND", "that grant does not exist", status=404)

    def subagent_grants(self, *, parent_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            if parent_id is None:
                rows = conn.execute(
                    "SELECT * FROM server_subagent_grants ORDER BY parent_profile_id,"
                    "child_profile_id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM server_subagent_grants WHERE parent_profile_id=? "
                    "ORDER BY child_profile_id", (parent_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_permissions(
        self, *, profile_id: str, preset: str, rules: Sequence[Any],
        expected_version: int, key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        """Write the profile's permission posture (order 60 A).

        The rules are validated against the closed key/action sets before
        anything is stored, and stored in order: the resolution is
        last-match-wins, so the order *is* part of the configuration.
        """
        from ordessa_server_compat.profiles.permissions import (
            PermissionRuleError,
            effective_rules,
        )

        try:
            expanded = effective_rules(preset, rules)
        except PermissionRuleError as refusal:
            raise ServerError(refusal.code, refusal.message, status=409) from refusal
        return self._mutate(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=request_digest, operation="update", bump_config=True,
            assignments={
                "permission_preset": preset,
                "permission_rules_json": json.dumps(expanded, sort_keys=False),
            },
        )

    def bind_account(
        self, *, profile_id: str, account_id: str | None, expected_version: int,
        key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        """Order 56: name the subscription account this Profile materialises.

        `None` unbinds. The account row owns the asset; this is only the
        reference, and the write goes through the same versioned mutation the
        other profile updates use.
        """
        return self._mutate(
            profile_id=profile_id, expected_version=expected_version, key=key,
            request_digest=request_digest, operation="update",
            assignments={"account_id": account_id},
        )

    def _mutate(
        self, *, profile_id: str, expected_version: int, key: str,
        request_digest: str, operation: str, assignments: dict[str, Any],
        bump_config: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        scope = f"profiles.{operation}:{profile_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return prior
            row = conn.execute("SELECT * FROM server_profiles WHERE id=?", (profile_id,)).fetchone()
            if row is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            if int(row["version"]) != expected_version:
                error = ServerError(
                    "RECORD_VERSION_CONFLICT", "Profile changed before the update", status=409,
                )
                error.current = dict(row)  # type: ignore[attr-defined]
                raise error
            if operation == "archive" and row["archived_at"] is not None:
                assignments = {"archived_at": row["archived_at"]}
            timestamp = now()
            fragments = [f"{name}=?" for name in assignments]
            values = list(assignments.values())
            fragments.extend(["version=version+1", "updated_at=?"])
            if bump_config:
                fragments.append("config_revision=config_revision+1")
            conn.execute(
                f"UPDATE server_profiles SET {','.join(fragments)} WHERE id=?",
                (*values, timestamp, profile_id),
            )
            updated = dict(conn.execute(
                "SELECT * FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone())
            body = {"profile": updated}
            self.idempotency.insert(conn, scope, key, request_digest, 200, body)
            return 200, body
