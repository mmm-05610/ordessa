"""Credential registration records; secret contents stay in the SecretStore."""
from __future__ import annotations

from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.ids import now
from ordessa_server.storage_port import DatabasePort


class CredentialRecords:
    def __init__(self, database: DatabasePort) -> None:
        self.database = database

    def register(self, credential_id: str, kind: str, secret_locator: str) -> dict[str, Any]:
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT INTO server_credentials(id,kind,secret_locator,created_at) VALUES (?,?,?,?)",
                (credential_id, kind, secret_locator, now()),
            )
        return {"credential_id": credential_id, "kind": kind}

    def register_if_missing(
        self, credential_id: str, kind: str, secret_locator: str,
    ) -> dict[str, Any]:
        """Establish an injectable credential as a bindable identity, once.

        Order 149 (`R-0078 ①`) is the single idempotent identity entry: every
        *supported* injection path - the deployment declaration, the trial
        launcher's ``--credential-id`` injection, and order 151's controlled wire
        entry - resolves its credential to a name the record layer can bind, and
        they share this one definition rather than re-implementing an ``exists()``
        guard next to a bare ``register()``.

        A name that already resolves is left exactly as it is - no second row, and
        the secret source is never re-read (the caller owns the store; this names
        the identity, it does not import a secret). Checking and creating happen in
        one transaction, so a concurrent double-declare cannot raise
        ``IntegrityError``. ``created`` reports which of the two happened so a
        caller can judge the half state (a name injected but never registered)
        rather than guess.

        It deliberately does not touch the wire family: a credential that was never
        injected stays a ``CREDENTIAL_NOT_FOUND`` at bind time, because widening
        that would turn "bound to the wrong credential" into a failure at
        execution time.
        """
        with self.database.transaction() as conn:
            prior = conn.execute(
                "SELECT id,kind,secret_locator,created_at FROM server_credentials WHERE id=?",
                (credential_id,),
            ).fetchone()
            if prior is not None:
                return {
                    "credential_id": prior["id"], "kind": prior["kind"],
                    "secret_locator": prior["secret_locator"], "created": False,
                }
            conn.execute(
                "INSERT INTO server_credentials(id,kind,secret_locator,created_at) VALUES (?,?,?,?)",
                (credential_id, kind, secret_locator, now()),
            )
        return {"credential_id": credential_id, "kind": kind, "created": True}

    def list(self) -> list[dict[str, Any]]:
        """Every registered credential, without its locator.

        The locator is where the secret lives, so it stays inside the Server: a
        client that offers a choice needs the id and the kind, not the address.
        """
        with self.database.read() as conn:
            rows = conn.execute(
                "SELECT id,kind,created_at FROM server_credentials ORDER BY created_at,id",
            ).fetchall()
        return [
            {"credentialId": row["id"], "kind": row["kind"], "createdAt": row["created_at"]}
            for row in rows
        ]

    def exists(self, credential_id: str) -> bool:
        """Whether this id already resolves; used to make a restart idempotent.

        Registration names an identity, so re-declaring it in a deployment must
        satisfy it rather than duplicate it (the id is the primary key) or
        re-read its source.
        """
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT 1 FROM server_credentials WHERE id=?", (credential_id,),
            ).fetchone()
        return row is not None

    def get(self, credential_id: str, *, kind: str | None = None) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_credentials WHERE id=?", (credential_id,),
            ).fetchone()
        if row is None or (kind is not None and row["kind"] != kind):
            raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
        return dict(row)

    def has(self, *, kind: str | None = None) -> bool:
        with self.database.read() as conn:
            if kind is None:
                row = conn.execute("SELECT 1 FROM server_credentials LIMIT 1").fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM server_credentials WHERE kind=? LIMIT 1", (kind,),
                ).fetchone()
        return row is not None
