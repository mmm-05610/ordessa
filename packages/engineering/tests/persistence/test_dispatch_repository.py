"""Schema13 dispatch row invariants on a local original-UoW-shaped connection."""
import hashlib
import sqlite3

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteDispatchRepository
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import DISPATCH_DDL
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest


SCOPE = Scope('dispatch-test-realm', 'dispatch-test-project')


class _Access:
    def __init__(self, connection, scope):
        self._connection = connection
        self.scope = scope
        self._mode = 'write'
        self.active = True

    def check_active(self):
        if not self.active or not self._connection.in_transaction:
            raise ApplicationError('UOW_NOT_ACTIVE')

    def require_write(self):
        self.check_active()
        if self._mode != 'write':
            raise ApplicationError('READ_ONLY_UOW')

    def execute(self, sql, parameters=()):
        self.check_active()
        try:
            return self._connection.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise ApplicationError('STORAGE_CONSTRAINT') from exc


def _database():
    connection = sqlite3.connect(':memory:')
    connection.executescript("""
    CREATE TABLE library_meta(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL);
    INSERT INTO library_meta VALUES (1, 13);
    CREATE TABLE runs (
      run_id TEXT PRIMARY KEY, method_ref_json TEXT NOT NULL, registry_ref_json TEXT NOT NULL,
      input_json TEXT NOT NULL, status TEXT NOT NULL, cursor INTEGER NOT NULL,
      wait_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE step_log (
      run_id TEXT NOT NULL REFERENCES runs(run_id), ordinal INTEGER NOT NULL,
      step_id TEXT NOT NULL, operation TEXT NOT NULL, attempt INTEGER NOT NULL,
      status TEXT NOT NULL, receipt_ref_json TEXT NOT NULL, PRIMARY KEY(run_id,ordinal)
    );
    """)
    connection.executescript(DISPATCH_DDL)
    connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                       ('run-1', '{}', '{}', '{}', 'running', 0, None, 'now', 'now'))
    connection.commit()
    connection.execute('BEGIN')
    return connection, _Access(connection, SCOPE)


def _binding():
    raw = canonical_bytes({'method_ref': {'method_id': 'synthetic-method'},
                           'step_id': 'step-1', 'attempt': 1})
    digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
    return raw, digest


def _reserve(repo, *, step_id='step-1', attempt=1, scope=SCOPE, operation_ref='operation-1'):
    raw, digest = _binding()
    return repo.reserve('run-1', step_id, attempt, scope, raw, digest, operation_ref)


def test_reserve_and_get_preserve_exact_binding_on_existing_step_log_row():
    connection, access = _database()
    repo = SQLiteDispatchRepository(access)
    raw, digest = _binding()
    record = repo.reserve('run-1', 'step-1', 1, SCOPE, raw, digest, 'operation-1')
    assert record['dispatch_phase'] == 'reserved'
    assert record['dispatch_version'] == 0
    assert record['dispatch_fence'] == 1
    assert record['binding_bytes'] == raw
    assert record['binding_digest'] == digest
    assert repo.get('run-1', 'step-1', 1, SCOPE) == record
    old_columns = connection.execute(
        'SELECT status,receipt_ref_json FROM step_log WHERE run_id=? AND step_id=? AND attempt=?',
        ('run-1', 'step-1', 1)).fetchone()
    assert old_columns == ('reserved', canonical_bytes({
        'dispatch': 'reserved', 'binding_digest': digest.hex, 'operation_ref': 'operation-1'
    }).decode())


def test_attempt_operation_run_and_scope_are_exactly_unique_and_present():
    _, access = _database()
    repo = SQLiteDispatchRepository(access)
    _reserve(repo)
    with pytest.raises(ApplicationError, match='DISPATCH_ATTEMPT_CONFLICT'):
        _reserve(repo)
    with pytest.raises(ApplicationError, match='STORAGE_CONSTRAINT'):
        _reserve(repo, step_id='step-2', operation_ref='operation-1')
    with pytest.raises(ApplicationError, match='RUN_NOT_FOUND'):
        raw, digest = _binding()
        repo.reserve('missing-run', 'step-x', 1, SCOPE, raw, digest, 'operation-x')
    with pytest.raises(ApplicationError, match='SCOPE_MISMATCH'):
        repo.get('run-1', 'step-1', 1, Scope('other-realm', 'other-project'))


