"""The plugin's private SQLite store (data-model.md, plan.md "数据与升级").

Lives in the Prompts-owned directory under the product data root; the
Server core DB and its markers are untouched. Schema facts:

* ``prompt_records`` / ``prompt_revisions`` — metadata head + immutable
  revisions; UPDATE/DELETE on revisions are refused by database triggers,
  so "revisions are never modified in place" and "no hard delete" are
  storage-enforced, not merely service discipline (G02/G03);
* ``prompt_idempotency`` — write receipts scoped to
  caller+operation+target+key with the payload digest, committed in the
  same transaction as the business write (a replay of a different
  payload is refused);
* ``prompt_meta`` — one schema-version row; a future schema is refused
  open rather than silently downgraded.

``fault_after`` is the only seam tests may use to interrupt a
transaction mid-write; production passes nothing (G02 counter-example).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

SCHEMA_VERSION = 1
_BUSY_TIMEOUT_SECONDS = 10.0

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS prompt_meta(
    key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """
CREATE TABLE IF NOT EXISTS prompt_records(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('instruction','persona','system-replacement')),
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('library','profile')),
    profile_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1)),
    metadata_version INTEGER NOT NULL CHECK (metadata_version >= 1),
    latest_revision INTEGER NOT NULL CHECK (latest_revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((scope_kind = 'profile') = (profile_id IS NOT NULL)))""",
    """
CREATE TABLE IF NOT EXISTS prompt_revisions(
    prompt_id TEXT NOT NULL REFERENCES prompt_records(id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    body BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (prompt_id, revision))""",
    """
CREATE TRIGGER IF NOT EXISTS prompt_revisions_no_update
BEFORE UPDATE ON prompt_revisions
BEGIN
    SELECT RAISE(ABORT, 'prompt revisions are immutable');
END""",
    """
CREATE TRIGGER IF NOT EXISTS prompt_revisions_no_delete
BEFORE DELETE ON prompt_revisions
BEGIN
    SELECT RAISE(ABORT, 'prompt revisions must not be deleted');
END""",
    """
CREATE TRIGGER IF NOT EXISTS prompt_records_no_delete
BEFORE DELETE ON prompt_records
BEGIN
    SELECT RAISE(ABORT, 'prompt records must not be hard-deleted');
END""",
    """
CREATE TABLE IF NOT EXISTS prompt_idempotency(
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key))""",
)
_DDL_STATEMENTS = _SCHEMA


class SchemaRefusalError(RuntimeError):
    """The store was written by a newer schema; opening is refused."""


class PromptsStore:
    """One private SQLite database for one Server data domain."""

    def __init__(self, path: "Path | str", *, timeout: float = _BUSY_TIMEOUT_SECONDS) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._closed = False
        #: test-only interruption seam: called with the step index after
        #: each statement inside a transaction; raising aborts the txn.
        #: Production code never assigns it (see PR-R3 in
        #: specs/011-q2-prompts-commands/review-notes.md): the constructor
        #: takes no such parameter and the Server plugin surface never sets
        #: it.
        self.fault_after: "Optional[Callable[[int], None]]" = None
        self._initialize()

    # -- lifecycle ----------------------------------------------------------

    @property
    def closed(self) -> bool:
        """True once :meth:`close` ran; a disposed store serves nothing."""
        return self._closed

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=self.timeout,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        if self._closed:
            raise sqlite3.ProgrammingError(
                f"the Prompts store at {self.path} was disposed; rebuild the "
                "plugin to serve again")
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def _initialize(self) -> None:
        with self._write_lock:
            conn = self.connection
            row = None
            try:
                row = conn.execute(
                    "SELECT value FROM prompt_meta WHERE key='schema_version'").fetchone()
            except sqlite3.OperationalError:
                row = None  # fresh database: the table does not exist yet
            if row is not None:
                version = int(row["value"])
                if version > SCHEMA_VERSION:
                    raise SchemaRefusalError(
                        f"store schema {version} is newer than this build "
                        f"({SCHEMA_VERSION}); refusing to open (no downgrade)")
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _DDL_STATEMENTS:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO prompt_meta(key,value) VALUES ('schema_version',?)",
                    (str(SCHEMA_VERSION),))
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def close(self) -> None:
        """Dispose this store: this thread's connection is released and every
        later use refuses, so a disposed plugin cannot keep serving."""
        conn = getattr(self._local, "conn", None)
        self._closed = True
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- transactions ---------------------------------------------------------

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """A plain snapshot read transaction (G07: one transaction, one
        instant of latest resolution)."""
        conn = self.connection
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        """A write transaction; steps are fault-injectable in order."""
        with self._write_lock:
            conn = self.connection
            conn.execute("BEGIN IMMEDIATE")
            holder = getattr(self._local, "step", None)
            self._local.step = 0
            try:
                yield conn
            except BaseException:
                self._local.step = holder
                conn.execute("ROLLBACK")
                raise
            else:
                self._local.step = holder
                conn.execute("COMMIT")

    def run_step(self, sql: str, params: "tuple[Any, ...]" = ()) -> sqlite3.Cursor:
        """Execute one statement of a multi-step write, then run the fault
        seam. All record/revision/idempotency writes go through here so an
        interrupted transaction can be proven to roll back (G02)."""
        conn = self.connection
        cursor = conn.execute(sql, params)
        step = getattr(self._local, "step", None)
        if step is not None:
            self._local.step = step + 1
            if self.fault_after is not None:
                self.fault_after(step + 1)
        return cursor


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical_digest(payload: "dict[str, Any]") -> str:
    """Digest of the request payload an idempotency key is bound to."""
    import hashlib
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         default=_digest_default).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _digest_default(value: Any) -> Any:
    if isinstance(value, bytes):
        # Hex keeps the digest byte-exact (a lossy decode could conflate
        # two different bodies behind one replay check).
        return "hex:" + value.hex()
    raise TypeError(f"un digestable payload type: {type(value).__name__}")
