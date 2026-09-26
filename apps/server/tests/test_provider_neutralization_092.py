"""Work Order 092 stage 2: harness-neutral provider records (the migration).

The risky, load-bearing piece is the 19->20 column-constraint drop: an existing
data root with harness-bound rows must survive the rebuild unchanged, the column
must actually become nullable, and re-running must be a no-op. The service-layer
shared-record logic (validate_references / freeze accept a NULL-harness record,
cross-harness-bound still refuses) is asserted here too against a small fake so
the neutralization is not just a DDL change with no consumer.

The *wire* half (making `protocols`/`endpoints`/harness-optional reachable
through providerModels.create) is out of this tree's write_paths (server/wire/**
is A-line) and its acceptance rides the relock chain - see the 092 stage-1
observation §4.
"""
from __future__ import annotations

import sqlite3

from pacthold.storage import database as db
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.model_configs.repository import ProviderModelRecords
from ordessa_server_compat.model_configs.service import ProviderModelService


def _v19_table(conn):
    conn.executescript(
        """
        CREATE TABLE server_credentials (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, secret_locator TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL);
        CREATE TABLE server_provider_models (
            id TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1, display_name TEXT NOT NULL,
            harness_type TEXT NOT NULL, provider_type TEXT NOT NULL,
            credential_id TEXT REFERENCES server_credentials(id),
            config_object_digest TEXT NOT NULL, models_object_digest TEXT NOT NULL,
            base_url TEXT, auth_style TEXT, wire_api TEXT, fields_source TEXT,
            archived_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        """
    )


def test_migrate_19_to_20_drops_the_constraint_and_preserves_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    _v19_table(conn)
    conn.execute(
        "INSERT INTO server_provider_models(id,version,display_name,harness_type,provider_type,"
        "config_object_digest,models_object_digest,created_at,updated_at) "
        "VALUES ('p1',1,'DeepSeek','pi','deepseek','c','m','t','t')")
    conn.commit()

    db._migrate_19_to_20(conn)
    conn.commit()

    column = next(r for r in conn.execute("PRAGMA table_info(server_provider_models)")
                  if r[1] == "harness_type")
    assert column[3] == 0                                  # NOT NULL gone
    # the existing bound row is preserved verbatim
    row = conn.execute("SELECT harness_type,display_name FROM server_provider_models "
                       "WHERE id='p1'").fetchone()
    assert row == ("pi", "DeepSeek")
    # NULL is now insertable (shared upstream)
    conn.execute(
        "INSERT INTO server_provider_models(id,version,display_name,harness_type,provider_type,"
        "config_object_digest,models_object_digest,created_at,updated_at) "
        "VALUES ('p2',1,'Shared',NULL,'deepseek','c','m','t','t')")
    assert conn.execute("SELECT harness_type FROM server_provider_models WHERE id='p2'").fetchone()[0] is None


def test_migrate_19_to_20_is_idempotent(tmp_path):
    conn = sqlite3.connect(tmp_path / "y.db")
    _v19_table(conn)
    db._migrate_19_to_20(conn)
    db._migrate_19_to_20(conn)   # second call: column already nullable -> no-op, no error
    column = next(r for r in conn.execute("PRAGMA table_info(server_provider_models)")
                  if r[1] == "harness_type")
    assert column[3] == 0


def test_fresh_schema_is_at_version_21_with_nullable_harness(tmp_path):
    # Version constant follows every approved migration (a-3 K1 20->21 here);
    # the harness-nullability assertion this pin really guards is unchanged.
    database = db.Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.read() as conn:
        assert conn.execute(
            "SELECT version FROM agentbox_product_schema WHERE singleton=1").fetchone()[0] == 21
        column = next(r for r in conn.execute("PRAGMA table_info(server_provider_models)")
                      if r[1] == "harness_type")
        assert column[3] == 0


class _StubRecords:
    def __init__(self, row):
        self._row = row

    def get(self, provider_id):
        return self._row


class _StubObjects:
    def read(self, digest):
        import json
        return json.dumps({"models": [{"modelId": "m1", "displayName": "m",
                                       "availability": "available", "unavailableReason": None}]})


def _service(row):
    svc = ProviderModelService.__new__(ProviderModelService)
    svc.records = _StubRecords(row)
    svc.objects = _StubObjects()
    svc.harnesses = {}
    svc.credentials = None
    svc.profiles = None
    return svc


def test_shared_record_is_referenced_by_any_harness_and_bound_still_refuses():
    shared = {"archived_at": None, "harness_type": None,
              "models_object_digest": "m", "id": "p"}
    bound_pi = {"archived_at": None, "harness_type": "pi",
                "models_object_digest": "m", "id": "p"}
    # A shared record: claude may reference it.
    _service(shared).validate_references("claude-code", [
        {"value": {"providerId": "p", "modelId": "m1"}}])
    # A pi-bound record: claude must still be refused (boundary unchanged).
    with _expect_invalid():
        _service(bound_pi).validate_references("claude-code", [
            {"value": {"providerId": "p", "modelId": "m1"}}])


class _expect_invalid:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        from ordessa_server.errors import ServerError
        assert exc_type is ServerError and getattr(exc, "status", None) == 422
        return True


def test_repository_inserts_a_shared_row(tmp_path):
    database = db.Database(tmp_path / "r.sqlite3")
    database.initialize()
    repository = ProviderModelRecords(database, IdempotentRecords(database))
    _status, result = repository.create(
        key="k1", request_digest="d1", display_name="Shared", harness_type=None,
        provider_type="deepseek", credential_id=None, config_digest="c", models_digest="m")
    row = repository.get(result["providerModelId"])
    assert row["harness_type"] is None
