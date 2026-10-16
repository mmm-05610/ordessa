from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from ordessa_infrastructure.database import SQLiteOptions, create_connection
from ordessa_infrastructure.database.migrations import (
    MigrationSource, MigrationRegistry, register_migration_source,
    registered_migration_sources, apply_migration_source, apply_registered_migrations,
)


def source(directory, namespace='fixture', table='fixture_versions'):
    return MigrationSource(namespace, directory, table)


def test_explicit_registry_retains_order_trailing_sources_and_idempotence(tmp_path):
    final = source(tmp_path / 'final', 'final', 'final_versions')
    reg = MigrationRegistry(trailing_sources=(final,))
    first = source(tmp_path / 'first', 'first', 'first_versions')
    second = source(tmp_path / 'second', 'second', 'second_versions')
    assert register_migration_source(first, registry=reg)
    assert register_migration_source(second, registry=reg)
    assert not register_migration_source(first, registry=reg)
    assert registered_migration_sources(registry=reg) == (first, second, final)
    assert registered_migration_sources(registry=MigrationRegistry()) == ()
    assert not tmp_path.joinpath('first').exists()  # registration does not provision SQL


@pytest.mark.parametrize('namespace,table', [('Bad Space', 'valid'), ('valid', 'table; DROP TABLE x')])
def test_invalid_metadata_is_refused_without_sql(tmp_path, namespace, table):
    with pytest.raises(ValueError):
        register_migration_source(source(tmp_path, namespace, table), registry=MigrationRegistry())
    conn = create_connection(SQLiteOptions(':memory:'))
    try:
        with pytest.raises(ValueError):
            apply_migration_source(conn, source(tmp_path, namespace, table))
        assert conn.execute("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        conn.close()


def test_registry_conflicts_do_not_replace_source_or_steal_ledger(tmp_path):
    original = source(tmp_path / 'one')
    reg = MigrationRegistry(trailing_sources=(source(tmp_path / 'final', 'final', 'final_versions'),))
    reg.register(original)
    for replacement in [source(tmp_path / 'two'), source(tmp_path / 'one', table='different'),
                        source(tmp_path, 'other'), source(tmp_path, 'final', 'other_versions'),
                        source(tmp_path, 'other', 'final_versions')]:
        with pytest.raises(ValueError):
            reg.register(replacement)
    assert reg.registered()[0] is original


@pytest.mark.parametrize('trailing', [
    (('same', 'one'), ('same', 'two')),
    (('one', 'same'), ('two', 'same')),
])
def test_trailing_sources_cannot_duplicate_namespace_or_table(tmp_path, trailing):
    with pytest.raises(ValueError):
        MigrationRegistry(trailing_sources=tuple(source(tmp_path, name, table) for name, table in trailing))


def test_concurrent_identical_registration_is_single_idempotent_append(tmp_path):
    reg = MigrationRegistry()
    value = source(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reg.register(value), range(8)))
    assert sum(results) == 1
    assert reg.registered() == (value,)


def test_sql_bytes_lexical_order_per_source_ledgers_and_restart_noop(tmp_path):
    one = tmp_path / 'one'; one.mkdir()
    two = tmp_path / 'two'; two.mkdir()
    (one / '002_next.sql').write_text("INSERT INTO events VALUES ('second');", encoding='utf-8')
    (one / '001_init.sql').write_text("CREATE TABLE events(value); INSERT INTO events VALUES ('第一');", encoding='utf-8')
    (one / 'ignored.sql').write_text('INVALID SQL', encoding='utf-8')
    (two / '001_tail.sql').write_text("INSERT INTO events VALUES ('tail');", encoding='utf-8')
    reg = MigrationRegistry(trailing_sources=(source(two, 'tail', 'tail_versions'),))
    reg.register(source(one))
    db = tmp_path / 'fixture.sqlite'
    conn = create_connection(SQLiteOptions(db))
    try:
        apply_registered_migrations(conn, registry=reg)
        assert conn.execute('SELECT value FROM events').fetchall() == [('第一',), ('second',), ('tail',)]
        assert conn.execute('SELECT version FROM fixture_versions ORDER BY version').fetchall() == [(1,), (2,)]
        assert conn.execute('SELECT version FROM tail_versions').fetchall() == [(1,)]
        shape = conn.execute('PRAGMA table_info(fixture_versions)').fetchall()
        assert shape[0][1:3] == ('version', 'INTEGER') and shape[1][1:3] == ('applied_at', 'TEXT')
    finally:
        conn.close()
    reopened = create_connection(SQLiteOptions(db))
    try:
        apply_registered_migrations(reopened, registry=reg)
        assert reopened.execute('SELECT COUNT(*) FROM events').fetchone() == (3,)
    finally:
        reopened.close()


def test_script_failure_retains_native_partial_effects_and_no_false_ledger(tmp_path):
    directory = tmp_path / 'sql'; directory.mkdir()
    (directory / '001_init.sql').write_text('CREATE TABLE events(value);', encoding='utf-8')
    (directory / '002_fail.sql').write_text("INSERT INTO events VALUES ('partial'); INVALID SQL;", encoding='utf-8')
    conn = create_connection(SQLiteOptions(':memory:'))
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migration_source(conn, source(directory))
        assert conn.execute('SELECT version FROM fixture_versions').fetchall() == [(1,)]
        assert conn.execute('SELECT value FROM events').fetchall() == [('partial',)]
        assert not conn.in_transaction
    finally:
        conn.close()


def test_version_table_setup_preserves_original_commit_of_caller_transaction(tmp_path):
    conn = create_connection(SQLiteOptions(':memory:'))
    try:
        conn.execute('CREATE TABLE owned(value)')
        conn.execute('INSERT INTO owned VALUES (1)')
        assert conn.in_transaction
        apply_migration_source(conn, source(tmp_path / 'absent'))
        conn.rollback()
        assert conn.execute('SELECT value FROM owned').fetchall() == [(1,)]
        assert conn.execute('SELECT version FROM fixture_versions').fetchall() == []
    finally:
        conn.close()
