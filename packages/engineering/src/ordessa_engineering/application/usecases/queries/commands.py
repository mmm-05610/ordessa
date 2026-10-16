"""Recover the original command result without dispatch or replaying effects.

Pending is an observation, not permission to take over a worker. Work/Step and
outbox recovery require their missing durable claim and reconciliation ports.
"""
from ordessa_engineering.application.contracts.commands import CommandContext, CommandKey, CommandResult
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.mechanisms.codec import canonical_value


def read_command(uow, context, request_id):
    if type(context) is not CommandContext:
        raise ApplicationError("INVALID_CONTEXT")
    if context.scope != uow.scope:
        raise ApplicationError("SCOPE_MISMATCH")
    # Preserve the original authenticated context object. A target request id
    # never substitutes a principal, project or capability admission.
    key = CommandKey(context.scope.realm_id, context.principal_id, request_id)
    entry = uow.commands.get(key)
    if entry is None:
        raise ApplicationError("COMMAND_NOT_FOUND")
    return CommandResult(uow.authority_id, entry.operation_id,
                         entry.state, entry.result_bytes)


_OPERATION_STATES = {'completed': 'completed', 'rejected': 'failed'}
_OPERATION_UNKNOWN = 'unknown'


def read_operation(uow, context, request_id):
    """Operation view over the same journal row: state, work, business, apart.

    No new store is involved. The operation state answers "how did the command
    go" (running/completed/failed/unknown) while `business` carries the original
    command result, so a caller never reads a business conclusion as an
    operation status. `unknown` is an observation that requires reconciliation:
    this read view never authorizes a retry.
    """
    if type(context) is not CommandContext:
        raise ApplicationError("INVALID_CONTEXT")
    if context.scope != uow.scope:
        raise ApplicationError("SCOPE_MISMATCH")
    key = CommandKey(context.scope.realm_id, context.principal_id, request_id)
    entry = uow.commands.get(key)
    if entry is None:
        raise ApplicationError("OPERATION_NOT_FOUND")
    state = _OPERATION_STATES.get(entry.state, _OPERATION_UNKNOWN)
    view = {'request_id': request_id, 'operation': entry.operation,
            'operation_id': entry.operation_id, 'state': state,
            'journal_state': entry.state,
            'unknown_requires_reconciliation': state == _OPERATION_UNKNOWN,
            # A read view never authorizes re-running an effect.
            'retry_allowed': False,
            'work': None, 'business': None}
    if entry.result_bytes is not None:
        result = canonical_value(entry.result_bytes)
        view['business'] = result
        if entry.operation == 'engineering.work.start' and type(result) is dict:
            view['work'] = {'work_id': result.get('work_id'), 'revision': result.get('revision'),
                            'method_id': result.get('method_id'),
                            'release_version': result.get('release_version')}
    return view
