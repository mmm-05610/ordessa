"""Request de-duplication records shared by all neutral use cases.

One row per (scope, key). A replay with a different request body is a
conflict; a replay with the same body returns the stored receipt. The
insert is atomic with the business acceptance inside the caller's
transaction, which is what makes exactly one racer the acceptance owner.
"""
from __future__ import annotations

import json
from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.ids import now
from ordessa_server.storage_port import DatabasePort


class IdempotentRecords:
    def __init__(self, database: DatabasePort) -> None:
        self.database = database

    @staticmethod
    def check(conn, scope: str, key: str, request_digest: str):
        """Return a prior receipt inside an open transaction, or None."""
        row = conn.execute(
            "SELECT * FROM server_idempotency WHERE scope=? AND key=?", (scope, key)
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != request_digest:
            raise ServerError(
                "IDEMPOTENCY_CONFLICT",
                "Idempotency-Key was already used with a different request",
                status=409,
            )
        return int(row["status_code"]), json.loads(row["response_json"])

    @staticmethod
    def insert(conn, scope: str, key: str, request_digest: str, status: int, body: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO server_idempotency(scope,key,request_digest,status_code,response_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (scope, key, request_digest, status, json.dumps(body, sort_keys=True), now()),
        )

    def get(self, scope: str, key: str, request_digest: str):
        with self.database.read() as conn:
            return self.check(conn, scope, key, request_digest)

    def save(self, scope: str, key: str, request_digest: str, status: int, body: dict[str, Any]):
        """Store a receipt after the fact; returns the winner's receipt."""
        with self.database.transaction() as conn:
            prior = self.check(conn, scope, key, request_digest)
            if prior:
                return prior
            self.insert(conn, scope, key, request_digest, status, body)
            return status, body
