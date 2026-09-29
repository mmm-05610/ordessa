"""Plugin-private SQLite storage with its own schema ledger.

Deliberately not ``pacthold.storage.Database``: that opens the shared product
data root whose schema is host-owned (constitution III). This store lives in
the plugin's own data directory and versions itself through ``profile_schema``.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .ids import now

SCHEMA_VERSION = 2

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS profile_profiles (
    profile_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 1),
    display_name TEXT NOT NULL,
    harness_id TEXT NOT NULL,
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_revisions (
    profile_id TEXT NOT NULL REFERENCES profile_profiles(profile_id),
    config_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, config_revision)
);
CREATE TABLE IF NOT EXISTS profile_facet_values (
    profile_id TEXT NOT NULL REFERENCES profile_profiles(profile_id),
    config_revision INTEGER NOT NULL,
    facet_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    value_json TEXT NOT NULL,
    facet_version TEXT NOT NULL,
    quarantined INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, config_revision, facet_id, item_id),
    FOREIGN KEY (profile_id, config_revision)
        REFERENCES profile_revisions(profile_id, config_revision)
);
CREATE TABLE IF NOT EXISTS profile_sessions (
    session_id TEXT PRIMARY KEY,
    harness_id TEXT NOT NULL,
    current_profile_id TEXT NOT NULL REFERENCES profile_profiles(profile_id),
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    pending_profile_id TEXT REFERENCES profile_profiles(profile_id),
    pending_seq INTEGER,
    switch_state TEXT NOT NULL DEFAULT 'settled'
        CHECK (switch_state IN ('settled', 'pending', 'needs_recovery')),
    blockers_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_session_overlays (
    session_id TEXT NOT NULL REFERENCES profile_sessions(session_id),
    facet_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    value_json TEXT NOT NULL,
    facet_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, facet_id, item_id)
);
CREATE TABLE IF NOT EXISTS profile_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES profile_sessions(session_id),
    turn_seq INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    config_revision INTEGER NOT NULL,
    effective_digest TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, turn_seq)
);
CREATE TABLE IF NOT EXISTS profile_idempotency (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    status INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
"""

# v2 adds server-realm columns, canonical session identity and the
# application evidence tables.  Pure additive migration: historical rows are
# backfilled with derivable defaults and never rewritten afterwards
# (data-model.md §5 — old ids/revisions survive verbatim).
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS profile_mechanism_policy (
    realm TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    facet_enabled_json TEXT NOT NULL DEFAULT '{}',
    allow_override_global INTEGER NOT NULL DEFAULT 1,
    allow_per_facet_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_application_journal (
    operation_id TEXT PRIMARY KEY,
    session_uid TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
        ('planned', 'applying', 'confirmed', 'rejected', 'unknown')),
    profile_id TEXT NOT NULL,
    profile_revision INTEGER NOT NULL,
    plan_digest TEXT NOT NULL,
    failure TEXT,
    detail_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_applied_receipts (
    operation_id TEXT PRIMARY KEY,
    session_uid TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_session
    ON profile_application_journal(session_uid, created_at);
CREATE INDEX IF NOT EXISTS idx_receipts_session
    ON profile_applied_receipts(session_uid, confirmed_at);
"""


def _migrate_to_v2(conn: sqlite3.Connection, timestamp: str) -> None:
    """Additive v2 columns + legacy backfill (runs once per database)."""
    existing_profiles = {
        row["name"] for row in conn.execute("PRAGMA table_info(profile_profiles)")
    }
    if "realm" not in existing_profiles:
        conn.execute(
            "ALTER TABLE profile_profiles ADD COLUMN realm TEXT"
            " NOT NULL DEFAULT 'local'"
        )
    existing_sessions = {
        row["name"] for row in conn.execute("PRAGMA table_info(profile_sessions)")
    }
    if "realm" not in existing_sessions:
        conn.execute(
            "ALTER TABLE profile_sessions ADD COLUMN realm TEXT"
            " NOT NULL DEFAULT 'local'"
        )
    if "native_session_key" not in existing_sessions:
        conn.execute(
            "ALTER TABLE profile_sessions ADD COLUMN native_session_key TEXT"
        )
    if "session_uid" not in existing_sessions:
        conn.execute("ALTER TABLE profile_sessions ADD COLUMN session_uid TEXT")
        # Legacy backfill: the v1 single-string id becomes the native key and
        # the deterministic legacy uid.  Ambiguity gates (duplicate uid) are
        # enforced below and in migration.py — collisions refuse, never merge.
        conn.execute(
            "UPDATE profile_sessions SET native_session_key = session_id,"
            " session_uid = 'legacy:' || session_id"
            " WHERE session_uid IS NULL"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_uid"
        " ON profile_sessions(session_uid)"
    )
    conn.executescript(_SCHEMA_V2)


class ProfileDatabase:
    """One process-local connection guarded by an RLock; write transactions
    are ``BEGIN IMMEDIATE`` so the switch application is atomic (FR-008)."""

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.RLock()
        # isolation_level=None: transaction boundaries are exclusively the
        # explicit BEGIN IMMEDIATE units below.
        self._conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        """Stepwise, idempotent migration; each applied version is recorded
        so re-running (copy upgrade, reopen) is a no-op past current."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS profile_schema ("
                    "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                row = self._conn.execute(
                    "SELECT MAX(version) AS v FROM profile_schema"
                ).fetchone()
                current = int(row["v"] or 0)
                if current > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"profile schema {current} is newer than supported {SCHEMA_VERSION}"
                    )
                steps: dict[int, object] = {
                    1: lambda: self._conn.executescript(_SCHEMA_V1),
                    2: lambda: _migrate_to_v2(self._conn, now()),
                }
                for version in sorted(steps):
                    if current >= version:
                        continue
                    steps[version]()
                    self._conn.execute(
                        "INSERT INTO profile_schema(version, applied_at)"
                        " VALUES (?,?)",
                        (version, now()),
                    )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()
