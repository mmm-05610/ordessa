"""``CoreStore`` — the instance-level durable store of one CoreRuntime.

Naming mapping (reports/A.md finding I1): the C1 contract name ``CoreStore``
is the *instance-level Store* neutral type.  It replaces the process-global
``_conn`` / ``configure_database`` singleton in ``pacthold.work_core.db``
(db.py:11-14) for the C1 surface: one ``CoreStore`` owns exactly one
``sqlite3.Connection``; two stores started in one process never see each
other's data (FR-001).  Neither this class nor this module keeps any global
mutable state.

The store is a thin, honest wrapper: it opens SQLite, exposes
``transaction()`` / ``execute()`` and ``close()`` and nothing else.  Schema
ownership (the neutral core tables) arrives with the T008 dispatch wiring;
this checkpoint guarantees only the isolation and lifecycle contract.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_MEMORY_SENTINEL = ":memory:"


class CoreStore:
    """One self-owned SQLite database bound to one CoreRuntime instance.

    Mechanism extraction note (order 005, T005-01): the SQLite
    connection/transaction *mechanism* belongs to the environment-level
    persistence package (``ordessa-persistence-sqlite``, the environment
    ``StorePort`` implementation).  ``CoreStore`` stays the kernel's internal
    schema implementation (the neutral ``core_execution``/``core_operation``
    tables) behind the ``CoreStoreProtocol`` seam
    (``pacthold.core.store_port``).  The core never imports or re-exports the
    environment implementation: import direction is implementation → core
    only, never core → implementation (no reverse export).  Consumers built
    as ``CoreStore(path)`` keep working unchanged.
    """

    __slots__ = ("_path", "_conn", "_closed")

    def __init__(self, path: Path | str) -> None:
        if not isinstance(path, (Path, str)):
            raise TypeError(f"CoreStore path must be Path or str, got {type(path)!r}")
        self._path = str(path)
        if self._path != _MEMORY_SENTINEL:
            target = Path(path)
            if str(target) == "":
                raise ValueError("CoreStore path must not be empty")
            target.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._path, timeout=10.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._closed = False

    @property
    def path(self) -> str:
        return self._path

    def connection(self) -> sqlite3.Connection:
        """The one connection this store owns, for same-instance borrowers.

        T006-01 (order 026): the host composition hands its legacy execution
        chain THIS connection (through ``CoreBinding.store``) so the chain and
        the C1 runtime share the instance store through one OS-level
        connection — the S1c composition decision. Borrowers execute their
        statements on it, never close it, and never open a second connection
        on the file (the counterexample witness for that hazard is
        ``apps/server/tests/platform/test_platform_core_instance.py``).
        Deliberately NOT part of the ``CoreStoreProtocol`` face: this is the
        concrete store's same-instance composition seam, not a runtime
        contract.
        """
        self._ensure_open()
        return self._conn

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("CoreStore is closed")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One all-or-nothing write scope on this instance's connection."""
        self._ensure_open()
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Thin single-statement wrapper; caller manages the transaction."""
        self._ensure_open()
        return self._conn.execute(sql, params)

    def query_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Read helper returning plain tuples (no row-factory leakage)."""
        self._ensure_open()
        return [tuple(row) for row in self._conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        """Close this store only.  Idempotent; never touches other stores."""
        if not self._closed:
            self._conn.close()
            self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed
