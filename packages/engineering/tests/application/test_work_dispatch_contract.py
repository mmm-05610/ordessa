"""The declared-Work dispatch contract on its real SQLite relation.

Asserted here: the *active* write form takes a declared Work identity and never a
run; the same identity and content read back identically; changed content (Unit,
frozen input, frozen package) is refused by name rather than silently accepted;
folded keys for very long ids do not collide; a ``frozen_package`` subject that is
not the full package projection still reads back but is refused at the active
write; and the query/read path is the schema-17 declared-Work relation, never the
historical run relation.

The persistence assertions run against the real ``SQLiteWorkDispatchRepository``
on a real in-memory database. The native owner is the only labelled double in the
file and it never touches a network or a credential.

Each assertion below states its contract directly and fails by assertion, never by
a skip or a weakened expectation; an assertion that was written ahead of the source
change it describes is marked ``DEPENDS-ON-SOURCE`` at its definition.
"""
import hashlib
import sqlite3
from dataclasses import asdict

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.dispatch_identity import (
    identity_agrees, is_folded_work_key, is_work_key, subject_of, work_dispatch_key)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.owner_operations import (
    EngineeringOwnerOperations)
from ordessa_engineering.application.orchestration.owner_capabilities import (
    owner_capabilities)
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import (
    SQLiteDispatchRepository, SQLiteWorkDispatchRepository)
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import (
    DISPATCH_DDL, WORK_DISPATCH_DDL, WORK_DISPATCH_SCHEMA_VERSION)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, package_ref_projection)
from ordessa_engineering.domain.changes.dispatch_codec import (
    decode_dispatch, encode_dispatch)
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef

SCOPE = Scope('dispatch-contract-realm', 'dispatch-contract-project')
WORK_ID = 'work-1'
ACTION = 'incremental.prepare-packages'
STEP = 'prepare-spec-kit-package'
IDENTITY = work_dispatch_key(WORK_ID, ACTION, STEP)
OTHER_IDENTITY = work_dispatch_key('work-2', ACTION, STEP)

UNIT = {'environmentNamespace': 'env', 'unitId': 'unit-1',
        'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}
OTHER_UNIT = {'environmentNamespace': 'env', 'unitId': 'unit-2',
              'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-2'}
PACKAGE = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-1',
                                   Digest('sha256', 'a' * 64))
OTHER_PACKAGE = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-2',
                                         Digest('sha256', 'e' * 64))
APPROVAL = ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-1',
                       Digest('sha256', 'c' * 64))

WORK_BODY = canonical_bytes({'work_id': WORK_ID,
                             'scope': {'realm_id': SCOPE.realm_id,
                                       'project_id': SCOPE.project_id},
                             'method_ref': {'method_id': 'm', 'release_version': '2.7.2',
                                            'snapshot_digest': 'a' * 64},
                             'revision': 1}).decode('utf-8')

