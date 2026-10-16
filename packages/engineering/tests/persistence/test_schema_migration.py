"""Explicit schema2-to-3 migration safety on synthetic libraries only."""
import hashlib
import sqlite3
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.artifacts.library_material_codec import canonical_json, material_ref_to_dict


Library = storage.EngineeringLibrary
LIBRARY_ID = "synthetic:migration"
LEGACY_TABLES = ("library_meta", "materials", "heads", "runs", "step_log", "idempotency")


def _create(path: Path, *, schema_version: int = 2) -> Library:
    return Library.create(path, library_id=LIBRARY_ID, schema_version=schema_version)


def _legacy_rows(connection: sqlite3.Connection, *, normalize_version: bool = False):
    result = {}
    for table in LEGACY_TABLES:
        rows = [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
        if normalize_version and table == "library_meta":
            rows = [row[:2] + (2,) + row[3:] for row in rows]
        result[table] = tuple(sorted(rows, key=repr))
    return result


def _add_legacy_history(library: Library) -> None:
    method = library.import_material(
        kind="method", stable_id="method:legacy", body={"source": "preserve me"})
    with library.transaction() as connection:
        generated = library._create_generated(
            connection, kind="review-judgement", stable_id="review:legacy",
            body={"decision": "pending", "historical": True})
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run:legacy", canonical_json(material_ref_to_dict(method)), canonical_json({"registry": "r1"}),
             canonical_json({"input": "historical"}), "WAITING", 4, "human", "t0", "t1"))
        connection.execute(
            "INSERT INTO step_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run:legacy", 3, "review", "request", 1, "WAITING",
             canonical_json(material_ref_to_dict(generated))))
        connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?)",
            ("operation:legacy", "digest:legacy", canonical_json(material_ref_to_dict(generated))))


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


def _legacy_rows_at(path: Path):
    connection = sqlite3.connect(path)
    try:
        return _legacy_rows(connection)
    finally:
        connection.close()


def _assert_code(error, expected: str) -> None:
    assert error.value.code == expected


def test_default_schema2_open_does_not_migrate_implicitly(tmp_path):
    path = tmp_path / "library.sqlite"
    library = _create(path)
    assert library._schema_version == 2
    library.close()
    before = path.read_bytes()

    reopened = Library.open(path, library_id=LIBRARY_ID)
    try:
        assert reopened._schema_version == 2
        assert _schema_version(path) == 2
        assert "eng_schema_migrations" not in _table_names(path)
    finally:
        reopened.close()
    assert path.read_bytes() == before


def test_snapshot_store_rejects_schema2_without_migrating_or_changing_bytes(tmp_path):
    path = tmp_path / "library.sqlite"
    library = _create(path)
    library.close()
    before = path.read_bytes()
    reopened = Library.open(path, library_id=LIBRARY_ID)
    try:
        with pytest.raises(MethodFailure) as caught:
            SQLiteSnapshotStore(reopened)
        assert caught.value.error.code == "SNAPSHOT_SCHEMA_REQUIRED"
        assert reopened._schema_version == 2
        assert _schema_version(path) == 2
        assert "eng_schema_migrations" not in _table_names(path)
    finally:
        reopened.close()
    assert path.read_bytes() == before


def test_explicit_schema3_creation_is_separate_from_migration_receipt(tmp_path):
    path = tmp_path / "library-v3.sqlite"
    library = _create(path, schema_version=3)
    try:
        assert library._schema_version == 3
        assert _schema_version(path) == 3
        assert "eng_schema_migrations" in _table_names(path)
        assert library._connection.execute(
            "SELECT COUNT(*) FROM eng_schema_migrations").fetchone() == (0,)
    finally:
        library.close()


