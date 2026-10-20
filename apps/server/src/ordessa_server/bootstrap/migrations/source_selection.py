"""Product historical SQL selection; technical registry/runner are Infrastructure.

No SQL execution, database holder or import-time legacy registration here.
The trailing source preserves its historical namespace/table and sealed bytes.
"""
from pathlib import Path
from ordessa_infrastructure.database.migrations import MigrationRegistry, MigrationSource

HISTORICAL_CORE_NAMESPACE = 'pacthold_core'
HISTORICAL_CORE_VERSION_TABLE = 'core_schema_versions'

def create_migration_registry():
    return MigrationRegistry(trailing_sources=(MigrationSource(
        HISTORICAL_CORE_NAMESPACE, Path(__file__).resolve().parent / 'historical_core',
        HISTORICAL_CORE_VERSION_TABLE),))

registry = create_migration_registry()