BASE_DDL = """
CREATE TABLE library_meta(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL);
CREATE TABLE materials (
  kind TEXT NOT NULL, stable_id TEXT NOT NULL, revision INTEGER NOT NULL,
  digest TEXT NOT NULL, body_json TEXT NOT NULL, generated INTEGER NOT NULL,
  PRIMARY KEY (kind, stable_id, revision), UNIQUE (kind, stable_id, digest));
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

    def check_active(self):
        if not self._connection.in_transaction:
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


def _database(schema_version=WORK_DISPATCH_SCHEMA_VERSION):
    connection = sqlite3.connect(':memory:')
    connection.executescript(BASE_DDL)
    connection.execute('INSERT INTO library_meta VALUES (1, ?)', (schema_version,))
    connection.executescript(DISPATCH_DDL)
    connection.executescript(WORK_DISPATCH_DDL)
    connection.execute(
        'INSERT INTO materials VALUES (?,?,?,?,?,?)',
        ('work-context', 'declarative-work:' + WORK_ID, 1, 'a' * 64, WORK_BODY, 0))
    connection.commit()
    connection.execute('BEGIN')
    return connection, _Access(connection, SCOPE)


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _frozen(unit_ref, params):
    """The frozen input a real execution owner would hand back for these params."""
    raw = canonical_bytes({'unitRef': unit_ref, 'params': params})
    return BlobRef(Digest('sha256', hashlib.sha256(raw).hexdigest()), len(raw),
                   'application/json', 'frozen-input')


def _frozen_binding(*, unit_ref=UNIT, params=None, package_ref=PACKAGE, subject_ref=None,
                    operation_ref='operation-1', attempt=1, work_id=WORK_ID,
                    action_id=ACTION, step_id=STEP):
    """A schema-2 binding for a declared implementation step on a frozen package."""
    params = {'prompt': 'frozen'} if params is None else params
    prompt = _frozen(unit_ref, params)
    # The subject of a frozen-package step is exactly the canonical projection of
    # the package the binding acts on; a caller may substitute a non-projection
    # to show that such a subject is refused.
    ref = package_ref_projection(package_ref) if subject_ref is None else subject_ref
    return DispatchBinding(
        SCOPE, work_dispatch_key(work_id, action_id, step_id), step_id, attempt, 1,
        package_ref, APPROVAL, Digest('sha256', 'b' * 64), 1,
        (('edit_repository', 'instance-%s' % attempt),), canonical_bytes(unit_ref),
        operation_ref, prompt, prompt.digest, 'd' * 64, ('submission',),
        binding_version=2,
        work={'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
              'dispatch_key': work_dispatch_key(work_id, action_id, step_id)},
        subject=subject_of('frozen_package', ref))


def _reserve(repository, binding, operation_ref=None):
    raw = encode_dispatch(binding)
    return raw, repository.reserve(binding.work['dispatch_key'], binding.step_id,
                                   binding.attempt, binding.scope, raw, _digest(raw),
                                   operation_ref or binding.execution_operation_ref)


def _context(scope=SCOPE, request_id='work-dispatch-contract'):
    return CommandContext(scope, 'principal-1', ActorRef('actor-1', 'agent', 'issuer-1'),
                          request_id, '2026-06-01T00:00:00.000000Z', 'trace-1')


# --------------------------------------------------------------------------
# The active write entry: a declared Work identity, never the historical run.
# --------------------------------------------------------------------------

class _UnreachableOwner:
    """A dispatch owner that a refused request form must never reach."""

    def __init__(self, factory, blobs, execution):
        self.factory, self.blobs, self.execution = factory, blobs, execution

    def dispatch_declared_work(self, *args, **kwargs):
        raise AssertionError('the active write owner was reached by a refused form')


class _Factory:
    authority_id = 'work-dispatch-contract-authority'

    def __init__(self, repository=None, scope=SCOPE):
        self._repository, self._scope = repository, scope

    def begin(self, scope, mode=None):
        assert scope == self._scope, 'the adapter read another scope'
        return _Uow(self._repository, scope)


class _Blobs:
    authority_id = 'work-dispatch-contract-authority'


class _Uow:
    def __init__(self, repository, scope):
        # `dispatch` keeps this double's original shape; `work_dispatch` is the
        # declared-Work relation (schema 17) the owner adapter reads back, with the
        # real `get(dispatch_key, step_id, attempt, scope)` signature. Both name the
        # one store the double was handed, so no read is invented or split.
        self.dispatch = self.work_dispatch = repository
        self.scope = scope

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _operations(dispatch_owner_factory, *, repository=None):
    factory, blobs = _Factory(repository), _Blobs()
    records = object()
    execution = type('Execution', (), {'records': records,
                                       'query_factory': staticmethod(lambda binding: object())})()
    dispatch = dispatch_owner_factory(factory, blobs, execution)
    return EngineeringOwnerOperations(factory, packages=_Owner(factory),
                                      dispatch=dispatch, submissions=_Owner(factory),
                                      records=records, blobs=blobs)


class _Owner:
    def __init__(self, factory):
        self.factory = factory


DECLARED_FORM = {'work_id': WORK_ID, 'action_id': ACTION, 'step_id': STEP, 'attempt': 1,
                 'unit_ref': UNIT, 'params': {'prompt': 'frozen'},
                 'actions': ['edit_repository'], 'timeout': 1}
RUN_FORM = {'run_id': 'run-1', 'step_id': STEP, 'attempt': 1, 'unit_ref': UNIT,
            'params': {'prompt': 'frozen'}, 'actions': ['edit_repository'], 'timeout': 1}
WITHOUT_WORK_ID = {name: value for name, value in DECLARED_FORM.items() if name != 'work_id'}


def test_active_write_entry_refuses_the_run_form_and_a_request_without_work_id():
    operations = _operations(_UnreachableOwner)
    context = _context()
    # A run-shaped request is never an active writer, whatever else it carries.
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution({'dispatch': dict(RUN_FORM)}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # Neither is a Work-shaped request that omits the declared identity.
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution({'dispatch': dict(WITHOUT_WORK_ID)}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # A request carrying both forms is still the historical run form.
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution(
            {'dispatch': dict(DECLARED_FORM, run_id='run-1')}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # The declared form is closed: an extra field or a non-list action set is the
    # same refused input, never a silently widened writer.
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution(
            {'dispatch': dict(DECLARED_FORM, package_id='package-1')}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution(
            {'dispatch': dict(DECLARED_FORM, actions=('edit_repository',))}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # The same refusal holds on the routed entry.
    with pytest.raises(ApplicationError) as exc:
        operations.execute('engineering.executions.dispatch',
                           {'dispatch': dict(RUN_FORM)}, context)
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # A complete, well-formed declared request does reach the owner (the form is
    # not itself the refusal); the owner is the labelled double that then fails.
    with pytest.raises(AssertionError, match='refused form'):
        operations.dispatch_execution({'dispatch': dict(DECLARED_FORM)}, context)


# --------------------------------------------------------------------------
# Identity round-trip on the real relation.
# --------------------------------------------------------------------------

def test_the_same_identity_and_content_reads_back_identical():
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    binding = _frozen_binding()
    raw, record = _reserve(repository, binding)
    assert record['binding_bytes'] == raw
    assert record['dispatch_phase'] == 'reserved'

    first = repository.get(IDENTITY, STEP, 1, SCOPE)
    second = repository.get(IDENTITY, STEP, 1, SCOPE)
    assert first == second, 'the same identity must read back identically'

    read = decode_dispatch(first['binding_bytes'])
    assert read.binding_version == 2
    assert read.run_id == IDENTITY, 'the namespaced declared-Work key, never a run id'
    assert (read.work['work_id'], read.work['action_id'], read.work['step_id']) == (
        WORK_ID, ACTION, STEP)
    assert read.work['dispatch_key'] == IDENTITY
    assert read.step_id == STEP and read.attempt == 1 and read.scope == SCOPE
    assert read.unit_ref_bytes == canonical_bytes(UNIT)
    assert tuple(action for action, _ in read.action_instances) == ('edit_repository',)
    # The declared Work's own parameters are carried by the frozen input: the same
    # request reproduces the same blob identity and the same input digest.
    assert read.prompt_ref == _frozen(UNIT, {'prompt': 'frozen'})
    assert read.prompt_input_digest == read.prompt_ref.digest
    # The original fields agree with the key they are stored under.
    assert is_work_key(IDENTITY) and not is_folded_work_key(IDENTITY)
    assert identity_agrees(IDENTITY, WORK_ID, ACTION, STEP)
    assert not identity_agrees(IDENTITY, 'work-2', ACTION, STEP)
    assert not identity_agrees(IDENTITY, WORK_ID, ACTION, 'other-step')

    # A duplicate reserve is a named refusal, never a silent re-write.
    with pytest.raises(ApplicationError) as exc:
        _reserve(repository, binding, operation_ref='operation-2')
    assert exc.value.code == 'DISPATCH_ATTEMPT_CONFLICT'
    assert repository.get(IDENTITY, STEP, 1, SCOPE)['binding_bytes'] == raw
    connection.close()


def test_changed_unit_ref_params_or_package_are_refused_by_name_not_silently_accepted():
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    raw, _ = _reserve(repository, _frozen_binding())

    variants = {
        # A different Unit for the same declared step and attempt.
        'unit': _frozen_binding(unit_ref=OTHER_UNIT, operation_ref='operation-unit'),
        # The same Unit with different frozen input (params).
        'params': _frozen_binding(params={'prompt': 'changed'},
                                  operation_ref='operation-params'),
        # A different frozen package for the same step.
        'package': _frozen_binding(package_ref=OTHER_PACKAGE,
                                   operation_ref='operation-package'),
    }
    for name, variant in variants.items():
        assert encode_dispatch(variant) != raw, 'the variant must really differ (%s)' % name
        with pytest.raises(ApplicationError) as exc:
            _reserve(repository, variant, operation_ref='operation-%s-2' % name)
        assert exc.value.code == 'DISPATCH_ATTEMPT_CONFLICT', name
        # Nothing was silently accepted: the original row is untouched.
        stored = repository.get(IDENTITY, STEP, 1, SCOPE)
        assert stored['binding_bytes'] == raw, name
        assert decode_dispatch(stored['binding_bytes']) == decode_dispatch(raw), name

    # Two different params can never share a frozen-input identity.
    assert (_frozen(UNIT, {'prompt': 'frozen'}).digest
            != _frozen(UNIT, {'prompt': 'changed'}).digest)
    connection.close()


# --------------------------------------------------------------------------
# Folded keys for very long, legal ids.
# --------------------------------------------------------------------------

def test_two_long_work_ids_that_would_collide_under_truncation_stay_distinct():
    """DEPENDS-ON-SOURCE: today the folded key is a plain 512-char truncation of
    ``w1h:<work_id>:<action>:<step>:<digest>``, so two 510-char work ids that
    differ only in their last character truncate to the same string, and
    ``identity_agrees`` returns False for every folded key. The declaration below
    is the target behaviour of the landing source change: distinct original ids
    must keep distinct identities, and a folded key must still be verifiable
    against its original fields.
    """
    shared = 'w' * 509
    first, second = shared + 'X', shared + 'Y'
    assert first != second and len(first) == 510 and len(second) == 510

    key_first = work_dispatch_key(first, ACTION, STEP)
    key_second = work_dispatch_key(second, ACTION, STEP)
    assert is_folded_work_key(key_first) and is_folded_work_key(key_second)
    assert len(key_first) <= 512 and len(key_second) <= 512
    assert key_first != key_second, 'a truncated prefix is not a collision-free identity'

    assert identity_agrees(key_first, first, ACTION, STEP)
    assert identity_agrees(key_second, second, ACTION, STEP)
    assert not identity_agrees(key_first, second, ACTION, STEP)
    assert not identity_agrees(key_second, first, ACTION, STEP)
    # A folded key stays namespaced: it can never be read as a historical run id.
    assert is_work_key(key_first) and not is_work_key('run-1')


# --------------------------------------------------------------------------
# The frozen-package subject binding.
# --------------------------------------------------------------------------

def test_frozen_package_subject_ref_equal_to_the_full_package_ref_projection_is_accepted():
    binding = _frozen_binding()
    assert binding.package_ref == PACKAGE
    assert binding.subject['subject_kind'] == 'frozen_package'
    assert binding.subject['subject_ref'] == asdict(PACKAGE)
    assert set(binding.subject['subject_ref']) == {
        'realm_id', 'project_id', 'package_id', 'digest', 'kind'}
    # The binding survives its own codec unchanged.
    assert decode_dispatch(encode_dispatch(binding)) == binding


def test_a_frozen_package_subject_that_is_not_the_package_projection_reads_back_but_is_refused_at_the_write():
    """Two-sided: the exact-projection rule is a write guard, never a decode rule.

    `_check_declared_work_binding` types a `frozen_package` subject but does not
    compare it to the binding's own package. A subject that is not the full
    projection — a partial reference, a reference naming another package, or a
    reference of another shape entirely — therefore still constructs, decodes and
    re-encodes with its original bytes kept: an old v2 row stays readable. The very
    same bytes are refused by name at the active write that consumes
    `package_ref_projection` (`SQLiteWorkDispatchRepository.reserve`) as
    `DISPATCH_BINDING_INVALID`, so a declared step can never execute a reference the
    frozen package does not name.
    """
    partial = {'package_id': PACKAGE.package_id}
    renamed = dict(asdict(PACKAGE), package_id='package-2')
    other_shape = {'review_id': 'review-1'}
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    try:
        for wrong in (partial, renamed, other_shape):
            # (1) Readable: the v2 record constructs, decodes and re-encodes with
            # its original bytes; the substitution is not a decode refusal.
            binding = _frozen_binding(subject_ref=wrong)
            raw = encode_dispatch(binding)
            read = decode_dispatch(raw)
            assert read.subject == {'subject_kind': 'frozen_package', 'subject_ref': wrong}
            assert encode_dispatch(read) == raw, 'the stored bytes are never rewritten'
            # (2) Not executable: the same shape is refused by name at the real
            # schema-17 write point, before anything is persisted.
            with pytest.raises(ApplicationError) as exc:
                _reserve(repository, binding)
            assert exc.value.code == 'DISPATCH_BINDING_INVALID'
            with pytest.raises(ApplicationError) as missing:
                repository.get(IDENTITY, STEP, 1, SCOPE)
            assert missing.value.code == 'NOT_FOUND', 'nothing was written'
    finally:
        connection.close()


# --------------------------------------------------------------------------
# The owner adapter refuses a durable row that disagrees with the request.
# --------------------------------------------------------------------------

class _ReservingDispatch:
    """Labelled stand-in for the native owner: it reserves the durable Work row.

    It performs the real schema-17 reservation and returns the owner's immediate
    view. It never sends anything and holds no credential.
    """

    def __init__(self, factory, blobs, execution, repository, binding):
        self.factory, self.blobs, self.execution = factory, blobs, execution
        self._repository, self._binding = repository, binding
        self.sends = 0

    def dispatch_declared_work(self, identity, work_id, action_id, step_id, attempt,
                               unit_ref, params, actions, context, *, timeout=60):
        assert identity == self._binding.work['dispatch_key']
        _reserve(self._repository, self._binding)
        return {'phase': 'reserved', 'step_id': step_id, 'attempt': attempt,
                'engineering_completed': False, 'result_blob_ref': None}


def test_the_owner_adapter_refuses_a_durable_row_bound_to_another_unit():
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    bound = _frozen_binding(unit_ref=UNIT)          # what the durable step already bound
    operations = _operations(
        lambda factory, blobs, execution: _ReservingDispatch(
            factory, blobs, execution, repository, bound), repository=repository)

    request = dict(DECLARED_FORM, unit_ref=OTHER_UNIT)
    result = operations.dispatch_execution({'dispatch': request}, _context())
    assert result.operation == 'engineering.executions.dispatch'
    assert result.reason == 'OWNER_BINDING_MISMATCH'
    assert result.outcome == 'unknown' and result.accepted is False
    assert result.engineering_completed is False
    # The disagreement is reported, not persisted over: the row still names unit-1.
    stored = repository.get(IDENTITY, STEP, 1, SCOPE)
    assert decode_dispatch(stored['binding_bytes']).unit_ref_bytes == canonical_bytes(UNIT)
    assert _other_identity_is_untouched(repository)
    connection.close()


def _other_identity_is_untouched(repository):
    """A refused request materialises no alternative row for the same Work."""
    with pytest.raises(ApplicationError) as exc:
        repository.get(OTHER_IDENTITY, STEP, 1, SCOPE)
    return exc.value.code == 'NOT_FOUND'


# --------------------------------------------------------------------------
# The schema-17 declared-Work relation is the read path, not the run relation.
# --------------------------------------------------------------------------

def test_the_declared_work_read_path_uses_the_schema17_relation_not_the_run_relation():
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    raw, _ = _reserve(repository, _frozen_binding())

    # The declared Work has no `runs` row and none is invented for it.
    assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0
    assert connection.execute('SELECT COUNT(*) FROM step_log').fetchone()[0] == 0
    assert connection.execute('SELECT COUNT(*) FROM work_step_log').fetchone()[0] == 1

    # The query path resolves the declared step through its own relation.
    by_operation = repository.by_operation('operation-1', SCOPE)
    assert by_operation['binding_bytes'] == raw
    assert by_operation['run_id'] == IDENTITY
    assert by_operation['step_id'] == STEP

    # The historical run relation does not carry, and cannot read, this row.
    with pytest.raises(ApplicationError) as exc:
        SQLiteDispatchRepository(access).by_operation('operation-1', SCOPE)
    assert exc.value.code == 'NOT_FOUND'
    with pytest.raises(ApplicationError) as exc:
        SQLiteDispatchRepository(access).get(IDENTITY, STEP, 1, SCOPE)
    assert exc.value.code == 'NOT_FOUND'

    # The declared-Work relation has no foreign key onto `runs`.
    assert connection.execute('PRAGMA foreign_key_list(work_step_log)').fetchall() == []
    connection.close()


def test_the_work_dispatch_relation_refuses_a_library_that_is_not_schema17():
    connection, access = _database(schema_version=13)
    repository = SQLiteWorkDispatchRepository(access)
    with pytest.raises(ApplicationError) as exc:
        repository.get(IDENTITY, STEP, 1, SCOPE)
    assert exc.value.code == 'DISPATCH_SCHEMA_REQUIRED'
    with pytest.raises(ApplicationError) as exc:
        _reserve(repository, _frozen_binding())
    assert exc.value.code == 'DISPATCH_SCHEMA_REQUIRED'
    assert connection.execute('SELECT COUNT(*) FROM work_step_log').fetchone()[0] == 0
    connection.close()


# --------------------------------------------------------------------------
# The advertised admission carries the 576KiB complete-prompt limit.
# --------------------------------------------------------------------------

def test_the_advertised_dispatch_admission_carries_the_576kib_prompt_limit():
    """The declared-Work admission and capture descriptor carry their own caps.

    Complete prompt and native evidence budgets move together. The historical
    report observation limit is a separate 256KiB budget and stays unchanged.
    """
    descriptors = {item.capability_id: item for item in owner_capabilities()}
    dispatch = descriptors['engineering.executions.dispatch']
    form = dispatch.contract['input_schema']['properties']['dispatch']
    assert form['properties']['params']['x-maxCanonicalBytes'] == 576 * 1024
    assert dispatch.contract['limits']['prompt_canonical_bytes_max'] == 576 * 1024
    assert dispatch.contract['limits']['unit_ref_canonical_bytes_max'] == 4096
    report = descriptors['engineering.submissions.record_report']
    assert report.contract['limits']['report_observation_bytes_max'] == 256 * 1024
    assert report.contract['limits']['declared_work_report_observation_bytes_max'] == 2621440
