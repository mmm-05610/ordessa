"""The Server product database consumes the Infrastructure connection contract.

These checks pin the *effective* parameters the migrated owner relies on, in
particular that the explicit ``busy_timeout`` (not the connect ``timeout``)
decides the final SQLite busy handler.
"""
import sqlite3
from pathlib import Path

from ordessa_server.bootstrap.storage.product_database import Database


def test_connect_uses_explicit_contract(tmp_path):
    database = Database(tmp_path)
    database.initialize()
    conn = database._connect()
    try:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_explicit_busy_timeout_wins_over_configured_timeout(tmp_path):
    database = Database(tmp_path, timeout=1.0)
    database.initialize()
    conn = database._connect()
    try:
        # sqlite3.connect(timeout=1.0) seeds 1000 ms; the explicit PRAGMA wins.
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_initialize_then_read_roundtrip(tmp_path):
    database = Database(tmp_path)
    database.initialize()
    assert database.path.exists()
    with database.read() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
