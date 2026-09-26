"""Order 66 stage C: the shared-store credential guard, typed and read-only.

The guard stands between a Session and a Profile switch inside one family: it
must refuse a shared library that still holds credential rows, and it must see
what the family's own next open would see - including committed rows that live
only in the SQLite WAL. The WAL test pins the rule that motivates all of it:
``immutable=1`` reads the main file alone and reports the WAL-resident row as
absent, while the guard, opening ``mode=ro``, refuses on that same row.
"""
from __future__ import annotations

import sqlite3

import pytest

from ordessa_server_compat.execution.session_store_guard import (
    CREDENTIAL_TABLES,
    SessionStoreGuardError,
    guard_shared_store,
)


def _create_tables(path, names=CREDENTIAL_TABLES) -> None:
    """A normal, writable connection lays down the empty credential tables."""
    connection = sqlite3.connect(path)
    try:
        for name in names:
            connection.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
        connection.commit()
    finally:
        connection.close()


def test_absent_store_is_fresh(tmp_path):
    assert guard_shared_store(tmp_path / "state.db") == {"state": "fresh", "rows": {}}


def test_empty_credential_tables_are_accepted(tmp_path):
    path = tmp_path / "state.db"
    _create_tables(path)

    assert guard_shared_store(path) == {
        "state": "empty",
        "rows": {name: 0 for name in CREDENTIAL_TABLES},
    }


def test_credential_row_is_refused(tmp_path):
    path = tmp_path / "state.db"
    _create_tables(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("INSERT INTO credential (id) VALUES (1)")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SessionStoreGuardError) as refusal:
        guard_shared_store(path)
    assert refusal.value.code == "SESSION_STORE_CREDENTIALS_PRESENT"
    assert refusal.value.table == "credential"


def test_wal_resident_row_is_refused_though_immutable_misses_it(tmp_path):
    path = tmp_path / "state.db"
    # The schema is checkpointed into the main file first, so what the
    # main-file-only reader below sees is a real (but empty) table.
    _create_tables(path)

    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO credential (id) VALUES (1)")
    writer.commit()
    # The writer closes without checkpointing: a live peer read transaction
    # keeps the closing connection from checkpointing the WAL away, so the
    # committed row stays in the -wal sidecar - exactly the state the
    # family's own store is in while it is live.
    peer = sqlite3.connect(path)
    peer.execute("BEGIN")
    assert peer.execute("SELECT COUNT(*) FROM credential").fetchone() == (1,)
    writer.close()
    wal = path.with_name(path.name + "-wal")
    assert wal.exists() and wal.stat().st_size > 0

    # (a) The negative control that motivates mode=ro: immutable=1 ignores the
    # sidecar and reports the main file, i.e. zero credential rows.
    immutable = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    try:
        assert immutable.execute("SELECT COUNT(*) FROM credential").fetchone() == (0,)
    finally:
        immutable.close()

    # (b) The guard reads through the WAL and refuses on the same row.
    with pytest.raises(SessionStoreGuardError) as refusal:
        guard_shared_store(path)
    assert refusal.value.code == "SESSION_STORE_CREDENTIALS_PRESENT"
    assert refusal.value.table == "credential"
    peer.close()


def test_non_database_is_a_structure_refusal(tmp_path):
    path = tmp_path / "state.db"
    path.write_text("not a sqlite database\n" * 8, encoding="utf-8")

    with pytest.raises(SessionStoreGuardError) as refusal:
        guard_shared_store(path)
    assert refusal.value.code == "SESSION_STORE_GUARD_STRUCTURE"
