"""SQLite implementation of the frozen ``StorePort`` (spec 026 order 005).

Scope discipline (compat-retirement §2 storage row): the CONNECTION and
TRANSACTION mechanism moves here; the product business DDL (server_profiles,
server_sessions, … PRODUCT_SCHEMA_VERSION=21) does NOT — the archived
history stays sealed in its own migrations and is only ever opened read-only
(see :mod:`ordessa_persistence_sqlite.legacy_read`).

C2 rules implemented here:

* same data root admits ONE effectful writer — a second ``open`` on a live
  root refuses; lease loss/timeout alone never proves the old writer dead,
  so recovery is an explicit evidence-backed release, not a timeout grab;
* request keys are claimed atomically with their digest; a spent key replays
  its stored receipt for the same digest and refuses a different one;
* response slots are consumed exactly once per (control_id, delivery_revision);
* receipts are append-only rows; current facts are revised, never rewritten.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from ordessa_environment_api.identity import RequestKey

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS env_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS env_writer_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner_token TEXT NOT NULL,
    acquired_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS env_requests (
    environment TEXT NOT NULL,
    principal TEXT NOT NULL,
    request_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    spent INTEGER NOT NULL DEFAULT 1,
    receipt TEXT,
    current TEXT,
    PRIMARY KEY (environment, principal, request_id)
);
CREATE TABLE IF NOT EXISTS env_objects (
    environment TEXT NOT NULL,
    owner_instance TEXT NOT NULL,
    owner_generation INTEGER NOT NULL,
    object_id TEXT NOT NULL,
    state TEXT NOT NULL,
    historical INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (environment, owner_instance, owner_generation, object_id)
);
CREATE TABLE IF NOT EXISTS env_usages (
    usage_id TEXT PRIMARY KEY,
    environment TEXT NOT NULL,
    object_env TEXT,
    state TEXT NOT NULL,
    rights TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS env_response_slots (
    control_id TEXT NOT NULL,
    delivery_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (control_id, delivery_revision)
);
CREATE TABLE IF NOT EXISTS env_relations (
    relation_id TEXT NOT NULL,
    source_entity TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (relation_id, source_entity, source_revision)
);
-- E5 change reservations (T005-11): durable admission tickets. Process death,
-- close/reopen or TTL never auto-releases one; only an explicit executed
-- release deletes its row (CREATE TABLE IF NOT EXISTS keeps this idempotent
-- for databases created before this table existed).
CREATE TABLE IF NOT EXISTS env_change_reservations (
    reservation_id TEXT PRIMARY KEY,
    target_entity TEXT NOT NULL,
    expected_revision TEXT NOT NULL,
    change_kind TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    refused_relations TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS env_key_tombstones (
    key_id TEXT PRIMARY KEY,
    retired_at REAL NOT NULL
);
"""


class WriterLockHeldError(RuntimeError):
    """Another live writer owns this data root (C2 same-root exclusivity)."""

    code = "WRITER_LOCK_HELD"


