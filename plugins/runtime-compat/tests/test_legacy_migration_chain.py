"""specs/010 T009 sealed legacy chain: registration, dual paths, old-DB rules.

Covers the acceptance surfaces the kernel side must not assert (they need the
sealed SQL itself):

* ``register_legacy_migrations()`` registers the sealed chain as one named
  namespace on its original ``schema_versions`` table (idempotent, ordered);
* a product database gets the exact historical chain plus the independent
  ``core_schema_versions`` record, and a second startup is a no-op;
* dual-path equivalence: the core_* table structures a bare kernel database
  builds from ``001_core_schema.sql`` are identical to the ones the assembled
  historical chain (004→009) produces (the promise in the neutral file's
  header; this is its proof);
* an old database is never re-run as an empty one, and a bare-core database
  cannot retroactively receive the historical ALTER chain — assembly must
  register before the first connection.
"""
from __future__ import annotations

import sqlite3

import pytest

from pacthold.work_core import db
from pacthold_runtime_compat import legacy_migrations
from pacthold_runtime_compat.legacy_migrations import (
    LEGACY_MIGRATION_NAMESPACE,
    LEGACY_SCHEMA_VERSION_TABLE,
    MIGRATIONS_DIR,
    register_legacy_migrations,
)

CANONICAL_CORE_TABLES = [
    "core_dispatches",
    "core_events",
    "core_execution_finalizations",
    "core_execution_refs",
    "core_executions",
    "core_resource_observations",
    "core_works",
]


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _fresh_db_path(tmp_path, name):
    # configure the module-global runner to a brand-new file and force the
    # built-in neutral source (plus any registered sources) to apply.
    path = tmp_path / name
    db.configure_database(path)
    conn = db.get_conn()
    real_path = str(path)
    db._reset_connection_for_tests()
    return real_path


def _table_structure(conn: sqlite3.Connection, table: str) -> dict:
    """Semantic structure snapshot: columns (ordered) + indexes + index cols."""
    columns = [
        tuple(row)
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        )
    ]
    indexes = []
    for row in conn.execute(f"PRAGMA index_list({table})"):
        seq, name, unique, origin, partial = row[0], row[1], row[2], row[3], row[4]
        if name.startswith("sqlite_autoindex"):
            # autoindexes from UNIQUE/PK constraints: keep the covered columns
            cols = [c[2] for c in conn.execute(f"PRAGMA index_info({name})")]
            indexes.append((name, unique, origin, tuple(cols)))
        else:
            cols = [c[2] for c in conn.execute(f"PRAGMA index_info({name})")]
            indexes.append((name, unique, origin, tuple(cols)))
    return {"columns": columns, "indexes": sorted(indexes, key=lambda i: str(i))}


def test_registration_namespace_identity_and_idempotence(tmp_agent_box_home):
    assert LEGACY_MIGRATION_NAMESPACE == "agent_box_legacy"
    assert LEGACY_SCHEMA_VERSION_TABLE == "schema_versions"
    assert MIGRATIONS_DIR.name == "migrations"
    sources = legacy_migrations.legacy_migration_source()
    assert register_legacy_migrations() is True
    again = register_legacy_migrations()
    assert again is False, "product assembly may register the chain twice; state is unchanged"
    registered = db.registered_migration_sources()
    assert [s.namespace for s in registered] == [
        LEGACY_MIGRATION_NAMESPACE,
        db.CORE_MIGRATION_NAMESPACE,
    ]
    assert registered[0].version_table == "schema_versions"
    assert registered[-1].version_table == db.CORE_SCHEMA_VERSION_TABLE


def test_product_database_runs_the_exact_historical_chain(tmp_agent_box_home):
    register_legacy_migrations()
    path = _fresh_db_path(tmp_agent_box_home, "product.db")
    conn = _conn_for(path)
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_versions ORDER BY version")]
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    core_versions = [r[0] for r in conn.execute(
        f"SELECT version FROM {db.CORE_SCHEMA_VERSION_TABLE} ORDER BY version")]
    assert core_versions == [1], "the neutral copy applies once, in its own namespace"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"profiles", "sessions"} <= tables, "legacy business tables come from the sealed chain"
    assert set(CANONICAL_CORE_TABLES) <= tables


def test_product_database_second_startup_is_a_no_op(tmp_agent_box_home):
    register_legacy_migrations()
    path = _fresh_db_path(tmp_agent_box_home, "twice.db")
    conn = _conn_for(path)
    first = (
        [r[0] for r in conn.execute("SELECT version FROM schema_versions ORDER BY version")],
        [r[0] for r in conn.execute(f"SELECT version FROM {db.CORE_SCHEMA_VERSION_TABLE}")],
    )
    conn.close()
    # second startup: same file, sources still registered, reconnect
    db.configure_database(path)
    conn2 = db.get_conn()
    second = (
        [r[0] for r in conn2.execute("SELECT version FROM schema_versions ORDER BY version")],
        [r[0] for r in conn2.execute(f"SELECT version FROM {db.CORE_SCHEMA_VERSION_TABLE}")],
    )
    assert second == first, "re-running the assembly must not re-apply or renumber"


def test_dual_path_core_table_structures_are_equivalent(tmp_agent_box_home):
    """Bare kernel DB vs assembled historical DB: identical core_* columns
    and constraints (the neutral end-state promise, verified)."""
    db._reset_registered_migration_sources_for_tests()
    bare = _fresh_db_path(tmp_agent_box_home, "bare.db")  # core source only

    register_legacy_migrations()
    assembled = _fresh_db_path(tmp_agent_box_home, "assembled.db")  # 001..009 + core no-op

    bare_conn, assembled_conn = _conn_for(bare), _conn_for(assembled)
    try:
        bare_tables = {r[0] for r in bare_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'core_%'")}
        # the archive table is a documented residue of the historical 006
        # rebuild and exists only on the assembled path; the canonical set
        # itself must match exactly.
        assert bare_tables == set(CANONICAL_CORE_TABLES) | {db.CORE_SCHEMA_VERSION_TABLE}
        for table in CANONICAL_CORE_TABLES:
            assert _table_structure(bare_conn, table) == _table_structure(assembled_conn, table), (
                f"dual-path schema drift on {table}"
            )
    finally:
        bare_conn.close()
        assembled_conn.close()


def test_old_database_is_not_treated_as_empty(tmp_agent_box_home):
    """An upgraded old database keeps its rows and its recorded versions; the
    chain never re-applies against data already on disk."""
    register_legacy_migrations()
    path = _fresh_db_path(tmp_agent_box_home, "old.db")
    conn = _conn_for(path)
    conn.execute(
        "INSERT INTO profiles (name, agent_type) VALUES ('keep-me', 'claude')"
    )
    conn.commit()
    conn.close()

    db.configure_database(path)
    reopened = db.get_conn()
    names = [r[0] for r in reopened.execute("SELECT name FROM profiles")]
    assert names == ["keep-me"], "user rows survive assembly re-open"
    versions = [r[0] for r in reopened.execute("SELECT version FROM schema_versions ORDER BY version")]
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_bare_core_database_cannot_retroactively_assemble(tmp_agent_box_home):
    """Counterexample for the assembly order rule: once a database has been
    created bare-core (final-shape core_* tables), running the historical
    ALTER chain over it fails closed (duplicate column on 006) instead of
    silently producing a hybrid schema."""
    db._reset_registered_migration_sources_for_tests()
    bare = _fresh_db_path(tmp_agent_box_home, "late-assembly.db")
    register_legacy_migrations()
    db.configure_database(bare)
    with pytest.raises(sqlite3.OperationalError):
        db.get_conn()
