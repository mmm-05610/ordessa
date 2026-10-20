"""Work-scoped dispatch persistence on real SQLite, plus the send-once adapter.

The repository is the real one; the Unit transport, the approval read and the
caller's access are clearly-labelled test doubles (no platform identity, no
credential, no network). What is asserted here is persistence, reopen, conflict
and re-entry behaviour, not a live Unit call.
"""
import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import (
    SQLiteDispatchRepository, SQLiteWorkDispatchRepository)
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import (
    DISPATCH_DDL, WORK_DISPATCH_DDL)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest

SCOPE = Scope('work-dispatch-realm', 'work-dispatch-project')
WORK_ID = 'work-1'
ACTION = 'incremental.prepare-packages'
STEP = 'prepare-spec-kit-package'
KEY = 'w1:%s:%s:%s' % (WORK_ID, ACTION, STEP)
CHANGE = 'change-1'
WORK_BODY = canonical_bytes({'work_id': WORK_ID,
                             'scope': {'realm_id': SCOPE.realm_id,
                                       'project_id': SCOPE.project_id},
                             'method_ref': {'method_id': 'm', 'release_version': '2.7.2',
                                            'snapshot_digest': 'a' * 64},
                             'revision': 1}).decode('utf-8')
OTHER_SCOPE_BODY = canonical_bytes({'work_id': WORK_ID,
                                    'scope': {'realm_id': 'x', 'project_id': 'y'},
                                    'method_ref': {'method_id': 'm', 'release_version': '2.7.2',
                                                   'snapshot_digest': 'a' * 64},
                                    'revision': 1}).decode('utf-8')

BASE_DDL = """
CREATE TABLE library_meta(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL);
INSERT INTO library_meta VALUES (1, 17);
CREATE TABLE materials (
  kind TEXT NOT NULL, stable_id TEXT NOT NULL, revision INTEGER NOT NULL,
  digest TEXT NOT NULL, body_json TEXT NOT NULL, generated INTEGER NOT NULL,
  PRIMARY KEY (kind, stable_id, revision), UNIQUE (kind, stable_id, digest));
CREATE TABLE heads (
  kind TEXT NOT NULL, stable_id TEXT NOT NULL, revision INTEGER NOT NULL,
  digest TEXT NOT NULL, PRIMARY KEY (kind, stable_id));
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, method_ref_json TEXT NOT NULL, registry_ref_json TEXT NOT NULL,
  input_json TEXT NOT NULL, status TEXT NOT NULL, cursor INTEGER NOT NULL,
  wait_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE step_log (
  run_id TEXT NOT NULL REFERENCES runs(run_id), ordinal INTEGER NOT NULL,
  step_id TEXT NOT NULL, operation TEXT NOT NULL, attempt INTEGER NOT NULL,
  status TEXT NOT NULL, receipt_ref_json TEXT NOT NULL, PRIMARY KEY(run_id,ordinal));
"""


class _Access:
    """The caller's own UoW-shaped access, as a labelled local double."""

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


def _database(path=':memory:'):
    connection = sqlite3.connect(path)
    connection.executescript(BASE_DDL)
    connection.executescript(DISPATCH_DDL)
    connection.executescript(WORK_DISPATCH_DDL)
    connection.execute(
        'INSERT INTO materials VALUES (?,?,?,?,?,?)',
        ('work-context', 'declarative-work:' + WORK_ID, 1, 'a' * 64, WORK_BODY, 0))
    connection.commit()
    connection.execute('BEGIN')
    return connection, _Access(connection, SCOPE)


def _generation_subject():
    """The reviewed change, its review, the pinned method and the inputs digest."""
    return {'review_ref': asdict(ReviewRef(SCOPE.realm_id, SCOPE.project_id,
                                            'review-1', Digest('sha256', 'd' * 64))),
            'change_ref': asdict(ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1',
                                            'proposal-1', Digest('sha256', 'f' * 64))),
            'method_ref': asdict(MethodRef('incremental-engineering', '2.7.2', 1,
                                          Digest('sha256', 'b' * 64))),
            'inputs_digest': asdict(Digest('sha256', 'e' * 64))}


