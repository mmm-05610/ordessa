"""Namespaced registration of the sealed historical migration chain.

docs/implementation/specifications/010 T009 (FR-011): the historical agent-box migrations ``001_init.sql``
through ``009_execution_finalization.sql`` live in this distribution,
byte-for-byte unchanged, and are applied through the Server historical migration
runner as one *named namespace* with its own version-record table — the
original ``schema_versions`` table.  Rows recorded by an old database are
never deleted or renumbered: the legacy chain reads exactly the table it
wrote, and the kernel's neutral schema keeps its own independent
``core_schema_versions`` namespace.
"""
from __future__ import annotations

from pathlib import Path

from ordessa_infrastructure.database.migrations import MigrationSource, register_migration_source
from . import source_selection

LEGACY_MIGRATION_NAMESPACE = "agent_box_legacy"
#: The historical version-record table name, unchanged.
LEGACY_SCHEMA_VERSION_TABLE = "schema_versions"

#: SQL directory shipped inside this distribution (sealed migration set).
MIGRATIONS_DIR = Path(__file__).resolve().parent / "agent_box_legacy"


def legacy_migration_source() -> MigrationSource:
    if not MIGRATIONS_DIR.is_dir() or any(not (MIGRATIONS_DIR / name).is_file() for name in (
        "001_init.sql", "002_rename_claude_md_ref.sql", "003_work_core.sql",
        "004_minimal_work_core.sql", "005_resource_contract_inputs.sql",
        "006_resource_contract_inputs.sql", "007_resource_observations.sql",
        "008_resource_observation_evidence_metadata.sql", "009_execution_finalization.sql",
    )):
        raise RuntimeError("LEGACY_MIGRATION_PROVIDER_MISSING: sealed SQL resources unavailable")
    return MigrationSource(
        namespace=LEGACY_MIGRATION_NAMESPACE,
        directory=MIGRATIONS_DIR,
        version_table=LEGACY_SCHEMA_VERSION_TABLE,
    )


def register_legacy_migrations() -> bool:
    """Register the legacy SQL chain with the Server historical runner (idempotent).

    Returns ``True`` when the registration changed runner state and
    ``False`` when the identical source was already registered.  A product
    process must call this before the first Core database connection so the
    chain applies from a clean slate (a bare-core database connected first
    cannot retroactively run the historical ALTER chain — see the assembly
    guards).
    """
    return register_migration_source(legacy_migration_source(), registry=source_selection.registry)


__all__ = [
    "LEGACY_MIGRATION_NAMESPACE",
    "LEGACY_SCHEMA_VERSION_TABLE",
    "MIGRATIONS_DIR",
    "legacy_migration_source",
    "register_legacy_migrations",
]
