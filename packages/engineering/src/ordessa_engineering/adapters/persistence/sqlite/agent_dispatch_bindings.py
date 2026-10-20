"""V2 byte boundary over the original dispatch repository; no second journal.

This adapter only reserves/reads Engineering binding bytes. It cannot issue an
Agent invocation, send, or treat stored facts as execution authorization.
"""
import hashlib

from ....domain.changes.agent_dispatch import AgentDispatchBinding, AgentWorkDispatchBinding
from ....domain.changes.agent_dispatch_codec import encode_agent_dispatch, decode_agent_dispatch
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....application.contracts.errors import ApplicationError


class AgentDispatchBindings:
    def __init__(self, repository):
        self.repository = repository

    def reserve(self, binding):
        if type(binding) not in (AgentDispatchBinding, AgentWorkDispatchBinding):
            raise ApplicationError('AGENT_DISPATCH_BINDING_REQUIRED')
        try:binding.require_turn_binding()
        except ReferenceError as exc:raise ApplicationError(exc.code) from exc
        # Revalidate a frozen DTO even if trusted Python bypassed __setattr__.
        raw = encode_agent_dispatch(binding)
        if decode_agent_dispatch(raw) != binding:
            raise ApplicationError('AGENT_DISPATCH_BINDING_INVALID')
        # Preserve the existing DB column name execution_operation_ref while
        # explicitly storing the EXTERNAL engineering attempt correlation. It
        # does not assign an Agent/endpoint operation identity.
        content_digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
        return self.repository.reserve(binding.run_id, binding.step_id, binding.attempt,
            binding.scope, raw, content_digest, binding.engineering_attempt_ref)

    def read(self, run_id, step_id, attempt, scope):
        # Original repository performs scope/UoW checks before exposing bytes.
        row = self.repository.get(run_id, step_id, attempt, scope)
        try:
            binding = decode_agent_dispatch(row['binding_bytes'])
        except (ReferenceError, TypeError, ValueError, KeyError) as exc:
            raise ApplicationError('AGENT_DISPATCH_BINDING_INVALID') from exc
        if ((binding.scope, binding.run_id, binding.step_id, binding.attempt,
                binding.engineering_attempt_ref) != (scope, run_id, step_id, attempt,
                row['execution_operation_ref'])):
            raise ApplicationError('AGENT_DISPATCH_BINDING_MISMATCH')
        try:binding.require_turn_binding()
        except ReferenceError as exc:raise ApplicationError(exc.code) from exc
        return row, binding
