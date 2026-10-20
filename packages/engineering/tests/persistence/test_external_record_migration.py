"""Acceptance for the explicit schema15->16 source-only Proposal upgrade."""
import sqlite3

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema15


def test_schema16_preserves_v1_bytes_and_allows_v2_with_immutable_rows(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    backup = (tmp_path / "schema15.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="synthetic:external-record", schema_version=15)
    old_bytes = b'{"historical":"proposal bytes stay opaque"}'
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_changes (realm_id,project_id,change_id,created_at,selected_proposal_id,version) VALUES (?, ?, ?, ?, ?, ?)",
            ("realm", "project", "change", "2026-10-14T00:00:00Z", None, 0))
        connection.execute("INSERT INTO eng_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("realm", "project", "old", "change", "old-digest", 1, old_bytes))
    old_identity = tuple(library._connection.execute(
        "SELECT realm_id,project_id,proposal_id,change_id,digest,schema_version,canonical_bytes "
        "FROM eng_proposals WHERE proposal_id='old'").fetchone())

    receipt = migrate_schema15(library, backup_path=backup)
    assert receipt.applied and receipt.target_version == 16
    assert library.schema_version == 16
    assert tuple(library._connection.execute(
        "SELECT realm_id,project_id,proposal_id,change_id,digest,schema_version,canonical_bytes "
        "FROM eng_proposals WHERE proposal_id='old'").fetchone()) == old_identity
    assert old_identity[-1] == old_bytes
    library._connection.execute("INSERT INTO eng_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("realm", "project", "new", "change", "new-digest", 2, b'{"source_change":{}}'))
    assert library._connection.execute(
        "SELECT schema_version FROM eng_proposals WHERE proposal_id='new'").fetchone() == (2,)
    with pytest.raises(sqlite3.IntegrityError):
        library._connection.execute("UPDATE eng_proposals SET digest='changed' WHERE proposal_id='old'")
    with pytest.raises(sqlite3.IntegrityError):
        library._connection.execute("DELETE FROM eng_proposals WHERE proposal_id='old'")
    assert library._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    library.close()

    reopened = EngineeringLibrary.open(path, library_id="synthetic:external-record")
    try:
        assert reopened.schema_version == 16
        assert tuple(reopened._connection.execute(
            "SELECT realm_id,project_id,proposal_id,change_id,digest,schema_version,canonical_bytes "
            "FROM eng_proposals WHERE proposal_id='old'").fetchone()) == old_identity
        assert reopened._connection.execute("SELECT schema_version FROM eng_proposals WHERE proposal_id='new'").fetchone() == (2,)
    finally:
        reopened.close()


def test_schema16_migration_ddl_failure_rolls_back_original_schema_and_rows(tmp_path, monkeypatch):
    path = (tmp_path / "engineering-rollback.sqlite").resolve()
    backup = (tmp_path / "rollback-backup.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="synthetic:external-record-rollback", schema_version=15)
    raw = b'{"historical":"unchanged on failed migration"}'
    with library.transaction() as connection:
        connection.execute("INSERT INTO eng_changes (realm_id,project_id,change_id,created_at,selected_proposal_id,version) VALUES (?, ?, ?, ?, ?, ?)",
            ("realm", "project", "change", "2026-10-14T00:00:00Z", None, 0))
        connection.execute("INSERT INTO eng_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("realm", "project", "old", "change", "old-digest", 1, raw))
    original_change = tuple(library._connection.execute("SELECT * FROM eng_changes").fetchone())
    original_proposal = tuple(library._connection.execute("SELECT * FROM eng_proposals").fetchone())
    library.close()
    library = EngineeringLibrary.open(path, library_id="synthetic:external-record-rollback")
    monkeypatch.setattr(migrations, "EXTERNAL_RECORD_DDL",
        migrations.EXTERNAL_RECORD_DDL + "\nCREATE TABLE eng_changes (injected INTEGER);\n")
    with pytest.raises(sqlite3.OperationalError):
        migrate_schema15(library, backup_path=backup)
    library.close()
    reopened = EngineeringLibrary.open(path, library_id="synthetic:external-record-rollback")
    try:
        assert reopened.schema_version == 15
        assert tuple(reopened._connection.execute("SELECT * FROM eng_changes").fetchone()) == original_change
        assert tuple(reopened._connection.execute("SELECT * FROM eng_proposals").fetchone()) == original_proposal
        assert reopened._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='eng_proposals_v16'").fetchone() is None
        assert reopened._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()