def test_explicit_migration_preserves_legacy_rows_and_reuses_same_connection(tmp_path):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "library-v2-backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    original_connection = library._connection
    original_rows = _legacy_rows(original_connection)
    original_digest = migrations._source_digest(original_connection)

    receipt = migrations.migrate_schema2(library, backup_path=backup)
    assert receipt.applied is True
    assert receipt.target_version == 3
    assert receipt.source_digest == original_digest
    assert len(receipt.source_digest) == 64
    assert len(receipt.backup_sha256) == 64
    assert receipt.backup_path == str(backup)
    assert library._connection is original_connection
    assert library._schema_version == 3
    assert original_connection.in_transaction is False
    assert _schema_version(path) == 3
    assert _legacy_rows(original_connection, normalize_version=True) == original_rows
    assert original_connection.execute(
        "SELECT source_digest, backup_sha256, backup_path "
        "FROM eng_schema_migrations WHERE target_version=3").fetchone() == (
            receipt.source_digest, receipt.backup_sha256, receipt.backup_path)

    backup_bytes = backup.read_bytes()
    assert hashlib.sha256(backup_bytes).hexdigest() == receipt.backup_sha256
    backup_library = Library.open(backup, library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 2
        assert _legacy_rows(backup_library._connection) == original_rows
        assert "eng_schema_migrations" not in _table_names(backup)
    finally:
        backup_library.close()

    migrated_bytes = path.read_bytes()
    repeated = migrations.migrate_schema2(library, backup_path=backup)
    assert repeated.applied is False
    assert (repeated.source_digest, repeated.backup_sha256, repeated.backup_path) == (
        receipt.source_digest, receipt.backup_sha256, receipt.backup_path)
    assert path.read_bytes() == migrated_bytes
    assert backup.read_bytes() == backup_bytes
    library.close()


def test_migration_rejects_source_inode_as_dotdot_backup_alias(tmp_path):
    path = tmp_path / "library.sqlite"
    child = tmp_path / "child"
    child.mkdir()
    alias = child / ".." / path.name
    library = _create(path)
    _add_legacy_history(library)
    before = path.read_bytes()
    rows = _legacy_rows(library._connection)

    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=alias)
        _assert_code(caught, "migration_backup_path_invalid")
        assert path.read_bytes() == before
        assert _legacy_rows(library._connection) == rows
        assert _schema_version(path) == 2
        assert alias.stat().st_ino == path.stat().st_ino
    finally:
        library.close()


@pytest.mark.parametrize("backup_kind", ["foreign", "conflict"])
def test_existing_foreign_or_conflicting_backup_is_preserved(tmp_path, backup_kind):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "existing-backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    source_bytes = path.read_bytes()

    other = Library.create(backup, library_id=("another:library" if backup_kind == "foreign"
                                                else LIBRARY_ID))
    if backup_kind == "conflict":
        other.import_material(kind="source-fact", stable_id="backup-only",
                              body={"different": True})
    other.close()
    backup_bytes = backup.read_bytes()

    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=backup)
        _assert_code(caught, "library_identity_or_schema_mismatch" if backup_kind == "foreign"
                     else "migration_backup_conflict")
        assert path.read_bytes() == source_bytes
        assert backup.read_bytes() == backup_bytes
        assert library._schema_version == 2
        assert _schema_version(path) == 2
    finally:
        library.close()


def test_existing_symlink_backup_is_refused_without_touching_target(tmp_path):
    path = tmp_path / "library.sqlite"
    real_backup = tmp_path / "real-backup.sqlite"
    backup = tmp_path / "backup-link.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    source_bytes = path.read_bytes()
    other = Library.create(real_backup, library_id=LIBRARY_ID)
    other.close()
    backup.symlink_to(real_backup)
    target_bytes = real_backup.read_bytes()

    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=backup)
        _assert_code(caught, "library_path_unsafe")
        assert path.read_bytes() == source_bytes
        assert real_backup.read_bytes() == target_bytes
        assert backup.is_symlink()
        assert backup.resolve() == real_backup
        assert _schema_version(path) == 2
    finally:
        library.close()


