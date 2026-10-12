"""Explicit SQL source registration and the original per-file migration runner.

The registry holds deployment configuration, not a database. Connections,
source directories, namespace/version-table names and source ordering belong to
the caller. No default source, global registry or connection is created here.
Importing this module performs no discovery or filesystem/database operations.

Applying retains native executescript/commit behavior: version-table setup
commits first, then each script and ledger insertion commits individually.
This is not an atomic migration batch; failed scripts can leave partial effects.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import threading
from typing import Iterable

__all__ = [
    "MigrationSource", "MigrationRegistry", "register_migration_source",
    "registered_migration_sources", "apply_migration_source",
    "apply_registered_migrations",
]

_MIGRATION_NAME = re.compile(r"^(\d{3})_.*\.sql$")


@dataclass(frozen=True)
class MigrationSource:
    namespace: str
    directory: Path
    version_table: str


def _validate_source(source: MigrationSource) -> None:
    if not re.fullmatch(r"[a-z0-9_.-]+", source.namespace):
        raise ValueError(f"invalid migration namespace: {source.namespace!r}")
    if not re.fullmatch(r"[a-z0-9_]+", source.version_table):
        raise ValueError(f"invalid version table: {source.version_table!r}")


class MigrationRegistry:
    """Caller-owned ordered sources, followed by explicit reserved sources.

    trailing_sources preserves a caller's assembly-first/history-last policy
    without teaching the mechanism any historical namespace or SQL directory.
    Metadata conflicts are rejected; no SQL is read or executed at registration.
    """

    def __init__(self, *, trailing_sources: Iterable[MigrationSource] = ()) -> None:
        trailing = tuple(trailing_sources)
        for index, source in enumerate(trailing):
            _validate_source(source)
            for prior in trailing[:index]:
                if prior.namespace == source.namespace:
                    raise ValueError(f"migration namespace {source.namespace!r} is already reserved")
                if prior.version_table == source.version_table:
                    raise ValueError(f"migration version table {source.version_table!r} is already reserved")
        self._trailing = trailing
        self._assembly: list[MigrationSource] = []
        self._lock = threading.RLock()

    def register(self, source: MigrationSource) -> bool:
        _validate_source(source)
        with self._lock:
            for existing in self._assembly:
                if existing.namespace == source.namespace:
                    if (Path(existing.directory).resolve() != Path(source.directory).resolve()
                            or existing.version_table != source.version_table):
                        raise ValueError(
                            f"migration namespace {source.namespace!r} is already "
                            "registered with a different source"
                        )
                    return False
                if existing.version_table == source.version_table:
                    raise ValueError(
                        f"migration version table {source.version_table!r} is already "
                        f"owned by namespace {existing.namespace!r}"
                    )
            if any(source.namespace == tail.namespace for tail in self._trailing):
                raise ValueError("the historical migration namespace is reserved")
            if any(source.version_table == tail.version_table for tail in self._trailing):
                raise ValueError("the historical version table is reserved")
            self._assembly.append(source)
            return True

    def registered(self) -> tuple[MigrationSource, ...]:
        with self._lock:
            return (*self._assembly, *self._trailing)


def register_migration_source(source: MigrationSource, *, registry: MigrationRegistry) -> bool:
    return registry.register(source)


def registered_migration_sources(*, registry: MigrationRegistry) -> tuple[MigrationSource, ...]:
    return registry.registered()


def _ensure_version_table(conn: sqlite3.Connection, version_table: str) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {version_table} "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()


def apply_migration_source(conn: sqlite3.Connection, source: MigrationSource) -> None:
    _validate_source(source)
    _ensure_version_table(conn, source.version_table)
    current = conn.execute(
        f"SELECT MAX(version) FROM {source.version_table}"
    ).fetchone()[0] or 0
    directory = Path(source.directory)
    if not directory.is_dir():
        return
    files = sorted(
        (f for f in directory.iterdir() if _MIGRATION_NAME.match(f.name)),
        key=lambda f: f.name,
    )
    for path in files:
        version = int(_MIGRATION_NAME.match(path.name).group(1))
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"INSERT INTO {source.version_table} (version) VALUES (?)", (version,))
        conn.commit()


def apply_registered_migrations(conn: sqlite3.Connection, *, registry: MigrationRegistry) -> None:
    for source in registered_migration_sources(registry=registry):
        apply_migration_source(conn, source)
