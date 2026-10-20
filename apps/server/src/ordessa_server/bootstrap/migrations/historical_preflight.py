"""Historical-root preflight without selecting any online execution owner.

The sole original check is shared by data-root validation and explicit legacy
runtime construction. It reads SQLite immutably and never registers/migrates a
schema, creates a store, acquires an Environment or constructs Unit services.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from ordessa_server.composition.root_ownership import DataRootPathUnsafeError


class LegacyMigrationProviderMissingError(RuntimeError):
    """A historical data root cannot be opened without its sealed SQL chain."""

    code = "LEGACY_MIGRATION_PROVIDER_MISSING"

def _reject_unsafe_data_root_links(root: Path) -> None:
    state = root / "state"
    database = state / "agentbox.sqlite"
    core_store = state / "core.sqlite"
    for path in (
        root,
        state,
        database,
        core_store,
        state / "core.sqlite-wal",
        state / "core.sqlite-shm",
        state / "agentbox.sqlite-wal",
        state / "agentbox.sqlite-shm",
    ):
        if path.is_symlink():
            raise DataRootPathUnsafeError(
                "DATA_ROOT_PATH_UNSAFE: Server state/database paths cannot be symlinks"
            )

def _require_legacy_provider_for_historical_root(root: Path) -> None:
    """Read the old database before marker, schema, or token writes.

    The legacy ledger itself marks a root that needs the historical chain.
    Inspecting via SQLite's immutable read-only URI does not create a missing
    database, lock file, or WAL sidecar. A fresh root has no database yet.
    """
    _reject_unsafe_data_root_links(root)
    database_path = root / "state" / "agentbox.sqlite"
    if not database_path.is_file():
        return
    uri = database_path.resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        historical = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('schema_versions', 'core_works') LIMIT 1"
        ).fetchone() is not None
    # Immutable reads intentionally ignore WAL. If one exists, do not infer
    # "fresh" from the main file alone and permit an unregistered migration
    # provider to touch an ambiguous historical root.
    historical = historical or database_path.with_name(database_path.name + "-wal").exists()
    if not historical:
        return
    from ordessa_server.bootstrap.migrations.legacy_source import (
        LEGACY_MIGRATION_NAMESPACE, legacy_migration_source,
    )
    from ordessa_infrastructure.database import migrations as migration_runner
    from ordessa_server.bootstrap.migrations import source_selection
    # 026 T006-01: the registry read below is the ONLY fact this preflight
    # still takes from `pacthold.work_core.db`, and it is a pure registration
    # read — `registered_migration_sources()` returns the assembled sources
    # under their own lock and never touches `_conn`/`configure_database`
    # (verified: no connection, no file, no AGENT_BOX_HOME resolution beyond
    # the module-import-time path computation). The host must not OPEN the
    # old database here; that stays the product DatabasePort's business.
    try:
        expected = legacy_migration_source()
    except RuntimeError as exc:
        raise LegacyMigrationProviderMissingError(str(exc)) from exc
    present = any(
        source.namespace == LEGACY_MIGRATION_NAMESPACE
        and source.version_table == expected.version_table
        and source.directory.resolve() == expected.directory.resolve()
        for source in migration_runner.registered_migration_sources(registry=source_selection.registry)
    )
    if not present:
        raise LegacyMigrationProviderMissingError(
            "LEGACY_MIGRATION_PROVIDER_MISSING: historical data root requires "
            "the agent_box_legacy migration source before startup"
        )
