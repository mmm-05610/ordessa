"""Explicit product registration of the sealed historical migration chain.

specs/026 T006-09 / compat-retirement §3 (``legacy_migrations.py`` row): the
*registration point* of the sealed ``agent_box_legacy`` chain is this product
assembly — the SQL bytes, their order, the namespace, the historical
``schema_versions`` version-record table and the table identities are all
unchanged.  ``pacthold_runtime_compat.legacy_migrations`` stays the thin
carrier of the sealed facts (the sealed SQL directory, the namespace and the
version table); the registration *action* lives here and happens only when a
product assembly path calls :func:`register_sealed_legacy_migrations` —
importing ``pacthold_runtime_compat`` (or this package) registers nothing.
"""
from __future__ import annotations


def register_sealed_legacy_migrations() -> bool:
    """Register the sealed historical chain on the kernel migration runner.

    The product composition must call this before the first Core database
    connection: the runner applies registered namespaces when the connection
    opens, and a bare-core database connected first cannot retroactively
    receive the historical ALTER chain (the assembly guards fail closed).

    Returns ``True`` when the registration changed runner state and ``False``
    when the identical source was already registered — registration is
    idempotent so a product may assemble twice.
    """
    from pacthold.work_core import db
    from pacthold_runtime_compat.legacy_migrations import legacy_migration_source

    return db.register_migration_source(legacy_migration_source())


__all__ = ["register_sealed_legacy_migrations"]
