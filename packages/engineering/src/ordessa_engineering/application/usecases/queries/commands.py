"""Recover the original command result without dispatch or replaying effects.

Pending is an observation, not permission to take over a worker. Work/Step and
outbox recovery require their missing durable claim and reconciliation ports.
"""
from ordessa_engineering.application.contracts.commands import CommandContext, CommandKey, CommandResult
from ordessa_engineering.application.contracts.errors import ApplicationError


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
