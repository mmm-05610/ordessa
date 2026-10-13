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
        if (set(value) != {'package_ref', 'binding_proof', 'action_instance_id', 'dispatchable'}
                or value['dispatchable'] is not False):
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RESULT_SHAPE_MISMATCH')
        ref = decode_package_ref(value['package_ref'])
        with self.factory.begin(context.scope, 'read') as uow:
            stored = uow.implementation.resolve_package(ref)
        if stored != record:
            return OwnerOperationResult(operation, 'unknown', reason='OWNER_RECORD_MISMATCH')
        return OwnerOperationResult(operation, 'completed', {'package_ref': ref, 'record': stored})

    def dispatch_execution(self, parameters, context):
        if set(parameters) != {'dispatch'} or type(parameters['dispatch']) is not dict:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        request = parameters['dispatch']
        required = {'run_id', 'step_id', 'attempt', 'unit_ref', 'params', 'actions', 'timeout'}
        if set(request) != required or type(request['actions']) is not list:
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        if (type(request['attempt']) is not int or not 1 <= request['attempt'] <= 4096
                or type(request['timeout']) not in (int, float) or not 0 < request['timeout'] <= 60
                or not request['actions'] or any(type(a) is not str or not a for a in request['actions'])
                or len(set(request['actions'])) != len(request['actions'])
                or type(request['unit_ref']) is not dict or type(request['params']) is not dict):
            raise ApplicationError('OWNER_OPERATION_INPUT_INVALID')
        operation = 'engineering.executions.dispatch'
        returned = self.dispatch.dispatch(request['run_id'], request['step_id'], request['attempt'],
            request['unit_ref'], request['params'], tuple(request['actions']), context,
            timeout=request['timeout'])
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.dispatch.get(request['run_id'], request['step_id'], request['attempt'], context.scope)
            binding = decode_dispatch(row['binding_bytes'])
            package = self.dispatch._work_package(uow, request['run_id'],step_id=request['step_id'])
        if (binding.run_id != request['run_id'] or binding.step_id != request['step_id']
                or binding.attempt != request['attempt']
                or binding.unit_ref_bytes != canonical_bytes(request['unit_ref'])
                or tuple(action for action, _ in binding.action_instances) != tuple(request['actions'])
                or binding.scope != context.scope or binding.package_ref != package.ref):
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
        # cannot substitute an outcome after the transaction has committed.
        if (type(returned) is not dict or returned.get('phase') != phase
                or returned.get('run_id') != request['run_id']
                or returned.get('step_id') != request['step_id']
                or returned.get('attempt') != request['attempt']
                or returned.get('binding_digest') != {'algorithm': binding.digest.algorithm,
                                                       'hex': binding.digest.hex}
                or returned.get('engineering_completed') is not False
                or canonical_bytes(returned.get('result_blob_ref')) !=
                   (b'null' if result_ref is None else canonical_bytes(decode_json(row['result_blob_json'])))):
            outcome = 'unknown'
        return OwnerOperationResult(operation, outcome,
            {'binding': binding, 'observation_ref': result_ref}, engineering_completed=False,
            accepted=False, dispatch_phase=phase,
            reason=None if outcome == phase else 'OWNER_RESULT_MISMATCH')

