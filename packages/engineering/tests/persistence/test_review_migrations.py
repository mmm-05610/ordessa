"""Synthetic SQLite acceptance for the explicit schema4->5 review migration."""
from ordessa_engineering.application.usecases.material_closure import verify_material
import hashlib
import sqlite3
from pathlib import Path

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.artifacts.library_material_codec import canonical_json, material_ref_to_dict


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:review-migration"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
OLD_TABLES = (
    "library_meta", "materials", "heads", "runs", "step_log", "idempotency",
    "eng_method_blobs", "eng_method_snapshots", "eng_method_releases", "eng_schema_migrations",
    "eng_artifacts", "eng_artifact_revisions", "eng_revision_parents", "eng_commands",
)
REVIEW_TABLES = (
    "eng_review_requirements", "eng_review_sets", "eng_review_plans", "eng_review_requests",
    "eng_reviews", "eng_review_controls", "eng_review_control_events",
)


def _all_rows(connection: sqlite3.Connection):
    return {
        table: tuple(sorted((tuple(row) for row in connection.execute("SELECT * FROM " + table)), key=repr))
        for table in OLD_TABLES
    }


def _all_rows_at(path: Path):
    connection = sqlite3.connect(path)
    try:
        return _all_rows(connection)
    finally:
        connection.close()


