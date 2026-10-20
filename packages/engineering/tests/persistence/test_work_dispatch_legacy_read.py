"""Historical declared-Work dispatch records on the real schema-17 relation.

Two historical facts are asserted here, both about records written *before* a
source change rather than about a fresh write:

* the frozen-package subject's exact-projection rule moved from decode to the
  active write point (`SQLiteWorkDispatchRepository.reserve`). A v2 row written
  before that guard therefore still decodes and reads back with its original
  bytes, while the very same bytes are refused at the write point; and
* the declared-Work key fix keeps two identity entries apart: the *current* key
  a new write mints, and an explicit *historical* folded form a read uses to
  recognise a row written before the fix. Such a row is returned with its own
  original key and bytes, is reported by the Work view as unretryable, and is
  never re-sent or re-minted.

Every historical record below is written as *raw historical v2 bytes* straight
into the relation; a current fixture is never substituted for a historical
record. The library, the relation, the repository, the codec and the Work view
are the real ones; only the caller's access and the Unit transport are labelled
local doubles (no platform identity, credential or network).
"""
import hashlib
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.dispatch_identity import (
    historical_identity_agrees, identity_is_current, is_folded_work_key, is_work_key,
    work_dispatch_key, work_dispatch_key_candidates,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import (
    SQLiteWorkDispatchRepository)
from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import (
    DISPATCH_DDL, WORK_DISPATCH_DDL, WORK_DISPATCH_SCHEMA_VERSION)
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary)
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
    DeclaredGenerationDispatch)
from ordessa_engineering.application.usecases.queries.works import WorkQueries
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding, package_ref_projection
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.reviews.refs import ReviewRef

# The historical-UNKNOWN case below drives the *real* `dispatch_generation`
# entry, whose real owners (the reviewed source chain, review admission and
# method guard) are built by the application-test fixtures. Put that sibling
# test directory on the path so this file also runs when selected on its own.
_APPLICATION_TESTS = Path(__file__).resolve().parent.parent / 'application'
if str(_APPLICATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_APPLICATION_TESTS))

SCOPE = Scope('work-dispatch-legacy-realm', 'work-dispatch-legacy-project')
WORK_ID = 'work-1'
ACTION = 'incremental.prepare-packages'
# The declared generation step's own `step_id`, exactly as the released
# declaration spells it (`methods/incremental-engineering/candidates/2.7.2/
# actions/prepare-packages.json`: `{"step_id": "draft", "name":
# "prepare-spec-kit-package"}`). The real generation entry and the public Work
# view both key on this id; `prepare-spec-kit-package` is that step's *name*,
# never its id, so a row seeded under the name is not the generation row and the
# view cannot (and must not) report it.
STEP = 'draft'
WORK_IDS = (WORK_ID, 'work-frozen', 'work-legacy-1', 'work-legacy-2',
            'work-legacy-write-1', 'work-legacy-write-2')

