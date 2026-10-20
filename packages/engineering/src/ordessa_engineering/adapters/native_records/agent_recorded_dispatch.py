"""Engineering adapter over the original Agent interaction/source authority.

No Unit lease, effect factory, application map, second journal or sync loop runner.
The opaque invocations come only from trusted composition and stay process-local.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import Mapping
import math

from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ...application.contracts.errors import ApplicationError
from ...domain.common.models.execution_refs import agent_instance_ref_bytes
from ...domain.common.models.values import Digest
from .agent_execution import AgentExecutionConsumer
from .prompt_values import _plain,_reject_callbacks,_MAX_PROMPT_BYTES


@dataclass(frozen=True)
class _OriginalAgentFlow:
    context:object
    prepared:object
    request_id:str
    send_invocation:object
    read_invocation:object


class RecordedDispatchExecution:
    """One original Agent source and the same original Engineering BlobStore."""
    def __init__(self,source,blobs,*,send_invocation_resolver,read_invocation_resolver,
                 query_factory,endpoint_resolver):
        from ordessa_execution_agents.public import InteractionService
        if (type(source) is not InteractionService or endpoint_resolver is not source.endpoint_resolver
                or not callable(getattr(endpoint_resolver,'resolve',None))
                or any(not callable(value) for value in
                    (send_invocation_resolver,read_invocation_resolver,query_factory))):
            raise ApplicationError('RECORDED_DISPATCH_ORIGINAL_OWNER_REQUIRED')
        self.source=source;self.blobs=blobs;self.endpoint_resolver=endpoint_resolver
        self.records=AgentExecutionConsumer(source,blobs)
        self.send_invocation_resolver=send_invocation_resolver
        self.read_invocation_resolver=read_invocation_resolver;self.query_factory=query_factory

    def freeze_input(self,agent_ref,params):
        from ordessa_execution_agents.sdk.instances import AgentInstanceRef
        raw_ref=agent_instance_ref_bytes(agent_ref)
        if not isinstance(params,Mapping):raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        value=_plain(params);_reject_callbacks(value);raw=canonical_bytes(value,profile=LIBRARY_JSON_PROFILE)
        if len(raw)>_MAX_PROMPT_BYTES:raise ApplicationError('RECORDED_DISPATCH_INPUT_TOO_LARGE')
        prompt=self.source.freeze_prompt(AgentInstanceRef.decode(decode_json(raw_ref)),raw)
        return prompt.params_bytes,Digest('sha256',prompt.input_digest[7:])

    @asynccontextmanager
    async def prepared_dispatch(self,context,agent_ref,params,*,request_id,engineering_attempt_ref,preparation_wait=None):
        from ordessa_execution_agents.sdk.endpoint import BoundEndpoint
        raw,_=self.freeze_input(agent_ref,params)
        send=self.send_invocation_resolver(context,agent_ref)
        read=self.read_invocation_resolver(context,agent_ref)
        if send is None or read is None:raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        with self.records.prepared_dispatch(agent_ref,raw,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,send_invocation=send,read_invocation=read) as prepared:
            # Required original physical port is checked before business debits.
            # Resolve only this existing endpoint; never acquire/launch/rebind.
            from ordessa_execution_agents.sdk.interactions import BindingProvenance
            provenance=BindingProvenance.decode(decode_json(prepared.provenance_bytes))
            from contextlib import nullcontext
            with (preparation_wait() if preparation_wait is not None else nullcontext()):
                endpoint=await self.endpoint_resolver.resolve(provenance.endpoint_ref,send)
            if (type(endpoint) is not BoundEndpoint or endpoint.ref!=provenance.endpoint_ref
                    or not callable(getattr(endpoint.communicate,'send_guarded',None))
                    or not callable(getattr(endpoint.communicate,'receive',None))):
                raise ApplicationError('RECORDED_DISPATCH_ORIGINAL_WRITER_REQUIRED')
            yield _OriginalAgentFlow(context,prepared,request_id,send,read)

    async def send(self,binding,flow,context,dispatch,*,timeout=60):
        from .agent_effect_write import EngineeringAgentEffectHandoff
        from ordessa_execution_agents.sdk.instances import AgentInstanceRef
        if (type(flow) is not _OriginalAgentFlow or flow.context is not context
                or type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=60):
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_BINDING_INVALID')
        instance=AgentInstanceRef.decode(decode_json(binding.agent_ref_bytes))
        prompt=self.source.freeze_prompt(instance,flow.prepared.prompt_bytes)
        import asyncio
        with EngineeringAgentEffectHandoff(dispatch,self.records).guard_effect_handoff(context,binding,flow.prepared,
                send_invocation=flow.send_invocation,read_invocation=flow.read_invocation,timeout=min(timeout,10)) as guard:
            return await self.source.prompt_recorded(instance,prompt,request_id=flow.request_id,
                engineering_attempt_ref=binding.engineering_attempt_ref,invocation=flow.send_invocation,
                write_guard=guard,deadline=asyncio.get_running_loop().time()+timeout)

    def capture(self,binding):
        invocation=self.query_factory(binding)
        if invocation is None:raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        return self.records.capture_dispatch(binding,read_invocation=invocation)


__all__=['RecordedDispatchExecution']
