"""Controlled close faults on the original SQLite writer; no service or user data."""
import sqlite3

import pytest

from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_units.persistence.sqlite.store import SqliteUnitStore


def test_readonly_release_failure_preserves_original_writer_for_retry(tmp_path):
    path = tmp_path / "core.sqlite"
    store = SqliteUnitStore(path)
    token = store.writer_token
    store._conn.execute("PRAGMA query_only=ON")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        store.inspect_and_close(lambda: {"unresolved": ("original",)})
    assert store._conn.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()[0] == token
    assert store._connection_closed is False
    assert store._writer_release_confirmed is False
    store._conn.execute("PRAGMA query_only=OFF")
    assert store.inspect_and_close(lambda: {"unresolved": ("original",)}) == {"unresolved": ("original",)}
    assert store._connection_closed is True
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone() is None
    replacement = SqliteUnitStore(path)
    replacement.close()


def test_inspection_failure_preserves_writer_and_never_reports_clean_close(tmp_path):
    """A raising close inspector must retain the writer, never look like a clean
    close — the safety the node-surface skip must not weaken."""
    path = tmp_path / "core.sqlite"
    store = SqliteUnitStore(path)
    token = store.writer_token

    def boom():
        raise RuntimeError("inventory refused")

    with pytest.raises(RuntimeError, match="inventory refused"):
        store.inspect_and_close(boom)
    assert store._conn.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()[0] == token
    assert store._connection_closed is False
    assert store._writer_release_confirmed is False
    store.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone() is None


def test_lost_commit_reply_is_not_assumed_to_preserve_writer_row(tmp_path):
    path = tmp_path / "core.sqlite"
    store = SqliteUnitStore(path)
    connection = store._conn

    class LostReply:
        def __getattr__(self, name):
            return getattr(connection, name)

        def commit(self):
            connection.commit()  # durable deletion occurred
            raise OSError("synthetic lost commit acknowledgement")

    store._conn = LostReply()
    with pytest.raises(OSError, match="lost commit acknowledgement"):
        store.close()
    assert store._connection_closed is False
    assert store._writer_release_confirmed is False
    with sqlite3.connect(path) as readback:
        assert readback.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone() is None
    with pytest.raises(GuaranteeUnavailableError, match="absent or belongs"):
        store.close()  # exact release is unproven; do not call this success
    assert store._connection_closed is False
    connection.close()  # controlled fixture cleanup only; no product recovery claim
