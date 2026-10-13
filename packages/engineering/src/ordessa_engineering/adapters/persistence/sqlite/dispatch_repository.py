"""Schema13 dispatch rows on the caller's original _RepositoryAccess."""
from dataclasses import asdict
import hashlib
import json

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from .dispatch_schema import DISPATCH_SCHEMA_VERSION
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION

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
        if row is None or row[0] not in (DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
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
