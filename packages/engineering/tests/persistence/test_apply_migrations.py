"""Explicit schema8->9 on dedicated temporary files, never real user data."""
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite import migrations
from ordessa_engineering.adapters.persistence.sqlite.apply_schema import APPLY_TABLES
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope


def table_names(lib):
    return {row[0] for row in lib._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_default_schema2_and_old_schema7_open_never_create_authorization(tmp_path):
    default = EngineeringLibrary.create((tmp_path / 'default.sqlite').resolve(), library_id='default')
    try:
        assert default._schema_version == 2
        assert not set(APPLY_TABLES).intersection(table_names(default))
    finally:
        default.close()
    path = (tmp_path / 'old.sqlite').resolve()
    old = EngineeringLibrary.create(path, library_id='old', schema_version=8)
    old.close()
    reopened = EngineeringLibrary.open(path, library_id='old')
    try:
        assert reopened._schema_version == 8
        assert not set(APPLY_TABLES).intersection(table_names(reopened))
        with SQLiteUoWFactory(reopened).begin(Scope('r', 'p'), 'read') as uow:
            with pytest.raises(ApplicationError, match='APPLY_SCHEMA_REQUIRED'):
                uow.authorization.require_apply_schema()
    finally:
        reopened.close()


def test_explicit_upgrade_preserves_legacy_material_and_backup(tmp_path):
    path = (tmp_path / 'source.sqlite').resolve()
    backup = (tmp_path / 'before7.sqlite').resolve()
    lib = EngineeringLibrary.create(path, library_id='migrate', schema_version=8)
    try:
        lib.import_material(kind='method', stable_id='historical-method', body={'text': 'legacy\r\nexact'})
        before = tuple(lib._connection.execute('SELECT * FROM materials'))
        receipt = migrations.migrate_schema8(lib, backup_path=backup)
        assert lib._schema_version == 9 and receipt.target_version == 9
        assert tuple(lib._connection.execute('SELECT * FROM materials')) == before
        assert set(APPLY_TABLES).issubset(table_names(lib))
    finally:
        lib.close()
    old = EngineeringLibrary.open(backup, library_id='migrate')
    try:
        assert old._schema_version == 8
        assert tuple(old._connection.execute('SELECT * FROM materials')) == before
    finally:
        old.close()
    upgraded = EngineeringLibrary.open(path, library_id='migrate')
    upgraded.close()


def test_partial_new_ddl_failure_rolls_back_whole_schema(tmp_path, monkeypatch):
    path = (tmp_path / 'source.sqlite').resolve()
    lib = EngineeringLibrary.create(path, library_id='rollback', schema_version=8)
    names = table_names(lib)
    original = migrations._statements
    def fail(ddl):
        for index, statement in enumerate(original(ddl)):
            if index == 2:
                raise RuntimeError('Injected failure after actual new tables.')
            yield statement
    monkeypatch.setattr(migrations, '_statements', fail)
    try:
        with pytest.raises(RuntimeError, match='Injected failure'):
            migrations.migrate_schema8(lib, backup_path=(tmp_path / 'before.sqlite').resolve())
        assert lib._schema_version == 8
        # Original migration failure closes its uncertain handle; inspect the
        # durable source by reopening, preserving that established behavior.
        reopened = EngineeringLibrary.open(path, library_id='rollback')
        try:
            assert table_names(reopened) == names
            assert reopened._connection.execute('PRAGMA user_version').fetchone() == (8,)
        finally:
            reopened.close()
    finally:
        lib.close()
