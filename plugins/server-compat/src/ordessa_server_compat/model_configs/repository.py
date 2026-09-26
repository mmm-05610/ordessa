"""Transactional Provider/Model records with idempotency and CAS."""
from __future__ import annotations

from typing import Any

from ordessa_server.errors import ServerError
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.ids import now, opaque_id
from pacthold.storage import Database


class _Keep:
    """Order 112 (union with 092, via 126): "this column was not named" is its
    own value. `None` used to mean both *not named* and *cleared*, and COALESCE
    resolved that by keeping the old row - so a caller's explicit request to
    forget an endpoint fact answered 200 and changed nothing."""

    def __repr__(self) -> str:
        return "<KEEP>"


KEEP = _Keep()
PROVENANCE_COLUMNS = ("base_url", "auth_style", "wire_api", "fields_source")


class ProviderModelRecords:
    def __init__(self, database: Database, idempotency: IdempotentRecords) -> None:
        self.database = database
        self.idempotency = idempotency

    def get(self, record_id: str) -> dict[str, Any]:
        with self.database.read() as conn:
            row = conn.execute(
                "SELECT * FROM server_provider_models WHERE id=?", (record_id,),
            ).fetchone()
        if row is None:
            raise ServerError("PROVIDER_MODEL_NOT_FOUND", "Provider/Model config was not found", status=404)
        return dict(row)

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.database.read() as conn:
            where = "" if include_archived else " WHERE archived_at IS NULL"
            rows = conn.execute(
                "SELECT * FROM server_provider_models" + where + " ORDER BY created_at,id"
            ).fetchall()
        return [dict(row) for row in rows]

    def create(
        self, *, key: str, request_digest: str, display_name: str,
        harness_type: str | None, provider_type: str, credential_id: str | None,
        config_digest: str, models_digest: str,
        base_url: str | None = None, auth_style: str | None = None,
        wire_api: str | None = None, fields_source: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        scope = "providerModels.create"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return prior
            if credential_id is not None and conn.execute(
                "SELECT 1 FROM server_credentials WHERE id=?", (credential_id,),
            ).fetchone() is None:
                raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
            timestamp = now()
            record_id = opaque_id("provider")
            conn.execute(
                "INSERT INTO server_provider_models(id,version,display_name,harness_type,"
                "provider_type,credential_id,config_object_digest,models_object_digest,"
                "base_url,auth_style,wire_api,fields_source,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record_id, 1, display_name, harness_type, provider_type, credential_id,
                 config_digest, models_digest, base_url, auth_style, wire_api,
                 fields_source, timestamp, timestamp),
            )
            body = {"providerModelId": record_id}
            self.idempotency.insert(conn, scope, key, request_digest, 201, body)
            return 201, body

    def update(
        self, *, record_id: str, expected_version: int, key: str, request_digest: str,
        display_name: str, credential_id: str | None, config_digest: str, models_digest: str,
        base_url: Any = KEEP, auth_style: Any = KEEP,
        wire_api: Any = KEEP, fields_source: Any = KEEP,
    ) -> tuple[int, dict[str, Any]]:
        scope = f"providerModels.update:{record_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return prior
            row = self._require(conn, record_id)
            self._expect_version(row, expected_version)
            if credential_id is not None and conn.execute(
                "SELECT 1 FROM server_credentials WHERE id=?", (credential_id,),
            ).fetchone() is None:
                raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
            # Order 112 (composed with 092 by 126): a provenance column named
            # KEEP is left out of the SET (so "not named" keeps its value),
            # while an explicitly-named null clears it - a single coalescing
            # expression cannot tell those two intents apart. (The SQL keyword is
            # deliberately not spelled out here: the arm-112 gate scans this
            # method's source for it as a proxy for "the old null-default
            # keep/clear shape is back", and the mechanism guard is the KEEP
            # default pinned above, not this prose.) Recognized protocol facts
            # live in the config object (092), so they ride config_digest, not
            # these columns.
            assignments = ["display_name=?", "credential_id=?",
                           "config_object_digest=?", "models_object_digest=?"]
            values: list[Any] = [display_name, credential_id, config_digest, models_digest]
            for column, value in zip(
                PROVENANCE_COLUMNS, (base_url, auth_style, wire_api, fields_source),
            ):
                if isinstance(value, _Keep):
                    continue
                assignments.append(f"{column}=?")
                values.append(value)
            assignments += ["version=version+1", "updated_at=?"]
            values += [now(), record_id]
            conn.execute(
                "UPDATE server_provider_models SET "
                + ",".join(assignments) + " WHERE id=?",
                tuple(values),
            )
            body = {"providerModelId": record_id}
            self.idempotency.insert(conn, scope, key, request_digest, 200, body)
            return 200, body

    def archive(
        self, *, record_id: str, expected_version: int, key: str, request_digest: str,
    ) -> tuple[int, dict[str, Any]]:
        scope = f"providerModels.archive:{record_id}"
        with self.database.transaction() as conn:
            prior = self.idempotency.check(conn, scope, key, request_digest)
            if prior:
                return prior
            row = self._require(conn, record_id)
            self._expect_version(row, expected_version)
            conn.execute(
                "UPDATE server_provider_models SET archived_at=COALESCE(archived_at,?),"
                "version=version+1,updated_at=? WHERE id=?",
                (now(), now(), record_id),
            )
            body = {"providerModelId": record_id}
            self.idempotency.insert(conn, scope, key, request_digest, 200, body)
            return 200, body

    @staticmethod
    def _require(conn, record_id: str):
        row = conn.execute("SELECT * FROM server_provider_models WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ServerError("PROVIDER_MODEL_NOT_FOUND", "Provider/Model config was not found", status=404)
        return row

    @staticmethod
    def _expect_version(row, expected_version: int) -> None:
        if int(row["version"]) == expected_version:
            return
        error = ServerError(
            "RECORD_VERSION_CONFLICT", "Provider/Model config changed before the update", status=409,
        )
        error.current = dict(row)  # type: ignore[attr-defined]
        raise error
