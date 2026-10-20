"""026 T006-01 (second half): the host never configures the global core_db.

The last host site that bound the ``pacthold.work_core.db`` process-global
singleton was ``LegacyCoreBinding`` (``configure_database(path)`` +
``get_conn()`` on start, ``configure_database(None)`` on stop). It is now an
INSTANCE connection holder: ``connect()`` opens the round's own ``sqlite3``
connection to the server-owned legacy database file, ``release()`` closes it,
and no module-level state is written anywhere in the host — so the default
product composition's build → start → wire call → stop → restart runs with
``core_db._database_override is None`` and ``core_db._conn is None`` the whole
way through (the module itself is retired by order 012; this slice only
severs the host from it).

The old library's remaining build-time READ need (the historical-root
preflight) goes through ``registered_migration_sources()`` — a pure
registration read that never opens a connection — which is why these rounds
leave the global byte-untouched while historical roots still refuse without
their sealed provider (guarded in ``test_platform_t023_legacy_data.py``).

Counterexample face: a monkeypatched call counter on BOTH ``configure_database``
and ``get_conn`` must read zero for every startup path — default product and
explicit compatibility selection alike. 0 real model calls, 0 credentials:
every database is a ``tmp_path`` file.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from ordessa_server.composition.runtime import build_runtime
from ordessa_server.composition.runtime import LegacyCoreBinding
from ordessa_interfaces.http import create_app
import sys
import importlib.abc
from ordessa_infrastructure.database import migrations as migration_runner
from ordessa_server.bootstrap.migrations import source_selection


def _global_untouched() -> bool:
    """The process-global kernel DB: never configured, never opened."""
    return not any(name == "pacthold" or name.startswith("pacthold.") for name in sys.modules)


def _wire_hello(runtime) -> None:
    """One controlled wire call against the running composition."""
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    answer = client.post(
        "/wire/v1/server.hello",
        headers={"Authorization": f"Bearer {runtime.token}"},
        json={"jsonrpc": "2.0", "id": "t006-01", "method": "server.hello",
              "params": {"clientVersions": ["wire/1"],
                         "clientPresentationSupports": []}},
    )
    assert answer.status_code == 200, answer.text
    assert "result" in answer.json(), answer.json()


def test_full_default_product_round_never_configures_or_opens_the_global(
        tmp_path, tmp_agent_box_home):
    """Positive face, whole lifecycle: build → start → wire call → stop (and
    one restart round) with the global singleton None at every observation
    point, while the round's OWN legacy connection rides the server-owned
    legacy database file."""
    runtime = build_runtime(tmp_path / "round")
    try:
        assert runtime.legacy_core is not None
        assert runtime.objects.root == runtime.data_root / "objects" / "sha256"
        # composition holds the path only; the connection opens at start()
        with pytest.raises(RuntimeError, match="LEGACY_CORE_NOT_CONNECTED"):
            runtime.legacy_core.connection
        assert _global_untouched()

        runtime.start()
        assert _global_untouched()
        # instance-side fact: the round's own connection IS on the legacy file
        row = runtime.legacy_core.connection.execute(
            "PRAGMA database_list").fetchone()
        assert Path(row[2]).resolve() == runtime.database.path.resolve()
        # ...and the file carries the applied chain's table (the product
        # DatabasePort migrated it; the binding runs no SQL chain itself)
        assert runtime.legacy_core.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='core_works'").fetchone() is not None

        _wire_hello(runtime)
        assert _global_untouched()
    finally:
        runtime.stop()
    assert _global_untouched()
    # stop released the round's OWN connection, typed
    with pytest.raises(RuntimeError, match="LEGACY_CORE_NOT_CONNECTED"):
        runtime.legacy_core.connection

    # a restart round re-opens the instance connection only — still zero-touch
    runtime.start()
    try:
        assert _global_untouched()
        row = runtime.legacy_core.connection.execute(
            "PRAGMA database_list").fetchone()
        assert Path(row[2]).resolve() == runtime.database.path.resolve()
        _wire_hello(runtime)
        assert _global_untouched()
    finally:
        runtime.stop()
    assert _global_untouched()


def _minimal_legacy_database(path: Path) -> None:
    """The bytes an old Server left, minimal but real-shaped: the historical
    ``schema_versions`` ledger and one ``core_works`` row (the shape the
    sealed chain builds; see the T023 synthesizer for the full nine)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE schema_versions ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
        conn.execute("INSERT INTO schema_versions (version) VALUES (1)")
        conn.execute(
            "CREATE TABLE core_works ("
            "id TEXT PRIMARY KEY, objective TEXT, lifecycle TEXT, "
            "created_at TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO core_works (id, objective, lifecycle, "
            "created_at, updated_at) VALUES "
            "('work-legacy-0001', 'objective sealed before the convergence', "
            "'active', '2026-01-01 00:00:00', '2026-01-01 00:00:00')")
        conn.commit()
    finally:
        conn.close()


