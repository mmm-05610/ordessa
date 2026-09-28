"""specs/010 T009 migration-namespace mechanism (kernel side).

The namespaced runner in :mod:`pacthold.work_core.db` keeps the neutral kernel
schema in its own version-record table ``core_schema_versions`` and applies
registered assembly sources *before* it, in registration order.  The data
rule (data-model.md Recovery/Historical): new migrations live in an
independent namespace and must never be skipped by the old
``schema_versions`` MAX(version); an old database is never treated as empty.

These tests exercise the mechanism with synthetic SQL sources only — the
kernel side never references the compatibility assembly (direction guard in
``test_t009_direction_guard.py``); the real sealed chain is covered by
``plugins/runtime-compat/tests/test_legacy_migration_chain.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pacthold.work_core import db
from pacthold.work_core.db import (
    CORE_MIGRATION_NAMESPACE,
    CORE_SCHEMA_VERSION_TABLE,
    MigrationSource,
    configure_database,
    get_conn,
    register_migration_source,
    registered_migration_sources,
)

CORE_TABLES = {
    "core_works",
    "core_executions",
    "core_execution_refs",
    "core_events",
    "core_dispatches",
    "core_resource_observations",
    "core_execution_finalizations",
}


@pytest.fixture
def isolated_db(tmp_path):
    """One temp database file, empty migration registry, restored after use."""
    path = tmp_path / "ns-test.db"
    db._reset_registered_migration_sources_for_tests()
    configure_database(path)
    get_conn()  # force migration
    yield path
    db._reset_connection_for_tests()
    configure_database(None)
    db._reset_registered_migration_sources_for_tests()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _versions(conn: sqlite3.Connection, table: str) -> list[int]:
    return [row[0] for row in conn.execute(f"SELECT version FROM {table} ORDER BY version")]


def test_bare_core_database_gets_only_the_neutral_namespace(isolated_db):
    conn = get_conn()
    tables = _table_names(conn)
    assert CORE_TABLES <= tables
    assert CORE_SCHEMA_VERSION_TABLE in tables
    assert _versions(conn, CORE_SCHEMA_VERSION_TABLE) == [1]
    # The historical table is *not* created by the kernel — the neutral copy
    # never touches the old namespace.
    assert "schema_versions" not in tables


def test_new_core_namespace_is_not_skipped_by_old_schema_versions_max(tmp_path):
    """The data-model rule, directly: an old database whose schema_versions
    already records 1..9 must still receive the neutral kernel schema."""
    path = tmp_path / "old.db"
    seed = sqlite3.connect(path)
    seed.execute(
        "CREATE TABLE schema_versions "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    seed.executemany("INSERT INTO schema_versions (version) VALUES (?)", [(v,) for v in range(1, 10)])
    seed.commit()
    seed.close()

    db._reset_registered_migration_sources_for_tests()
    configure_database(path)
    try:
        conn = get_conn()
        assert CORE_TABLES <= _table_names(conn)
        assert _versions(conn, CORE_SCHEMA_VERSION_TABLE) == [1]
        # old rows stand, unmodified:
        assert _versions(conn, "schema_versions") == list(range(1, 10))
    finally:
        db._reset_connection_for_tests()
        configure_database(None)
        db._reset_registered_migration_sources_for_tests()


def test_second_startup_is_a_no_op(isolated_db):
    before_tables = _table_names(get_conn())
    before_rows = _versions(get_conn(), CORE_SCHEMA_VERSION_TABLE)
    db._reset_connection_for_tests()
    configure_database(isolated_db)
    conn = get_conn()
    assert _table_names(conn) == before_tables
    assert _versions(conn, CORE_SCHEMA_VERSION_TABLE) == before_rows == [1]


def _write_source(directory: Path, name: str, version: int, marker: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{version:03d}_{name}.sql").write_text(
        "CREATE TABLE IF NOT EXISTS migration_order (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        f"who TEXT NOT NULL);\nINSERT INTO migration_order (who) VALUES ('{marker}');\n",
        encoding="utf-8",
    )


def test_assembly_sources_run_before_core_in_registration_order(tmp_path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    _write_source(a_dir, "alpha", 1, "a")
    _write_source(b_dir, "beta", 1, "b")
    db._reset_registered_migration_sources_for_tests()
    configure_database(tmp_path / "order.db")
    try:
        assert register_migration_source(
            MigrationSource("alpha_ns", a_dir, "alpha_versions")
        ) is True
        assert register_migration_source(
            MigrationSource("beta_ns", b_dir, "beta_versions")
        ) is True
        sources = registered_migration_sources()
        assert [s.namespace for s in sources] == ["alpha_ns", "beta_ns", CORE_MIGRATION_NAMESPACE]
        conn = get_conn()
        order = [row[0] for row in conn.execute("SELECT who FROM migration_order ORDER BY seq")]
        assert order == ["a", "b"], "assembly chain must be applied before the core source"
        assert CORE_TABLES <= _table_names(conn), "the core source still runs last"
    finally:
        db._reset_connection_for_tests()
        configure_database(None)
        db._reset_registered_migration_sources_for_tests()


def test_assembly_source_respects_its_own_recorded_versions(tmp_path):
    """An existing version table with a high MAX skips the same-namespace
    files (old-chain semantics kept) — and that skipping is confined to that
    namespace, never leaking into the core table (proved in the dedicated
    test above)."""
    src_dir = tmp_path / "legacy_like"
    _write_source(src_dir, "one", 1, "a")
    _write_source(src_dir, "two", 2, "b")
    path = tmp_path / "partial.db"
    seed = sqlite3.connect(path)
    seed.execute(
        "CREATE TABLE legacy_versions "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    seed.execute("INSERT INTO legacy_versions (version) VALUES (2)")
    seed.commit()
    seed.close()

    db._reset_registered_migration_sources_for_tests()
    configure_database(path)
    try:
        register_migration_source(MigrationSource("legacy_like", src_dir, "legacy_versions"))
        conn = get_conn()
        # versions 1 and 2 are both <= the recorded MAX(2): nothing re-applied.
        assert "migration_order" not in _table_names(conn)
        assert _versions(conn, "legacy_versions") == [2]
        # The core namespace is independent and applied anyway:
        assert _versions(conn, CORE_SCHEMA_VERSION_TABLE) == [1]
    finally:
        db._reset_connection_for_tests()
        configure_database(None)
        db._reset_registered_migration_sources_for_tests()


def test_re_registration_of_an_identical_source_is_idempotent(tmp_path):
    _write_source(tmp_path / "dup", "one", 1, "a")
    db._reset_registered_migration_sources_for_tests()
    try:
        source = MigrationSource("dup_ns", tmp_path / "dup", "dup_versions")
        assert register_migration_source(source) is True
        assert register_migration_source(source) is False
        assert len(registered_migration_sources()) == 2  # dup_ns + core
    finally:
        db._reset_registered_migration_sources_for_tests()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"namespace": "Bad NS", "version_table": "ok_versions"}, "invalid migration namespace"),
        ({"namespace": "ok_ns", "version_table": "bad-table"}, "invalid version table"),
        ({"namespace": CORE_MIGRATION_NAMESPACE, "version_table": "own_versions"}, "kernel migration namespace is reserved"),
        ({"namespace": "product_ns", "version_table": CORE_SCHEMA_VERSION_TABLE}, "kernel version table is reserved"),
    ],
)
def test_registration_rejects_illegal_sources(tmp_path, kwargs, match):
    directory = tmp_path / "srcdir"
    directory.mkdir()
    source = MigrationSource(directory=directory, **kwargs)
    with pytest.raises(ValueError, match=match):
        register_migration_source(source)


def test_namespace_reuse_with_a_different_directory_fails_closed(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    db._reset_registered_migration_sources_for_tests()
    try:
        register_migration_source(MigrationSource("clash_ns", one, "clash_versions"))
        with pytest.raises(ValueError, match="already registered with a different source"):
            register_migration_source(MigrationSource("clash_ns", two, "clash_versions"))
        with pytest.raises(ValueError, match="already owned by namespace"):
            register_migration_source(MigrationSource("other_ns", two, "clash_versions"))
    finally:
        db._reset_registered_migration_sources_for_tests()