def test_binding_bytes_must_be_canonical_and_digest_consistent():
    _, access = _database()
    repo = SQLiteDispatchRepository(access)
    raw, digest = _binding()
    with pytest.raises(ApplicationError, match='DISPATCH_BINDING_INVALID'):
        repo.reserve('run-1', 'step-1', 1, SCOPE, raw, Digest('sha256', '0' * 64), 'operation-1')
    with pytest.raises(ApplicationError, match='DISPATCH_RECORD_CORRUPT'):
        repo.reserve('run-1', 'step-1', 1, SCOPE, b'{ "x": 1 }',
                     Digest('sha256', hashlib.sha256(b'{ "x": 1 }').hexdigest()), 'operation-1')


def test_only_allowed_cas_transitions_are_possible_and_terminal_rows_are_immutable():
    connection, access = _database()
    repo = SQLiteDispatchRepository(access)
    _reserve(repo)
    sent = repo.transition('run-1', 'step-1', 1, SCOPE,
                           expected_version=0, fence=1, phase='possibly_written')
    assert (sent['dispatch_phase'], sent['dispatch_version']) == ('possibly_written', 1)
    unknown = repo.transition('run-1', 'step-1', 1, SCOPE,
                              expected_version=1, fence=1, phase='unknown')
    assert (unknown['dispatch_phase'], unknown['dispatch_version']) == ('unknown', 2)
    result = BlobRef(Digest('sha256', 'b' * 64), 10, 'application/octet-stream', 'result-object')
    completed = repo.transition('run-1', 'step-1', 1, SCOPE,
                                expected_version=2, fence=1, phase='completed',
                                result_blob_ref=result)
    assert completed['dispatch_phase'] == 'completed'
    assert completed['result_blob_json'] == canonical_bytes({
        'digest': {'algorithm': 'sha256', 'hex': 'b' * 64},
        'byte_length': 10, 'media_type': 'application/octet-stream',
        'storage_object_id': 'result-object',
    }).decode()
    with pytest.raises(ApplicationError, match='DISPATCH_TRANSITION_INVALID'):
        repo.transition('run-1', 'step-1', 1, SCOPE,
                        expected_version=3, fence=1, phase='unknown')
    with pytest.raises(ApplicationError, match='STORAGE_CONSTRAINT'):
        access.execute("DELETE FROM step_log WHERE run_id='run-1' AND step_id='step-1'")


def test_reserved_cannot_jump_to_result_and_stale_version_fence_refuse():
    _, access = _database()
    repo = SQLiteDispatchRepository(access)
    _reserve(repo)
    with pytest.raises(ApplicationError, match='DISPATCH_TRANSITION_INVALID'):
        repo.transition('run-1', 'step-1', 1, SCOPE,
                        expected_version=0, fence=1, phase='completed')
    repo.transition('run-1', 'step-1', 1, SCOPE,
                    expected_version=0, fence=1, phase='possibly_written')
    with pytest.raises(ApplicationError, match='DISPATCH_CHANGED'):
        repo.transition('run-1', 'step-1', 1, SCOPE,
                        expected_version=0, fence=1, phase='unknown')


def test_raw_sql_cannot_insert_or_transition_a_bound_row_with_null_phase():
    connection, access = _database()
    with pytest.raises(sqlite3.IntegrityError, match='DISPATCH_BINDING_INVALID'):
        connection.execute(
            """INSERT INTO step_log (
                 run_id, ordinal, step_id, operation, attempt, status, receipt_ref_json,
                 dispatch_scope_json, binding_digest, binding_bytes,
                 execution_operation_ref, dispatch_phase, dispatch_version,
                 dispatch_fence, result_blob_json
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('run-1', 10, 'step-null-insert', 'engineering.execution.dispatch', 1,
             'reserved', '{}', '{}', 'a' * 64, b'{}', 'operation-null-insert',
             None, 0, 1, None))

    repo = SQLiteDispatchRepository(access)
    _reserve(repo)
    with pytest.raises(sqlite3.IntegrityError, match='DISPATCH_TRANSITION_INVALID'):
        connection.execute(
            """UPDATE step_log SET dispatch_phase=NULL, dispatch_version=1
               WHERE run_id='run-1' AND step_id='step-1' AND attempt=1""")


def test_historical_unbound_rows_remain_writable_with_null_dispatch_phase():
    connection, _ = _database()
    connection.execute(
        """INSERT INTO step_log (
             run_id, ordinal, step_id, operation, attempt, status, receipt_ref_json
           ) VALUES (?,?,?,?,?,?,?)""",
        ('run-1', 20, 'historical-step', 'legacy.operation', 1, 'reserved', '{}'))
    connection.execute(
        """UPDATE step_log SET status='running', dispatch_phase=NULL
           WHERE run_id='run-1' AND step_id='historical-step'""")
    row = connection.execute(
        """SELECT status, binding_digest, dispatch_phase FROM step_log
           WHERE run_id='run-1' AND step_id='historical-step'""").fetchone()
    assert row == ('running', None, None)