def test_legacy_core_binding_instance_connection_reads_the_old_database(
        tmp_path, tmp_agent_box_home):
    """Positive face, unit level: ``connect()`` opens the binding's OWN
    connection that reads the minimal legacy fixture's tables — without any
    module-global configure/open (both stay None), and ``release()`` really
    closes that connection.

    Registration state is reset for the duration (T023's pattern) so this
    gate stays unit-scoped: the minimal fixture proves the CONNECTION reads
    the old library, while the full-chain convergence on real roots is the
    T023 file's business. Restored in ``finally`` for the rest of the suite.
    """
    database_path = tmp_path / "state" / "agentbox.sqlite"
    _minimal_legacy_database(database_path)
    previous = migration_runner.registered_migration_sources(registry=source_selection.registry)[:-1]
    setattr(source_selection, "registry", source_selection.create_migration_registry())
    try:
        _read_the_old_database_through_the_binding(database_path)
    finally:
        setattr(source_selection, "registry", source_selection.create_migration_registry())
        for source in previous:
            migration_runner.register_migration_source(source, registry=source_selection.registry)
    assert _global_untouched()


def _read_the_old_database_through_the_binding(database_path: Path) -> None:
    binding = LegacyCoreBinding(database_path)
    assert binding.database_path == database_path
    binding.connect()
    try:
        # its OWN connection, resolving to the fixture file (not the global,
        # not a home-default path)
        row = binding.connection.execute("PRAGMA database_list").fetchone()
        assert Path(row[2]).resolve() == database_path.resolve()
        historical = binding.connection.execute(
            "SELECT id, objective, lifecycle FROM core_works "
            "WHERE id = 'work-legacy-0001'").fetchone()
        assert tuple(historical) == (
            "work-legacy-0001", "objective sealed before the convergence",
            "active")
        assert [r[0] for r in binding.connection.execute(
            "SELECT version FROM schema_versions ORDER BY version")] == [1]
        # connect is idempotent within a round: the SAME connection, no second
        conn = binding.connection
        binding.connect()
        assert binding.connection is conn
        # the module global was never configured and never opened
        assert _global_untouched()
    finally:
        binding.release()

    # the round's own connection is really closed (typed refusals both ways)
    with pytest.raises(RuntimeError, match="LEGACY_CORE_NOT_CONNECTED"):
        binding.connection
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    binding.release()  # idempotent


def test_no_startup_path_configures_or_opens_the_global_kernel_db(
        tmp_path, tmp_agent_box_home, monkeypatch):
    """Both complete startup arms must reject any attempt to load Kernel.

    The historical DB module is physically retired; no substitute module is
    installed to fabricate a callable global singleton for this negative.
    """
    attempted_imports = []
    class RefuseKernel(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'pacthold' or fullname.startswith('pacthold.'):
                attempted_imports.append(fullname)
                raise AssertionError('retired Kernel import: '+fullname)
    monkeypatch.setattr(sys, 'meta_path', [RefuseKernel(), *sys.meta_path])
    assert _global_untouched(), 'Kernel was already imported before actual startup'

    # path 1: the default product composition (the widest startup path)
    runtime = build_runtime(tmp_path / "default-round")
    try:
        runtime.start()
        _wire_hello(runtime)
    finally:
        runtime.stop()
    assert _global_untouched()

    # path 2: an explicit compatibility selection over the product database
    # (selected_product=False branch — a different composition arm, same host)
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition
    from ordessa_server.bootstrap.migrations.legacy_source import register_legacy_migrations
    from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition
    product = create_composition()
    from ordessa_server.bootstrap.storage.product_database import Database
    product.bind_host_execution_ports(migration_registrar=register_legacy_migrations,
                                     runtime_assembler=assemble_runtime_composition, database_factory=Database)
    explicit = build_runtime(
        tmp_path / "explicit-round",
        server_plugins=())
    try:
        explicit.start()
        assert explicit.legacy_core is not None
    finally:
        explicit.stop()
    assert _global_untouched()

    assert attempted_imports == [], 'a startup path tried to reach retired Kernel global DB'