def test_backup_publication_collision_never_overwrites_new_file(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    source_bytes = path.read_bytes()
    sentinel = b"concurrent backup owner"
    original_link = migrations.os.link

    def collide(staged, destination, **kwargs):
        Path(destination).write_bytes(sentinel)
        return original_link(staged, destination, **kwargs)

    monkeypatch.setattr(migrations.os, "link", collide)
    try:
        with pytest.raises(FileExistsError):
            migrations.migrate_schema2(library, backup_path=backup)
        assert backup.read_bytes() == sentinel
        assert path.read_bytes() == source_bytes
        assert library._schema_version == 2
        assert _schema_version(path) == 2
    finally:
        library.close()


def test_future_schema_is_rejected_without_changing_database_bytes(tmp_path):
    path = tmp_path / "future.sqlite"
    library = _create(path)
    library.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE library_meta SET schema_version=99")
        connection.execute("PRAGMA user_version=99")
        connection.commit()
    finally:
        connection.close()
    before = path.read_bytes()

    with pytest.raises(EngineeringError) as caught:
        Library.open(path, library_id=LIBRARY_ID)
    _assert_code(caught, "library_identity_or_schema_mismatch")
    assert path.read_bytes() == before
    assert _schema_version(path) == 99


def test_mid_ddl_failure_rolls_back_to_schema2_and_closes_connection(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    original_rows = _legacy_rows(library._connection)
    library.close()
    base_connection = storage._LibraryConnection

    class FailingDdlConnection(base_connection):
        def execute(self, sql, *args, **kwargs):
            if sql.lstrip().startswith("CREATE TABLE eng_method_releases"):
                raise sqlite3.OperationalError("synthetic DDL interruption")
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", FailingDdlConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic DDL interruption"):
            migrations.migrate_schema2(library, backup_path=backup)
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 2
        assert _legacy_rows_at(path) == original_rows
        names = _table_names(path)
        assert not {"eng_method_blobs", "eng_method_snapshots", "eng_method_releases",
                    "eng_schema_migrations"}.intersection(names)
        assert backup.exists()  # the complete explicit backup survives the failed migration
        assert _schema_version(backup) == 2
    finally:
        library.close()


def test_backup_failure_with_rollback_failure_closes_and_preserves_primary_cause(
    tmp_path, monkeypatch
):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    library.close()
    before = path.read_bytes()
    base_connection = storage._LibraryConnection
    primary = sqlite3.OperationalError("synthetic backup failure")
    rollback_error = sqlite3.OperationalError("synthetic rollback failure")

    class BackupAndRollbackFailure(base_connection):
        fail_rollback = False

        def backup(self, *args, **kwargs):
            raise primary

        def rollback(self):
            if self.fail_rollback:
                raise rollback_error
            return super().rollback()

    monkeypatch.setattr(storage, "_LibraryConnection", BackupAndRollbackFailure)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    connection.fail_rollback = True
    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=backup)
        _assert_code(caught, "library_rollback_failed")
        assert caught.value.__cause__ is primary
        assert caught.value.rollback_error is rollback_error
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert path.read_bytes() == before
        assert _schema_version(path) == 2
        assert not backup.exists()
    finally:
        library.close()


def test_migration_succeeds_with_small_cache_spill_and_multipage_legacy_data(tmp_path):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    payload = "0123456789abcdef" * 512
    library._connection.execute("PRAGMA cache_size=1")
    library._connection.execute("PRAGMA cache_spill=ON")
    with library.transaction() as connection:
        for index in range(320):
            library._write_material(
                connection, kind="source-fact", stable_id=f"fact:{index:04d}",
                revision=1, body={"payload": payload}, generated=False)
    assert library._connection.execute("PRAGMA cache_size").fetchone()[0] == 1
    assert library._connection.execute("PRAGMA cache_spill").fetchone()[0] == 1
    assert library._connection.execute("PRAGMA page_count").fetchone()[0] > 256
    expected = _legacy_rows(library._connection)

    receipt = migrations.migrate_schema2(library, backup_path=backup)
    assert receipt.applied is True
    assert library._schema_version == 3
    assert _legacy_rows(library._connection, normalize_version=True) == expected
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == receipt.backup_sha256
    backup_library = Library.open(backup, library_id=LIBRARY_ID)
    try:
        assert backup_library._schema_version == 2
        assert backup_library._connection.execute(
            "SELECT COUNT(*) FROM materials WHERE kind='source-fact'").fetchone() == (320,)
    finally:
        backup_library.close()
        library.close()


