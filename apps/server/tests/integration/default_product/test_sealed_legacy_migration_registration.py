"""docs/implementation/specifications/026 T006-09: the sealed legacy chain registers only by explicit
product assembly.

Positive: after the product assembly — the explicit entry
``ordessa_server.bootstrap.migrations.legacy_source.register_legacy_migrations()``
or any default/native composition path — the sealed ``agent_box_legacy``
chain is registered on the kernel runner under its original version-record
table, and the nine sealed SQL files are byte-identical (pinned sha256
digests, application-name order).

Negative: importing the Server migration provider registers nothing.  The
Server bootstrap owns the sealed facts (SQL directory,
namespace, version table); registration is never an import side effect.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from ordessa_infrastructure.database import migrations as db
from ordessa_server.bootstrap.migrations import source_selection
from ordessa_server.bootstrap.migrations.legacy_source import LEGACY_MIGRATION_NAMESPACE, LEGACY_SCHEMA_VERSION_TABLE, MIGRATIONS_DIR

from ordessa_server_product.composition import create_composition as unbound_composition
from ordessa_server.bootstrap.migrations.legacy_source import register_legacy_migrations as register_sealed_legacy_migrations
from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition

def create_composition():
    product = unbound_composition()
    from ordessa_server.bootstrap.storage.product_database import Database
    product.bind_host_execution_ports(migration_registrar=register_sealed_legacy_migrations,
                                     runtime_assembler=assemble_runtime_composition, database_factory=Database)
    from ordessa_server.composition.configuration.product_selection import bind_product_harness_effects
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    product.bind_harness_registry(capture_selected_harness_catalog().registry)
    return bind_product_harness_effects(product)

#: The nine sealed migration files with the sha256 digests of their exact
#: bytes (compat-retirement §1.7: sealed SQL keeps its bytes, order,
#: namespace, version table and table identities).  Any byte change to the
#: sealed chain is a data-compatibility break and must fail here first.
SEALED_SQL_DIGESTS = {
    "001_init.sql": "556abd7252c0941d202c87c1b83327107c08f0c812e4839cdc7ca63c5da19c35",
    "002_rename_claude_md_ref.sql": "296727f8c9238f9bd90b25ed70ce85a9850b0052980f4311b67153e9ec56a171",
    "003_work_core.sql": "046286b3669ecfad5097ac5e4348c6823da8681dc6f23eac825ebb0e1476b534",
    "004_minimal_work_core.sql": "1202e06f678c3af55a2b5a05ad8e97d86301ecf04e309cf4950b1c577ba9cd15",
    "005_resource_contract_inputs.sql": "961a19845a60b69fb8c6a9ab915f74ceabb1e85d3f378d6a534b40edb94d6870",
    "006_resource_contract_inputs.sql": "0ac124d4bfcd74d3debd885c7221afea076204b964ed5a3c710ad7066f775b3f",
    "007_resource_observations.sql": "84fcdf3805497f2cce7b81fbf81879cd96631524fd04ae9af655c6342d611c29",
    "008_resource_observation_evidence_metadata.sql": "96f9e8007d30ad27b0441255b9780a02a86d04e7715bb18bd135fd371a512575",
    "009_execution_finalization.sql": "d66c4de7df8216d24028c2c4180ed6bf47ae18018f2853d197b7e2f80ca43e5b",
}


@pytest.fixture
def isolated_runner_state():
    """Snapshot and restore the process-global assembly registrations.

    The kernel runner keeps registrations for the whole process; each test
    here starts from an empty assembly list and puts the previous state back
    so suite order can never fake or hide a registration.
    """
    snapshot = db.registered_migration_sources(registry=source_selection.registry)[:-1]  # assembly sources only
    setattr(source_selection, "registry", source_selection.create_migration_registry())
    try:
        yield
    finally:
        setattr(source_selection, "registry", source_selection.create_migration_registry())
        for source in snapshot:
            db.register_migration_source(source, registry=source_selection.registry)


def _assembly_sources():
    return db.registered_migration_sources(registry=source_selection.registry)[:-1]


def test_importing_runtime_compat_registers_nothing(isolated_runner_state):
    """Counterexample: no import of the compat distribution may register the
    sealed chain.  Run in a subprocess because import side effects execute
    once per process — this process may already hold registrations."""
    code = (
        "import ordessa_server.bootstrap.migrations.legacy_source, "
        "ordessa_units.assembly.runtime.assembler, "
        "ordessa_units.assembly.runtime.coordinator; "
        "from ordessa_infrastructure.database import migrations as db; "
        "from ordessa_server.bootstrap.migrations import source_selection; "
        "print([s.namespace for s in db.registered_migration_sources(registry=source_selection.registry)])"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str([source_selection.HISTORICAL_CORE_NAMESPACE]), completed.stdout


def test_explicit_product_registration_pins_namespace_and_version_table(
    isolated_runner_state,
):
    assert _assembly_sources() == (), "precondition: runner starts clean"
    assert register_sealed_legacy_migrations() is True
    sources = _assembly_sources()
    assert [source.namespace for source in sources] == [LEGACY_MIGRATION_NAMESPACE]
    assert sources[0].version_table == LEGACY_SCHEMA_VERSION_TABLE == "schema_versions"
    assert sources[0].directory == MIGRATIONS_DIR
    # idempotent re-assembly: no duplicate, runner state unchanged
    assert register_sealed_legacy_migrations() is False
    assert len(_assembly_sources()) == 1


def test_registered_sealed_chain_matches_the_nine_sql_digests(isolated_runner_state):
    register_sealed_legacy_migrations()
    source = _assembly_sources()[0]
    files = sorted(path for path in source.directory.iterdir() if path.suffix == ".sql")
    assert len(files) == 9
    assert [path.name for path in files] == sorted(SEALED_SQL_DIGESTS)
    for path in files:
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest() == SEALED_SQL_DIGESTS[path.name]
        ), f"sealed migration bytes changed: {path.name}"


def test_default_product_composition_registers_the_sealed_chain(
    isolated_runner_state,
):
    from ordessa_server.bootstrap.storage.product_database import Database

    product = create_composition()
    # the DB-provider entry runs at composition time, before any connection
    assert product.database_type() is Database
    assert [source.namespace for source in _assembly_sources()] == [
        LEGACY_MIGRATION_NAMESPACE
    ]
    # re-assembly stays idempotent on the same path
    product.database_type()
    assert len(_assembly_sources()) == 1


def test_default_plugin_selection_registers_the_sealed_chain(isolated_runner_state):
    product = create_composition()
    plugins = product.default_plugins()
    assert plugins == (), "no unselected or legacy plugin may activate by default"
    assert [source.namespace for source in _assembly_sources()] == [
        LEGACY_MIGRATION_NAMESPACE
    ]


