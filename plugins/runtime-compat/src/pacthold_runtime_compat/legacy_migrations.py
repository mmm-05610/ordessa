"""Namespaced registration of the sealed historical migration chain.

specs/010 T009 (FR-011): the historical agent-box migrations ``001_init.sql``
through ``009_execution_finalization.sql`` live in this distribution,
byte-for-byte unchanged, and are applied through the kernel's migration
runner as one *named namespace* with its own version-record table — the
original ``schema_versions`` table.  Rows recorded by an old database are
never deleted or renumbered: the legacy chain reads exactly the table it
wrote, and the kernel's neutral schema keeps its own independent
``core_schema_versions`` namespace.
"""
from __future__ import annotations

from pathlib import Path

from pacthold.work_core import db

LEGACY_MIGRATION_NAMESPACE = "agent_box_legacy"
#: The historical version-record table name, unchanged.
LEGACY_SCHEMA_VERSION_TABLE = "schema_versions"

#: SQL directory shipped inside this distribution (sealed migration set).
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def legacy_migration_source() -> db.MigrationSource:
    return db.MigrationSource(
        namespace=LEGACY_MIGRATION_NAMESPACE,
        directory=MIGRATIONS_DIR,
        version_table=LEGACY_SCHEMA_VERSION_TABLE,
    )


def register_legacy_migrations() -> bool:
    """Register the legacy SQL chain with the kernel runner (idempotent).

    Returns ``True`` when the registration changed runner state and
    ``False`` when the identical source was already registered.  A product
    process must call this before the first Core database connection so the
    chain applies from a clean slate (a bare-core database connected first
    cannot retroactively run the historical ALTER chain — see the assembly
    guards).
    """
    return db.register_migration_source(legacy_migration_source())


__all__ = [
    "LEGACY_MIGRATION_NAMESPACE",
    "LEGACY_SCHEMA_VERSION_TABLE",
    "MIGRATIONS_DIR",
    "legacy_migration_source",
    "register_legacy_migrations",
]