def _binding(*, work_id=WORK_ID, action_id=ACTION, step_id=STEP, attempt=1, scope=SCOPE,
             subject_kind='reviewed_change', key=None):
    prompt_raw = canonical_bytes({'prompt': 'frozen'})
    prompt_digest = Digest('sha256', hashlib.sha256(prompt_raw).hexdigest())
    return encode_dispatch(DispatchBinding(
        scope, key or ('w1:%s:%s:%s' % (work_id, action_id, step_id)), step_id, attempt, 1,
        None, None, None, None,
        (('generate_package', 'instance-1'),),
        canonical_bytes({'environmentNamespace': 'env', 'unitId': 'unit-1',
                         'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}),
        'operation-%s' % attempt,
        BlobRef(Digest('sha256', 'c' * 64), 10, 'application/json', 'prompt-object'),
        prompt_digest,
        'd' * 64, ('submission',), binding_version=2,
        work={'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
              'dispatch_key': key or ('w1:%s:%s:%s' % (work_id, action_id, step_id))},
        subject={'subject_kind': subject_kind, 'subject_ref': _generation_subject()}))


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def test_success_is_persisted_with_the_transition_chain():
    connection, access = _database()
    repo = SQLiteWorkDispatchRepository(access)
    raw = _binding()
    record = repo.reserve(KEY, STEP, 1, SCOPE, raw, _digest(raw), 'operation-1')
    assert record['dispatch_phase'] == 'reserved' and record['dispatch_version'] == 0
    assert record['binding_bytes'] == raw
    assert repo.transition(KEY, STEP, 1, SCOPE, expected_version=0, fence=1,
                           phase='possibly_written')['dispatch_phase'] == 'possibly_written'
    result = BlobRef(Digest('sha256', 'e' * 64), 10, 'application/json', 'result-object')
    final = repo.transition(KEY, STEP, 1, SCOPE, expected_version=1, fence=1,
                            phase='completed', result_blob_ref=result)
    assert final['dispatch_phase'] == 'completed'
    assert final['result_blob_json'] == canonical_bytes(
        {'digest': {'algorithm': 'sha256', 'hex': 'e' * 64}, 'byte_length': 10,
         'media_type': 'application/json', 'storage_object_id': 'result-object'}
    ).decode('utf-8')
    assert repo.by_operation('operation-1', SCOPE)['dispatch_phase'] == 'completed'


def test_reopen_reads_the_same_row(tmp_path):
    path = str(tmp_path / 'work-dispatch.sqlite')
    connection, access = _database(path)
    repo = SQLiteWorkDispatchRepository(access)
    raw = _binding()
    repo.reserve(KEY, STEP, 1, SCOPE, raw, _digest(raw), 'operation-1')
    repo.transition(KEY, STEP, 1, SCOPE, expected_version=0, fence=1, phase='possibly_written')
    repo.transition(KEY, STEP, 1, SCOPE, expected_version=1, fence=1, phase='completed')
    connection.commit()
    connection.close()

    resumed = sqlite3.connect(path)
    resumed.execute('BEGIN')
    reader = SQLiteWorkDispatchRepository(_Access(resumed, SCOPE))
    record = reader.get(KEY, STEP, 1, SCOPE)
    assert record['binding_bytes'] == raw
    assert record['binding_digest'] == _digest(raw)
    assert record['dispatch_phase'] == 'completed'
    assert reader.by_operation('operation-1', SCOPE)['step_id'] == STEP
    resumed.close()


def test_same_identity_different_binding_and_digest_conflicts():
    connection, access = _database()
    repo = SQLiteWorkDispatchRepository(access)
    raw = _binding()
    repo.reserve(KEY, STEP, 1, SCOPE, raw, _digest(raw), 'operation-1')
    with pytest.raises(ApplicationError) as exc:
        repo.reserve(KEY, STEP, 1, SCOPE, _binding(), _digest(_binding()), 'operation-2')
    assert exc.value.code == 'DISPATCH_ATTEMPT_CONFLICT'
    with pytest.raises(ApplicationError) as exc:
        repo.reserve(KEY, STEP, 2, SCOPE, raw, Digest('sha256', 'f' * 64), 'operation-3')
    assert exc.value.code in ('DISPATCH_RECORD_CORRUPT', 'DISPATCH_BINDING_INVALID')


def test_the_work_and_scope_must_be_real_and_match():
    connection, access = _database()
    repo = SQLiteWorkDispatchRepository(access)
    other = Scope('other-realm', 'other-project')
    with pytest.raises(ApplicationError) as exc:
        repo.reserve(KEY, STEP, 1, other, _binding(), _digest(_binding()), 'operation-1')
    assert exc.value.code == 'SCOPE_MISMATCH'
    missing = _binding(work_id='work-absent', key='w1:work-absent:%s:%s' % (ACTION, STEP))
    with pytest.raises(ApplicationError) as exc:
        repo.reserve('w1:work-absent:%s:%s' % (ACTION, STEP), STEP, 1, SCOPE, missing,
                     _digest(missing), 'operation-1')
    assert exc.value.code == 'WORK_NOT_FOUND'
    mismatched = _binding(work_id='work-1', key='w1:other-work:%s:%s' % (ACTION, STEP))
    with pytest.raises(ApplicationError) as exc:
        repo.reserve(KEY, STEP, 1, SCOPE, mismatched, _digest(mismatched), 'operation-1')
    assert exc.value.code == 'DISPATCH_BINDING_INVALID'


class _Transport:
    """Labelled Unit-transport double: counts sends, never touches a network."""

    def __init__(self, *, fail=False):
        self.sends = 0
        self.fail = fail

    def freeze_input(self, unit_ref, params):
        raw = canonical_bytes({'frozen': {'unit_ref': unit_ref, 'params': params}})
        return raw, Digest('sha256', hashlib.sha256(raw).hexdigest())

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return 'q' * 64

    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        @contextmanager
        def _handoff():
            yield
        return _handoff()

    def send(self, binding, *, timeout=60):
        self.sends += 1
        if self.fail:
            raise RuntimeError('synthetic transport failure')

    def capture(self, binding):
        blob = BlobRef(Digest('sha256', 'f' * 64), 10, 'application/json', 'result-object')
        return SimpleNamespace(blob_ref=blob, observation={'captured': True})


class _Blobs:
    def put_verified(self, raw, digest, media):
        return BlobRef(digest, 10, media, 'prompt-%s' % digest.hex[:8])


class _Approvals:
    """Labelled stand-in for the authorization read (see the real verifier)."""

    def __init__(self, *, state='active', version=0, actions=('generate_package',)):
        self.state, self.version, self.actions = state, version, actions
        self.consumed = []

    def get_grant(self, ref):
        return SimpleNamespace(ref=ref, control_version=self.version,
                               intent=SimpleNamespace(not_before='2026-01-01T00:00:00Z',
                                                      expires_at='2027-01-01T00:00:00Z',
                                                      actions=self.actions, scope=SCOPE,
                                                      targets=(CHANGE,),
                                                      digest=Digest('sha256', 'a' * 64)))

    def get_control(self, ref):
        return SimpleNamespace(state=self.state, version=self.version)

    def consume_action(self, ref, *, action, action_instance_id, target_digest, now):
        self.consumed.append(action)


class _Uow:
    def __init__(self, connection, dispatch, authorization, scope):
        self._connection = connection
        self.dispatch = dispatch
        self.authorization = authorization
        self.scope = scope

    def commit(self):
        self._connection.commit()
        if not self._connection.in_transaction:
            self._connection.execute('BEGIN')

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _adapter(connection, access, transport, approvals):
    from ordessa_engineering.application.orchestration.steps import (
        declared_generation_dispatch as module)

    module.decode_approval_ref = lambda value: value   # labelled: the read is doubled
    real = SQLiteWorkDispatchRepository(access)

    class _Factory:
        def begin(self, scope, mode=None):
            if not connection.in_transaction:
                connection.execute('BEGIN')
            return _Uow(connection, real, approvals, scope)

    adapter = module.DeclaredGenerationDispatch(
        _Factory(), _Holder(access), blobs=_Blobs(), execution=transport)
    return adapter, real


class _Holder:
    def __init__(self, access):
        self.access = access

    def require(self, context, capability):
        self.access.check_active()
        if capability != 'engineering.executions.dispatch':
            raise ApplicationError('CAPABILITY_NOT_BOUND')


def _context():
    return SimpleNamespace(scope=SCOPE, received_at='2026-06-01T00:00:00Z')


def _unit_ref():
    return {'environmentNamespace': 'env', 'unitId': 'unit-1',
            'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}


def _approval_ref_value():
    return ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'grant-1', Digest('sha256', 'a' * 64))


def test_a_same_id_material_under_another_scope_is_not_this_work():
    connection, access = _database()
    connection.execute(
        'INSERT INTO materials VALUES (?,?,?,?,?,?)',
        ('work-context', 'declarative-work:' + WORK_ID, 2, 'b' * 64, OTHER_SCOPE_BODY, 0))
    repo = SQLiteWorkDispatchRepository(access)
    raw = _binding()
    with pytest.raises(ApplicationError) as exc:
        repo.reserve(KEY, STEP, 1, SCOPE, raw, _digest(raw), 'operation-1')
    assert exc.value.code == 'WORK_NOT_FOUND'


def test_upgrade_on_one_database_keeps_both_relations_and_their_object_names():
    """The new relation is added to a database that already has the run one."""
    connection, access = _database()
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger') "
        "AND name LIKE 'step_log%' OR name LIKE 'work_step_log%'")]
    assert len(names) == len(set(names)), names
    assert {'step_log', 'work_step_log'} <= set(names)
    # the historical relation is present, empty and unrenamed
    assert connection.execute('SELECT COUNT(*) FROM step_log').fetchone()[0] == 0
    for row in connection.execute('PRAGMA table_info(step_log)'):
        assert row[1] != 'dispatch_key'


