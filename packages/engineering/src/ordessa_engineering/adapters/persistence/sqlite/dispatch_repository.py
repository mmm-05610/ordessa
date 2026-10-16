"""Schema13 dispatch rows on the caller's original _RepositoryAccess."""
from dataclasses import asdict
import hashlib
import json

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from ordessa_engineering.application.contracts.work_context import WORK_STABLE_ID_PREFIX
from ordessa_engineering.application.contracts.dispatch_identity import identity_is_current
from ordessa_engineering.domain.changes.dispatch import package_ref_projection
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from .dispatch_schema import DISPATCH_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION

_MAX_BINDING_BYTES = 2 * 1024 * 1024
_OPERATION = 'engineering.execution.dispatch'
_PHASES = frozenset({'reserved', 'possibly_written', 'completed', 'failed', 'unknown'})
_RESULT_PHASES = frozenset({'completed', 'failed', 'unknown'})


def _canonical_json(raw):
    try:
        value = json.loads(raw)
        encoded = canonical_bytes(value)
        if (type(raw) is bytes and encoded != raw
                or type(raw) is str and encoded.decode('utf-8') != raw):
            raise ValueError()
        return value
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise ApplicationError('DISPATCH_RECORD_CORRUPT') from None


class SQLiteDispatchRepository:
    """Persist immutable dispatch binding and CAS outcome in original step_log."""

    def __init__(self, access):
        self.access = access

    def _prefix(self, scope, *, write=False):
        self.access.check_active()
        if type(scope) is not Scope or scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        row = self.access.execute(
            'SELECT schema_version FROM library_meta WHERE singleton=1').fetchone()
        if row is None or row[0] not in (DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('DISPATCH_SCHEMA_REQUIRED')
        if write:
            self.access.require_write()
        return scope.realm_id, scope.project_id

    @staticmethod
    def _binding(binding_bytes, binding_digest):
        if (type(binding_bytes) is not bytes or not binding_bytes
                or len(binding_bytes) > _MAX_BINDING_BYTES
                or type(binding_digest) is not Digest or binding_digest.algorithm != 'sha256'
                or hashlib.sha256(binding_bytes).hexdigest() != binding_digest.hex):
            raise ApplicationError('DISPATCH_BINDING_INVALID')
        _canonical_json(binding_bytes)
        return binding_digest.hex

    @staticmethod
    def _row(row, scope, run_id, step_id, attempt):
        (ordinal, operation, status, receipt_ref_json, scope_json, binding_digest,
         binding_bytes, operation_ref, phase, version, fence, result_blob_json) = row
        expected_scope = canonical_bytes(asdict(scope)).decode('utf-8')
        if (type(scope_json) is not str or scope_json != expected_scope
                or type(binding_digest) is not str or type(binding_bytes) is not bytes
                or hashlib.sha256(binding_bytes).hexdigest() != binding_digest
                or operation != _OPERATION or phase not in _PHASES
                or type(version) is not int or type(fence) is not int
                or status != phase):
            raise ApplicationError('DISPATCH_RECORD_CORRUPT')
        try:
            digest = Digest('sha256', binding_digest)
        except (TypeError, ValueError):
            raise ApplicationError('DISPATCH_RECORD_CORRUPT') from None
        SQLiteDispatchRepository._binding(binding_bytes, digest)
        marker = _canonical_json(receipt_ref_json)
        if marker != {'dispatch': 'reserved', 'binding_digest': binding_digest,
                      'operation_ref': operation_ref}:
            raise ApplicationError('DISPATCH_RECORD_CORRUPT')
        if result_blob_json is not None:
            _canonical_json(result_blob_json)
        return {
            'run_id': run_id, 'step_id': step_id, 'attempt': attempt, 'ordinal': ordinal,
            'operation': operation, 'dispatch_scope_json': scope_json,
            'binding_digest': digest, 'binding_bytes': binding_bytes,
            'execution_operation_ref': operation_ref, 'dispatch_phase': phase,
            'dispatch_version': version, 'dispatch_fence': fence,
            'result_blob_json': result_blob_json,
        }

    def reserve(self, run_id, step_id, attempt, scope, binding_bytes, binding_digest, operation_ref):
        prefix = self._prefix(scope, write=True)
        validate_id(run_id)
        validate_id(step_id)
        validate_id(operation_ref)
        if type(attempt) is not int or not 1 <= attempt <= 4096:
            raise ApplicationError('INVALID_ARGUMENT')
        digest_hex = self._binding(binding_bytes, binding_digest)
        if self.access.execute('SELECT 1 FROM runs WHERE run_id=?', (run_id,)).fetchone() is None:
            raise ApplicationError('RUN_NOT_FOUND')
        existing = self.access.execute(
            'SELECT binding_digest FROM step_log WHERE run_id=? AND step_id=? AND attempt=?',
            (run_id, step_id, attempt)).fetchone()
        if existing is not None:
            raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
        ordinal = self.access.execute(
            'SELECT COALESCE(MAX(ordinal),-1)+1 FROM step_log WHERE run_id=?', (run_id,)
        ).fetchone()[0]
        scope_json = canonical_bytes(asdict(scope)).decode('utf-8')
        marker = canonical_bytes({'dispatch': 'reserved', 'binding_digest': digest_hex,
                                  'operation_ref': operation_ref}).decode('utf-8')
        self.access.execute(
            'INSERT INTO step_log (run_id,ordinal,step_id,operation,attempt,status,receipt_ref_json,'
            'dispatch_scope_json,binding_digest,binding_bytes,execution_operation_ref,dispatch_phase,'
            'dispatch_version,dispatch_fence,result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (run_id, ordinal, step_id, _OPERATION, attempt, 'reserved', marker, scope_json,
             digest_hex, binding_bytes, operation_ref, 'reserved', 0, 1, None))
        return self.get(run_id, step_id, attempt, scope)

    def get(self, run_id, step_id, attempt, scope):
        self._prefix(scope)
        validate_id(run_id)
        validate_id(step_id)
        if type(attempt) is not int or attempt < 1:
            raise ApplicationError('INVALID_ARGUMENT')
        row = self.access.execute(
            'SELECT ordinal,operation,status,receipt_ref_json,dispatch_scope_json,binding_digest,'
            'binding_bytes,execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
            'result_blob_json FROM step_log WHERE run_id=? AND step_id=? AND attempt=? '
            'AND binding_digest IS NOT NULL',
            (run_id, step_id, attempt)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self._row(row, scope, run_id, step_id, attempt)

    def by_operation(self, operation_ref, scope):
        self._prefix(scope)
        validate_id(operation_ref)
        row = self.access.execute(
            'SELECT run_id,step_id,attempt FROM step_log WHERE execution_operation_ref=? '
            'AND binding_digest IS NOT NULL', (operation_ref,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self.get(row[0], row[1], row[2], scope)

    def transition(self, run_id, step_id, attempt, scope, *, expected_version, fence, phase,
                   result_blob_ref=None):
        prefix = self._prefix(scope, write=True)
        validate_id(run_id)
        validate_id(step_id)
        if (type(attempt) is not int or attempt < 1 or type(expected_version) is not int
                or expected_version < 0 or type(fence) is not int or fence < 1
                or type(phase) is not str or phase not in _PHASES):
            raise ApplicationError('INVALID_ARGUMENT')
        record = self.get(run_id, step_id, attempt, scope)
        old_phase = record['dispatch_phase']
        allowed = ((old_phase == 'reserved' and phase == 'possibly_written')
                   or (old_phase in {'possibly_written', 'unknown'}
                       and phase in _RESULT_PHASES))
        if not allowed:
            raise ApplicationError('DISPATCH_TRANSITION_INVALID')
        if result_blob_ref is not None and type(result_blob_ref) is not BlobRef:
            raise ApplicationError('INVALID_ARGUMENT')
        result_json = None if result_blob_ref is None else canonical_bytes(asdict(result_blob_ref)).decode('utf-8')
        cursor = self.access.execute(
            'UPDATE step_log SET status=?,dispatch_phase=?,dispatch_version=dispatch_version+1,'
            'result_blob_json=? WHERE run_id=? AND step_id=? AND attempt=? AND dispatch_scope_json=? '
            'AND dispatch_version=? AND dispatch_fence=? AND dispatch_phase=?',
            (phase, phase, result_json, run_id, step_id, attempt,
             canonical_bytes(asdict(scope)).decode('utf-8'), expected_version, fence, old_phase))
        if cursor.rowcount != 1:
            raise ApplicationError('DISPATCH_CHANGED')
        return self.get(run_id, step_id, attempt, scope)


class SQLiteWorkDispatchRepository:
    """The only *active* write path for declared Work dispatch rows.

    Same phases, same CAS transition and same conflict codes as the run-scoped
    repository — whose binding and row validation helpers are reused rather than
    copied — on a table keyed by the namespaced declared-Work identity, with no
    `runs` foreign key. A declared Work has no run row and none is invented.
    The run-scoped repository remains the only line for historical run rows and
    their recovery; it is not a second active line for declared Work.
    """

    def __init__(self, access):
        self.access = access
        self._shared = SQLiteDispatchRepository(access)

    def _prefix(self, scope, *, write=False):
        self.access.check_active()
        if type(scope) is not Scope or scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        row = self.access.execute(
            'SELECT schema_version FROM library_meta WHERE singleton=1').fetchone()
        if row is None or row[0] != WORK_DISPATCH_SCHEMA_VERSION:
            raise ApplicationError('DISPATCH_SCHEMA_REQUIRED')
        if write:
            self.access.require_write()
        return scope.realm_id, scope.project_id

    def _work_exists(self, work_id, scope):
        """The stored Work must exist *and* declare this exact scope.

        A same-id material recorded under another scope is not this Work.
        """
        row = self.access.execute(
            'SELECT body_json FROM materials WHERE kind=? AND stable_id=? '
            'ORDER BY revision DESC LIMIT 1',
            ('work-context', WORK_STABLE_ID_PREFIX + work_id)).fetchone()
        if row is None:
            return False
        try:
            declared = (json.loads(row[0]) or {}).get('scope') or {}
        except (TypeError, ValueError):
            return False
        return (declared.get('realm_id'), declared.get('project_id')) == (
            scope.realm_id, scope.project_id)

    def _declared(self, dispatch_key, step_id, attempt, scope, binding_bytes):
        """A row may only be reserved for the declared Work its binding names.

        The active write is strict where decode is permissive. The key must be
        exactly the one the *current* identity algorithm mints for the binding's
        own `work_id`/`action_id`/`step_id` (a historical folded form is never
        adopted by a new write), the binding's `run_id`, `step`, `attempt` and
        scope must agree with the row being written, and a frozen-package subject
        must be the bound package's own full projection. Any disagreement is a
        named refusal and nothing is written.
        """
        try:
            binding = decode_dispatch(binding_bytes)
        except Exception:
            raise ApplicationError('DISPATCH_BINDING_INVALID') from None
        work = binding.work if type(binding.work) is dict else {}
        if (binding.binding_version != 2 or not work
                or work.get('dispatch_key') != dispatch_key
                or work.get('step_id') != binding.step_id
                or binding.step_id != step_id
                or binding.attempt != attempt
                or binding.run_id != dispatch_key or binding.scope != scope):
            raise ApplicationError('DISPATCH_BINDING_INVALID')
        # The current algorithm's own key for these exact fields, and nothing else:
        # a new reserve never reuses the historical folded form.
        if not identity_is_current(dispatch_key, work.get('work_id'),
                                   work.get('action_id'), work.get('step_id')):
            raise ApplicationError('DISPATCH_BINDING_INVALID')
        subject = binding.subject
        if (type(subject) is not dict
                or subject.get('subject_kind') not in ('reviewed_change', 'frozen_package')):
            raise ApplicationError('DISPATCH_BINDING_INVALID')
        if subject['subject_kind'] == 'frozen_package' and (
                type(binding.package_ref) is not ImplementationPackageRef
                or subject.get('subject_ref') != package_ref_projection(binding.package_ref)):
            # A frozen-package subject must be *this* package's own projection; a
            # substituted or partial reference is refused here, at the write, not
            # while reading an already stored row.
            raise ApplicationError('DISPATCH_BINDING_INVALID')
        work_id = work.get('work_id')
        if type(work_id) is not str or not self._work_exists(work_id, scope):
            raise ApplicationError('WORK_NOT_FOUND')
        return binding

    def reserve(self, dispatch_key, step_id, attempt, scope, binding_bytes, binding_digest,
                operation_ref):
        self._prefix(scope, write=True)
        validate_id(dispatch_key)
        validate_id(step_id)
        validate_id(operation_ref)
        if type(attempt) is not int or not 1 <= attempt <= 4096:
            raise ApplicationError('INVALID_ARGUMENT')
        digest_hex = self._shared._binding(binding_bytes, binding_digest)
        self._declared(dispatch_key, step_id, attempt, scope, binding_bytes)
        existing = self.access.execute(
            'SELECT binding_digest FROM work_step_log WHERE dispatch_key=? AND step_id=? '
            'AND attempt=?', (dispatch_key, step_id, attempt)).fetchone()
        if existing is not None:
            raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
        ordinal = self.access.execute(
            'SELECT COALESCE(MAX(ordinal),-1)+1 FROM work_step_log WHERE dispatch_key=?',
            (dispatch_key,)).fetchone()[0]
        scope_json = canonical_bytes(asdict(scope)).decode('utf-8')
        marker = canonical_bytes({'dispatch': 'reserved', 'binding_digest': digest_hex,
                                  'operation_ref': operation_ref}).decode('utf-8')
        self.access.execute(
            'INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,'
            'receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,'
            'execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
            'result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (dispatch_key, ordinal, step_id, _OPERATION, attempt, 'reserved', marker,
             scope_json, digest_hex, binding_bytes, operation_ref, 'reserved', 0, 1, None))
        return self.get(dispatch_key, step_id, attempt, scope)

    def get(self, dispatch_key, step_id, attempt, scope):
        self._prefix(scope)
        validate_id(dispatch_key)
        validate_id(step_id)
        if type(attempt) is not int or attempt < 1:
            raise ApplicationError('INVALID_ARGUMENT')
        row = self.access.execute(
            'SELECT ordinal,operation,status,receipt_ref_json,dispatch_scope_json,binding_digest,'
            'binding_bytes,execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,'
            'result_blob_json FROM work_step_log WHERE dispatch_key=? AND step_id=? AND attempt=? '
            'AND binding_digest IS NOT NULL', (dispatch_key, step_id, attempt)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self._shared._row(row, scope, dispatch_key, step_id, attempt)

    def by_operation(self, operation_ref, scope):
        self._prefix(scope)
        validate_id(operation_ref)
        row = self.access.execute(
            'SELECT dispatch_key,step_id,attempt FROM work_step_log WHERE '
            'execution_operation_ref=? AND binding_digest IS NOT NULL',
            (operation_ref,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        return self.get(row[0], row[1], row[2], scope)

    def transition(self, dispatch_key, step_id, attempt, scope, *, expected_version, fence,
                   phase, result_blob_ref=None):
        self._prefix(scope, write=True)
        validate_id(dispatch_key)
        validate_id(step_id)
        if (type(attempt) is not int or attempt < 1 or type(expected_version) is not int
                or expected_version < 0 or type(fence) is not int or fence < 1
                or type(phase) is not str or phase not in _PHASES):
            raise ApplicationError('INVALID_ARGUMENT')
        record = self.get(dispatch_key, step_id, attempt, scope)
        old_phase = record['dispatch_phase']
        allowed = ((old_phase == 'reserved' and phase == 'possibly_written')
                   or (old_phase in {'possibly_written', 'unknown'}
                       and phase in _RESULT_PHASES))
        if not allowed:
            raise ApplicationError('DISPATCH_TRANSITION_INVALID')
        if result_blob_ref is not None and type(result_blob_ref) is not BlobRef:
            raise ApplicationError('INVALID_ARGUMENT')
        result_json = (None if result_blob_ref is None
                       else canonical_bytes(asdict(result_blob_ref)).decode('utf-8'))
        cursor = self.access.execute(
            'UPDATE work_step_log SET status=?,dispatch_phase=?,'
            'dispatch_version=dispatch_version+1,result_blob_json=? WHERE dispatch_key=? '
            'AND step_id=? AND attempt=? AND dispatch_scope_json=? AND dispatch_version=? '
            'AND dispatch_fence=? AND dispatch_phase=?',
            (phase, phase, result_json, dispatch_key, step_id, attempt,
             canonical_bytes(asdict(scope)).decode('utf-8'), expected_version, fence, old_phase))
        if cursor.rowcount != 1:
            raise ApplicationError('DISPATCH_CHANGED')
        return self.get(dispatch_key, step_id, attempt, scope)
