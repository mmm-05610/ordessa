"""Synthetic SQLite acceptance for the explicit schema6->7 Proposal migration."""
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
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_infrastructure.encoding import canonical_bytes


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:proposal-migration"
SCOPE = Scope("realm-proposal-migration", "project-proposal-migration")
CREATED_AT = "2026-10-09T12:00:00.000000Z"
OLD_TABLES = (
    "library_meta", "materials", "heads", "runs", "step_log", "idempotency",
    "eng_method_blobs", "eng_method_snapshots", "eng_method_releases", "eng_schema_migrations",
    "eng_artifacts", "eng_artifact_revisions", "eng_revision_parents", "eng_commands",
    "eng_review_requirements", "eng_review_sets", "eng_review_plans", "eng_review_requests",
    "eng_reviews", "eng_review_controls", "eng_review_control_events",
)


def _rows(connection):
    return {
        table: tuple(sorted(
            (tuple(row) for row in connection.execute("SELECT * FROM " + table)), key=repr,
        ))
        for table in OLD_TABLES
    }


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


def _source_digest_at(path: Path, version: int) -> str:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return migrations._source_digest(connection, source_version=version)
    finally:
        connection.close()


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def _seed_schema6(path: Path, tmp_path: Path):
    library = Library.create(path.resolve(), library_id=LIBRARY_ID, schema_version=3)
    migrations.migrate_schema3(library, backup_path=(tmp_path / "schema3.sqlite").resolve())
    factory = SQLiteUoWFactory(library)
    with factory.begin(SCOPE, "write") as uow:
        uow.engineering.create(Artifact(SCOPE, "artifact-1", "plan", CREATED_AT))
        actor = ActorRef("author-1", "human", "synthetic-proposal-migration")
        revision = ArtifactRevision(
            SCOPE, "artifact-1", "revision-1", CREATED_AT, actor,
            InlinePayload.from_value("application/json", "urn:test:proposal", {"old": 1}),
        )
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=0)
        key = CommandKey(SCOPE.realm_id, "principal-1", "request-1")
        reservation = uow.commands.reserve(
            key, project_id=SCOPE.project_id, operation="engineering.artifacts.create",
            operation_id="operation-1", request_digest=Digest("sha256", "a" * 64),
        )
        uow.commands.complete(
            key, expected_version=reservation.entry.version,
            result_bytes=canonical_bytes({"artifact_id": "artifact-1"}),
        )
        uow.commit()

    # Preserve nonempty legacy methods and opaque content bytes.
    library.import_material(kind="method", stable_id="method-old", body={"source": "old"})
    blob = b"old opaque method bytes\x00\xff"
    snapshot = b"old method snapshot bytes\x00\x80"
    blob_digest = hashlib.sha256(blob).hexdigest()
    snapshot_digest = hashlib.sha256(snapshot).hexdigest()
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_method_blobs VALUES (?, ?, ?)",
                           (blob_digest, len(blob), blob))
        connection.execute("INSERT INTO eng_method_snapshots VALUES (?, ?)",
                           (snapshot_digest, snapshot))
        connection.execute("INSERT INTO eng_method_releases VALUES (?, ?, ?, ?)",
                           ("method-old", "1.0", 1, snapshot_digest))
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-old", '{"method":"method-old"}', '{"registry":"r1"}',
             '{"input":"old"}', "WAITING", (1 << 53) + 123, "review", CREATED_AT, CREATED_AT),
        )
        connection.execute("INSERT INTO step_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                           ("run-old", 1, "step-old", "operation-old", 1, "WAITING", '{"receipt":"old"}'))
        connection.execute("INSERT INTO idempotency VALUES (?, ?, ?)",
                           ("operation-old", "digest-old", '{"receipt":"old"}'))

    backup3 = (tmp_path / "schema3-to4.sqlite").resolve()
    migrations.migrate_schema4(library, backup_path=backup3)
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_review_requirements VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "requirement-1", 1,
                            "req-digest", b'{"requirement":1}'))
        connection.execute("INSERT INTO eng_review_sets VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "set-digest", "requirement-1", 1,
                            b'{"set":1}', 7))
        connection.execute("INSERT INTO eng_review_plans VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "set-digest",
                            "plan-digest", b'{"plan":1}'))
        connection.execute("INSERT INTO eng_review_requests VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "recorded", 2, 1))
        connection.execute("INSERT INTO eng_reviews VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "set-digest",
                            "review-digest", b'{"review":1}'))
        connection.execute("INSERT INTO eng_review_controls VALUES (?, ?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", "active", 0,
                            b'{"control":1}'))
        connection.execute("INSERT INTO eng_review_control_events VALUES (?, ?, ?, ?, ?)",
                           (SCOPE.realm_id, SCOPE.project_id, "review-1", 0, b'{"event":1}'))

    receipt4 = library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=4").fetchone()
    receipt5 = library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=5").fetchone()
    result_bytes = library._connection.execute(
        "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0]
    revision_bytes = library._connection.execute(
        "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-1'").fetchone()[0]
    command_rows = tuple(tuple(row) for row in library._connection.execute(
        "SELECT * FROM eng_commands ORDER BY request_id"))
    method_bytes = library._connection.execute(
        "SELECT body FROM eng_method_blobs WHERE digest=?", (blob_digest,)).fetchone()[0]
    snapshot_bytes = library._connection.execute(
        "SELECT canonical_bytes FROM eng_method_snapshots WHERE snapshot_digest=?", (snapshot_digest,)).fetchone()[0]
    assert receipt4 is not None and receipt5 is not None
    assert result_bytes and revision_bytes and method_bytes == blob and snapshot_bytes == snapshot
    assert len(command_rows) == 1

    backup5 = (tmp_path / "schema5-to6.sqlite").resolve()
    migrations.migrate_schema5(library, backup_path=backup5)
    receipt6 = library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=6").fetchone()
    assert receipt6 is not None and receipt6[0] == 6
    assert _version(backup5) == 5
    original_rows = _rows(library._connection)
    assert library._schema_version == 6
    return library, {
        "original_rows": original_rows,
        "receipt4": tuple(receipt4),
        "receipt5": tuple(receipt5),
        "receipt6": tuple(receipt6),
        "command_rows": command_rows,
        "result_bytes": result_bytes,
        "revision_bytes": revision_bytes,
        "method_bytes": method_bytes,
        "snapshot_bytes": snapshot_bytes,
        "backup3": backup3,
        "backup5": backup5,
    }


def _prepare(tmp_path: Path):
    path = (tmp_path / "library-v6.sqlite").resolve()
    library, seed = _seed_schema6(path, tmp_path)
    original_rows = _rows(library._connection)
    library.close()
    return path, (tmp_path / "library-v6-backup.sqlite").resolve(), {
        **seed, "original_rows": original_rows,
    }


def _assert_old_rows_preserved(library, original_rows):
    rows = _rows(library._connection)
    normalized = dict(rows)
    normalized["library_meta"] = tuple(row[:2] + (6,) + row[3:]
                                       for row in rows["library_meta"])
    normalized["eng_schema_migrations"] = tuple(
        row for row in rows["eng_schema_migrations"] if row[0] != 7)
    assert normalized == original_rows


def test_explicit_schema6_to7_preserves_history_backup_and_matches_fresh_schema7(
    tmp_path: Path,
):
    path, backup, seed = _prepare(tmp_path)

    # Opening an explicit schema6 library remains a read of schema6; no
    # Proposal DDL or implicit upgrade is performed.
    schema6 = Library.open(path, library_id=LIBRARY_ID)
    schema6_signature = _schema_signature(schema6._connection)
    assert schema6._schema_version == 6
    assert "eng_changes" not in {
        row[0] for row in schema6._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    schema6.close()
    fresh6 = Library.create((tmp_path / "fresh-v6.sqlite").resolve(),
                            library_id=LIBRARY_ID, schema_version=6)
    assert _schema_signature(fresh6._connection) == schema6_signature
    fresh6.close()

    fresh7 = Library.create((tmp_path / "fresh-v7.sqlite").resolve(),
                            library_id=LIBRARY_ID, schema_version=7)
    fresh_signature = _schema_signature(fresh7._connection)
    assert fresh7._schema_version == 7
    assert fresh7._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert fresh7._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    fresh7.close()

    library = Library.open(path, library_id=LIBRARY_ID)
    source_connection = library._connection
    before_digest = migrations._source_digest(library._connection, source_version=6)
    receipt = migrations.migrate_schema6(library, backup_path=backup)
    assert receipt.applied is True and receipt.target_version == 7
    assert receipt.source_digest == before_digest
    assert receipt.backup_path == str(backup)
    assert len(receipt.source_digest) == len(receipt.backup_sha256) == 64
    assert library._connection is source_connection
    assert library._schema_version == 7 and _version(path) == 7
    assert _schema_signature(library._connection) == fresh_signature
    assert library._connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert library._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert set(seed["original_rows"]) <= set(_rows(library._connection))
    _assert_old_rows_preserved(library, seed["original_rows"])
    assert library._connection.execute(
        "SELECT * FROM eng_commands ORDER BY request_id").fetchall() == list(seed["command_rows"])
    assert library._connection.execute(
        "SELECT canonical_bytes FROM eng_artifact_revisions WHERE revision_id='revision-1'").fetchone()[0] == seed["revision_bytes"]
    assert library._connection.execute(
        "SELECT result_bytes FROM eng_commands WHERE request_id='request-1'").fetchone()[0] == seed["result_bytes"]
    assert library._connection.execute(
        "SELECT body FROM eng_method_blobs WHERE body=?", (seed["method_bytes"],)).fetchone()[0] == seed["method_bytes"]
    assert library._connection.execute(
        "SELECT canonical_bytes FROM eng_method_snapshots WHERE canonical_bytes=?",
        (seed["snapshot_bytes"],)).fetchone()[0] == seed["snapshot_bytes"]
    for target_version in (4, 5, 6):
        expected = seed[f"receipt{target_version}"]
        assert library._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=?", (target_version,)).fetchone() == expected
    receipt_row = (7, receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert library._connection.execute(
        "SELECT target_version, source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=7").fetchone() == receipt_row
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt.backup_sha256
    assert _source_digest_at(backup, 6) == receipt.source_digest
    backup_library = Library.open(backup, library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 6
        assert _rows(backup_library._connection) == seed["original_rows"]
        assert "eng_changes" not in {
            row[0] for row in backup_library._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        backup_library.close()

    # The new schema's declared revision/proposal FKs and immutable event/data
    # triggers are real SQLite constraints, not a Python-only projection.
    fks = library._connection.execute(
        "PRAGMA foreign_key_list(eng_proposal_mutations)").fetchall()
    assert any(row[2] == "eng_artifact_revisions" for row in fks)
    assert any(row[2] == "eng_proposals" for row in fks)
    library._connection.execute(
        "INSERT INTO eng_changes VALUES (?, ?, ?, ?, ?, ?)",
        (SCOPE.realm_id, SCOPE.project_id, "change-1", CREATED_AT, None, 0))
    proposal_bytes = canonical_bytes({"change_id": "change-1", "proposal_id": "proposal-1"})
    library._connection.execute(
        "INSERT INTO eng_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
        (SCOPE.realm_id, SCOPE.project_id, "proposal-1", "change-1",
         hashlib.sha256(proposal_bytes).hexdigest(), 1, proposal_bytes))
    library._connection.execute(
        "INSERT INTO eng_proposal_mutations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (SCOPE.realm_id, SCOPE.project_id, "proposal-1", 0, "artifact-1",
         "create", None, "revision-1"))
    library._connection.execute(
        "INSERT INTO eng_proposal_controls VALUES (?, ?, ?, ?, ?)",
        (SCOPE.realm_id, SCOPE.project_id, "proposal-1", 0, b'{"control":1}'))
    library._connection.execute(
        "INSERT INTO eng_proposal_control_events VALUES (?, ?, ?, ?, ?)",
        (SCOPE.realm_id, SCOPE.project_id, "proposal-1", 0, b'{"event":1}'))
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        library._connection.execute(
            "UPDATE eng_proposals SET digest='changed' WHERE proposal_id='proposal-1'")
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
        library._connection.execute(
            "DELETE FROM eng_proposal_control_events WHERE proposal_id='proposal-1'")

    source_bytes, backup_bytes = path.read_bytes(), backup.read_bytes()
    repeated = migrations.migrate_schema6(library, backup_path=backup)
    assert repeated.applied is False
    assert (repeated.source_digest, repeated.backup_sha256, repeated.backup_path) == (
        receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert path.read_bytes() == source_bytes and backup.read_bytes() == backup_bytes
    library.close()

    reopened = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 7
        assert reopened._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=7").fetchone() == receipt_row
        assert reopened._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()


def test_conflicting_existing_schema6_backup_is_not_overwritten(tmp_path: Path):
    path, backup, seed = _prepare(tmp_path)
    other = Library.create(backup, library_id=LIBRARY_ID, schema_version=6)
    other_bytes = backup.read_bytes()
    other.close()

    library = Library.open(path, library_id=LIBRARY_ID)
    before = path.read_bytes()
    with pytest.raises(EngineeringError, match="migration_backup_conflict"):
        migrations.migrate_schema6(library, backup_path=backup)
    assert library._closed is False
    assert _version(path) == 6 and _rows_at(path) == seed["original_rows"]
    assert path.read_bytes() == before and backup.read_bytes() == other_bytes
    assert not ({"eng_changes", "eng_proposals"} & _tables(path))
    library.close()


@pytest.mark.parametrize("failure_point", ["ddl-after", "receipt"])
def test_schema7_ddl_or_receipt_failure_rolls_back_and_closes_schema6(
    tmp_path: Path, monkeypatch, failure_point: str,
):
    path, backup, seed = _prepare(tmp_path)
    base_connection = storage._LibraryConnection

    class FailingMigrationConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            normalized = sql.strip().upper()
            if failure_point == "ddl-after" and normalized.startswith(
                    "CREATE TABLE ENG_PROPOSAL_CONTROLS"):
                super().execute(sql, *args, **kwargs)
                raise sqlite3.OperationalError("synthetic schema7 mid-DDL failure")
            if failure_point == "receipt" and normalized.startswith(
                    "INSERT INTO ENG_SCHEMA_MIGRATIONS VALUES"):
                raise sqlite3.OperationalError("synthetic schema7 receipt failure")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", FailingMigrationConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    message = ("synthetic schema7 mid-DDL failure" if failure_point == "ddl-after"
               else "synthetic schema7 receipt failure")
    with pytest.raises(sqlite3.OperationalError, match=message):
        migrations.migrate_schema6(library, backup_path=backup)
    assert library._closed is True
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert _version(path) == 6
    assert _rows_at(path) == seed["original_rows"]
    assert not ({"eng_changes", "eng_proposals", "eng_proposal_controls"} & _tables(path))
    assert backup.exists() and _version(backup) == 6
    assert _rows_at(backup) == seed["original_rows"]
    reopened = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 6
        assert _rows(reopened._connection) == seed["original_rows"]
    finally:
        reopened.close()


def test_commit_succeeded_reply_lost_is_unknown_and_reopen_reconciles_once(
    tmp_path: Path, monkeypatch,
):
    path, backup, seed = _prepare(tmp_path)
    base_connection = storage._LibraryConnection

    class CommitReplyLostConnection(base_connection):
        def commit(self):
            super().commit()
            raise sqlite3.OperationalError("synthetic schema7 COMMIT reply lost")

    monkeypatch.setattr(storage, "_LibraryConnection", CommitReplyLostConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    with pytest.raises(EngineeringError, match="migration_commit_unknown"):
        migrations.migrate_schema6(library, backup_path=backup)
    assert library._closed is True
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert _version(path) == 7
    assert _rows_at(path)["eng_schema_migrations"]

    reopened = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 7
        rows = reopened._connection.execute(
            "SELECT target_version, source_digest, backup_sha256, backup_path "
            "FROM eng_schema_migrations WHERE target_version=7").fetchall()
        assert len(rows) == 1
        target7_receipt = rows[0]
        assert target7_receipt[0] == 7 and target7_receipt[3] == str(backup)
        assert target7_receipt[1] == _source_digest_at(backup, 6)
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == target7_receipt[2]
        assert _version(backup) == 6 and _rows_at(backup) == seed["original_rows"]
        _assert_old_rows_preserved(reopened, seed["original_rows"])

        final_bytes = path.read_bytes()
        receipt = migrations.migrate_schema6(reopened, backup_path=backup)
        assert receipt.applied is False
        assert (receipt.target_version, receipt.source_digest,
                receipt.backup_sha256, receipt.backup_path) == target7_receipt
        assert path.read_bytes() == final_bytes
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM eng_schema_migrations WHERE target_version=7").fetchone() == (1,)
    finally:
        reopened.close()
