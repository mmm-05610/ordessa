"""Order 66 stage C: the read-only credential guard in front of a shared session library.

Switching a Session to another Profile of the same family is only safe while
the family's shared store carries no credential rows: a row still sitting there
belongs to the Profile that wrote it, and the next Profile would read it back
as its own. This module holds the one check that stands before such a switch.
It looks and refuses, and does nothing else: the store is opened ``mode=ro``
and every credential table that exists is counted. ``immutable=1`` is
deliberately not used - it ignores the ``-wal`` sidecar, so a live store whose
committed rows have not been checkpointed would read as empty; ``mode=ro``
reads exactly what the family's own next open would read, takes no write lock,
and never checkpoints. A store that cannot be opened or read is a typed
refusal, never a silent pass.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

#: The credential-bearing tables a shared session library must not carry.
CREDENTIAL_TABLES = ("credential", "account", "control_account", "account_state")


class SessionStoreGuardError(RuntimeError):
    """A typed refusal from the shared-store guard; ``code`` names the boundary."""

    def __init__(self, code: str, message: str, *, table: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        # The message names the table and never a value; the table is the
        # whole fact the refusal carries.
        self.message = message
        self.table = table


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def guard_shared_store(path, *, tables=CREDENTIAL_TABLES) -> dict:
    """Assert the shared session library holds no credential rows.

    Returns ``{"state": "fresh", "rows": {}}`` when the library does not exist
    yet, and ``{"state": "empty", "rows": {table: count}}`` when every
    credential table that exists is empty. A counted table with rows refuses
    with ``SESSION_STORE_CREDENTIALS_PRESENT``, naming the table. Only counts
    leave here, never a value and never a write: the connection is read-only,
    the schema listing is a plain SELECT, and nothing may checkpoint or
    otherwise lock the family's live store.
    """
    store = Path(path)
    if not store.exists():
        # A fresh library has nothing to guard; this is the positive case.
        return {"state": "fresh", "rows": {}}

    connection = None
    try:
        # mode=ro, never immutable=1: committed rows in the -wal sidecar are
        # part of what the family's next open would read, and an immutable
        # connection skips that sidecar entirely.
        connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=2.0)
        existing = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        counted: dict[str, int] = {}
        for table in tables:
            if table not in existing:
                continue
            count = connection.execute(
                f"SELECT COUNT(*) FROM {_quoted(table)}"
            ).fetchone()[0]
            counted[table] = int(count)
            if count:
                raise SessionStoreGuardError(
                    "SESSION_STORE_CREDENTIALS_PRESENT",
                    f"shared session library holds credential rows in table {table}",
                    table=table,
                )
    except sqlite3.Error as error:
        # Unopenable, not a database, an unreadable schema, a failed count:
        # the guard cannot see the store, and cannot see it means refuse.
        raise SessionStoreGuardError(
            "SESSION_STORE_GUARD_STRUCTURE",
            f"shared session library at {store} is not a readable database",
        ) from error
    finally:
        if connection is not None:
            connection.close()
    return {"state": "empty", "rows": counted}