def _schema_version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def _seed_schema4(path: Path, backup3: Path) -> tuple[Library, dict]:
    library = Library.create(path.resolve(), library_id=LIBRARY_ID, schema_version=3)
    migrations.migrate_schema3(library, backup_path=backup3.resolve())

    scope = Scope("realm-review-migration", "project-review-migration")
    factory = SQLiteUoWFactory(library)
    with factory.begin(scope, "write") as uow:
        artifact = Artifact(scope, "artifact-1", "plan", CREATED_AT)
        uow.engineering.create(artifact)
        revision = ArtifactRevision(
            scope, artifact.artifact_id, "revision-1", CREATED_AT,
            ActorRef("author-1", "human", "synthetic-migration"),
            InlinePayload.from_value("application/json", "urn:test:artifact", {"v": 1}),
        )
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=0)
        key = CommandKey(scope.realm_id, "principal-1", "request-1")
        reserved = uow.commands.reserve(
            key, project_id=scope.project_id, operation="engineering.artifacts.create",
            operation_id="operation-1", request_digest=Digest("sha256", "a" * 64),
        )
        uow.commands.complete(
            key, expected_version=reserved.entry.version,
            result_bytes=canonical_bytes({"artifact_id": artifact.artifact_id}),
        )
        uow.commit()

    # Preserve opaque method-store bytes verbatim through the next schema step.
    blob = b"method resource\x00with opaque bytes\xff"
    snapshot = b"method snapshot bytes\x00not decoded by migration"
    blob_digest = hashlib.sha256(blob).hexdigest()
    snapshot_digest = hashlib.sha256(snapshot).hexdigest()
    material = library.import_material(kind="method", stable_id="method-old", body={"source": "old"})
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_method_blobs VALUES (?, ?, ?)",
                           (blob_digest, len(blob), blob))
        connection.execute("INSERT INTO eng_method_snapshots VALUES (?, ?)",
                           (snapshot_digest, snapshot))
        connection.execute("INSERT INTO eng_method_releases VALUES (?, ?, ?, ?)",
                           ("method-old", "1", 1, snapshot_digest))
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-old", canonical_json(material_ref_to_dict(material)), canonical_json({"registry": "r1"}),
             canonical_json({"request": "old"}), "WAITING", (1 << 53) + 123, "review",
             CREATED_AT, CREATED_AT))
        connection.execute(
            "INSERT INTO step_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-old", 1, "step-old", "operation-old", 1, "WAITING", "{\"receipt\":\"old\"}"))
        connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?)",
            ("operation-old", "digest-old", "{\"receipt\":\"old\"}"))

    seed = {
        "blob": blob,
        "snapshot": snapshot,
        "artifact_revision_bytes": library._connection.execute(
            "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-1'").fetchone()[0],
        "command_result_bytes": library._connection.execute(
            "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0],
        "review_receipt4": library._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=4").fetchone(),
    }
    return library, seed


def _prepare_schema4(tmp_path: Path) -> tuple[Path, Path, dict]:
    path = tmp_path / "library-v4.sqlite"
    backup3 = tmp_path / "library-v3-backup.sqlite"
    library, seed = _seed_schema4(path, backup3)
    assert library._schema_version == 4
    assert _schema_version(path) == 4
    original_rows = _all_rows(library._connection)
    assert original_rows["runs"][0][5] == (1 << 53) + 123
    library.close()
    return path, tmp_path / "library-v4-backup.sqlite", {
        **seed,
        "original_rows": original_rows,
        "backup3": backup3,
    }


def test_explicit_schema4_to5_preserves_rows_bytes_receipt_and_reconciles_on_reopen(tmp_path):
    path, backup, seed = _prepare_schema4(tmp_path)
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    before_digest = migrations._source_digest(library._connection, source_version=4)
    source_connection = library._connection

    receipt = migrations.migrate_schema4(library, backup_path=backup.resolve())
    assert receipt.applied is True
    assert receipt.target_version == 5
    assert receipt.source_digest == before_digest
    assert receipt.backup_path == str(backup.resolve())
    assert len(receipt.source_digest) == len(receipt.backup_sha256) == 64
    assert library._connection is source_connection
    assert library._schema_version == 5
    assert _schema_version(path) == 5
    assert set(OLD_TABLES + REVIEW_TABLES) <= _table_names(path)

    # The old rows are unchanged except schema metadata; the new migration
    # receipt is the only allowed addition to the old receipt table.
    after_rows = _all_rows(library._connection)
    after_rows["library_meta"] = tuple(row[:2] + (4,) + row[3:]
                                       for row in after_rows["library_meta"])
    after_rows["eng_schema_migrations"] = tuple(
        row for row in after_rows["eng_schema_migrations"] if row[0] != 5)
    assert after_rows == seed["original_rows"]
    assert library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=4").fetchone() == seed["review_receipt4"]
    assert library._connection.execute(
        "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-1'").fetchone()[0] == seed["artifact_revision_bytes"]
    assert library._connection.execute(
        "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0] == seed["command_result_bytes"]
    assert library._connection.execute(
        "SELECT body FROM eng_method_blobs").fetchone()[0] == seed["blob"]
    assert library._connection.execute(
        "SELECT canonical_bytes FROM eng_method_snapshots").fetchone()[0] == seed["snapshot"]
    assert library._connection.execute("SELECT cursor FROM runs WHERE run_id='run-old'").fetchone()[0] == (
        (1 << 53) + 123)
    assert library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=5").fetchone() == (
            5, receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt.backup_sha256

    backup_library = Library.open(backup.resolve(), library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 4
        assert _all_rows(backup_library._connection) == seed["original_rows"]
        assert not set(REVIEW_TABLES) & _table_names(backup)
    finally:
        backup_library.close()

    migrated_bytes = path.read_bytes()
    backup_bytes = backup.read_bytes()
    repeated = migrations.migrate_schema4(library, backup_path=backup.resolve())
    assert repeated.applied is False
    assert (repeated.source_digest, repeated.backup_sha256, repeated.backup_path) == (
        receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert path.read_bytes() == migrated_bytes
    assert backup.read_bytes() == backup_bytes
    library.close()

    reopened = Library.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 5
        assert reopened._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=5").fetchone() == (
                5, receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
        assert reopened._connection.execute("SELECT COUNT(*) FROM eng_review_requirements").fetchone() == (0,)
    finally:
        reopened.close()


@pytest.mark.parametrize("failure_point", ["ddl", "receipt"])
def test_ddl_or_migration_receipt_failure_rolls_back_schema4(tmp_path, monkeypatch, failure_point):
    path, backup, seed = _prepare_schema4(tmp_path)
    base_connection = storage._LibraryConnection

    class FailingMigrationConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            if failure_point == "ddl" and sql.lstrip().startswith("CREATE TABLE eng_review_plans"):
                raise sqlite3.OperationalError("synthetic schema5 DDL failure")
            if failure_point == "receipt" and sql.strip().startswith(
                    "INSERT INTO eng_schema_migrations VALUES"):
                raise sqlite3.OperationalError("synthetic schema5 receipt failure")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", FailingMigrationConnection)
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    connection = library._connection
    expected = ("synthetic schema5 DDL failure" if failure_point == "ddl"
                else "synthetic schema5 receipt failure")
    try:
        with pytest.raises(sqlite3.OperationalError, match=expected):
            migrations.migrate_schema4(library, backup_path=backup.resolve())
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 4
        assert _all_rows_at(path) == seed["original_rows"]
        assert not set(REVIEW_TABLES) & _table_names(path)
        assert backup.exists() and _schema_version(backup) == 4
        assert _all_rows_at(backup) == seed["original_rows"]
    finally:
        library.close()