class SqliteStorePort:
    """One SQLite file implementing StorePort for one environment root."""

    def __init__(self, path: Path | str, *, writer_token: str | None = None,
                 allow_takeover: bool = False) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._token = writer_token or f"writer-{uuid.uuid4().hex}"
        self._conn = sqlite3.connect(str(self._path), timeout=10.0,
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._acquire_writer_lock(allow_takeover=allow_takeover)

    # -- lifecycle -----------------------------------------------------------

    def _acquire_writer_lock(self, *, allow_takeover: bool) -> None:
        cur = self._conn.execute("SELECT owner_token FROM env_writer_lock WHERE id=1")
        row = cur.fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO env_writer_lock (id, owner_token, acquired_at) VALUES (1, ?, ?)",
                (self._token, time.time()),
            )
            self._conn.commit()
            return
        if row["owner_token"] == self._token:
            return
        if not allow_takeover:
            raise WriterLockHeldError(
                f"data root {self._path} is owned by writer {row['owner_token']!r}; "
                "lease age never proves that writer dead — release explicitly or "
                "open with allow_takeover only with failure evidence"
            )
        # explicit evidence-backed takeover: record the previous owner's facts
        self._conn.execute(
            "UPDATE env_writer_lock SET owner_token=?, acquired_at=? WHERE id=1",
            (self._token, time.time()),
        )
        self._conn.commit()

    def release_writer(self) -> None:
        self._conn.execute("DELETE FROM env_writer_lock WHERE id=1 AND owner_token=?",
                           (self._token,))
        self._conn.commit()

    def close(self) -> None:
        try:
            self.release_writer()
        finally:
            self._conn.close()

    @property
    def writer_token(self) -> str:
        return self._token

    @property
    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM env_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT OR REPLACE INTO env_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
            return SCHEMA_VERSION
        return int(row["value"])

    def check_future_schema(self) -> None:
        version = self.schema_version
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {version} is newer than this code ({SCHEMA_VERSION}); "
                "refusing to write (read-only downgrade is not a migration)"
            )

    # -- StorePort (E1) --------------------------------------------------------

    def transaction(self) -> "sqlite3.Connection":
        return self._conn

    def reserve_request(self, key: RequestKey, digest: str) -> bool:
        """Atomically claim a request key; True when newly claimed.

        A spent key returns True only for the SAME digest (the caller replays
        the stored receipt); a different digest raises IdentityMismatchError
        semantics via False-with-conflict marker ``KeyConflictError``."""
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO env_requests (environment, principal, request_id, digest, spent) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (key.environment_namespace, key.principal_scope, key.request_id, digest),
                )
            return True
        except sqlite3.IntegrityError:
            row = self._conn.execute(
                "SELECT digest FROM env_requests WHERE environment=? AND principal=? AND request_id=?",
                (key.environment_namespace, key.principal_scope, key.request_id),
            ).fetchone()
            if row is None:
                raise
            if row["digest"] != digest:
                raise KeyConflictError(
                    f"request key {key.request_id} is spent with a different digest"
                )
            return True  # same digest → replay path; caller reads the receipt

    def commit_activity(self, activity_id: str, receipt: Mapping[str, Any]) -> None:
        self.append_receipt(activity_id, receipt)

    def append_receipt(self, activity_id: str, receipt: Mapping[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE env_requests SET receipt=? WHERE request_id=?",
                (json.dumps(dict(receipt), sort_keys=True), activity_id),
            )
            if self._conn.execute("SELECT changes()").fetchone()[0] == 0:
                self._conn.execute(
                    "INSERT INTO env_requests (environment, principal, request_id, digest, spent, receipt) "
                    "VALUES ('', '', ?, '', 1, ?)",
                    (activity_id, json.dumps(dict(receipt), sort_keys=True)),
                )

    def read_current(self, activity_id: str) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT current FROM env_requests WHERE request_id=?", (activity_id,)
        ).fetchone()
        return json.loads(row["current"]) if row and row["current"] else None

    def revise_current(self, activity_id: str, current: Mapping[str, Any]) -> None:
        """Current facts are REVISED, never overwritten silently (V2-3)."""
        with self._conn:
            self._conn.execute(
                "UPDATE env_requests SET current=? WHERE request_id=?",
                (json.dumps(dict(current), sort_keys=True), activity_id),
            )

    def lookup_history(self, activity_id: str) -> Mapping[str, Any] | None:
        row = self._conn.execute(
            "SELECT receipt, current FROM env_requests WHERE request_id=?", (activity_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
            "current": json.loads(row["current"]) if row["current"] else None,
        }

    def claim_response_slot(self, control_id: str, delivery_revision: int) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO env_response_slots (control_id, delivery_revision, state) "
                "VALUES (?, ?, 'claimed')",
                (control_id, delivery_revision),
            )
            if cur.rowcount == 0:
                row = self._conn.execute(
                    "SELECT state FROM env_response_slots WHERE control_id=? AND delivery_revision=?",
                    (control_id, delivery_revision),
                ).fetchone()
                if row and row["state"] == "free":
                    self._conn.execute(
                        "UPDATE env_response_slots SET state='claimed' "
                        "WHERE control_id=? AND delivery_revision=?",
                        (control_id, delivery_revision),
                    )
                    return True
                return False  # already spent — one effectful answer per slot
            return True

    def commit_creation_and_usage(
        self, activity_id: str, objects: Mapping[str, Any], usages: Mapping[str, Any]
    ) -> None:
        """V3-1: objects + usages + receipt in ONE transaction."""
        env_row = self._conn.execute(
            "SELECT environment FROM env_requests WHERE request_id=?", (activity_id,)
        ).fetchone()
        environment = env_row["environment"] if env_row else ""
        with self._conn:
            for ref, state in objects.items():
                env, inst, gen, oid = _split_object(ref)
                self._conn.execute(
                    "INSERT OR REPLACE INTO env_objects "
                    "(environment, owner_instance, owner_generation, object_id, state) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (env, inst, gen, oid, state),
                )
            for usage_id, state in usages.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO env_usages (usage_id, environment, state, rights) "
                    "VALUES (?, ?, ?, 'use')",
                    (usage_id, environment, state),
                )
            self._conn.execute(
                "UPDATE env_requests SET receipt=COALESCE(receipt, ?) WHERE request_id=?",
                (json.dumps({"creation": True}, sort_keys=True), activity_id),
            )

    # -- tombstones (C2 §密钥与墓碑) -------------------------------------------

    def record_key_tombstone(self, key_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO env_key_tombstones (key_id, retired_at) VALUES (?, ?)",
                (key_id, time.time()),
            )

    def has_key_tombstone(self, key_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM env_key_tombstones WHERE key_id=?", (key_id,)
        ).fetchone() is not None


def _split_object(ref: str) -> tuple[str, str, int, str]:
    parts = ref.split(":", 3)
    if len(parts) != 4:
        raise ValueError(f"object ref must be env:instance:generation:object, got {ref!r}")
    return parts[0], parts[1], int(parts[2]), parts[3]


class KeyConflictError(RuntimeError):
    """Same request key, different digest — never a re-dispatch."""

    code = "KEY_CONFLICT"
