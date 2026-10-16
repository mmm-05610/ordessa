"""Narrow typed adapters over the three original Engineering owners.

Composition dependencies (factory, context, native execution records and blob
store) are deliberately not accepted from the operation payload.
"""
from dataclasses import asdict, dataclass
from typing import Any

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ..contracts.commands import CommandContext, CommandResult
from ..contracts.errors import ApplicationError
from ..orchestration.steps.implementation_dispatch import ImplementationDispatch
from .packages.implementation import ImplementationUseCases
from .changes.submissions import SubmissionUseCases
from ...domain.packages.codec import decode_package, decode_package_ref
from ...domain.changes.submission_codec import decode_submission
from ...domain.changes.dispatch_codec import decode_dispatch
from ...domain.common.mechanisms.codec import decode_blob_ref


MAX_RECORD_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class OwnerOperationResult:
    operation: str
    outcome: str
    value: Any = None
    engineering_completed: bool = False
    accepted: bool = False
    dispatch_phase: str | None = None
    reason: str | None = None


def _closed_record(value, decoder):
    try:
        raw = canonical_bytes(value)
        if len(raw) > MAX_RECORD_BYTES:
            raise ApplicationError('OWNER_OPERATION_INPUT_TOO_LARGE')
        return decoder(raw)
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError('OWNER_OPERATION_RECORD_INVALID') from exc


def _result_json(result, factory):
    if type(result) is not CommandResult or result.authority_id != factory.authority_id:
        raise ApplicationError('OWNER_OPERATION_RESULT_AUTHORITY_MISMATCH')
    if result.result_bytes is None:
        return None
    return decode_json(result.result_bytes)


def _journal_matches(factory, context, operation, result):
    with factory.begin(context.scope, 'read') as uow:
        entry = uow.commands.get(context.key)
        return (entry is not None and entry.operation == operation
                and entry.operation_id == result.operation_id
                and entry.project_id == context.scope.project_id
                and entry.state == result.status
                and entry.result_bytes == result.result_bytes)


