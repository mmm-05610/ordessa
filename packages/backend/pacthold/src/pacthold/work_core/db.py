"""Durable Work Core SQLite persistence and namespaced migration runner.

 specs/010 T009: the historical agent-box migration set (``001_init.sql`` …
``009_execution_finalization.sql``) is sealed in the compatibility assembly
(``pacthold_runtime_compat``) and registered against this runner under its
own namespace.  The kernel keeps only a neutral, idempotent schema under an
independent version-record namespace, so a bare instance never depends on a
business distribution — and an old product database is never treated as an
empty one: its ``schema_versions`` rows stay byte-for-byte meaningful (they
are neither deleted nor renumbered), and the legacy chain still decides what
applies to it.

Application order is deliberate: registered assembly sources run first (in
registration order), the built-in neutral core source runs last.  A fresh
product database therefore gets the exact historical chain, and the idempotent
neutral copy no-ops on top of it; a fresh bare-core database gets only the
neutral copy.  The neutral copy contains only ``CREATE TABLE/INDEX IF NOT
EXISTS`` DDL — never ALTERs — so it can never rewrite an existing chain's
result.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import threading

from .runtime import agent_box_home, database_path, migrations_dir

_conn: sqlite3.Connection | None = None
_database_override: Path | None = None
_lock = threading.RLock()
write_lock = _lock

_MIGRATION_NAME = re.compile(r"^(\d{3})_.*\.sql$")

#: Version-record table of the neutral kernel schema.  Deliberately NOT the
#: historical ``schema_versions`` table: the data-model rule "new migrations
#: live in an independent namespace and must not be skipped by the old
#: schema_versions MAX(version)" is enforced by using a separate table.
CORE_SCHEMA_VERSION_TABLE = "core_schema_versions"
CORE_MIGRATION_NAMESPACE = "pacthold_core"


@dataclass(frozen=True)
class MigrationSource:
    """One named SQL directory with its own version-record table."""

    namespace: str
    directory: Path
    version_table: str


_CORE_SOURCE = MigrationSource(
    namespace=CORE_MIGRATION_NAMESPACE,
    directory=migrations_dir(),
    version_table=CORE_SCHEMA_VERSION_TABLE,
)

_assembly_sources: list[MigrationSource] = []
_sources_lock = threading.RLock()


def register_migration_source(source: MigrationSource) -> bool:
    """Register one assembly/legacy SQL directory ahead of the core source.

    Returns ``True`` when the registration changed state, ``False`` when an
    identical source (same namespace, directory and version table) was already
    registered — registration is idempotent so a product may assemble twice.
    A namespace reused with a *different* directory or table is a fail-closed
    conflict, never a silent override.
    """
    if not re.fullmatch(r"[a-z0-9_.-]+", source.namespace):
        raise ValueError(f"invalid migration namespace: {source.namespace!r}")
    if not re.fullmatch(r"[a-z0-9_]+", source.version_table):
        raise ValueError(f"invalid version table: {source.version_table!r}")
    with _sources_lock:
        for existing in _assembly_sources:
            if existing.namespace == source.namespace:
                if (
                    Path(existing.directory).resolve() != Path(source.directory).resolve()
                    or existing.version_table != source.version_table
                ):
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
        if source.namespace == _CORE_SOURCE.namespace:
            raise ValueError("the kernel migration namespace is reserved")
        if source.version_table == _CORE_SOURCE.version_table:
            raise ValueError("the kernel version table is reserved")
        _assembly_sources.append(source)
        return True


def registered_migration_sources() -> tuple[MigrationSource, ...]:
    """Assembly sources (registration order) followed by the core source."""
    with _sources_lock:
        return (*_assembly_sources, _CORE_SOURCE)


def _reset_registered_migration_sources_for_tests() -> None:
    global _assembly_sources
    with _sources_lock:
        _assembly_sources = []


def _ensure_version_table(conn: sqlite3.Connection, version_table: str) -> None:
    # The shape matches the historical schema_versions table exactly, so an
    # old database's table is accepted unchanged and a new one is identical.
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {version_table} "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()


def _run_migration_source(conn: sqlite3.Connection, source: MigrationSource) -> None:
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


def _run_migrations(conn: sqlite3.Connection) -> None:
    for source in registered_migration_sources():
        _run_migration_source(conn, source)


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                path = _database_override or database_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                _conn = sqlite3.connect(str(path), timeout=10.0, check_same_thread=False)
                _conn.row_factory = sqlite3.Row
                _conn.execute("PRAGMA foreign_keys = ON")
                _run_migrations(_conn)
    return _conn


def configure_database(path: Path | str | None) -> None:
    """Bind Core to one host-owned SQLite file before repository use.

    Existing callers retain the historical AGENT_BOX_HOME default.  A Server
    process calls this once during lifespan startup so Core and product tables
    share one local database without teaching Core about Server concepts.
    """
    global _conn, _database_override
    target = Path(path).resolve() if path is not None else None
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _database_override = target


def _reset_connection_for_tests() -> None:
    global _conn, _database_override
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _database_override = None
