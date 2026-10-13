"""Synthetic acceptance for the explicit schema5->6 material migration."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import _schema_signature
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandKey
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:material-migration"
SCOPE = Scope("realm-material-migration", "project-material-migration")
CREATED_AT = "2026-10-09T12:00:00.000000Z"
OLD_TABLES = (
    "library_meta", "materials", "heads", "runs", "step_log", "idempotency",
    "eng_method_blobs", "eng_method_snapshots", "eng_method_releases", "eng_schema_migrations",
    "eng_artifacts", "eng_artifact_revisions", "eng_revision_parents", "eng_commands",
    "eng_review_requirements", "eng_review_sets", "eng_review_plans", "eng_review_requests",
    "eng_reviews", "eng_review_controls", "eng_review_control_events",
)


def _rows(connection):
    return {table: tuple(sorted((tuple(row) for row in connection.execute("SELECT * FROM " + table)),
                                key=repr)) for table in OLD_TABLES}


def _rows_at(path: Path):
    connection = sqlite3.connect(path)
    try:
        return _rows(connection)
    finally:
        connection.close()


def _version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def _seed_schema5(path: Path, tmp_path: Path):
    library = Library.create(path.resolve(), library_id=LIBRARY_ID, schema_version=3)
    migrations.migrate_schema3(library, backup_path=(tmp_path / "schema3.sqlite").resolve())
    factory = SQLiteUoWFactory(library)
    with factory.begin(SCOPE, "write") as uow:
        uow.engineering.create(Artifact(SCOPE, "artifact-1", "plan", CREATED_AT))
        actor = ActorRef("author-1", "human", "synthetic-material-migration")
        first = ArtifactRevision(
            SCOPE, "artifact-1", "revision-1", CREATED_AT, actor,
            InlinePayload.from_value("application/json", "urn:test:material", {"n": 1}),
        )
        second = ArtifactRevision(
            SCOPE, "artifact-1", "revision-2", CREATED_AT, actor,
            InlinePayload.from_value("application/json", "urn:test:material", {"n": 2}),
        )
        verify_material(first, uow.engineering.validated_budget())
        first_ref = uow.engineering.append_revision(first, expected_version=0)
        verify_material(second, uow.engineering.validated_budget())
        second_ref = uow.engineering.append_revision(second, expected_version=1)
        child = ArtifactRevision(
            SCOPE, "artifact-1", "revision-3", CREATED_AT, actor,
            InlinePayload.from_value("application/json", "urn:test:material", {"n": 3}),
            (first_ref, second_ref),
        )
        verify_material(child, uow.engineering.validated_budget())
        uow.engineering.append_revision(child, expected_version=2)
        key = CommandKey(SCOPE.realm_id, "principal-1", "request-1")
        command = uow.commands.reserve(
            key, project_id=SCOPE.project_id, operation="engineering.artifacts.create",
            operation_id="operation-1", request_digest=Digest("sha256", "a" * 64),
        )
        uow.commands.complete(key, expected_version=command.entry.version,
                              result_bytes=canonical_bytes({"artifact_id": "artifact-1"}))
        uow.commit()

    # Preserve a legacy current head and opaque method bytes alongside the
    # artifact revision history and materialized command record.
    legacy = library.import_material(kind="method", stable_id="method-old", body={"source": "old"})
    with library.transaction() as connection:
        connection.execute("UPDATE eng_artifacts SET head_revision_id=?, version=3 WHERE artifact_id=?",
                           ("revision-3", "artifact-1"))
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-old", "{\"method\":\"method-old\"}", "{\"registry\":\"r1\"}",
             "{\"input\":\"old\"}", "WAITING", (1 << 53) + 123, "review", CREATED_AT, CREATED_AT),
        )
        connection.execute("INSERT INTO step_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("run-old", 1, "step-old", "operation-old", 1, "WAITING", "{\"receipt\":\"old\"}"))
        connection.execute("INSERT INTO idempotency VALUES (?, ?, ?)",
                           ("operation-old", "digest-old", "{\"receipt\":\"old\"}"))
        blob = b"old opaque method bytes\x00\xff"
        snapshot = b"old snapshot bytes\x00\x80"
        blob_digest = hashlib.sha256(blob).hexdigest()
        snapshot_digest = hashlib.sha256(snapshot).hexdigest()
        connection.execute("INSERT INTO eng_method_blobs VALUES (?, ?, ?)",
                           (blob_digest, len(blob), blob))
        connection.execute("INSERT INTO eng_method_snapshots VALUES (?, ?)", (snapshot_digest, snapshot))
        connection.execute("INSERT INTO eng_method_releases VALUES (?, ?, ?, ?)",
                           ("method-old", "1.0", 1, snapshot_digest))

    # Schema 4->5 is explicit and has its own durable backup and receipt.
    schema4_backup = (tmp_path / "schema4.sqlite").resolve()
    migrations.migrate_schema4(library, backup_path=schema4_backup)

    # A structurally valid historical review graph, with opaque canonical
    # bytes. The migration preserves these records; it does not reinterpret them.
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_review_requirements VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "requirement-1", 1, "req-digest", b"{\"r\":1}"))
        connection.execute("INSERT INTO eng_review_sets VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "set-digest", "requirement-1", 1,
                            b"{\"set\":1}", 7))
        connection.execute("INSERT INTO eng_review_plans VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "set-digest", "plan-digest",
                            b"{\"plan\":1}"))
        connection.execute("INSERT INTO eng_review_requests VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "recorded", 2, 1))
        connection.execute("INSERT INTO eng_reviews VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "set-digest", "review-digest",
                            b"{\"review\":1}"))
        connection.execute("INSERT INTO eng_review_controls VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "active", 0, b"{\"control\":1}"))
        connection.execute("INSERT INTO eng_review_control_events VALUES (?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", 0, b"{\"event\":1}"))

    receipt4 = library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=4").fetchone()
    receipt5 = library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=5").fetchone()
    result_bytes = library._connection.execute(
        "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0]
    child_bytes = library._connection.execute(
        "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-3'").fetchone()[0]
    command_rows = library._connection.execute("SELECT * FROM eng_commands ORDER BY request_id").fetchall()
    assert library._connection.execute(
        "SELECT COUNT(*) FROM eng_revision_parents WHERE revision_id='revision-3'").fetchone() == (2,)
    assert library._connection.execute(
        "SELECT head_revision_id FROM eng_artifacts WHERE artifact_id='artifact-1'").fetchone() == ("revision-3",)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_method_blobs").fetchone() == (1,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
    assert receipt4 is not None and result_bytes and child_bytes and len(command_rows) == 1
    assert legacy is not None
    assert _version(schema4_backup) == 4
    assert receipt5 is not None and receipt5[0] == 5
    assert receipt5[2:] == (hashlib.sha256(schema4_backup.read_bytes()).hexdigest(), str(schema4_backup))
    original_rows = _rows(library._connection)
    assert library._schema_version == 5
    return library, {
        "original_rows": original_rows,
        "receipt4": receipt4,
        "receipt5": receipt5,
        "result_bytes": result_bytes,
        "child_bytes": child_bytes,
        "command_rows": tuple(tuple(row) for row in command_rows),
        "schema4_backup": schema4_backup,
    }


def _prepare(tmp_path: Path):
    path = tmp_path / "library-v5.sqlite"
    library, seed = _seed_schema5(path, tmp_path)
    backup = tmp_path / "library-v5-backup.sqlite"
    assert library._schema_version == 5
    original_rows = _rows(library._connection)
    library.close()
    return path, backup, {**seed, "original_rows": original_rows}


def _assert_old_rows_preserved(library, original_rows):
    rows = _rows(library._connection)
    normalized = dict(rows)
    normalized["library_meta"] = tuple(row[:2] + (5,) + row[3:] for row in rows["library_meta"])
    normalized["eng_schema_migrations"] = tuple(row for row in rows["eng_schema_migrations"] if row[0] != 6)
    assert normalized == original_rows


def _assert_schema6(path: Path, original_rows, receipt):
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert library._schema_version == 6
        assert library._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert library._connection.execute("PRAGMA foreign_key_check").fetchall() == []
        _assert_old_rows_preserved(library, original_rows)
        assert library._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=6").fetchone() == (
                6, receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
        revision_fks = library._connection.execute(
            "PRAGMA foreign_key_list(eng_artifact_revisions)").fetchall()
        assert any(row[2] == "eng_artifacts" for row in revision_fks)
        trigger_names = {row[0] for row in library._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"eng_artifact_revisions_no_update", "eng_artifact_revisions_no_delete"} <= trigger_names
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
            library._connection.execute("UPDATE eng_artifact_revisions SET digest='tampered' WHERE revision_id='revision-1'")
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
            library._connection.execute("DELETE FROM eng_artifact_revisions WHERE revision_id='revision-1'")
    finally:
        library.close()


def test_schema5_to6_preserves_all_history_and_matches_fresh_schema6(tmp_path: Path):
    path, backup, seed = _prepare(tmp_path)
    schema5 = Library.open(path.resolve(), library_id=LIBRARY_ID)
    schema5_signature = _schema_signature(schema5._connection)
    schema5.close()
    fresh5 = Library.create((tmp_path / "fresh-v5.sqlite").resolve(), library_id=LIBRARY_ID,
                            schema_version=5)
    assert _schema_signature(fresh5._connection) == schema5_signature
    fresh5.close()

    fresh6 = Library.create((tmp_path / "fresh-v6.sqlite").resolve(), library_id=LIBRARY_ID,
                            schema_version=6)
    fresh_signature = _schema_signature(fresh6._connection)
    assert fresh6._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert fresh6._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    fresh6.close()

    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    before = migrations._source_digest(library._connection, source_version=5)
    source_connection = library._connection
    receipt = migrations.migrate_schema5(library, backup_path=backup.resolve())
    assert receipt.applied is True and receipt.target_version == 6
    assert receipt.source_digest == before and receipt.backup_path == str(backup.resolve())
    assert library._connection is source_connection
    assert library._schema_version == 6 and _version(path) == 6
    assert _schema_signature(library._connection) == fresh_signature
    _assert_old_rows_preserved(library, seed["original_rows"])
    assert library._connection.execute(
        "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-3'").fetchone()[0] == seed["child_bytes"]
    assert library._connection.execute(
        "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0] == seed["result_bytes"]
    assert tuple(library._connection.execute("SELECT * FROM eng_commands ORDER BY request_id").fetchall()) == seed["command_rows"]
    assert library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=4").fetchone() == seed["receipt4"]
    assert library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=5").fetchone() == seed["receipt5"]
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt.backup_sha256
    backup_library = Library.open(backup.resolve(), library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 5
        assert _rows(backup_library._connection) == seed["original_rows"]
    finally:
        backup_library.close()

    old_source, old_backup = path.read_bytes(), backup.read_bytes()
    repeated = migrations.migrate_schema5(library, backup_path=backup.resolve())
    assert repeated.applied is False
    assert (repeated.source_digest, repeated.backup_sha256, repeated.backup_path) == (
        receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert path.read_bytes() == old_source and backup.read_bytes() == old_backup
    library.close()
    _assert_schema6(path, seed["original_rows"], receipt)


@pytest.mark.parametrize("failure_point", [
    "copy", "drop", "rename", "receipt", "drop-after", "rename-after",
])
def test_precommit_migration_faults_close_authority_and_reopen_schema5(
    tmp_path: Path, monkeypatch, failure_point: str,
):
    path, backup, seed = _prepare(tmp_path)
    base_connection = storage._LibraryConnection

    class FailingMigrationConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            normalized = sql.strip().upper()
            after = failure_point.endswith("-after")
            phase = failure_point.removesuffix("-after")
            targets = {
                "copy": "INSERT INTO ENG_ARTIFACT_REVISIONS_MATERIAL_UPGRADE",
                "drop": "DROP TABLE ENG_ARTIFACT_REVISIONS",
                "rename": "ALTER TABLE ENG_ARTIFACT_REVISIONS_MATERIAL_UPGRADE RENAME TO",
                "receipt": "INSERT INTO ENG_SCHEMA_MIGRATIONS VALUES",
            }
            if normalized.startswith(targets[phase]):
                if after:
                    super().execute(sql, *args, **kwargs)
                raise sqlite3.OperationalError("synthetic schema6 " + failure_point + " failure")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", FailingMigrationConnection)
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    connection = library._connection
    with pytest.raises(sqlite3.OperationalError, match="synthetic schema6 " + failure_point):
        migrations.migrate_schema5(library, backup_path=backup.resolve())
    assert library._closed is True
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert _version(path) == 5
    assert _rows_at(path) == seed["original_rows"]
    assert _version(backup) == 5 and _rows_at(backup) == seed["original_rows"]
    reopened = Library.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 5
        assert _rows(reopened._connection) == seed["original_rows"]
        assert reopened._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    finally:
        reopened.close()


def test_damaged_schema5_foreign_key_fails_closed_and_rolls_back(tmp_path: Path):
    path, backup, _seed = _prepare(tmp_path)
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    library._connection.execute("PRAGMA foreign_keys=OFF")
    deleted = library._connection.execute(
        "DELETE FROM eng_artifacts WHERE artifact_id='artifact-1'").rowcount
    assert deleted == 1
    library._connection.execute("PRAGMA foreign_keys=ON")
    assert library._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    bad_fks = library._connection.execute("PRAGMA foreign_key_check").fetchall()
    assert bad_fks and any(row[0] == "eng_artifact_revisions" for row in bad_fks)
    damaged_rows = _rows(library._connection)
    assert not any(row[0] == 6 for row in damaged_rows["eng_schema_migrations"])
    library.close()

    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    connection = library._connection
    with pytest.raises(EngineeringError) as caught:
        migrations.migrate_schema5(library, backup_path=backup.resolve())
    assert caught.value.code == "migration_foreign_keys_invalid"
    assert library._closed is True
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert _version(path) == 5
    assert _rows_at(path) == damaged_rows
    assert _version(backup) == 5 and _rows_at(backup) == damaged_rows
    reopened = Library.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 5
        assert _rows(reopened._connection) == damaged_rows
        assert not any(row[0] == 6 for row in reopened._connection.execute(
            "SELECT target_version FROM eng_schema_migrations"))
        assert reopened._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert reopened._connection.execute("PRAGMA foreign_key_check").fetchall() == bad_fks
    finally:
        reopened.close()


@pytest.mark.parametrize("failure_point", ["commit-lost", "foreign-key-on"])
def test_postcommit_uncertainty_closes_then_reopen_reconciles_schema6(
    tmp_path: Path, monkeypatch, failure_point: str,
):
    path, backup, seed = _prepare(tmp_path)
    base_connection = storage._LibraryConnection

    class PostCommitUncertainConnection(base_connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.migration_commit_done = False
            self.fail_migration_commit = False

        def commit(self):
            super().commit()
            if self.fail_migration_commit:
                self.fail_migration_commit = False
                self.migration_commit_done = True
                raise sqlite3.OperationalError("synthetic committed reply lost")
            self.migration_commit_done = True

        def execute(self, sql, *args, **kwargs):
            if (failure_point == "foreign-key-on" and self.migration_commit_done
                    and sql.strip().upper() == "PRAGMA FOREIGN_KEYS=ON"):
                raise sqlite3.OperationalError("synthetic foreign key restore failure")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", PostCommitUncertainConnection)
    library = Library.open(path.resolve(), library_id=LIBRARY_ID)
    connection = library._connection
    if failure_point == "commit-lost":
        connection.fail_migration_commit = True
    expected_cause = ("synthetic committed reply lost" if failure_point == "commit-lost"
                      else "synthetic foreign key restore failure")
    with pytest.raises(EngineeringError) as caught:
        migrations.migrate_schema5(library, backup_path=backup.resolve())
    assert caught.value.code == "migration_commit_unknown"
    assert str(caught.value.__cause__) == expected_cause
    assert library._closed is True
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert _version(path) == 6
    reopened = Library.open(path.resolve(), library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 6
        assert reopened._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert reopened._connection.execute("PRAGMA foreign_key_check").fetchall() == []
        _assert_old_rows_preserved(reopened, seed["original_rows"])
        receipt = reopened._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=6").fetchone()
        assert receipt[0] == 6 and receipt[3] == str(backup.resolve())
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt[2]
    finally:
        reopened.close()