def test_postcommit_bound_check_failure_closes_but_keeps_schema3_receipt(tmp_path):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    library.close()
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    original_check = library._check_bound_state
    injected = []

    def fail_after_commit(*, allow_journal=False):
        if library._schema_version == 3:
            injected.append(True)
            raise EngineeringError("synthetic_postcommit_boundcheck")
        return original_check(allow_journal=allow_journal)

    library._check_bound_state = fail_after_commit
    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=backup)
        _assert_code(caught, "synthetic_postcommit_boundcheck")
        assert injected == [True]
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 3
        reopened = Library.open(path, library_id=LIBRARY_ID)
        try:
            receipt = reopened._connection.execute(
                "SELECT source_digest, backup_sha256, backup_path "
                "FROM eng_schema_migrations WHERE target_version=3").fetchone()
            assert receipt is not None
            assert receipt[2] == str(backup)
            assert receipt[1] == hashlib.sha256(backup.read_bytes()).hexdigest()
            assert len(receipt[0]) == 64
            assert reopened._connection.execute(
                "SELECT COUNT(*) FROM runs WHERE run_id='run:legacy'").fetchone() == (1,)
        finally:
            reopened.close()
    finally:
        library.close()


def test_commit_lost_reply_closes_connection_and_receipt_is_durable(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    library.close()
    base_connection = storage._LibraryConnection
    committed_then_raised = []

    class CommitLostReplyConnection(base_connection):
        def commit(self):
            result = super().commit()
            committed_then_raised.append(self)
            raise sqlite3.OperationalError("synthetic COMMIT reply lost")

    monkeypatch.setattr(storage, "_LibraryConnection", CommitLostReplyConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    connection = library._connection
    try:
        with pytest.raises(sqlite3.OperationalError, match="synthetic COMMIT reply lost"):
            migrations.migrate_schema2(library, backup_path=backup)
        assert committed_then_raised == [connection]
        assert library._closed is True
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        assert _schema_version(path) == 3
        reopened = Library.open(path, library_id=LIBRARY_ID)
        try:
            assert reopened._schema_version == 3
            row = reopened._connection.execute(
                "SELECT source_digest, backup_sha256, backup_path "
                "FROM eng_schema_migrations WHERE target_version=3").fetchone()
            assert row is not None
            assert row[2] == str(backup)
            assert row[1] == hashlib.sha256(backup.read_bytes()).hexdigest()
            assert len(row[0]) == 64
        finally:
            reopened.close()
    finally:
        library.close()


def test_concurrent_writer_after_backup_is_detected_before_ddl(tmp_path, monkeypatch):
    path = tmp_path / "library.sqlite"
    backup = tmp_path / "backup.sqlite"
    library = _create(path)
    _add_legacy_history(library)
    old_body = library._connection.execute(
        "SELECT body_json FROM materials WHERE stable_id='method:legacy'").fetchone()[0]
    library.close()
    writer = sqlite3.connect(path, isolation_level=None)
    base_connection = storage._LibraryConnection
    writer_changes = []

    class InterleavingConnection(base_connection):
        injected = False

        def execute(self, sql, *args, **kwargs):
            if sql == "BEGIN IMMEDIATE" and not type(self).injected:
                type(self).injected = True
                writer.execute(
                    "UPDATE materials SET body_json=? WHERE stable_id='method:legacy'",
                    ('{"source":"concurrent writer"}',))
                writer_changes.append(True)
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", InterleavingConnection)
    library = Library.open(path, library_id=LIBRARY_ID)
    try:
        with pytest.raises(EngineeringError) as caught:
            migrations.migrate_schema2(library, backup_path=backup)
        _assert_code(caught, "migration_source_changed")
        assert writer_changes == [True]
        assert library._closed is True
        assert _schema_version(path) == 2
        assert "eng_schema_migrations" not in _table_names(path)
        assert backup.exists() and _schema_version(backup) == 2
        raw = sqlite3.connect(path)
        try:
            assert raw.execute(
                "SELECT body_json FROM materials WHERE stable_id='method:legacy'").fetchone()[0] == (
                    '{"source":"concurrent writer"}')
        finally:
            raw.close()
        backup_library = Library.open(backup, library_id=LIBRARY_ID)
        try:
            assert backup_library._connection.execute(
                "SELECT body_json FROM materials WHERE stable_id='method:legacy'").fetchone()[0] == old_body
        finally:
            backup_library.close()
    finally:
        writer.close()
        library.close()
