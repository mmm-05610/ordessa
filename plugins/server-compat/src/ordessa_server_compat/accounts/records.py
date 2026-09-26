"""Order 56: the account ledger - identity, state, and the asset reference.

One row per managed subscription account. The row never carries a token: it
carries the SecretStore locator, the asset digest, and the family the account
belongs to. `state` is what the product shows ("unknown" until a turn actually
ran with the account, then "valid" after a successful reclaim); it is derived
from observed turns, never asserted by an import.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


class AccountRecords:
    def __init__(self, database: Database, idempotency: IdempotentRecords) -> None:
        self.database = database
        self.idempotency = idempotency

    def create(
        self, *, key: str, request_digest: str, harness_type: str,
        account_identifier: str,
    ) -> tuple[str, dict[str, Any]]:
        scope = "accounts.create"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return "replay", prior[1]
            if not harness_type or not account_identifier:
                raise ServerError(
                    "ACCOUNT_INVALID", "an account needs a family and an identifier", status=400,
                )
            account_id = opaque_id("account")
            timestamp = now()
            conn.execute(
                "INSERT INTO server_accounts(id,harness_type,account_identifier,state,"
                "created_at,updated_at) VALUES (?,?,?,'unknown',?,?)",
                (account_id, harness_type, account_identifier, timestamp, timestamp),
            )
            body = self._view(conn, account_id)
            self.idempotency.insert(conn, scope, key, request_digest, 201, body)
            return "created", body

    def get(self, account_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_accounts WHERE id=?", (account_id,),
            ).fetchone()
        if row is None:
            raise ServerError("ACCOUNT_NOT_FOUND", "Account was not found", status=404)
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT * FROM server_accounts ORDER BY created_at, id",
            ).fetchall()
        return [dict(row) for row in rows]

    def asset_reference(self, account_id: str) -> tuple[str | None, str | None]:
        """(locator, digest) - the reference a turn materialises from."""
        row = self.get(account_id)
        return row.get("asset_locator"), row.get("asset_digest")

    def record_asset(
        self, account_id: str, *, locator: str, digest: str, state: str,
    ) -> dict[str, Any]:
        """Write the reference back after a reclaim (never a token)."""
        timestamp = now()
        with self.database.transaction() as conn:
            updated = conn.execute(
                "UPDATE server_accounts SET asset_locator=?,asset_digest=?,state=?,"
                "last_verified_at=?,updated_at=? WHERE id=?",
                (locator, digest, state, timestamp, timestamp, account_id),
            )
            if updated.rowcount != 1:
                raise ServerError("ACCOUNT_NOT_FOUND", "Account was not found", status=404)
            return self._view(conn, account_id)

    def _view(self, conn, account_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM server_accounts WHERE id=?", (account_id,),
        ).fetchone()
        return {
            "account_id": row["id"],
            "harness_type": row["harness_type"],
            "account_identifier": row["account_identifier"],
            "state": row["state"],
            "has_asset": row["asset_locator"] is not None,
            "last_verified_at": row["last_verified_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def account_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """The wire-facing shape: no locator, no digest, no token."""
    return {
        "accountId": row["id"],
        "harnessType": row["harness_type"],
        "accountIdentifier": row["account_identifier"],
        "state": row["state"],
        "hasAsset": row.get("asset_locator") is not None,
        "lastVerifiedAt": row.get("last_verified_at"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
