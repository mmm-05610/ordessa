"""Real production bootstrap and the 16->17 declared-Work migration.

The library is built by the production `EngineeringLibrary.create`, the upgrade
goes through the production registry entry `migrate_schema16`, and the old
records must survive untouched and stay readable after the upgrade.
"""
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import (
    SQLiteWorkDispatchRepository)
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest

SCOPE = Scope('r', 'p')
WORK_ID = 'work-1'
ACTION = 'incremental.prepare-packages'
STEP = 'prepare-spec-kit-package'
KEY = 'w1:%s:%s:%s' % (WORK_ID, ACTION, STEP)


class _Access:
    def __init__(self, connection, scope):
        self._connection = connection
        self.scope = scope

    def check_active(self):
        if not self._connection.in_transaction:
            raise RuntimeError('UOW_NOT_ACTIVE')

    def require_write(self):
        self.check_active()

    def execute(self, sql, parameters=()):
        return self._connection.execute(sql, parameters)


def _work_binding():
    return encode_dispatch(DispatchBinding(
        SCOPE, KEY, STEP, 1, 1, None,
        ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'grant-1', Digest('sha256', 'a' * 64)),
        Digest('sha256', 'b' * 64), 0, (('generate_package', 'i-1'),),
        canonical_bytes({'environmentNamespace': 'env', 'unitId': 'unit-1',
                         'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}),
        'operation-1', BlobRef(Digest('sha256', 'c' * 64), 10, 'application/json', 'prompt'),
        Digest('sha256', 'd' * 64), 'e' * 64, ('submission',), binding_version=2,
        work={'work_id': WORK_ID, 'action_id': ACTION, 'step_id': STEP,
              'dispatch_key': KEY},
        subject={'subject_kind': 'reviewed_change',
                 'subject_ref': {'reviewed_change_id': 'change-1'}}))


def test_real_bootstrap_then_16_to_17_keeps_old_records_and_a_reopen_reads_it(tmp_path):
    path = (tmp_path / 'schema16.sqlite').resolve()
    backup = (tmp_path / 'schema16.backup.sqlite').resolve()
    lib = EngineeringLibrary.create(path, library_id='work-migration', schema_version=16)
    try:
        method = lib.import_material(kind='method', stable_id='historical-method',
                                     body={'text': 'exact\r\nold'})
        lib.start_run('old-run', method_ref=method, registry_ref={'historical': 'exact'},
                      inputs={'source': 'old'}, now='old-time', expected_refs=())
        factory = SQLiteUoWFactory(lib)
        with factory.begin(SCOPE) as uow:
            uow.workflow.insert_step_log(run_id='old-run', ordinal=0, step_id='old',
                                         operation='old', attempt=1, status='old',
                                         receipt_ref=method)
            uow.commit()
        # the original columns of the historical row, exactly as written
        before = tuple(lib._connection.execute(
            'SELECT %s FROM step_log' % 'run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json'))
        assert lib._schema_version == 16
        # the declared-Work relation does not exist before the upgrade
        assert lib._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='work_step_log'").fetchone() is None

        receipt = migrate_schema16(lib, backup_path=backup)

        assert receipt.target_version == 17 and lib._schema_version == 17
        assert tuple(lib._connection.execute(
            'SELECT run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json '
            'FROM step_log')) == before
        # the historical row is not a dispatch row: its dispatch columns stay empty
        assert lib._connection.execute(
            'SELECT dispatch_phase,binding_digest,dispatch_version,dispatch_fence '
            'FROM step_log').fetchone() == (None, None, 0, 1)
        assert lib.step_rows('old-run')[0]['receipt_ref'] == method
        assert lib.run_row('old-run')['method_ref'] == method
        assert lib._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='work_step_log'").fetchone() is not None
        assert lib._connection.execute('PRAGMA foreign_key_check').fetchall() == []

        # the relation is usable on the migrated library, through the real repository
        if not lib._connection.in_transaction:
            lib._connection.execute('BEGIN')
        lib._connection.execute(
            'INSERT INTO materials VALUES (?,?,?,?,?,?)',
            ('work-context', 'declarative-work:' + WORK_ID, 1, 'f' * 64,
             canonical_bytes({'work_id': WORK_ID,
                              'scope': {'realm_id': 'r', 'project_id': 'p'},
                              'revision': 1}).decode('utf-8'), 0))
        repo = SQLiteWorkDispatchRepository(_Access(lib._connection, SCOPE))
        binding_bytes = _work_binding()
        record = repo.reserve(KEY, STEP, 1, SCOPE, binding_bytes,
                              Digest('sha256', hashlib.sha256(binding_bytes).hexdigest()),
                              'operation-1')
        assert record['dispatch_phase'] == 'reserved'
        lib._connection.commit()
        lib._connection.execute('BEGIN')
    finally:
        lib.close()

    # the pre-upgrade backup is still the old schema, with the old records
    old = EngineeringLibrary.open(backup, library_id='work-migration')
    try:
        assert old._schema_version == 16
        assert tuple(old._connection.execute(
            'SELECT %s FROM step_log' % 'run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json')) == before
        assert old._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='work_step_log'").fetchone() is None
    finally:
        old.close()

    # and the upgraded library reopens readable at 17 with its Work row intact
    final = EngineeringLibrary.open(path, library_id='work-migration')
    try:
        assert final._schema_version == 17
        row = final._connection.execute(
            'SELECT dispatch_key,step_id,attempt,dispatch_phase FROM work_step_log').fetchone()
        assert row == (KEY, STEP, 1, 'reserved')
        assert final.run_row('old-run')['method_ref'] == method
    finally:
        final.close()
