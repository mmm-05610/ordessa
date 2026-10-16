"""Real BEGIN/COMMIT fault boundaries, exclusively on synthetic databases."""
import sqlite3

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema2
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.methods.definitions.errors import MethodFailure
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError


@pytest.mark.parametrize("phase", ["read", "write"])
def test_migration_real_begin_then_non_sqlite_failure_leaves_no_transaction(tmp_path, monkeypatch, phase):
    path = tmp_path / "source.sqlite"
    original = storage.EngineeringLibrary.create(path, library_id="begin.library")
    original.close()
    base = storage._LibraryConnection
    fault = RuntimeError("synthetic lost BEGIN reply")

    class Connection(base):
        armed = False

        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if self.armed and sql == ("BEGIN" if phase == "read" else "BEGIN IMMEDIATE"):
                raise fault
            return result

    monkeypatch.setattr(storage, "_LibraryConnection", Connection)
    library = storage.EngineeringLibrary.open(path, library_id="begin.library")
    connection = library._connection
    connection.armed = True
    with pytest.raises(RuntimeError) as caught:
        migrate_schema2(library, backup_path=tmp_path / "backup.sqlite")
    assert caught.value is fault
    if phase == "read":
        assert not connection.in_transaction
        connection.armed = False
        assert library._schema_version == 2
        library.close()
    else:
        assert library._closed
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    reopened = storage.EngineeringLibrary.open(path, library_id="begin.library")
    assert reopened._schema_version == 2
    reopened.close()


@pytest.mark.parametrize("fail_on", [1, 2], ids=["file-sync", "directory-sync"])
def test_backup_sync_failure_never_changes_source_schema(tmp_path, monkeypatch, fail_on):
    path = tmp_path / "source.sqlite"
    library = storage.EngineeringLibrary.create(path, library_id="sync.library")
    before = path.read_bytes()
    fault = OSError("synthetic backup directory sync failure")
    original_fsync = migrations.os.fsync
    calls = []
    statements = []
    library._connection.set_trace_callback(statements.append)

    def fail_sync(fd):
        calls.append(fd)
        if len(calls) == fail_on:
            raise fault
        return original_fsync(fd)

    monkeypatch.setattr(migrations.os, "fsync", fail_sync)
    with pytest.raises(OSError) as caught:
        migrate_schema2(library, backup_path=tmp_path / "backup.sqlite")
    assert caught.value is fault
    assert len(calls) == fail_on
    assert "BEGIN IMMEDIATE" not in statements
    assert not library._connection.in_transaction
    assert library._schema_version == 2
    assert path.read_bytes() == before
    assert library._connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'eng_%'").fetchall() == []
    library.close()


def test_backup_changed_before_write_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    library = storage.EngineeringLibrary.create(path, library_id="backup-race.library")
    original = path.read_bytes()
    backup = tmp_path / "backup.sqlite"
    original_sync = migrations._sync_backup

    def sync_then_change(selected):
        original_sync(selected)
        other = storage.EngineeringLibrary.open(backup, library_id="backup-race.library")
        other.import_material(kind="source-fact", stable_id="fact:injected", body={"synthetic": True})
        other.close()

    monkeypatch.setattr(migrations, "_sync_backup", sync_then_change)
    with pytest.raises(EngineeringError) as caught:
        migrate_schema2(library, backup_path=backup)
    assert caught.value.code == "migration_backup_changed"
    assert library._closed
    assert path.read_bytes() == original
    reopened = storage.EngineeringLibrary.open(path, library_id="backup-race.library")
    assert reopened._schema_version == 2
    assert reopened.head("source-fact", "fact:injected") is None
    reopened.close()


def test_backup_writer_cannot_commit_after_receipt_revalidation(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    original = storage.EngineeringLibrary.create(path, library_id="backup-lock.library")
    original.close()
    backup = tmp_path / "backup.sqlite"
    base = storage._LibraryConnection
    attempts = []

    class Connection(base):
        armed = False

        def execute(self, sql, *args, **kwargs):
            if self.armed and sql == "BEGIN IMMEDIATE":
                other = sqlite3.connect(backup, timeout=0.01)
                try:
                    other.execute("UPDATE library_meta SET library_id='synthetic-change'")
                    with pytest.raises(sqlite3.OperationalError, match="locked"):
                        other.commit()
                    attempts.append("commit-refused-by-read-lock")
                finally:
                    other.rollback()
                    other.close()
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(storage, "_LibraryConnection", Connection)
    library = storage.EngineeringLibrary.open(path, library_id="backup-lock.library")
    library._connection.armed = True
    receipt = migrate_schema2(library, backup_path=backup)
    assert receipt.applied
    assert attempts == ["commit-refused-by-read-lock"]
    library.close()
    recovered = storage.EngineeringLibrary.open(backup, library_id="backup-lock.library")
    assert recovered._schema_version == 2
    recovered.close()


def test_store_real_read_begin_then_runtime_failure_is_closed_finite(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    original = storage.EngineeringLibrary.create(path, library_id="begin.library", schema_version=3)
    original.close()
    base = storage._LibraryConnection

    class Connection(base):
        armed = False

        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if self.armed and sql == "BEGIN":
                raise RuntimeError("synthetic lost BEGIN reply")
            return result

    monkeypatch.setattr(storage, "_LibraryConnection", Connection)
    library = storage.EngineeringLibrary.open(path, library_id="begin.library")
    store = SQLiteSnapshotStore(library)
    library._connection.armed = True
    with pytest.raises(MethodFailure) as caught:
        store.get_digest("test.method", "1.0.0")
    assert caught.value.error.code == "SNAPSHOT_STORAGE_UNAVAILABLE"
    assert library._closed
    reopened = storage.EngineeringLibrary.open(path, library_id="begin.library")
    assert SQLiteSnapshotStore(reopened).get_digest("test.method", "1.0.0") is None
    reopened.close()


def test_library_real_commit_then_runtime_failure_is_unknown_not_reusable(tmp_path, monkeypatch):
    path = tmp_path / "source.sqlite"
    original = storage.EngineeringLibrary.create(path, library_id="commit.library")
    original.close()
    base = storage._LibraryConnection
    fault = RuntimeError("synthetic lost COMMIT reply")

    class Connection(base):
        def commit(self):
            super().commit()
            raise fault

    monkeypatch.setattr(storage, "_LibraryConnection", Connection)
    library = storage.EngineeringLibrary.open(path, library_id="commit.library")
    with pytest.raises(EngineeringError) as caught:
        library.import_material(kind="source-fact", stable_id="fact:1", body={"synthetic": True})
    assert caught.value.code == "library_commit_unknown"
    assert caught.value.__cause__ is fault
    assert library._closed
    reopened = storage.EngineeringLibrary.open(path, library_id="commit.library")
    assert reopened.head("source-fact", "fact:1") is not None
    reopened.close()
