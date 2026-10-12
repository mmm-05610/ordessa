"""Reusable SQLite connection creation returning a native connection.

This is deliberately *only* connection creation plus the explicit parameter
contract from :mod:`ordessa_infrastructure.database.options`. Business schema,
migrations, repositories, transaction units of work, commit/rollback policy and
WAL timing stay with their existing owners.

Lifecycle contract:

* On any initialisation failure the freshly opened connection is closed and the
  exception propagates, so a caller never receives a half-configured handle.
* On success the returned connection is owned entirely by the caller. A
  ``with connection:`` block is a transaction scope, **not** a close; the
  caller must close it (or hand it to a long-lived owner) explicitly.
"""
from __future__ import annotations

import sqlite3

from .options import SQLiteOptions

__all__ = ["create_connection", "SQLiteConfigurationError"]


class SQLiteConfigurationError(RuntimeError):
    """A requested connection setting could not actually take effect."""


def _apply_pragma(conn: sqlite3.Connection, statement: str) -> None:
    # ``executescript``/``execute`` run through the same cursor API; using the
    # connection ensures the PRAGMA executes against this handle only.
    conn.execute(statement)


def _apply_foreign_keys(conn: sqlite3.Connection, foreign_keys: bool) -> None:
    """Apply ``PRAGMA foreign_keys`` and prove it took effect.

    ``PRAGMA foreign_keys`` is a silent no-op inside a transaction. In
    particular ``autocommit=False`` starts a connection already inside an
    implicit transaction, so the PRAGMA would leave foreign keys *off* while
    returning success. Reading the value back and refusing a silent mismatch is
    what keeps that combination from handing back an unexpectedly unprotected
    connection.
    """
    wanted = 1 if foreign_keys else 0
    _apply_pragma(conn, "PRAGMA foreign_keys = ON" if foreign_keys else "PRAGMA foreign_keys = OFF")
    actual = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if actual != wanted:
        raise SQLiteConfigurationError(
            "PRAGMA foreign_keys did not take effect (requested "
            f"{wanted}, got {actual}); this happens when the connection is "
            "already inside a transaction, e.g. autocommit=False"
        )


def _apply_busy_timeout(conn: sqlite3.Connection, busy_timeout: int) -> None:
    """Apply the requested millisecond value and reject SQLite's silent clamp."""
    wanted = int(busy_timeout)
    _apply_pragma(conn, f"PRAGMA busy_timeout = {wanted}")
    actual = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    if actual != wanted:
        raise SQLiteConfigurationError(
            "PRAGMA busy_timeout did not take effect (requested "
            f"{wanted}, got {actual})"
        )


def create_connection(options: SQLiteOptions) -> sqlite3.Connection:
    """Open one SQLite connection described by ``options``.

    The result is a plain :class:`sqlite3.Connection`. ``options.uri`` selects
    URI handling; ``options.timeout`` and ``options.check_same_thread`` are
    forwarded. ``row_factory``, ``foreign_keys`` and ``busy_timeout`` are
    applied only when the caller asked for them.
    """
    conn = sqlite3.connect(str(options.location), **options.connect_kwargs())
    try:
        if options.row_factory is not None:
            conn.row_factory = options.row_factory
        if options.foreign_keys is not None:
            _apply_foreign_keys(conn, options.foreign_keys)
        if options.busy_timeout is not None:
            _apply_busy_timeout(conn, options.busy_timeout)
    except BaseException:
        # Initialisation failed: the new connection is not yet handed over, so
        # closing it is this function's responsibility.
        conn.close()
        raise
    return conn
