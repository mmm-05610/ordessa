"""Real original temporary library schema12->13; no user database migration."""
import pytest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema12
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_explicit_dispatch_upgrade_preserves_original_step_bytes_and_old_columns(tmp_path):
    path=(tmp_path/'schema12.sqlite').resolve();backup=(tmp_path/'schema12.backup.sqlite').resolve()
    lib=EngineeringLibrary.create(path,library_id='dispatch-migration',schema_version=12)
    try:
        method=lib.import_material(kind='method',stable_id='historical-method',body={'text':'exact\r\nold'})
        lib.start_run('old-run',method_ref=method,registry_ref={'historical':'exact'},inputs={'source':'old'},now='old-time',expected_refs=())
        factory=SQLiteUoWFactory(lib);scope=Scope('r','p')
        with factory.begin(scope) as uow:
            uow.workflow.insert_step_log(run_id='old-run',ordinal=0,step_id='old',operation='old',attempt=1,status='old',receipt_ref=method)
            uow.commit()
        before=tuple(lib._connection.execute('SELECT * FROM step_log'))
        receipt=migrate_schema12(lib,backup_path=backup)
        assert receipt.target_version==13 and lib._schema_version==13
        assert tuple(lib._connection.execute('SELECT run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json FROM step_log'))==before
        assert lib.step_rows('old-run')[0]['receipt_ref']==method
        assert lib.run_row('old-run')['method_ref']==method
        assert lib._connection.execute('PRAGMA foreign_key_check').fetchall()==[]
        with SQLiteUoWFactory(lib).begin(scope) as uow:
            uow.workflow.insert_step_log(run_id='old-run',ordinal=1,step_id='old-again',operation='old',attempt=1,status='old',receipt_ref=method)
            uow.commit()
    finally:lib.close()
    old=EngineeringLibrary.open(backup,library_id='dispatch-migration')
    try:
        assert old._schema_version==12
        assert tuple(old._connection.execute('SELECT * FROM step_log'))==before
        with SQLiteUoWFactory(old).begin(scope,'read') as uow:
            with pytest.raises(ApplicationError,match='DISPATCH_SCHEMA_REQUIRED'):uow.dispatch
    finally:old.close()
    final=EngineeringLibrary.open(path,library_id='dispatch-migration');final.close()


def test_dispatch_schema13_explicit_create_keeps_default_schema2(tmp_path):
    default=EngineeringLibrary.create((tmp_path/'default.sqlite').resolve(),library_id='default')
    try:
        assert default._schema_version==2
        assert 'binding_bytes' not in {r[1] for r in default._connection.execute('PRAGMA table_info(step_log)')}
    finally:default.close()
    new=EngineeringLibrary.create((tmp_path/'new.sqlite').resolve(),library_id='new',schema_version=13)
    try:
        assert new._schema_version==13
        assert 'binding_bytes' in {r[1] for r in new._connection.execute('PRAGMA table_info(step_log)')}
    finally:new.close()