class EngineeringOwnerOperations:
    """Call package freeze, native dispatch and submission recording owners."""
    def __init__(self, factory, *, packages: ImplementationUseCases,
                 dispatch: ImplementationDispatch, submissions: SubmissionUseCases,
                 records, blobs, access=None):
        if any(getattr(owner, 'factory', None) is not factory
               for owner in (packages, dispatch, submissions)):
            raise ApplicationError('OWNER_OPERATION_FACTORY_MISMATCH')
        execution = getattr(dispatch, 'execution', None)
        if (getattr(blobs, 'authority_id', None) != factory.authority_id
                or getattr(dispatch, 'blobs', None) is not blobs
                or records is None or getattr(execution, 'records', None) is not records
                or not callable(getattr(execution, 'query_factory', None))):
            raise ApplicationError('OWNER_OPERATION_SOURCE_AUTHORITY_UNAVAILABLE')
        self.factory, self.packages, self.dispatch = factory, packages, dispatch
        self.submissions, self.records, self.blobs = submissions, records, blobs
        if access is not None and any(getattr(owner,'access',None) is not access
                                     for owner in (packages,dispatch,submissions)):
            raise ApplicationError('OWNER_OPERATION_ACCESS_MISMATCH')
        self.access=access

    def execute(self, operation: str, parameters, context: CommandContext) -> OwnerOperationResult:
        if type(context) is not CommandContext or type(parameters) is not dict:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        try:
            raw = canonical_bytes(parameters)
        except Exception as exc:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID') from exc
        if len(raw) > MAX_RECORD_BYTES:
            raise ApplicationError('OWNER_OPERATION_INPUT_TOO_LARGE')
        if operation == 'engineering.packages.freeze':
            return self.freeze_package(parameters, context)
        if operation == 'engineering.executions.dispatch':
            return self.dispatch_execution(parameters, context)
        if operation == 'engineering.submissions.record_report':
            return self.record_report(parameters, context)
        raise ApplicationError('OWNER_OPERATION_UNKNOWN')

    def record_report(self, parameters, context):
        if set(parameters) != {'record'}:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        record = _closed_record(parameters['record'], decode_submission)
        operation = 'engineering.submissions.record_report'
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.dispatch.by_operation(record.execution_ref.operation_ref, context.scope)
            binding = decode_dispatch(row['binding_bytes'])
        invocation = self.dispatch.execution.query_factory(binding)
        result = self.submissions.record_report(record, context, records=self.records,
            blobs=self.blobs, query_invocation=invocation)
        value = _result_json(result, self.factory)
        if (result.status != 'completed' or type(value) is not dict
                or not _journal_matches(self.factory, context, operation, result)):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        if (set(value) != {'submission_ref', 'workflow_state', 'review_status', 'accepted'}
                or value['workflow_state'] != 'submitted' or value['review_status'] != 'pending_review'
                or value['accepted'] is not False):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_SHAPE_MISMATCH')
        from ...domain.reviews.target_codec import decode_subject_ref
        ref = decode_subject_ref(value['submission_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            stored = uow.submissions.resolve(ref)
        if stored != record or stored.ref != ref:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RECORD_MISMATCH')
        return OwnerOperationResult(operation, 'submitted', value, accepted=False)

    def freeze_package(self, parameters, context):
        if set(parameters) != {'record'}:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        record = _closed_record(parameters['record'], decode_package)
        operation = 'engineering.packages.freeze'
        result = self.packages.freeze_package(record, context)
        value = _result_json(result, self.factory)
        if result.status != 'completed' or type(value) is not dict:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_INCOMPLETE')
        if not _journal_matches(self.factory, context, operation, result):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_JOURNAL_MISMATCH')
        if (set(value) != {'package_ref', 'dispatchable'}
                or value['dispatchable'] is not False):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_SHAPE_MISMATCH')
        ref = decode_package_ref(value['package_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            stored = uow.implementation.resolve_package(ref)
        if stored != record:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RECORD_MISMATCH')
        return OwnerOperationResult(operation, 'completed', {'package_ref': ref, 'record': stored})

    # The declared-Work dispatch form: the Work's own identity (its dispatch key
    # is derived from `work_id`/`action_id`/`step_id`) on schema-17 work_step_log.
    # `run_id` is never part of it — the historical run form is not an active
    # writer — and this exact set is what the owner capability advertises.
    _WORK_DISPATCH_FORM = frozenset({'work_id', 'action_id', 'step_id', 'attempt',
                                     'unit_ref', 'params', 'actions', 'timeout'})

    def dispatch_execution(self, parameters, context):
        if set(parameters) != {'dispatch'} or type(parameters['dispatch']) is not dict:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        request = parameters['dispatch']
        # The active write entry takes a declared Work identity only. The
        # historical run form is never an active writer here; old dispatch rows
        # stay readable/reconcilable through their own records.
        if 'run_id' in request or 'work_id' not in request:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        required = self._WORK_DISPATCH_FORM
        if set(request) != required or type(request['actions']) is not list:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        if (type(request['attempt']) is not int or not 1 <= request['attempt'] <= 4096
                or type(request['timeout']) not in (int, float) or not 0 < request['timeout'] <= 60
                or not request['actions'] or any(type(a) is not str or not a for a in request['actions'])
                or len(set(request['actions'])) != len(request['actions'])
                or type(request['unit_ref']) is not dict or type(request['params']) is not dict):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        operation = 'engineering.executions.dispatch'
        from ..contracts.dispatch_identity import work_dispatch_key
        identity = work_dispatch_key(request['work_id'], request['action_id'],
                                    request['step_id'])
        # `params` is handed to the owner as the caller's declared input and is
        # *not* checked here against the trusted assembly (the Work's declared
        # subject, the frozen package, the exact method resource, the original
        # Unit session): this adapter holds no assembly of its own, and inventing
        # one from the caller's payload would fabricate the very authority the
        # owner is asked for. The gap is reported in the result below instead of
        # being assumed away.
        returned = self.dispatch.dispatch_declared_work(identity,
            request['work_id'], request['action_id'], request['step_id'], request['attempt'],
            request['unit_ref'], request['params'], tuple(request['actions']), context,
            timeout=request['timeout'])
        # The declared Work's own relation (schema 17) is the only row an active
        # dispatch writes: a declared Work has no `runs` row, so the run-scoped
        # `step_log` is never this step's record. The stored row must be this
        # Work identity, this step and this attempt, and its binding must be the
        # frozen declared-Work binding the owner accepted.
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.get(identity, request['step_id'], request['attempt'],
                                        context.scope)
            binding = decode_dispatch(row['binding_bytes'])
        if (row['run_id'] != identity or row['step_id'] != request['step_id']
                or row['attempt'] != request['attempt']
                or binding.binding_version != 2 or binding.work is None
                or binding.work.get('dispatch_key') != identity
                or binding.work.get('work_id') != request['work_id']
                or binding.work.get('action_id') != request['action_id']
                or binding.work.get('step_id') != request['step_id']
                or binding.attempt != request['attempt']
                or binding.unit_ref_bytes != canonical_bytes(request['unit_ref'])
                or tuple(action for action, _ in binding.action_instances) != tuple(request['actions'])
                or binding.scope != context.scope):
            return OwnerOperationResult(operation, 'unknown', engineering_completed=False,
                                        reason='OWNER_BINDING_MISMATCH')
        phase = row['dispatch_phase']
        outcome = phase if phase in {'completed', 'failed'} else 'unknown'
        result_ref = None
        if row['result_blob_json'] is not None:
            result_ref = decode_blob_ref(decode_json(row['result_blob_json']))
            # The original UoW verifies the observed bytes under the same
            # authority before this adapter reports a native record outcome.
            with self.factory.begin(context.scope, 'read') as uow:
                uow.implementation.read_blob(result_ref)
        # Compare the owner's immediate view with its durable row. A caller
        # cannot substitute an identity, an attempt, a frozen input or an outcome
        # after the transaction has committed. The view carries the declared Work
        # identity, never a run id; an absent completion flag is not a claim, a
        # present true one is refused.
        if (type(returned) is not dict or returned.get('phase') != phase
                or returned.get('identity') != identity
                or returned.get('step_id') != request['step_id']
                or returned.get('attempt') != request['attempt']
                or returned.get('binding_digest') != {'algorithm': binding.digest.algorithm,
                                                       'hex': binding.digest.hex}
                or returned.get('engineering_completed', False) is not False
                or canonical_bytes(returned.get('result_blob_ref')) !=
                   (b'null' if result_ref is None else canonical_bytes(decode_json(row['result_blob_json'])))):
            outcome = 'unknown'
        return OwnerOperationResult(operation, outcome,
            {'binding': binding, 'observation_ref': result_ref,
             # Never silently treated as verified: this adapter cannot compare the
             # caller's params with the trusted Work/package/method/Unit assembly.
             'params_assembly': 'NOT_VERIFIED_AGAINST_TRUSTED_WORK_ASSEMBLY'},
            engineering_completed=False, accepted=False, dispatch_phase=phase,
            reason=None if outcome == phase else 'OWNER_RESULT_MISMATCH')

