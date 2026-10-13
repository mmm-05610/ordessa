"""Explicit schema3->4 migration safety on synthetic libraries only."""
import hashlib
import sqlite3
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.artifacts.library_material_codec import canonical_json, material_ref_to_dict


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:application-migration"
LEGACY_TABLES = ("library_meta", "materials", "heads", "runs", "step_log", "idempotency")
SNAPSHOT_TABLES = (
    "eng_method_blobs", "eng_method_snapshots", "eng_method_releases", "eng_schema_migrations",
)
SOURCE_PRESERVATION_TABLES = LEGACY_TABLES + SNAPSHOT_TABLES[:3]
APPLICATION_TABLES = (
    "eng_artifacts", "eng_artifact_revisions", "eng_revision_parents", "eng_commands",
)


def _create(path: Path, *, schema_version: int = 2) -> Library:
    return Library.create(path, library_id=LIBRARY_ID, schema_version=schema_version)


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


def _all_rows(connection: sqlite3.Connection, tables=LEGACY_TABLES + SNAPSHOT_TABLES):
    return {
        table: tuple(sorted((tuple(row) for row in connection.execute(
            "SELECT * FROM " + table)), key=repr))
        for table in tables
    }


def _add_history_and_snapshot_bytes(library: Library) -> dict:
    material = library.import_material(
        kind="method", stable_id="method:legacy", body={"source": "preserve bytes"})
    with library.transaction() as connection:
        generated = library._create_generated(
            connection, kind="review-judgement", stable_id="review:legacy",
            body={"decision": "pending", "historical": True})
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run:legacy", canonical_json(material_ref_to_dict(material)), canonical_json({"registry": "r1"}),
             canonical_json({"input": "historical"}), "WAITING", 4, "human", "t0", "t1"))
        connection.execute(
            "INSERT INTO step_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run:legacy", 3, "review", "request", 1, "WAITING",
             canonical_json(material_ref_to_dict(generated))))
        connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?)",
            ("operation:legacy", "digest:legacy", canonical_json(material_ref_to_dict(generated))))

    # Schema migration protects the source bytes as stored. These rows model
    # existing immutable snapshot payloads without inventing another publisher.
    blob = b"snapshot-source\x00bytes\xff"
    snapshot = b'{"legacy":"snapshot bytes"}\n'
    blob_digest = hashlib.sha256(blob).hexdigest()
    snapshot_digest = hashlib.sha256(snapshot).hexdigest()
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_method_blobs VALUES (?, ?, ?)",
                           (blob_digest, len(blob), blob))
        connection.execute("INSERT INTO eng_method_snapshots VALUES (?, ?)",
                           (snapshot_digest, snapshot))
        connection.execute("INSERT INTO eng_method_releases VALUES (?, ?, ?, ?)",
                           ("method:stored", "1.0", 1, snapshot_digest))
    return {"blob": blob, "snapshot": snapshot}


def _assert_code(error, expected: str) -> None:
    assert error.value.code == expected


def test_default_schema2_and_opened_schema3_do_not_migrate_implicitly(tmp_path):
    v2_path = tmp_path / "library-v2.sqlite"
    v2 = _create(v2_path)
    assert v2._schema_version == 2
    v2.close()
    v2_bytes = v2_path.read_bytes()
    reopened_v2 = Library.open(v2_path, library_id=LIBRARY_ID)
    try:
        assert reopened_v2._schema_version == 2
        assert _schema_version(v2_path) == 2
        assert not set(SNAPSHOT_TABLES + APPLICATION_TABLES) & _table_names(v2_path)
    finally:
        reopened_v2.close()
    assert v2_path.read_bytes() == v2_bytes

    v3_path = tmp_path / "library-v3.sqlite"
    v3 = _create(v3_path, schema_version=3)
    _add_history_and_snapshot_bytes(v3)
    v3.close()
    v3_bytes = v3_path.read_bytes()
    reopened_v3 = Library.open(v3_path, library_id=LIBRARY_ID)
    try:
        assert reopened_v3._schema_version == 3
        assert _schema_version(v3_path) == 3
        assert not set(APPLICATION_TABLES) & _table_names(v3_path)
        assert reopened_v3._connection.execute(
            "SELECT COUNT(*) FROM eng_schema_migrations WHERE target_version=4").fetchone() == (0,)
    finally:
        reopened_v3.close()
    assert v3_path.read_bytes() == v3_bytes

    v4_path = tmp_path / "library-v4.sqlite"
    v4 = _create(v4_path, schema_version=4)
    try:
        assert v4._schema_version == 4
        assert _schema_version(v4_path) == 4
        assert set(APPLICATION_TABLES) <= _table_names(v4_path)
        assert v4._connection.execute(
            "SELECT COUNT(*) FROM eng_schema_migrations WHERE target_version=4").fetchone() == (0,)
    finally:
        v4.close()