BASE_DDL = """
CREATE TABLE library_meta(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL);
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

_OPERATION = 'engineering.execution.dispatch'


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


class _NeverAccess:
    """A Work view is a read: this authority must never be asked anything."""

    def require(self, *_args, **_kwargs):
        raise AssertionError('the read path must not consult the write authority')


def _work_body(work_id):
    return canonical_bytes({'work_id': work_id,
                            'scope': {'realm_id': SCOPE.realm_id,
                                      'project_id': SCOPE.project_id},
                            'method_ref': {'method_id': 'ordessa.incremental-engineering',
                                           'release_version': '2.7.2',
                                           'snapshot_digest': 'a' * 64},
                            'revision': 1}).decode('utf-8')


def _database():
    connection = sqlite3.connect(':memory:')
    connection.executescript(BASE_DDL)
    connection.execute('INSERT INTO library_meta VALUES (1, ?)', (WORK_DISPATCH_SCHEMA_VERSION,))
    connection.executescript(DISPATCH_DDL)
    connection.executescript(WORK_DISPATCH_DDL)
    for work_id in WORK_IDS:
        connection.execute(
            'INSERT INTO materials VALUES (?,?,?,?,?,?)',
            ('work-context', 'declarative-work:' + work_id, 1, 'f' * 64, _work_body(work_id), 0))
    connection.commit()
    connection.execute('BEGIN')
    return connection, _Access(connection, SCOPE)


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _unit_bytes():
    return canonical_bytes({'environmentNamespace': 'env', 'unitId': 'unit-1',
                            'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})


def _prompt_ref():
    return BlobRef(Digest('sha256', 'c' * 64), 10, 'application/json', 'prompt-object')


def _generation_subject():
    """The reviewed change, its review, the pinned method and the inputs digest."""
    return {'review_ref': asdict(ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-1',
                                           Digest('sha256', 'd' * 64))),
            'change_ref': asdict(ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1',
                                             'proposal-1', Digest('sha256', 'f' * 64))),
            'method_ref': asdict(MethodRef('ordessa.incremental-engineering', '2.7.2', 1,
                                           Digest('sha256', 'b' * 64))),
            'inputs_digest': asdict(Digest('sha256', 'e' * 64))}


def _generation_binding(*, work_id, action_id=ACTION, step_id=STEP, key=None):
    key = work_dispatch_key(work_id, action_id, step_id) if key is None else key
    return DispatchBinding(
        SCOPE, key, step_id, 1, 1, None, None, None, None,
        (('generate_package', 'instance-1'),), _unit_bytes(), 'operation-1',
        _prompt_ref(), Digest('sha256', 'd' * 64), 'q' * 64, ('submission',),
        binding_version=2,
        work={'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
              'dispatch_key': key},
        subject={'subject_kind': 'reviewed_change', 'subject_ref': _generation_subject()})


def _frozen_binding(*, work_id, action_id=ACTION, step_id=STEP, key=None,
                    package_ref=None, subject_ref=None):
    package_ref = (ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-1',
                                            Digest('sha256', 'a' * 64))
                   if package_ref is None else package_ref)
    key = work_dispatch_key(work_id, action_id, step_id) if key is None else key
    return DispatchBinding(
        SCOPE, key, step_id, 1, 1, package_ref,
        ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-1', Digest('sha256', 'c' * 64)),
        Digest('sha256', 'b' * 64), 0,
        (('edit_repository', 'instance-1'),), _unit_bytes(), 'operation-1',
        _prompt_ref(), Digest('sha256', 'd' * 64), 'q' * 64, ('submission',),
        binding_version=2,
        work={'work_id': work_id, 'action_id': action_id, 'step_id': step_id,
              'dispatch_key': key},
        subject={'subject_kind': 'frozen_package',
                 'subject_ref': (package_ref_projection(package_ref) if subject_ref is None
                                 else subject_ref)})


def _insert_raw(connection, dispatch_key, step_id, attempt, binding_bytes, operation_ref, *,
                scope=SCOPE):
    """Write one row exactly as the pre-fix writer left it: raw bytes, reserved.

    Nothing here re-encodes or re-derives the binding; the row carries the
    original bytes and their digest under the original key. The scope is the
    module scope by default; a caller seeding against another real chain passes
    that chain's own scope.
    """
    digest_hex = hashlib.sha256(binding_bytes).hexdigest()
    scope_json = canonical_bytes(asdict(scope)).decode('utf-8')
    marker = canonical_bytes({'dispatch': 'reserved', 'binding_digest': digest_hex,
                              'operation_ref': operation_ref}).decode('utf-8')
    connection.execute(
        'INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,'
        'receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,'
        'execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
        'result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (dispatch_key, 0, step_id, _OPERATION, attempt, 'reserved', marker, scope_json,
         digest_hex, binding_bytes, operation_ref, 'reserved', 0, 1, None))


# --------------------------------------------------------------------------
# A pre-guard v2 frozen-package row: readable, but not writable.
# --------------------------------------------------------------------------

def test_a_pre_guard_v2_frozen_package_row_reads_back_while_the_write_refuses_it():
    """The exact-projection rule is a write guard, not a decode rule.

    A subject that names another package, or states only part of the reference,
    was accepted by the codec before the guard existed. Such a row must still
    decode and read back with its original bytes — and the same bytes must be
    refused at the active write point, never silently re-written.
    """
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    bound = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-1',
                                     Digest('sha256', 'a' * 64))
    other = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-2',
                                     Digest('sha256', 'a' * 64))
    wrong_subjects = (package_ref_projection(other),            # another package
                      {'package_id': bound.package_id})          # a partial projection
    for index, wrong in enumerate(wrong_subjects, start=1):
        read_key = work_dispatch_key('work-legacy-%d' % index, ACTION, STEP)
        binding = _frozen_binding(work_id='work-legacy-%d' % index, key=read_key,
                                  package_ref=bound, subject_ref=wrong)
        raw = encode_dispatch(binding)
        # The historical bytes decode: decode never applies the active-write guard.
        decoded = decode_dispatch(raw)
        assert decoded.subject == {'subject_kind': 'frozen_package', 'subject_ref': wrong}
        assert encode_dispatch(decoded) == raw

        _insert_raw(connection, read_key, STEP, 1, raw, 'legacy-operation-%d' % index)
        stored = repository.get(read_key, STEP, 1, SCOPE)
        assert stored['binding_bytes'] == raw
        assert stored['dispatch_phase'] == 'reserved'
        assert decode_dispatch(stored['binding_bytes']).subject['subject_ref'] == wrong

        # The same bytes are refused at the write point. The Work does not exist,
        # so only the subject guard can be the reason; a fresh identity keeps the
        # duplicate-attempt check out of the way.
        write_key = work_dispatch_key('work-legacy-write-%d' % index, ACTION, STEP)
        write_binding = _frozen_binding(work_id='work-legacy-write-%d' % index,
                                        key=write_key, package_ref=bound, subject_ref=wrong)
        write_raw = encode_dispatch(write_binding)
        with pytest.raises(ApplicationError) as exc:
            repository.reserve(write_key, STEP, 1, SCOPE, write_raw, _digest(write_raw),
                               'operation-write-%d' % index)
        assert exc.value.code == 'DISPATCH_BINDING_INVALID'
    connection.close()


# --------------------------------------------------------------------------
# A row stored under the pre-fix folded key: found, never re-minted.
# --------------------------------------------------------------------------

def test_a_historical_folded_key_row_is_found_by_the_explicit_historical_entry():
    """A row written before the key fix keeps its own key and bytes.

    The current entry never accepts the historical key and the historical entry
    never mints one; a read reconciles the two candidates, so such a row is
    recognised instead of reading as absent.
    """
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    work_id, action, step = 'w' * 400, 'a' * 100, 's' * 100
    current = work_dispatch_key(work_id, action, step)
    candidates = work_dispatch_key_candidates(work_id, action, step)
    assert len(candidates) == 2 and candidates[0] == current
    historical = candidates[1]
    assert historical != current and len(historical) <= 512
    assert is_work_key(historical) and is_folded_work_key(historical)
    # The two identity entries are deliberately apart.
    assert identity_is_current(current, work_id, action, step)
    assert not identity_is_current(historical, work_id, action, step)
    assert historical_identity_agrees(historical, work_id, action, step)

    binding = _generation_binding(work_id=work_id, action_id=action, step_id=step,
                                  key=historical)
    raw = encode_dispatch(binding)
    _insert_raw(connection, historical, step, 1, raw, 'historical-operation-1')

    stored = repository.get(historical, step, 1, SCOPE)
    assert stored['run_id'] == historical          # the original key, unchanged
    assert stored['binding_bytes'] == raw          # the original bytes, unchanged
    assert repository.by_operation('historical-operation-1', SCOPE)['run_id'] == historical

    # A new write never adopts the historical key: it mints exactly the current one.
    with pytest.raises(ApplicationError) as exc:
        repository.reserve(historical, step, 1, SCOPE, raw, _digest(raw),
                           'historical-operation-2')
    assert exc.value.code == 'DISPATCH_BINDING_INVALID'
    connection.close()


# --------------------------------------------------------------------------
# A historical UNKNOWN row: reported, unretryable, never re-sent.
# --------------------------------------------------------------------------

def test_a_historical_unknown_row_is_reported_unretryable_and_not_re_sent(tmp_path):
    """A stored unknown attempt must be visible, not read as absent.

    The Work view and the generation adapter's re-entry decision both look up
    the current *and* the historical folded key. A found attempt is returned with
    its own key and bytes and `retry_allowed` false, and the relation still holds
    exactly one row and one operation: no second send is recorded.
    """
    path = (tmp_path / 'historical-unknown.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='historical-unknown',
                                        schema_version=WORK_DISPATCH_SCHEMA_VERSION)
    try:
        connection = library._connection
        if not connection.in_transaction:
            connection.execute('BEGIN')
        access = _Access(connection, SCOPE)
        repository = SQLiteWorkDispatchRepository(access)

        work_id, action, step = 'w' * 480, 'incremental.prepare-packages', 'draft'
        historical = work_dispatch_key_candidates(work_id, action, step)[1]
        assert historical != work_dispatch_key(work_id, action, step)
        binding = _generation_binding(work_id=work_id, action_id=action, step_id=step,
                                      key=historical)
        raw = encode_dispatch(binding)
        _insert_raw(connection, historical, step, 1, raw, 'historical-operation-unknown')
        repository.transition(historical, step, 1, SCOPE, expected_version=0, fence=1,
                              phase='possibly_written')
        repository.transition(historical, step, 1, SCOPE, expected_version=1, fence=1,
                              phase='unknown')
        connection.commit()
        assert connection.execute('SELECT COUNT(*) FROM work_step_log').fetchone()[0] == 1

        # The Work view finds the historical row and never allows a retry.
        view = WorkQueries(SQLiteUoWFactory(library), _NeverAccess())._generation_dispatch(
            SimpleNamespace(scope=SCOPE), work_id)
        assert view is not None
        assert view['dispatch_key'] == historical and view['phase'] == 'unknown'
        assert view['retry_allowed'] is False
        assert view['unknown_requires_reconciliation'] is True
        assert view['binding_bytes'] == raw

        # The adapter's re-entry decision resolves the same row through the same
        # candidate list and reports it as already dispatched.
        with SQLiteUoWFactory(library).begin(SCOPE, 'read') as uow:
            existing = DeclaredGenerationDispatch._existing(uow, work_id, action, step, 1)
            assert existing is not None and existing['run_id'] == historical
            reentry = DeclaredGenerationDispatch._view(existing, already_dispatched=True)
        assert reentry['already_dispatched'] is True and reentry['phase'] == 'unknown'
        assert reentry['identity'] == historical
        assert reentry['binding_bytes'] == raw

        # Nothing was re-sent: one row, one operation, the original one.
        assert connection.execute('SELECT COUNT(*) FROM work_step_log').fetchone()[0] == 1
        assert connection.execute(
            'SELECT COUNT(*) FROM work_step_log WHERE execution_operation_ref=?',
            ('historical-operation-unknown',)).fetchone()[0] == 1
    finally:
        library.close()


# --------------------------------------------------------------------------
# The current 2.7.2 Work/generation fixture, by the current algorithm.
# --------------------------------------------------------------------------

def test_the_current_2_7_2_generation_fixture_reserves_and_reads_back():
    connection, access = _database()
    repository = SQLiteWorkDispatchRepository(access)
    binding = _generation_binding(work_id=WORK_ID)
    key = binding.work['dispatch_key']
    assert key == work_dispatch_key(WORK_ID, ACTION, STEP)
    assert identity_is_current(key, WORK_ID, ACTION, STEP)
    raw = encode_dispatch(binding)
    record = repository.reserve(key, STEP, 1, SCOPE, raw, _digest(raw), 'operation-1')
    assert record['dispatch_phase'] == 'reserved' and record['run_id'] == key
    assert record['binding_bytes'] == raw
    stored = repository.get(key, STEP, 1, SCOPE)
    assert decode_dispatch(stored['binding_bytes']) == binding

    # The frozen-package positive path: the exact projection of the bound
    # package is what the write guard accepts.
    package = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-1',
                                       Digest('sha256', 'a' * 64))
    frozen = _frozen_binding(work_id='work-frozen', package_ref=package)
    frozen_raw = encode_dispatch(frozen)
    frozen_record = repository.reserve(frozen.work['dispatch_key'], STEP, 1, SCOPE,
                                       frozen_raw, _digest(frozen_raw), 'operation-frozen')
    assert frozen_record['dispatch_phase'] == 'reserved'
    assert decode_dispatch(frozen_record['binding_bytes']).subject['subject_ref'] == (
        package_ref_projection(package))
    connection.close()


# --------------------------------------------------------------------------
# A short identity never admits a fabricated historical fold.
# --------------------------------------------------------------------------

def _historical_folded_key_for(work_id, action_id, step_id):
    """Reproduce the pre-fix folded form *only* to test what it is admitted for.

    The pre-fix algorithm spelled the escaped fields out and folded *only* when
    the spelled key exceeded the key bound, cutting the folded result to that
    bound. This recomputes that exact form so a test can present it to the
    identity contract.
    """
    parts = tuple(value.replace('%', '%25').replace(':', '%3A')
                  for value in (work_id, action_id, step_id))
    digest = 'sha256:' + hashlib.sha256(canonical_bytes(list(parts))).hexdigest()
    folded = ':'.join(('w1h',) + parts + (digest,))
    return folded if len(folded) <= 512 else folded[:512]


def test_a_short_identity_admits_only_the_current_key_not_a_fabricated_fold():
    """A short id combination was never folded, so its folded form is a ghost.

    The pre-fix algorithm kept the spelled-out key for a short combination, and
    that spelled key is already the current key. Recognising a folded form for
    such a combination would invent a key no writer ever minted, so only the
    current key is admitted — while a long combination, which the old algorithm
    did fold, still admits its historical form.
    """
    short_work, short_action, short_step = 'short-work', ACTION, STEP
    current = work_dispatch_key(short_work, short_action, short_step)
    assert is_work_key(current) and not is_folded_work_key(current)
    # The candidate list offers exactly one form: the current spelled key.
    assert work_dispatch_key_candidates(short_work, short_action, short_step) == (current,)
    fabricated = _historical_folded_key_for(short_work, short_action, short_step)
    assert fabricated != current
    assert is_work_key(fabricated) and is_folded_work_key(fabricated)
    assert identity_is_current(fabricated, short_work, short_action, short_step) is False
    assert historical_identity_agrees(fabricated, short_work, short_action, short_step) is False

    # A long combination *was* folded by the old algorithm: its historical form
    # is recognised, and it is still never the current key.
    long_work = 'w' * 480
    current_long = work_dispatch_key(long_work, ACTION, STEP)
    candidates = work_dispatch_key_candidates(long_work, ACTION, STEP)
    assert len(candidates) == 2 and candidates[0] == current_long
    historical = candidates[1]
    assert historical == _historical_folded_key_for(long_work, ACTION, STEP)
    assert historical != current_long
    assert is_work_key(historical) and is_folded_work_key(historical)
    assert identity_is_current(historical, long_work, ACTION, STEP) is False
    assert historical_identity_agrees(historical, long_work, ACTION, STEP) is True


# --------------------------------------------------------------------------
# A historical UNKNOWN re-enters the real entry and never sends.
# --------------------------------------------------------------------------

def test_a_historical_unknown_row_reenters_the_real_entry_without_a_send(tmp_path, monkeypatch):
    """A stored historical UNKNOWN is re-entered through the real entry.

    The row is written before the key fix, under the pre-fix folded form, as raw
    historical bytes at the SQL layer — never through a current `reserve`. The
    real `dispatch_generation` entry then finds it by its candidate list and
    returns the original key, bytes and phase *without* calling the transport.
    The witness is the transport's own send counter, not a helper return value
    nor a row count; the Work view reports the same attempt as unretryable.

    The id is a *legal* one, and the pre-fix algorithm really folded it and then
    really cut the folded result to the key bound, so the key this row is seeded
    under is one that writer itself could have left.
    """
    import asyncio

    from ordessa_engineering.application.contracts.work_context import (
        WORK_STABLE_ID_PREFIX, WorkAssociation, WorkBinding, work_binding_projection)
    from test_real_source_chain import (
        SCOPE as CHAIN_SCOPE, close_chain, context as chain_context)
    from test_work_invoke_generation import (
        _Transport, _chain_adapter, _chain_ready, _unit_ref)
    from work_step_access_fixture import enable_controlled_work_steps

    enable_controlled_work_steps(monkeypatch)
    env, chain, blob = _chain_ready(tmp_path)
    try:
        # A legal id whose pre-fix key was folded: `':' * 170` escapes to 510
        # characters, so the spelled key is 548 and the old algorithm folded it —
        # and then cut the folded result, because the escaped fields plus the
        # whole-field digest exceed the 512-character key bound. It is legal for
        # the Work's own writer too: `declarative-work:` plus this id is 187
        # characters, inside the 192-character material-identifier bound. The
        # Work is written through that authorized writer, binding exactly the
        # reviewed change the entry re-derives from the owners.
        work_id = ':' * 170
        work = WorkBinding(work_id, CHAIN_SCOPE, env.method, 1,
                           (WorkAssociation('proposal', chain.successor),))
        with env.factory.begin(CHAIN_SCOPE) as uow:
            uow.workflow.write_work_context(stable_id=WORK_STABLE_ID_PREFIX + work_id,
                                            revision=1, body=work_binding_projection(work))
            uow.commit()

        current = work_dispatch_key(work_id, ACTION, STEP)
        candidates = work_dispatch_key_candidates(work_id, ACTION, STEP)
        assert len(candidates) == 2 and candidates[0] == current
        historical = candidates[1]
        # The historical form the pre-fix writer itself could have left: the
        # escaped fields spelled out, the whole field set digested, then cut to
        # the key bound. A folded key carries no fields back, so its `w1h` prefix
        # and its length at that bound are the whole shape there is to assert.
        assert historical != current
        assert historical.startswith('w1h') and len(historical) == 512
        assert is_folded_work_key(historical)
        assert historical_identity_agrees(historical, work_id, ACTION, STEP)
        assert not identity_is_current(historical, work_id, ACTION, STEP)

        unit_ref = _unit_ref()
        params = {'p': 1}
        transport = _Transport(blob, blobs=env.blobs)
        snapshot = transport.freeze_input(unit_ref, params)[1]
        # The reviewed-change subject the real entry re-derives from the owners:
        # the same change, review, method and frozen input digest.
        evidence = {'change_ref': asdict(chain.successor), 'review_ref': asdict(chain.review_ref),
                    'method_ref': asdict(env.method), 'inputs_digest': asdict(snapshot)}
        binding = DispatchBinding(
            CHAIN_SCOPE, historical, STEP, 1, 1, None, None, None, None,
            (('generate_package', 'instance-1'),), canonical_bytes(unit_ref),
            'historical-operation-unknown', _prompt_ref(), snapshot, 'q' * 64, ('submission',),
            binding_version=2,
            work={'work_id': work_id, 'action_id': ACTION, 'step_id': STEP,
                  'dispatch_key': historical},
            subject={'subject_kind': 'reviewed_change', 'subject_ref': evidence})
        raw = encode_dispatch(binding)

        connection = env.library._connection
        if not connection.in_transaction:
            connection.execute('BEGIN')
        access = _Access(connection, CHAIN_SCOPE)
        repository = SQLiteWorkDispatchRepository(access)
        _insert_raw(connection, historical, STEP, 1, raw, 'historical-operation-unknown',
                    scope=CHAIN_SCOPE)
        repository.transition(historical, STEP, 1, CHAIN_SCOPE, expected_version=0, fence=1,
                              phase='possibly_written')
        repository.transition(historical, STEP, 1, CHAIN_SCOPE, expected_version=1, fence=1,
                              phase='unknown')
        connection.commit()
        assert connection.execute(
            'SELECT COUNT(*) FROM work_step_log WHERE dispatch_key=?',
            (historical,)).fetchone()[0] == 1

        # The real entry: a controlled re-entry that resolves the historical row.
        adapter = _chain_adapter(env, transport)
        outcome = adapter.dispatch_generation(
            work_id, ACTION, STEP, 1, unit_ref, params, chain_context('historical-unknown-reentry'),
            change_ref=chain.successor, review_ref=chain.review_ref, method_ref=env.method)
        assert outcome['already_dispatched'] is True
        assert outcome['phase'] == 'unknown'
        assert outcome['identity'] == historical
        assert outcome['binding_bytes'] == raw
        # The witness: the transport's own send counter never advanced.
        assert transport.sends == 0

        view = asyncio.run(env.service.query('engineering.work.get', {'work_id': work_id},
                                             chain_context('read-historical-unknown')))
        assert view['generation_dispatch']['phase'] == 'unknown'
        assert view['generation_dispatch']['retry_allowed'] is False
        assert view['generation_dispatch']['unknown_requires_reconciliation'] is True
        assert transport.sends == 0
        # No second attempt was recorded for this Work either.
        assert connection.execute(
            'SELECT COUNT(*) FROM work_step_log WHERE dispatch_key=?',
            (historical,)).fetchone()[0] == 1
    finally:
        close_chain(env)


def test_a_historical_unknown_row_under_the_spelled_key_reenters_without_a_send(
        tmp_path, monkeypatch):
    """The same zero-send re-entry for an id the old algorithm never folded.

    A short id combination has exactly one key form: the spelled-out key, which
    is already the current key. The historical row is therefore seeded under
    that form — the only key the pre-fix writer could have left for this Work —
    and the real `dispatch_generation` entry still finds it and still never
    sends. The explicit historical folded form is an addition for ids too long
    to spell out, never a replacement for the ordinary key.
    """
    import asyncio

    from ordessa_engineering.application.contracts.work_context import (
        WORK_STABLE_ID_PREFIX, WorkAssociation, WorkBinding, work_binding_projection)
    from test_real_source_chain import (
        SCOPE as CHAIN_SCOPE, close_chain, context as chain_context)
    from test_work_invoke_generation import (
        _Transport, _chain_adapter, _chain_ready, _unit_ref)
    from work_step_access_fixture import enable_controlled_work_steps

    enable_controlled_work_steps(monkeypatch)
    env, chain, blob = _chain_ready(tmp_path)
    try:
        work_id = 'historical-unknown-spelled'
        work = WorkBinding(work_id, CHAIN_SCOPE, env.method, 1,
                           (WorkAssociation('proposal', chain.successor),))
        with env.factory.begin(CHAIN_SCOPE) as uow:
            uow.workflow.write_work_context(stable_id=WORK_STABLE_ID_PREFIX + work_id,
                                            revision=1, body=work_binding_projection(work))
            uow.commit()

        key = work_dispatch_key(work_id, ACTION, STEP)
        # Never folded: the pre-fix algorithm's only form for this combination is
        # the spelled key, so the candidate list offers exactly that one form.
        assert work_dispatch_key_candidates(work_id, ACTION, STEP) == (key,)
        assert not is_folded_work_key(key)
        assert identity_is_current(key, work_id, ACTION, STEP)

        unit_ref = _unit_ref()
        params = {'p': 1}
        transport = _Transport(blob, blobs=env.blobs)
        snapshot = transport.freeze_input(unit_ref, params)[1]
        evidence = {'change_ref': asdict(chain.successor), 'review_ref': asdict(chain.review_ref),
                    'method_ref': asdict(env.method), 'inputs_digest': asdict(snapshot)}
        binding = DispatchBinding(
            CHAIN_SCOPE, key, STEP, 1, 1, None, None, None, None,
            (('generate_package', 'instance-1'),), canonical_bytes(unit_ref),
            'historical-operation-spelled', _prompt_ref(), snapshot, 'q' * 64, ('submission',),
            binding_version=2,
            work={'work_id': work_id, 'action_id': ACTION, 'step_id': STEP,
                  'dispatch_key': key},
            subject={'subject_kind': 'reviewed_change', 'subject_ref': evidence})
        raw = encode_dispatch(binding)

        connection = env.library._connection
        if not connection.in_transaction:
            connection.execute('BEGIN')
        access = _Access(connection, CHAIN_SCOPE)
        repository = SQLiteWorkDispatchRepository(access)
        _insert_raw(connection, key, STEP, 1, raw, 'historical-operation-spelled',
                    scope=CHAIN_SCOPE)
        repository.transition(key, STEP, 1, CHAIN_SCOPE, expected_version=0, fence=1,
                              phase='possibly_written')
        repository.transition(key, STEP, 1, CHAIN_SCOPE, expected_version=1, fence=1,
                              phase='unknown')
        connection.commit()
        assert connection.execute(
            'SELECT COUNT(*) FROM work_step_log WHERE dispatch_key=?',
            (key,)).fetchone()[0] == 1

        adapter = _chain_adapter(env, transport)
        outcome = adapter.dispatch_generation(
            work_id, ACTION, STEP, 1, unit_ref, params,
            chain_context('spelled-unknown-reentry'),
            change_ref=chain.successor, review_ref=chain.review_ref, method_ref=env.method)
        assert outcome['already_dispatched'] is True
        assert outcome['phase'] == 'unknown'
        assert outcome['identity'] == key
        assert outcome['binding_bytes'] == raw
        # The witness: the transport's own send counter never advanced.
        assert transport.sends == 0

        view = asyncio.run(env.service.query('engineering.work.get', {'work_id': work_id},
                                             chain_context('read-spelled-unknown')))
        assert view['generation_dispatch']['phase'] == 'unknown'
        assert view['generation_dispatch']['retry_allowed'] is False
        assert view['generation_dispatch']['unknown_requires_reconciliation'] is True
        assert transport.sends == 0
        assert connection.execute(
            'SELECT COUNT(*) FROM work_step_log WHERE dispatch_key=?',
            (key,)).fetchone()[0] == 1
    finally:
        close_chain(env)
