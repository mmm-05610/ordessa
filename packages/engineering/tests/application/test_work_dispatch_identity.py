"""The declared-Work dispatch identity and the read-back an active entry accepts.

Two things are under test, both about *identity* rather than execution:

* `work_dispatch_key` folds a very long but legal id into one fixed-size digest
  of the whole field set. It never truncates: a cut key let two distinct
  identities share one, and a stored key is verified by recomputing that digest
  from the original fields.
* `EngineeringOwnerOperations.dispatch_execution` accepts only the declared Work
  form (never a run), reads its row from the declared-Work relation (schema 17)
  and re-checks the stored Work identity, attempt, binding digest and persisted
  result before it reports anything.

The Unit transport, the owner, the access authority and the blob store are
labelled local doubles or the real same-authority storage; no platform identity,
credential or network is involved, and nothing here claims a live dispatch or a
grant.
"""
import hashlib
from dataclasses import asdict

import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.dispatch_identity import (
    identity_agrees, is_folded_work_key, is_work_key, split_work_dispatch_key,
    work_dispatch_key,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, package_ref_projection,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes

SCOPE = Scope('work-dispatch-realm', 'work-dispatch-project')
LIBRARY_ID = 'test.work-dispatch-identity'
CREATED_AT = '2026-10-09T12:00:00.000000Z'
ACTOR = ActorRef('test-human', 'human', 'synthetic-test-issuer')

WORK_ID = 'work-1'
OTHER_WORK_ID = 'work-2'
ACTION = 'incremental.prepare-packages'
STEP = 'prepare-spec-kit-package'
ACTIONS = ('edit_repository',)
UNIT_A = {'environmentNamespace': 'env', 'unitId': 'unit-a',
          'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}
UNIT_B = {'environmentNamespace': 'env', 'unitId': 'unit-b',
          'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}


def _sha(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _context(request_id):
    return CommandContext(SCOPE, 'principal-1', ACTOR, request_id, CREATED_AT, 'trace-1')


def _work_body(work_id):
    return {'work_id': work_id, 'revision': 1,
            'scope': {'realm_id': SCOPE.realm_id, 'project_id': SCOPE.project_id},
            'method_ref': {'method_id': 'incremental-engineering', 'release_version': '2.7.2',
                           'snapshot_digest': 'a' * 64}}


def _package_ref(package_id='package-1'):
    return ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, package_id,
                                    _sha(b'package:' + package_id.encode()))


def _frozen_subject(package_ref):
    """A frozen-package subject: the exact projection of the package it acts on."""
    return {'subject_kind': 'frozen_package',
            'subject_ref': package_ref_projection(package_ref)}


def _declared_binding(*, work_id=WORK_ID, unit_ref=UNIT_A, package_ref=None, key=None,
                      step_id=STEP, attempt=1, subject=None):
    """One frozen declared-Work binding; the caller owns the identity it is stored under."""
    package_ref = _package_ref() if package_ref is None else package_ref
    prompt_raw = canonical_bytes({'prompt': 'frozen'})
    return encode_dispatch(DispatchBinding(
        SCOPE, key, step_id, attempt, 1, package_ref,
        ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-1', _sha(b'approval')),
        _sha(b'intent'), 0, ((ACTIONS[0], 'instance-1'),),
        canonical_bytes(unit_ref), 'operation-1',
        BlobRef(_sha(b'prompt'), len(prompt_raw), 'application/json', 'prompt-object'),
        _sha(prompt_raw), 'q' * 64, ('submission',), binding_version=2,
        work={'work_id': work_id, 'action_id': ACTION, 'step_id': step_id,
              'dispatch_key': key},
        subject=_frozen_subject(package_ref) if subject is None else subject))


# -- the identity itself ----------------------------------------------------
def _removed_truncating_fold(work_id, action_id, step_id):
    """The previous fold, reproduced *only* to show the collision it had.

    It kept the escaped fields and then cut the result to the key bound, so two
    distinct identities sharing that window produced one identical key.
    """
    parts = tuple(value.replace('%', '%25').replace(':', '%3A')
                  for value in (work_id, action_id, step_id))
    digest = 'sha256:' + hashlib.sha256(canonical_bytes(list(parts))).hexdigest()
    folded = ':'.join(('w1h',) + parts + (digest,))
    return folded[:512]


def test_a_long_legal_identity_folds_its_whole_field_set_without_colliding():
    # Two distinct ids that share the whole 512-character window the removed
    # truncating fold kept: it mapped them onto one key.
    shared, action, step = 'w' * 508, 'a' * 100, 's' * 100
    first, second = shared + 'aaa', shared + 'bbb'
    key_first = work_dispatch_key(first, action, step)
    key_second = work_dispatch_key(second, action, step)
    assert first != second and len(first) <= 512 and len(second) <= 512
    assert is_work_key(key_first) and is_folded_work_key(key_first)
    assert is_work_key(key_second) and is_folded_work_key(key_second)
    assert len(key_first) <= 512
    # The removed truncating fold mapped both distinct identities onto one key.
    assert _removed_truncating_fold(first, action, step) == _removed_truncating_fold(
        second, action, step)
    # The folded key covers every field, so they never share one.
    assert key_first != key_second
    with pytest.raises(ApplicationError):
        split_work_dispatch_key(key_first)
    assert identity_agrees(key_first, first, action, step)
    assert not identity_agrees(key_first, second, action, step)
    assert not identity_agrees(key_second, first, action, step)


def test_a_historical_truncated_folded_row_is_still_verifiable_read_only():
    work_id, action, step = 'w' * 400, 'a' * 100, 's' * 100
    stored = _removed_truncating_fold(work_id, action, step)
    assert is_work_key(stored) and is_folded_work_key(stored)
    # Its bytes are never rewritten; only the digest is recomputed from the
    # original fields, so the row can still be checked against them.
    assert identity_agrees(stored, work_id, action, step)
    assert not identity_agrees(stored, work_id, action, 'x' * 100)
    assert not identity_agrees(stored, work_id, action + '-other', step)
    # and it is not the key a new write mints for the same fields
    assert work_dispatch_key(work_id, action, step) != stored


def test_a_frozen_package_subject_naming_another_package_reads_back_but_is_refused_at_the_write(tmp_path):
    """Two-sided: a substituted frozen-package subject is readable, never executable.

    `_check_declared_work_binding` types a `frozen_package` subject but does not
    compare it to the binding's own package, so a subject naming another package -
    or stating only part of the reference - still constructs, encodes and decodes
    with its bytes kept: an old v2 row stays readable. The same shape is refused by
    name at the active write: the schema-17 `work_dispatch.reserve` consumes
    `package_ref_projection` and refuses a subject that is not the bounded package's
    own full projection, as `DISPATCH_BINDING_INVALID`, writing nothing.
    """
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        identity = work_dispatch_key(WORK_ID, ACTION, STEP)
        # The one canonical subject the active write admits, so the refusals below
        # are the substitution, not the shape.
        accepted = _declared_binding(key=identity)
        assert decode_dispatch(accepted).subject['subject_ref'] == package_ref_projection(
            _package_ref('package-1'))
        _seed(factory, identity, accepted)
        # Decode keeps its own structural gate: an empty subject reference is
        # refused at construction, so the permissive path is exactly "typed but not
        # compared", never "anything goes".
        with pytest.raises(ReferenceError):
            _declared_binding(key=identity,
                              subject={'subject_kind': 'frozen_package', 'subject_ref': {}})
        for attempt, swapped in enumerate((
                _frozen_subject(_package_ref('package-2')),
                {'subject_kind': 'frozen_package',
                 'subject_ref': {'package_id': 'package-1', 'kind': 'implementation_package'}},
                {'subject_kind': 'frozen_package',
                 'subject_ref': {**package_ref_projection(_package_ref('package-1')),
                                 'project_id': 'other-project'}}), start=2):
            # (1) Readable: the record constructs, decodes and re-encodes unchanged.
            raw = _declared_binding(key=identity, subject=swapped, attempt=attempt)
            assert decode_dispatch(raw).subject['subject_ref'] == swapped['subject_ref']
            assert encode_dispatch(decode_dispatch(raw)) == raw
            # (2) Not executable: the real schema-17 write refuses it by name, and
            # the Work it names does exist, so only the subject can be the reason.
            with pytest.raises(ApplicationError) as exc:
                with factory.begin(SCOPE) as uow:
                    uow.work_dispatch.reserve(identity, STEP, attempt, SCOPE, raw,
                                              _sha(raw), 'operation-%d' % attempt)
                    uow.commit()
            assert exc.value.code == 'DISPATCH_BINDING_INVALID'
        # Nothing was written for any refused subject; the accepted row stands.
        with factory.begin(SCOPE, 'read') as uow:
            assert uow.work_dispatch.get(identity, STEP, 1, SCOPE)['binding_bytes'] == accepted
            for attempt in (2, 3, 4):
                with pytest.raises(ApplicationError) as missing:
                    uow.work_dispatch.get(identity, STEP, attempt, SCOPE)
                assert missing.value.code == 'NOT_FOUND'
    finally:
        library.close()


# -- the active entry, its form and its read-back ---------------------------
class _Factory:
    authority_id = 'fixture-engineering-authority'


class _DoubleBlobs:
    authority_id = 'fixture-engineering-authority'


class _Owner:
    def __init__(self, factory, blobs=None, execution=None):
        self.factory, self.blobs, self.execution = factory, blobs, execution


class _DispatchOwner(_Owner):
    """Labelled owner double: records the call, returns the view it was given."""

    def __init__(self, factory, blobs, execution, view):
        super().__init__(factory, blobs, execution)
        self.view, self.calls = view, 0

    def dispatch_declared_work(self, *args, **kwargs):
        self.calls += 1
        # This controlled owner attests only its fixed test recipe. Real
        # method/package assembly is covered by test_work_package_dispatch_v2.
        if args[6] != {'task': 'frozen'}:
            raise ApplicationError('DISPATCH_WORK_INPUT_CHANGED')
        return self.view


def _double_operations():
    factory, blobs = _Factory(), _DoubleBlobs()
    records = object()
    execution = type('Execution', (), {'records': records,
        'query_factory': staticmethod(lambda binding: object())})()
    return EngineeringOwnerOperations(factory, packages=_Owner(factory),
        dispatch=_DispatchOwner(factory, blobs, execution, view=None),
        submissions=_Owner(factory), records=records, blobs=blobs)


def _request(*, work_id=WORK_ID, unit_ref=UNIT_A, step_id=STEP, attempt=1):
    return {'dispatch': {'work_id': work_id, 'action_id': ACTION, 'step_id': step_id,
                         'attempt': attempt, 'unit_ref': unit_ref, 'params': {'task': 'frozen'},
                         'actions': list(ACTIONS), 'timeout': 30}}


def test_the_active_entry_refuses_the_historical_run_form():
    operations = _double_operations()
    legacy = {'run_id': 'run-1', 'step_id': STEP, 'attempt': 1, 'unit_ref': UNIT_A,
              'params': {'task': 'frozen'}, 'actions': list(ACTIONS), 'timeout': 30}
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution({'dispatch': legacy}, object())
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    # A run-shaped field is never accepted next to the Work form either.
    with pytest.raises(ApplicationError) as exc:
        operations.dispatch_execution(
            {'dispatch': {**legacy, 'work_id': WORK_ID, 'action_id': ACTION}}, object())
    assert exc.value.code == 'OWNER_OPERATION_INPUT_INVALID'
    assert operations.dispatch.calls == 0


def test_the_advertised_form_is_the_working_declared_work_form():
    descriptor = next(item for item in owner_capabilities()
                      if item.capability_id == 'engineering.executions.dispatch')
    form = descriptor.contract['input_schema']['properties']['dispatch']
    assert set(form['required']) == set(EngineeringOwnerOperations._WORK_DISPATCH_FORM)
    assert set(form['properties']) == set(EngineeringOwnerOperations._WORK_DISPATCH_FORM)
    assert 'run_id' not in form['properties'] and 'run_id' not in form['required']
    assert form['additionalProperties'] is False
    # The same vocabulary the template bindings may draw on.
    bindings = descriptor.contract['method_config_schema']['properties']['task_prompt'][
        'properties']['bindings']['additionalProperties']['enum']
    assert 'run_id' not in bindings and {'work_id', 'action_id'} <= set(bindings)


def _library(tmp_path):
    return EngineeringLibrary.create((tmp_path / 'work-dispatch-identity.sqlite').resolve(),
                                     library_id=LIBRARY_ID, schema_version=17)


def _seed(factory, key, raw, *, step_id=STEP, attempt=1, other_work=False):
    """Persist the declared Work and reserve one declared-Work dispatch row."""
    with factory.begin(SCOPE) as uow:
        uow.workflow.write_work_context(stable_id='declarative-work:' + WORK_ID,
                                        revision=1, body=_work_body(WORK_ID))
        if other_work:
            uow.workflow.write_work_context(stable_id='declarative-work:' + OTHER_WORK_ID,
                                            revision=1, body=_work_body(OTHER_WORK_ID))
        uow.work_dispatch.reserve(key, step_id, attempt, SCOPE, raw, _sha(raw), 'operation-1')
        uow.commit()


def _seed_historical_row(library, factory, key, raw, *, step_id=STEP, attempt=1,
                         operation_ref='operation-1'):
    """Seed the declared Work rows, then store one dispatch row as raw historical bytes.

    The active `work_dispatch.reserve` refuses a binding whose `work` names another
    Work than its own key (`DISPATCH_BINDING_INVALID`), so the *historical* row such
    a binding models can no longer be produced through the write path. This writes
    it the way an older library held it: the same canonical bytes, digest, scope and
    `reserved` marker the write path would have stored, inserted at the SQL layer
    without `reserve` and without its current-identity guard. Every other column
    matches a well-formed reserved row, so the reader admits it unchanged.
    """
    with factory.begin(SCOPE) as uow:
        uow.workflow.write_work_context(stable_id='declarative-work:' + WORK_ID,
                                        revision=1, body=_work_body(WORK_ID))
        uow.workflow.write_work_context(stable_id='declarative-work:' + OTHER_WORK_ID,
                                        revision=1, body=_work_body(OTHER_WORK_ID))
        uow.commit()
    digest_hex = _sha(raw).hex
    scope_json = canonical_bytes(asdict(SCOPE)).decode('utf-8')
    marker = canonical_bytes({'dispatch': 'reserved', 'binding_digest': digest_hex,
                              'operation_ref': operation_ref}).decode('utf-8')
    with library.transaction() as connection:
        connection.execute(
            'INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,'
            'receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,'
            'execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
            'result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (key, 0, step_id, 'engineering.execution.dispatch', attempt, 'reserved', marker,
             scope_json, digest_hex, raw, operation_ref, 'reserved', 0, 1, None))


def _stored_dispatch_rows(library):
    """Every stored declared-Work row, keyed by its own identity columns."""
    with library.transaction() as connection:
        return {(row[0], row[1], row[2]):
                {'binding_digest': Digest('sha256', row[3]), 'binding_bytes': row[4],
                 'dispatch_phase': row[5]}
                for row in connection.execute(
                    'SELECT dispatch_key,step_id,attempt,binding_digest,binding_bytes,'
                    'dispatch_phase FROM work_step_log')}


def _seal(factory, key, *, step_id=STEP, attempt=1, phase='possibly_written', result_ref=None):
    with factory.begin(SCOPE) as uow:
        current = uow.work_dispatch.get(key, step_id, attempt, SCOPE)['dispatch_version']
        uow.work_dispatch.transition(key, step_id, attempt, SCOPE,
                                     expected_version=current, fence=1, phase=phase,
                                     result_blob_ref=result_ref)
        uow.commit()


def _view(key, binding, *, phase, result_ref=None, **overrides):
    value = {'identity': key, 'step_id': binding.step_id, 'attempt': binding.attempt,
             'phase': phase,
             'result_blob_ref': None if result_ref is None else asdict(result_ref),
             'binding_digest': {'algorithm': binding.digest.algorithm, 'hex': binding.digest.hex},
             'params_assembly': 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT'}
    value.update(overrides)
    return value


def _operations(factory, blobs, view):
    records = object()
    execution = type('Execution', (), {'records': records,
        'query_factory': staticmethod(lambda binding: object())})()
    dispatch = _DispatchOwner(factory, blobs, execution, view)
    operations = EngineeringOwnerOperations(factory, packages=_Owner(factory),
        dispatch=dispatch, submissions=_Owner(factory), records=records, blobs=blobs)
    return operations, dispatch


def test_the_same_identity_and_content_read_back_consistently(tmp_path):
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        blobs = SQLiteBlobStore(library)
        identity = work_dispatch_key(WORK_ID, ACTION, STEP)
        raw = _declared_binding(key=identity)
        _seed(factory, identity, raw)
        result_raw = canonical_bytes({'native': 'recorded-result'})
        result_ref = blobs.put_verified(result_raw, _sha(result_raw), 'application/json')
        # The sealed chain is the repository's own: reserved -> possibly_written
        # -> completed, with the result blob under the same byte authority.
        _seal(factory, identity, phase='possibly_written')
        _seal(factory, identity, phase='completed', result_ref=result_ref)
        binding = decode_dispatch(raw)
        operations, owner = _operations(factory, blobs,
            _view(identity, binding, phase='completed', result_ref=result_ref))
        first = operations.dispatch_execution(_request(), _context('dispatch-read-1'))
        second = operations.dispatch_execution(_request(), _context('dispatch-read-2'))
        assert owner.calls == 2
        for result in (first, second):
            assert result.outcome == 'completed' and result.reason is None
            assert result.dispatch_phase == 'completed'
            assert result.engineering_completed is False and result.accepted is False
            assert result.value['binding'] == binding
            assert result.value['observation_ref'] == result_ref
            # The explicitly controlled owner checked the fixed fixture recipe;
            # this read-back test is not a production input-authority proof.
            assert result.value['params_assembly'] == (
                'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT')
        assert first == second
        with factory.begin(SCOPE, 'read') as uow:
            assert uow.work_dispatch.get(identity, STEP, 1, SCOPE)['binding_bytes'] == raw
    finally:
        library.close()


def test_a_swapped_unit_ref_is_refused(tmp_path):
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        blobs = SQLiteBlobStore(library)
        identity = work_dispatch_key(WORK_ID, ACTION, STEP)
        # The stored attempt binds Unit B; the caller declares Unit A.
        raw = _declared_binding(key=identity, unit_ref=UNIT_B)
        _seed(factory, identity, raw)
        binding = decode_dispatch(raw)
        operations, _ = _operations(factory, blobs,
            _view(identity, binding, phase='possibly_written'))
        result = operations.dispatch_execution(_request(unit_ref=UNIT_A),
                                               _context('dispatch-swapped-unit'))
        assert result.outcome == 'unknown' and result.reason == 'OWNER_BINDING_MISMATCH'
        assert result.engineering_completed is False
    finally:
        library.close()


def test_a_row_whose_work_identity_disagrees_with_the_key_is_refused(tmp_path):
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        blobs = SQLiteBlobStore(library)
        # Stored under this Work's key, but naming another existing Work: the
        # storage relation only compares the key, so the reader re-checks the
        # Work identity itself. The active write refuses to mint such a row (the
        # negative below), so the historical row it models is seeded as its own
        # raw bytes instead of through `reserve`.
        identity = work_dispatch_key(WORK_ID, ACTION, STEP)
        raw = _declared_binding(key=identity, work_id=OTHER_WORK_ID)
        _seed_historical_row(library, factory, identity, raw)
        seeded = _stored_dispatch_rows(library)
        assert seeded[(identity, STEP, 1)]['binding_bytes'] == raw
        # The seeded row is a well-formed reserved row the reader admits as-is.
        with factory.begin(SCOPE, 'read') as uow:
            assert uow.work_dispatch.get(identity, STEP, 1, SCOPE)['binding_bytes'] == raw
        binding = decode_dispatch(raw)
        operations, _ = _operations(factory, blobs,
            _view(identity, binding, phase='possibly_written'))
        result = operations.dispatch_execution(_request(), _context('dispatch-other-work'))
        assert result.outcome == 'unknown' and result.reason == 'OWNER_BINDING_MISMATCH'
        assert result.accepted is False and result.engineering_completed is False
        # Reading and refusing the row never rewrites it: the original key, bytes
        # and digest are exactly what was seeded, and no row was added or lost.
        after = _stored_dispatch_rows(library)
        assert after == seeded
        assert after[(identity, STEP, 1)] == {'binding_digest': _sha(raw),
                                              'binding_bytes': raw,
                                              'dispatch_phase': 'reserved'}
        # The same wrong binding can no longer be written by the active entry:
        # one fresh attempt through the real `reserve` is refused by name, and
        # the stored identity set is unchanged.
        fresh = _declared_binding(key=identity, work_id=OTHER_WORK_ID, attempt=2)
        with pytest.raises(ApplicationError) as exc:
            with factory.begin(SCOPE) as uow:
                uow.work_dispatch.reserve(identity, STEP, 2, SCOPE, fresh, _sha(fresh),
                                          'operation-2')
                uow.commit()
        assert exc.value.code == 'DISPATCH_BINDING_INVALID'
        assert _stored_dispatch_rows(library) == seeded
    finally:
        library.close()


def test_a_substituted_owner_view_is_refused_as_unknown(tmp_path):
    library = _library(tmp_path)
    try:
        factory = SQLiteUoWFactory(library)
        blobs = SQLiteBlobStore(library)
        identity = work_dispatch_key(WORK_ID, ACTION, STEP)
        raw = _declared_binding(key=identity)
        _seed(factory, identity, raw)
        result_raw = canonical_bytes({'native': 'recorded-result'})
        result_ref = blobs.put_verified(result_raw, _sha(result_raw), 'application/json')
        _seal(factory, identity, phase='possibly_written')
        _seal(factory, identity, phase='completed', result_ref=result_ref)
        binding = decode_dispatch(raw)
        # The owner's immediate view claims the committed phase and identity but
        # another frozen input, so the durable row's binding digest is not what it
        # says it dispatched. A consistent read of this row reports `completed`
        # with no reason, so the refusal below is the substitution, not staleness.
        substituted = {'binding_digest': {'algorithm': 'sha256', 'hex': '1' * 64}}
        operations, _ = _operations(factory, blobs,
            _view(identity, binding, phase='completed', result_ref=result_ref, **substituted))
        result = operations.dispatch_execution(_request(), _context('dispatch-substituted'))
        assert result.outcome == 'unknown' and result.reason == 'OWNER_RESULT_MISMATCH'
        assert result.dispatch_phase == 'completed'
        # The committed row is untouched by the refusal.
        with factory.begin(SCOPE, 'read') as uow:
            row = uow.work_dispatch.get(identity, STEP, 1, SCOPE)
            assert row['dispatch_phase'] == 'completed' and row['binding_bytes'] == raw
    finally:
        library.close()
