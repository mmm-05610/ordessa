"""specs/026 T006-09: the sealed legacy chain registers only by explicit
product assembly.

Positive: after the product assembly — the explicit entry
``ordessa_server_product.sealed_migrations.register_sealed_legacy_migrations()``
or any default/native composition path — the sealed ``agent_box_legacy``
chain is registered on the kernel runner under its original version-record
table, and the nine sealed SQL files are byte-identical (pinned sha256
digests, application-name order).

Negative: importing ``pacthold_runtime_compat`` registers nothing.  The
compat distribution stays a thin carrier of the sealed facts (SQL directory,
namespace, version table); registration is never an import side effect.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys

import pytest

from pacthold.work_core import db
from pacthold_runtime_compat.legacy_migrations import (
    LEGACY_MIGRATION_NAMESPACE,
    LEGACY_SCHEMA_VERSION_TABLE,
    MIGRATIONS_DIR,
)

from ordessa_server_product.composition import create_composition
from ordessa_server_product.sealed_migrations import (
    register_sealed_legacy_migrations,
)

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
    snapshot = db.registered_migration_sources()[:-1]  # assembly sources only
    db._reset_registered_migration_sources_for_tests()
    try:
        yield
    finally:
        db._reset_registered_migration_sources_for_tests()
        for source in snapshot:
            db.register_migration_source(source)


def _assembly_sources():
    return db.registered_migration_sources()[:-1]


def test_importing_runtime_compat_registers_nothing(isolated_runner_state):
    """Counterexample: no import of the compat distribution may register the
    sealed chain.  Run in a subprocess because import side effects execute
    once per process — this process may already hold registrations."""
    code = (
        "import pacthold_runtime_compat, pacthold_runtime_compat.legacy_migrations, "
        "pacthold_runtime_compat.bootstrap, pacthold_runtime_compat.storage; "
        "from pacthold.work_core import db; "
        "print([s.namespace for s in db.registered_migration_sources()])"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str([db.CORE_MIGRATION_NAMESPACE]), completed.stdout


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
    from pacthold_runtime_compat.storage import Database

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
    assert plugins, "the default product selection is non-empty"
    assert [source.namespace for source in _assembly_sources()] == [
        LEGACY_MIGRATION_NAMESPACE
    ]


def test_native_assembly_registers_the_sealed_chain_before_runtime_build(
    isolated_runner_state, tmp_path, monkeypatch
):
    """The native composition path registers at assembly time, before the
    runtime builder is reached.  Seam control: the builder is replaced by a
    sentinel so no runtime is started and nothing past the registration
    seam executes."""
    import ordessa_server_compat.composition as compat_composition
    import ordessa_server_product.platform_secrets as platform_secrets

    sentinel = RuntimeError("sealed-chain-seam")

    def _fail_builder(*args, **kwargs):
        raise sentinel

    monkeypatch.setattr(
        compat_composition, "build_runtime_from_native_adapter", _fail_builder
    )
    monkeypatch.setattr(platform_secrets, "product_secret_store", lambda data_root: object())

    product = create_composition()
    with pytest.raises(RuntimeError) as excinfo:
        product.native_runtime(
            tmp_path / "data-root",
            plugin_root=tmp_path,
            harness_id="pi",
            adapter_command="true",
        )
    assert excinfo.value is sentinel, "the sentinel must surface, not an earlier failure"
    assert [source.namespace for source in _assembly_sources()] == [
        LEGACY_MIGRATION_NAMESPACE
    ]
