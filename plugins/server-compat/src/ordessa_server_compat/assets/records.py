"""Order 58: the asset catalogue and the per-Profile binding.

One row per asset (kind / name / latest revision / digest / source) and one row
per binding (a Profile references an asset id and a revision, enabled or
disabled). Content never appears here - the assets root holds it, content
addressed, and the digest in the row is what a materialised projection is
verified against.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database

KINDS = ("skill", "mcp", "command", "plugin")
_ASSET_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class AssetRecords:
    def __init__(self, database: Database, idempotency: IdempotentRecords) -> None:
        self.database = database
        self.idempotency = idempotency

    def publish(
        self, *, key: str, request_digest: str, kind: str, name: str, revision: int,
        digest: str, description: str | None = None, source: str | None = None,
        asset_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Register one installed revision, creating the asset row on first use.

        The digest is required: an asset without a digest could not be verified
        when it is materialised, and the order's whole storage story is
        content addressing. `source` is the provenance string the hub sync
        records; an update never silently changes it.
        """
        if kind not in KINDS or not name or not digest.startswith("sha256:"):
            raise ServerError("ASSET_INVALID", "an asset needs a kind, a name and a digest", status=400)
        scope = f"assets.publish:{asset_id or name}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return "replay", prior[1]
            timestamp = now()
            row = None
            if asset_id is not None:
                row = conn.execute(
                    "SELECT * FROM server_assets WHERE id=?", (asset_id,),
                ).fetchone()
            if row is None:
                # A caller-chosen id is honoured on first publish: the store
                # directory, the catalogue row and every binding then share
                # one identity. Without one, the row gets an opaque id and the
                # caller installs under it.
                if asset_id is not None:
                    if _ASSET_ID.fullmatch(asset_id) is None:
                        raise ServerError(
                            "ASSET_INVALID", "asset_id must be a lowercase slug", status=400,
                        )
                else:
                    asset_id = opaque_id("asset")
                conn.execute(
                    "INSERT INTO server_assets(id,kind,name,description,latest_revision,"
                    "digest,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (asset_id, kind, name, description, revision, digest, source,
                     timestamp, timestamp),
                )
            else:
                conn.execute(
                    "UPDATE server_assets SET kind=?,name=?,description=?,latest_revision=?,"
                    "digest=?,source=COALESCE(?,source),updated_at=? WHERE id=?",
                    (kind, name, description, revision, digest, source, timestamp, asset_id),
                )
            body = self._view(conn, asset_id)
            self.idempotency.insert(conn, scope, key, request_digest, 200, body)
            return "published", body

    def get(self, asset_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute("SELECT * FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise ServerError("ASSET_NOT_FOUND", "Asset was not found", status=404)
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute("SELECT * FROM server_assets ORDER BY kind,name,id").fetchall()
        return [dict(row) for row in rows]

    def bind(
        self, *, profile_id: str, asset_id: str, revision: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Bind an asset to a Profile (idempotent per pair)."""
        asset = self.get(asset_id)
        chosen = int(asset["latest_revision"] if revision is None else revision)
        if chosen <= 0 or chosen > int(asset["latest_revision"]):
            raise ServerError("ASSET_REVISION_UNKNOWN", "that revision is not published", status=409)
        timestamp = now()
        with self.database.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM server_profiles WHERE id=?", (profile_id,),
            ).fetchone() is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,revision,enabled,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(profile_id,asset_id) DO UPDATE SET revision=?,enabled=?,updated_at=?",
                (profile_id, asset_id, chosen, 1 if enabled else 0, timestamp, timestamp,
                 chosen, 1 if enabled else 0, timestamp),
            )
            return self._binding_view(conn, profile_id, asset_id)

    def unbind(self, *, profile_id: str, asset_id: str) -> None:
        with self.database.transaction() as conn:
            removed = conn.execute(
                "DELETE FROM server_profile_assets WHERE profile_id=? AND asset_id=?",
                (profile_id, asset_id),
            )
            if removed.rowcount != 1:
                raise ServerError("ASSET_BINDING_NOT_FOUND", "that binding does not exist", status=404)

    def copy_bindings(
        self, *, source_profile_id: str, target_profile_id: str,
        items: Sequence[str],
    ) -> list[str]:
        """Copy the bindings a clone's plan marked as migrated.

        `items` are the report labels ("skill:my-skill"); only those rows are
        copied, with their revision and enabled flag, so a clone's bindings are
        exactly what the user was told traveled.
        """
        wanted = {str(item) for item in items}
        copied: list[str] = []
        timestamp = now()
        with self.database.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM server_profiles WHERE id=?", (target_profile_id,),
            ).fetchone() is None:
                raise ServerError("PROFILE_NOT_FOUND", "Profile was not found", status=404)
            rows = conn.execute(
                "SELECT b.asset_id,b.revision,b.enabled,a.kind,a.name "
                "FROM server_profile_assets b JOIN server_assets a ON a.id=b.asset_id "
                "WHERE b.profile_id=?",
                (source_profile_id,),
            ).fetchall()
            for row in rows:
                label = f"{row['kind']}:{row['name']}"
                if label not in wanted:
                    continue
                conn.execute(
                    "INSERT INTO server_profile_assets(profile_id,asset_id,revision,enabled,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(profile_id,asset_id) DO UPDATE SET revision=?,enabled=?,"
                    "updated_at=?",
                    (target_profile_id, row["asset_id"], int(row["revision"]),
                     int(row["enabled"]), timestamp, timestamp,
                     int(row["revision"]), int(row["enabled"]), timestamp),
                )
                copied.append(label)
        return sorted(copied)

    def bindings(self, profile_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT b.*,a.kind,a.name,a.digest FROM server_profile_assets b "
                "JOIN server_assets a ON a.id=b.asset_id WHERE b.profile_id=? "
                + ("AND b.enabled=1 " if enabled_only else "")
                + "ORDER BY a.kind,a.name",
                (profile_id,),
            ).fetchall()
        return [
            {
                "assetId": row["asset_id"],
                "kind": row["kind"],
                "name": row["name"],
                "revision": int(row["revision"]),
                "digest": row["digest"],
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    def _view(self, conn, asset_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM server_assets WHERE id=?", (asset_id,)).fetchone()
        return {
            "asset_id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"],
            "latest_revision": int(row["latest_revision"]),
            "digest": row["digest"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _binding_view(self, conn, profile_id: str, asset_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT b.*,a.kind,a.name,a.digest FROM server_profile_assets b "
            "JOIN server_assets a ON a.id=b.asset_id "
            "WHERE b.profile_id=? AND b.asset_id=?",
            (profile_id, asset_id),
        ).fetchone()
        return {
            "assetId": row["asset_id"],
            "kind": row["kind"],
            "name": row["name"],
            "revision": int(row["revision"]),
            "digest": row["digest"],
            "enabled": bool(row["enabled"]),
        }


def asset_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The wire-facing catalogue shape (no content, no host paths)."""
    return {
        "assetId": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "description": row.get("description"),
        "latestRevision": int(row["latest_revision"]),
        "digest": row["digest"],
        "source": row.get("source"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