def test_explicit_schema3_to4_preserves_all_rows_and_receipt_and_installs_triggers(tmp_path):
    path = tmp_path / "library-v3.sqlite"
    backup = tmp_path / "library-v3-backup.sqlite"
    library = _create(path, schema_version=3)
    original_snapshot_bytes = _add_history_and_snapshot_bytes(library)
    connection = library._connection
    before_rows = _all_rows(connection)
    old_connection = connection

    receipt = migrations.migrate_schema3(library, backup_path=backup)
    assert receipt.applied is True
    assert receipt.target_version == 4
    assert receipt.backup_path == str(backup)
    assert len(receipt.source_digest) == len(receipt.backup_sha256) == 64
    assert library._connection is old_connection
    assert library._schema_version == 4
    assert not connection.in_transaction
    assert _schema_version(path) == 4
    assert set(LEGACY_TABLES + SNAPSHOT_TABLES + APPLICATION_TABLES) <= _table_names(path)
    after_source_rows = _all_rows(connection, SOURCE_PRESERVATION_TABLES)
    after_source_rows["library_meta"] = tuple(
        row[:2] + (3,) + row[3:] for row in after_source_rows["library_meta"])
    assert after_source_rows == {
        table: before_rows[table] for table in SOURCE_PRESERVATION_TABLES
    }
    assert connection.execute(
        "SELECT source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=4").fetchone() == (
            receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt.backup_sha256
    assert original_snapshot_bytes["blob"] in [row[2] for row in connection.execute(
        "SELECT * FROM eng_method_blobs")]
    assert original_snapshot_bytes["snapshot"] in [row[1] for row in connection.execute(
        "SELECT * FROM eng_method_snapshots")]

    backup_library = Library.open(backup, library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 3
        assert not set(APPLICATION_TABLES) & _table_names(backup)
        assert _all_rows(backup_library._connection) == before_rows
    finally:
        backup_library.close()

    # Exercise the four immutability triggers with a minimal valid relational
    # shape, then verify each stored trigger rejects mutation.
    with library.transaction() as connection:
        connection.execute(
            "INSERT INTO eng_artifacts VALUES (?, ?, ?, ?, ?, NULL, 0)",
            ("realm:r", "project:p", "artifact:a", "kind", "t0"))
        for revision in ("revision:1", "revision:2"):
            connection.execute(
                "INSERT INTO eng_artifact_revisions VALUES (?, ?, ?, ?, ?, 1, ?)",
                ("realm:r", "project:p", revision, "artifact:a", "digest:" + revision,
                 b'{"revision":1}'))
        connection.execute(
            "INSERT INTO eng_revision_parents VALUES (?, ?, ?, ?, ?)",
            ("realm:r", "project:p", "artifact:a", "revision:2", "revision:1"))
    for sql in (
        "UPDATE eng_artifact_revisions SET digest='changed' WHERE revision_id='revision:1'",
        "DELETE FROM eng_artifact_revisions WHERE revision_id='revision:1'",
        "UPDATE eng_revision_parents SET parent_revision_id='revision:2' WHERE revision_id='revision:2'",
        "DELETE FROM eng_revision_parents WHERE revision_id='revision:2'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RECORD"):
            connection.execute(sql)

    migrated_bytes = path.read_bytes()
    backup_bytes = backup.read_bytes()
    repeated = migrations.migrate_schema3(library, backup_path=backup)
    assert repeated.applied is False
    assert (repeated.source_digest, repeated.backup_sha256, repeated.backup_path) == (
        receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert path.read_bytes() == migrated_bytes
    assert backup.read_bytes() == backup_bytes
    library.close()


@pytest.mark.parametrize("backup_kind", ["foreign", "conflict"])
def test_wrong_source_schema_and_existing_backup_are_rejected_without_overwrite(
    tmp_path, backup_kind
):
    source = tmp_path / "library-v2.sqlite"
    backup = tmp_path / "existing-backup.sqlite"
    library = _create(source, schema_version=2)
    source_before = source.read_bytes()
    with pytest.raises(EngineeringError) as caught:
        migrations.migrate_schema3(library, backup_path=backup)
    _assert_code(caught, "migration_source_version_required")
    assert source.read_bytes() == source_before
    assert not backup.exists()
    assert library._schema_version == 2
    library.close()

    source = tmp_path / "library-v3.sqlite"
    library = _create(source, schema_version=3)
    source_before = source.read_bytes()
    existing = Library.create(
        backup, library_id=("synthetic:other-library" if backup_kind == "foreign" else LIBRARY_ID),
        schema_version=3)
    if backup_kind == "conflict":
        existing.import_material(kind="source-fact", stable_id="backup-only",
                                 body={"different": True})
    existing.close()
    backup_before = backup.read_bytes()
    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema3(library, backup_path=backup)
        _assert_code(caught, "library_identity_or_schema_mismatch" if backup_kind == "foreign"
                     else "migration_backup_conflict")
        assert source.read_bytes() == source_before
        assert backup.read_bytes() == backup_before
        assert library._schema_version == 3
        assert _schema_version(source) == 3
    finally:
        library.close()


def test_mid_ddl_failure_rolls_back_to_schema3_and_closes_connection(tmp_path, monkeypatch):
    path = tmp_path / "library-v3.sqlite"
    backup = tmp_path / "backup-v3.sqlite"
    library = _create(path, schema_version=3)
    _add_history_and_snapshot_bytes(library)
    original_rows = _all_rows(library._connection)
    library.close()
    base_connection = storage._LibraryConnection

    class FailingDdlConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            if sql.lstrip().startswith("CREATE TRIGGER eng_revision_parents_no_delete"):
                raise sqlite3.OperationalError("synthetic schema4 DDL interruption")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", FailingDdlConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic schema4 DDL interruption"):
            migrations.migrate_schema3(library, backup_path=backup)
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 3
        assert _all_rows_at(path) == original_rows
        assert not set(APPLICATION_TABLES) & _table_names(path)
        assert backup.exists() and _schema_version(backup) == 3
        assert _all_rows_at(backup) == original_rows
    finally:
        library.close()


def test_commit_lost_reply_closes_and_reopen_finds_durable_receipt_without_retry(
    tmp_path, monkeypatch
):
    path = tmp_path / "library-v3.sqlite"
    backup = tmp_path / "backup-v3.sqlite"
    library = _create(path, schema_version=3)
    _add_history_and_snapshot_bytes(library)
    library.close()
    base_connection = storage._LibraryConnection
    committed_then_raised = []

    class CommitLostReplyConnection(base_connection):
        def commit(self):
            result = super().commit()
            committed_then_raised.append(self)
            raise sqlite3.OperationalError("synthetic schema4 COMMIT reply lost")

    monkeypatch.setattr(storage, "_LibraryConnection", CommitLostReplyConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic schema4 COMMIT reply lost"):
            migrations.migrate_schema3(library, backup_path=backup)
        assert committed_then_raised == [connection]
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 4

        reopened = Library.open(path, library_id=LIBRARY_ID)
        try:
            assert reopened._schema_version == 4
            row = reopened._connection.execute(
                "SELECT source_digest, backup_sha256, backup_path "
                "FROM eng_schema_migrations WHERE target_version=4").fetchone()
            assert row is not None
            assert len(row[0]) == len(row[1]) == 64
            assert row[2] == str(backup)
            assert row[1] == hashlib.sha256(backup.read_bytes()).hexdigest()
            receipt = migrations.migrate_schema3(reopened, backup_path=backup)
            assert receipt.applied is False
            assert receipt.source_digest == row[0]
            assert receipt.backup_sha256 == row[1]
            assert receipt.backup_path == row[2]
            assert committed_then_raised == [connection]
        finally:
            reopened.close()
    finally:
        library.close()


def _all_rows_at(path: Path):
    connection = sqlite3.connect(path)
    try:
        return _all_rows(connection)
    finally:
        connection.close()


@pytest.mark.parametrize("tamper", [False, True])
def test_schema4_preserves_real_prior_migration_receipt_or_rejects_tampering(tmp_path, tamper):
    path = tmp_path / "library.sqlite"
    library = _create(path)
    receipt3 = migrations.migrate_schema2(library, backup_path=tmp_path / "backup2.sqlite")
    prior = library._connection.execute("SELECT * FROM eng_schema_migrations").fetchall()
    connection = library._connection

    class TamperPriorReceipt:
        def execute(self, sql, parameters=()):
            if sql.startswith("UPDATE library_meta SET schema_version"):
                connection.execute("UPDATE eng_schema_migrations SET source_digest=? WHERE target_version=3",
                                   ("f" * 64,))
            return connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(connection, name)

    if tamper:
        library._connection = TamperPriorReceipt()
        with pytest.raises(EngineeringError) as error:
            migrations.migrate_schema3(library, backup_path=tmp_path / "backup3.sqlite")
        assert error.value.code == "migration_legacy_data_changed"
        assert library._schema_version == 3
        assert not set(APPLICATION_TABLES) & _table_names(path)
        assert library._closed
        library = Library.open(path, library_id=LIBRARY_ID)
        connection = library._connection
    else:
        receipt4 = migrations.migrate_schema3(library, backup_path=tmp_path / "backup3.sqlite")
        assert receipt4.applied and receipt4.target_version == 4
        assert migrations.migrate_schema2(library, backup_path=tmp_path / "backup2.sqlite").source_digest == receipt3.source_digest
    assert connection.execute("SELECT * FROM eng_schema_migrations WHERE target_version=3").fetchall() == prior
    library.close()
