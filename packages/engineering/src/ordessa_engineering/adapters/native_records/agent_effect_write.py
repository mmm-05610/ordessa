"""Original Engineering handoff bridged to the synchronous Agent writer cut.

No permission/approval issuer, copied grant, database or retry owner. The opaque
handoff is created and consumed by the existing CommandAccessPort, and the SAME
ImplementationDispatch checks its original package/grant/debit/control records.
"""
import asyncio
from contextlib import contextmanager
import hashlib,math,time,threading

from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ...application.contracts.errors import ApplicationError
from ...application.contracts.commands import CommandContext
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ...application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ...domain.changes.agent_dispatch import AgentDispatchBinding, AgentWorkDispatchBinding
from ...domain.changes.agent_dispatch_codec import encode_agent_dispatch,decode_agent_dispatch
from .agent_execution import AgentExecutionConsumer,PreparedAgentInput


class EngineeringAgentEffectHandoff:
    """One request bridge; original CommandAccessPort remains the issuer."""
    def __init__(self,dispatch,consumer):
        if (type(dispatch) is not ImplementationDispatch or type(consumer) is not AgentExecutionConsumer
                or dispatch.blobs is not consumer._blobs or dispatch.blobs.authority_id!=dispatch.factory.authority_id
                or not callable(getattr(dispatch.access,'handoff_effect_write',None))
                or not callable(getattr(dispatch.access,'consume_effect_write',None))):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_AUTHORITY_UNAVAILABLE')
        self.dispatch,self.consumer=dispatch,consumer

    def _validate(self,binding,prepared,*,read_invocation):
        if type(binding) not in (AgentDispatchBinding, AgentWorkDispatchBinding) or type(prepared) is not PreparedAgentInput:
            raise ApplicationError('AGENT_DISPATCH_BINDING_REQUIRED')
        if decode_agent_dispatch(encode_agent_dispatch(binding))!=binding:
            raise ApplicationError('AGENT_DISPATCH_BINDING_INVALID')
        from ...domain.common.outcomes.diagnostics import ReferenceError
        try:binding.require_turn_binding()
        except ReferenceError as exc:raise ApplicationError(exc.code) from exc
        if (binding.agent_ref_bytes!=prepared.agent_ref_bytes
                or binding.turn_ref_bytes!=prepared.turn_ref_bytes
                or binding.engineering_attempt_ref!=prepared.engineering_attempt_ref
                or binding.expected_query_digest!=prepared.query_digest
                or 'sha256:'+binding.prompt_input_digest.hex!=prepared.prompt_input_digest
                or binding.prompt_ref.media_type!='application/json'
                or self.dispatch.blobs.read_verified(binding.prompt_ref)!=prepared.prompt_bytes):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        from ordessa_execution_agents.sdk.interactions import TurnRef,TurnReceipt,BindingProvenance,turn_query
        from ordessa_execution_agents.sdk.instances import AgentInstanceRef
        from .agent_execution import _original_sync
        turn=TurnRef.decode(decode_json(prepared.turn_ref_bytes))
        if canonical_bytes(turn.instance_ref.projection())!=binding.agent_ref_bytes:
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        query=turn_query(turn,prepared.prompt_input_digest)
        if query.query_digest!=prepared.query_digest or query.query_digest!=binding.expected_query_digest:
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        if read_invocation is None:raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        source=self.consumer._source
        provenance=_original_sync(source.read_binding(turn.instance_ref,invocation=read_invocation))
        if type(provenance) is not BindingProvenance or canonical_bytes(provenance.projection())!=prepared.provenance_bytes:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        receipt=_original_sync(source.query_turn(query,invocation=read_invocation))
        # An original read may conservatively report unknown after the private
        # fresh association was consumed before await. This checks identity ONLY;
        # original source single-use writer + opaque business handoff authorize
        # the actual cut. It never promotes unknown history to a send grant.
        if (type(receipt) is not TurnReceipt or receipt.turn_ref!=turn
                or receipt.agent_operation_ref!=prepared.agent_operation_ref
                or receipt.session_id!=prepared.session_id or receipt.input_digest!=prepared.prompt_input_digest
                or receipt.engineering_attempt_ref!=binding.engineering_attempt_ref
                or receipt.endpoint_operation_ref is not None):
            raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')

    @contextmanager
    def guard_effect_handoff(self,context,binding,prepared,*,send_invocation,read_invocation,timeout=10):
        invalidate=getattr(self.consumer._source,'invalidate_invocation',None)
        if not callable(invalidate):
            raise ApplicationError('AGENT_PREWRITE_BINDING_AUTHORITY_UNAVAILABLE')
        try:
            with self._guard_effect_handoff(context,binding,prepared,send_invocation=send_invocation,
                    read_invocation=read_invocation,timeout=timeout) as guard:
                yield guard
        finally:
            # Includes source validation and business admission failures before
            # the original access owner has issued any handoff.
            invalidate(send_invocation)

    @contextmanager
    def _guard_effect_handoff(self,context,binding,prepared,*,send_invocation,read_invocation,timeout):
        self._validate(binding,prepared,read_invocation=read_invocation)
        if (type(context) is not CommandContext or context.scope!=binding.scope or send_invocation is None
                or type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=10):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        dispatch=self.dispatch;dispatch._access(context,EXECUTION_DISPATCH)
        from ...adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
        with dispatch.factory.begin(context.scope,'read') as uow:
            row,actual=AgentDispatchBindings(uow.work_dispatch if type(binding) is AgentWorkDispatchBinding else uow.dispatch).read(
                binding.run_id,binding.step_id,binding.attempt,binding.scope)
            if actual!=binding or row['dispatch_phase']!='possibly_written' or row['dispatch_fence']!=binding.fence:
                raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        origin_task,origin_thread=asyncio.current_task(),threading.current_thread()
        deadline=time.monotonic()+timeout
        with dispatch.access.handoff_effect_write(context,invocation_key=bytes.fromhex(binding.digest.hex),
                action_instances=binding.action_instances,target_thread=origin_thread,expires_at=deadline,
                contract='engineering.agent-effect-write/1') as handoff:
            active=True;used=False;owner=self
            class Guard:
                @contextmanager
                def guard_write(self,write,invocation):
                    nonlocal used
                    from ordessa_execution_agents.sdk.interactions import WriteBinding,TurnRef
                    from ordessa_execution_agents.sdk.acp import prompt_frame
                    if (not active or used or invocation is not send_invocation
                            or asyncio.current_task() is not origin_task or threading.current_thread() is not origin_thread):
                        raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
                    if (type(write) is not WriteBinding or write.turn_ref!=TurnRef.decode(decode_json(prepared.turn_ref_bytes))
                            or canonical_bytes(write.turn_ref.instance_ref.projection())!=binding.agent_ref_bytes
                            or write.agent_operation_ref!=prepared.agent_operation_ref
                            or write.engineering_attempt_ref!=prepared.engineering_attempt_ref
                            or write.input_digest!=prepared.prompt_input_digest or write.session_id!=prepared.session_id
                            or write.frame_digest!='sha256:'+hashlib.sha256(prompt_frame(prepared.prompt_bytes,prepared.agent_operation_ref)).hexdigest()):
                        raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
                    owner._validate(binding,prepared,read_invocation=read_invocation)
                    used=True  # Original handoff can never authorize a second cut.
                    identity={'agentRef':decode_json(binding.agent_ref_bytes),
                        'engineeringAttemptRef':prepared.engineering_attempt_ref,'inputDigest':prepared.prompt_input_digest,
                        'queryDigest':prepared.query_digest,'frameDigest':write.frame_digest}
                    with dispatch.acquire_agent_effect_write(context,binding,identity,deadline,handoff=handoff,
                            expected_provenance=prepared.provenance_bytes):yield
            try:yield Guard()
            finally:active=False
