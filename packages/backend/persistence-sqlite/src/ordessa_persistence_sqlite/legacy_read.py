"""Read-only view over the sealed compat history schema (T005-02).

The nine archived SQL files under
``plugins/runtime-compat/src/pacthold_runtime_compat/migrations/`` keep their
bytes, order, namespace, version table and table identifiers (compat-
retirement §1.7). This module opens such a database **read-only** and maps
the minimal neutral facts; it never writes, never migrates and never deletes
old migrations to manufacture green. A future-version database is refused.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

#: The sealed version table name and its meaning stay EXACTLY as archived
#: (database.py:763 agentbox_product_schema, PRODUCT_SCHEMA_VERSION=21).
SCHEMA_VERSION_TABLE = "agentbox_product_schema"
SUPPORTED_LEGACY_MAX = 21


class LegacySchemaError(RuntimeError):
    code = "LEGACY_SCHEMA"


class LegacyCompatReader:
    """Read-only accessor for one archived-schema database file."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise LegacySchemaError(f"no legacy database at {self._path}")
        # immutable=1 keeps this honestly read-only at the VFS level
        uri = f"file:{self._path}?mode=ro&immutable=1"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def schema_version(self) -> int:
        try:
            row = self._conn.execute(
                f"SELECT version FROM {SCHEMA_VERSION_TABLE} WHERE singleton=1"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0  # pre-product schema: only the base SQL tables exist
        if row is None:
            return 0
        return int(row["version"])

    def check_supported(self) -> None:
        version = self.schema_version()
        if version > SUPPORTED_LEGACY_MAX:
            raise LegacySchemaError(
                f"legacy schema version {version} is newer than the reader supports "
                f"({SUPPORTED_LEGACY_MAX}); refusing instead of guessing"
            )

    def tables(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return tuple(r["name"] for r in rows)

    def neutral_counts(self) -> Mapping[str, Any]:
        """Minimal neutral facts — no business interpretation, no bodies."""
        self.check_supported()
        out: dict[str, int] = {}
        for table in self.tables():
            if table.startswith("sqlite_") or table == SCHEMA_VERSION_TABLE:
                continue
            out[table] = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        return out


def replay_archived_migrations(target: Path, migrations_dir: Path) -> int:
    """Fixture helper: build a legacy database by replaying the SEALED SQL,
    byte-for-byte, in file order. Test-only; real user data is never touched."""
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise LegacySchemaError(f"no archived migrations in {migrations_dir}")
    conn = sqlite3.connect(str(target))
    try:
        for sql_file in files:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return len(files)
