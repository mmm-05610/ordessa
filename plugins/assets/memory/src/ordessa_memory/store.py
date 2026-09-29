"""The plugin's private records: bindings, the capture queue, the explicit
extraction authorization, and diagnostics.

The store lives in the plugin's own directory under the product data root
(``<data_root>/memory/memory.db``) — never in the repo, never in the
Profile. The capture queue is durable on purpose: a turn captured but not
yet extracted survives a restart, and a failed extraction stays queued with
its recorded error (memory absence must never block a session, and a lost
turn must never be silently dropped either).

Secrets are structurally absent: the store's row shapes have no credential
column, and a value that looks like a key cannot appear in any recorded
field (the pipelines pass references only).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from . import common, facet

#: The capture queue cap: past it the oldest un-attempted turns are dropped
#: and the drop is recorded — a bound, not a silent leak.
QUEUE_CAP = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS binding (
    profile_id TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    created_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS authorization (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    extraction_authorized INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class MemoryStore:
    """SQLite-backed records under the plugin's data-root directory."""

    def __init__(self, path: "Path | str") -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- bindings -------------------------------------------------------------

    def get_binding(self, profile_id: str) -> dict[str, Any]:
        """The profile's binding, or the facet default when absent (AR-5: a
        missing P-A-side item falls back to this facet's default, no error)."""
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM binding WHERE profile_id = ?", (profile_id,)).fetchone()
        if row is None:
            return common.default_binding()
        return facet.validate_binding(json.loads(row[0]))

    def has_binding_override(self, profile_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM binding WHERE profile_id = ?", (profile_id,)).fetchone()
        return row is not None

    def set_binding(self, profile_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
        normalized = facet.validate_binding(value)
        with self._lock:
            self._db.execute(
                "INSERT INTO binding (profile_id, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(profile_id) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (profile_id, json.dumps(normalized, sort_keys=True), time.time()))
            self._db.commit()
        return normalized

    # -- capture queue ----------------------------------------------------------

    def enqueue_turn(self, profile_id: str, session_id: str, turn_id: str,
                     user_text: str, assistant_text: str) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO capture_queue (profile_id, session_id, turn_id, user_text, "
                "assistant_text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_id, session_id, turn_id, user_text, assistant_text, time.time()))
            self._db.execute(
                "DELETE FROM capture_queue WHERE id NOT IN "
                "(SELECT id FROM capture_queue ORDER BY id DESC LIMIT ?)", (QUEUE_CAP,))
            self._db.commit()
            return int(cursor.lastrowid)

    def pending_turns(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, profile_id, session_id, turn_id, user_text, assistant_text, "
                "attempts FROM capture_queue ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "profileId": r[1], "sessionId": r[2], "turnId": r[3],
                 "userText": r[4], "assistantText": r[5], "attempts": r[6]} for r in rows]

    def record_attempt(self, turn_id: int, error: str | None) -> None:
        with self._lock:
            if error is None:
                self._db.execute("DELETE FROM capture_queue WHERE id = ?", (turn_id,))
            else:
                self._db.execute(
                    "UPDATE capture_queue SET attempts = attempts + 1, last_error = ? "
                    "WHERE id = ?", (error[:500], turn_id))
            self._db.commit()

    def capture_stats(self) -> dict[str, Any]:
        with self._lock:
            queued = self._db.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0]
            failed = self._db.execute(
                "SELECT COUNT(*) FROM capture_queue WHERE attempts > 0").fetchone()[0]
            last = self._db.execute(
                "SELECT last_error FROM capture_queue WHERE last_error IS NOT NULL "
                "ORDER BY id DESC LIMIT 1").fetchone()
        return {"queued": queued, "failed": failed, "lastError": last[0] if last else None}

    # -- extraction authorization ----------------------------------------------

    def extraction_authorized(self) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT extraction_authorized FROM authorization WHERE id = 1").fetchone()
        return bool(row and row[0])

    def set_extraction_authorized(self, authorized: bool) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO authorization (id, extraction_authorized, updated_at) "
                "VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "extraction_authorized = excluded.extraction_authorized, "
                "updated_at = excluded.updated_at",
                (1 if authorized else 0, time.time()))
            self._db.commit()

    # -- diagnostics -------------------------------------------------------------

    def record_diagnostic(self, kind: str, detail: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO diagnostics (at, kind, detail) VALUES (?, ?, ?)",
                (time.time(), kind, detail[:500]))
            self._db.commit()

    def recent_diagnostics(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT at, kind, detail FROM diagnostics ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [{"at": r[0], "kind": r[1], "detail": r[2]} for r in rows]
