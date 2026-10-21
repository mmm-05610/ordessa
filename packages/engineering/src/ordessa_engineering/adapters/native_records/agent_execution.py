"""Demand-side F1.2 preparation/capture over one original injected Agent source.

No turn allocation, send, grant mint, fallback Unit lookup or duplicate record
store. An externally reserved TurnRef must be verified by its original owner.
Until the original service/closed F1.2 DTOs are complete every read fails closed.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import inspect

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ...application.contracts.errors import ApplicationError
from ...domain.common.models.execution_refs import agent_instance_ref_bytes
from ...domain.common.models.values import Digest, validate_id
from ...domain.common.models.refs import BlobRef
from .prompt_values import _decode_prompt, _reject_callbacks, _MAX_PROMPT_BYTES


def _hash(raw):
    return 'sha256:'+hashlib.sha256(raw).hexdigest()


def _projection(value, schema):
    project=getattr(value,'projection',None)
    if not callable(project):raise ApplicationError('AGENT_F12_CODEC_UNAVAILABLE')
    result=project()
    if type(result) is not dict or result.get('schemaVersion')!=schema:
        raise ApplicationError('AGENT_F12_CODEC_UNAVAILABLE')
    return result


def _original_sync(value):
    # Frozen §12 owner reads are synchronous. Do not drive another event loop or
    # silently adapt a draft helper with different authority/call semantics.
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):value.close()
        raise ApplicationError('AGENT_ORIGINAL_READ_CONTRACT_UNAVAILABLE')
    return value


@dataclass(frozen=True)
class PreparedAgentInput:
    """Immutable consumed facts only. Never a send invocation or action grant."""
    agent_ref_bytes: bytes
    turn_ref_bytes: bytes
    prompt_bytes: bytes
    prompt_input_digest: str
    query_digest: str
    agent_operation_ref: str
    engineering_attempt_ref: str
    session_id: str
    provenance_bytes: bytes


@dataclass(frozen=True)
class CapturedAgentObservation:
    prepared: PreparedAgentInput
    state: str
    revision: int
    blob_ref: BlobRef
    authority_id: str


class AgentExecutionConsumer:
    def __init__(self, original_source, blobs):
        self._source,self._blobs=original_source,blobs

    @property
    def blob_store(self):
        """The original injected store for same-authority assembly validation."""
        return self._blobs

    def read_agent_reference(self,agent_ref,*,read_invocation):
        """Independently authorized original identity read, not a reviewer role."""
        self._require_source(read_invocation)
        raw=agent_instance_ref_bytes(agent_ref)
        from ordessa_agents.public import AgentInstanceRef
        from ordessa_agents.sdk.interactions import BindingProvenance
        instance=AgentInstanceRef.decode(decode_json(raw))
        observed=_original_sync(self._source.read_binding(instance,invocation=read_invocation))
        if type(observed) is not BindingProvenance or observed.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        return canonical_bytes(observed.instance_ref.projection())

    def read_agent_binding(self, agent_ref, *, read_invocation):
        """Original independently authorized Profile/source provenance, never a label."""
        self._require_source(read_invocation)
        from ordessa_agents.public import AgentInstanceRef
        from ordessa_agents.sdk.interactions import BindingProvenance
        instance = AgentInstanceRef.decode(decode_json(agent_instance_ref_bytes(agent_ref)))
        observed = _original_sync(self._source.read_binding(instance, invocation=read_invocation))
        if type(observed) is not BindingProvenance or observed.instance_ref != instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        # The SDK's closed decoder rechecks its original projection seal.
        return BindingProvenance.decode(observed.projection())

    def prompt_input_digest(self,execution_ref,params):
        """Original fixed-session digest DATA for a selected review invocation."""
        from ...domain.changes.agent_execution_ref import AgentExecutionRecordRef
        from ordessa_agents.public import AgentInstanceRef
        if type(execution_ref) is not AgentExecutionRecordRef:raise ApplicationError('AGENT_EXECUTION_RECORD_REQUIRED')
        raw=canonical_bytes(params,profile=LIBRARY_JSON_PROFILE)
        if len(raw)>_MAX_PROMPT_BYTES:raise ApplicationError('RECORDED_DISPATCH_INPUT_TOO_LARGE')
        _reject_callbacks(_decode_prompt(raw))
        value=_original_sync(self._source.freeze_prompt(AgentInstanceRef.decode(decode_json(execution_ref.agent_ref_bytes)),raw))
        if value.input_digest!='sha256:'+execution_ref.prompt_input_digest.hex:
            raise ApplicationError('AGENT_PROMPT_DIGEST_MISMATCH')
        return value.input_digest

    @contextmanager
    def prepared_dispatch(self, agent_ref, params_bytes, *, request_id,
                          engineering_attempt_ref, send_invocation, read_invocation):
        """Bound original fresh flow across business preparation and handoff.

        The caller encloses its original approval/reservation COMMITs and send
        in this scope. Abort, cancellation and normal exit only revoke private
        send eligibility; no parent/child row, approval or debit is rewritten.
        """
        invalidate=getattr(self._source,'invalidate_invocation',None)
        if not callable(invalidate):
            raise ApplicationError('AGENT_PREWRITE_BINDING_AUTHORITY_UNAVAILABLE')
        try:
            yield self.claim_and_prepare(agent_ref,params_bytes,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,send_invocation=send_invocation,
                read_invocation=read_invocation)
        finally:
            invalidate(send_invocation)

    def _require_source(self,invocation):
        if (invocation is None or self._source is None or not all(callable(getattr(self._source,n,None))
                for n in ('freeze_prompt','turn_query','query_turn','read_binding','prompt_recorded'))):
            raise ApplicationError('AGENT_ORIGINAL_INTERACTION_AUTHORITY_UNAVAILABLE')
        if (not callable(getattr(self._blobs,'put_verified',None))
                or not callable(getattr(self._blobs,'read_verified',None))
                or type(getattr(self._blobs,'authority_id',None)) is not str):
            raise ApplicationError('AGENT_ORIGINAL_BLOB_AUTHORITY_UNAVAILABLE')

    def claim_and_prepare(self, agent_ref, params_bytes, *, request_id,
                          engineering_attempt_ref, send_invocation, read_invocation):
        """Consume §12.7 once; allocation/authority stays in the original source."""
        raw_ref=agent_instance_ref_bytes(agent_ref)
        self._require_source(read_invocation)
        reserve=getattr(self._source,'reserve_turn',None)
        invalidate=getattr(self._source,'invalidate_invocation',None)
        if not callable(reserve) or not callable(invalidate) or send_invocation is None:
            raise ApplicationError('AGENT_PREWRITE_BINDING_AUTHORITY_UNAVAILABLE')
        validate_id(request_id);validate_id(engineering_attempt_ref)
        if type(params_bytes) is not bytes or len(params_bytes)>_MAX_PROMPT_BYTES:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        _reject_callbacks(_decode_prompt(params_bytes))
        from ordessa_agents.sdk.instances import AgentInstanceRef
        from ordessa_agents.sdk.interactions import FrozenPrompt,TurnReceipt
        instance=AgentInstanceRef.decode(decode_json(raw_ref))
        provenance=_original_sync(self._source.read_binding(instance,invocation=read_invocation))
        projected=_projection(provenance,'agent-binding-provenance/1')
        if getattr(provenance,'instance_ref',None)!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        if _hash(canonical_bytes({k:v for k,v in projected.items() if k!='observationDigest'}))!=provenance.observation_digest:
            raise ApplicationError('AGENT_PROVENANCE_DIGEST_MISMATCH')
        prompt=_original_sync(self._source.freeze_prompt(instance,params_bytes))
        if type(prompt) is not FrozenPrompt or prompt.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROMPT_UNAVAILABLE')
        if type(_projection(prompt,'agent-frozen-prompt/1').get('paramsBytes')) is not dict:
            raise ApplicationError('AGENT_F12_CODEC_UNAVAILABLE')
        # Exactly ONE original metadata claim; no retry or application-made id.
        try:
            reservation=_original_sync(reserve(instance,prompt,request_id=request_id,
                engineering_attempt_ref=engineering_attempt_ref,invocation=send_invocation))
            if type(reservation) is not TurnReceipt:
                raise ApplicationError('AGENT_ORIGINAL_TURN_BINDING_REQUIRED')
            self._receipt(reservation,TurnReceipt,reservation.turn_ref,prompt,engineering_attempt_ref)
            if reservation.state!='reserved' or reservation.endpoint_operation_ref is not None:
                raise ApplicationError('AGENT_TURN_NOT_AT_PREWRITE_BINDING_POINT')
            # Re-read original facts with separate read authorization. These pure
            # checks do not consume an action or turn a reservation into a grant.
            prepared=self.prepare(agent_ref,params_bytes,reservation.turn_ref,
                engineering_attempt_ref=engineering_attempt_ref,read_invocation=read_invocation)
            if prepared.agent_operation_ref!=reservation.agent_operation_ref:
                raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')
            return prepared
        except BaseException:
            invalidate(send_invocation)
            raise

    def prepare(self, agent_ref, params_bytes, original_turn_ref, *, engineering_attempt_ref, read_invocation):
        # Reject historical/mixed refs before any call to the supplied source.
        raw_ref=agent_instance_ref_bytes(agent_ref)
        self._require_source(read_invocation)
        validate_id(engineering_attempt_ref)
        if type(params_bytes) is not bytes or len(params_bytes)>_MAX_PROMPT_BYTES:
            raise ApplicationError('RECORDED_DISPATCH_INPUT_INVALID')
        _reject_callbacks(_decode_prompt(params_bytes))
        from ordessa_agents.sdk.instances import AgentInstanceRef
        from ordessa_agents.sdk.interactions import FrozenPrompt,TurnRef,TurnReadQuery,TurnReceipt,BindingProvenance
        instance=AgentInstanceRef.decode(decode_json(raw_ref))
        if type(original_turn_ref) is not TurnRef or original_turn_ref.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_TURN_BINDING_REQUIRED')
        # Every source call receives ORIGINAL opaque read authority, not JSON
        # scope claims or old Unit grants. Source owns the actual read checks.
        provenance=_original_sync(self._source.read_binding(instance,invocation=read_invocation))
        if type(provenance) is not BindingProvenance or provenance.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        provenance_json=_projection(provenance,'agent-binding-provenance/1')
        expected_provenance={k:v for k,v in provenance_json.items() if k!='observationDigest'}
        if _hash(canonical_bytes(expected_provenance))!=provenance.observation_digest:
            raise ApplicationError('AGENT_PROVENANCE_DIGEST_MISMATCH')
        prompt=_original_sync(self._source.freeze_prompt(instance,params_bytes))
        if type(prompt) is not FrozenPrompt or prompt.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROMPT_UNAVAILABLE')
        prompt_json=_projection(prompt,'agent-frozen-prompt/1')
        if type(prompt_json.get('paramsBytes')) is not dict:
            raise ApplicationError('AGENT_F12_CODEC_UNAVAILABLE')
        frozen_params=_decode_prompt(prompt.params_bytes);_reject_callbacks(frozen_params)
        if frozen_params.get('sessionId')!=prompt.session_id:
            raise ApplicationError('RECORDED_DISPATCH_SESSION_MISMATCH')
        if _hash(canonical_bytes({'schemaVersion':'agent-prompt-input/1','instanceRef':agent_ref,
                'sessionId':prompt.session_id,'params':frozen_params},profile=LIBRARY_JSON_PROFILE))!=prompt.input_digest:
            raise ApplicationError('AGENT_PROMPT_DIGEST_MISMATCH')
        query=_original_sync(self._source.turn_query(original_turn_ref,prompt.input_digest))
        if type(query) is not TurnReadQuery or query.turn_ref!=original_turn_ref or query.expected_input_digest!=prompt.input_digest:
            raise ApplicationError('AGENT_ORIGINAL_QUERY_BINDING_MISMATCH')
        if _hash(canonical_bytes({'schemaVersion':'agent-turn-query/1','turnRef':original_turn_ref.projection(),
                'expectedInputDigest':prompt.input_digest}))!=query.query_digest:
            raise ApplicationError('AGENT_QUERY_DIGEST_MISMATCH')
        receipt=_original_sync(self._source.query_turn(query,invocation=read_invocation))
        self._receipt(receipt,TurnReceipt,original_turn_ref,prompt,engineering_attempt_ref)
        if receipt.state!='reserved' or receipt.endpoint_operation_ref is not None:
            raise ApplicationError('AGENT_TURN_NOT_AT_PREWRITE_BINDING_POINT')
        # This is only an observed reservation. It cannot authorize a fresh
        # write, revive a crashed claim, consume approval or spend model budget.
        return PreparedAgentInput(raw_ref,canonical_bytes(original_turn_ref.projection()),prompt.params_bytes,
            prompt.input_digest,query.query_digest,receipt.agent_operation_ref,engineering_attempt_ref,
            prompt.session_id,canonical_bytes(provenance_json))

    @staticmethod
    def _receipt(receipt,receipt_type,turn,prompt,attempt):
        if (type(receipt) is not receipt_type or receipt.turn_ref!=turn
                or receipt.session_id!=prompt.session_id or receipt.input_digest!=prompt.input_digest
                or receipt.engineering_attempt_ref!=attempt):
            raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')
        projected=_projection(receipt,'agent-protocol-turn/1')
        if type(projected.get('observationBytes')) is not dict:
            raise ApplicationError('AGENT_F12_CODEC_UNAVAILABLE')
        if _hash(receipt.observation_bytes)!=receipt.observation_digest:
            raise ApplicationError('AGENT_OBSERVATION_DIGEST_MISMATCH')
        raw=canonical_bytes(projected)
        if len(raw)>262144:raise ApplicationError('EXECUTION_RECEIPT_BOUND_EXCEEDED')
        return raw

    def capture(self,prepared,*,read_invocation):
        self._require_source(read_invocation)
        if type(prepared) is not PreparedAgentInput:
            raise ApplicationError('AGENT_PREPARED_INPUT_REQUIRED')
        from ordessa_agents.sdk.interactions import FrozenPrompt,TurnRef,TurnReadQuery,TurnReceipt
        from ordessa_agents.sdk.instances import AgentInstanceRef
        instance=AgentInstanceRef.decode(decode_json(prepared.agent_ref_bytes))
        turn=TurnRef.decode(decode_json(prepared.turn_ref_bytes))
        prompt=FrozenPrompt(instance,prepared.session_id,prepared.prompt_bytes,prepared.prompt_input_digest)
        query=_original_sync(self._source.turn_query(turn,prepared.prompt_input_digest))
        if type(query) is not TurnReadQuery or query.query_digest!=prepared.query_digest:
            raise ApplicationError('AGENT_ORIGINAL_QUERY_BINDING_MISMATCH')
        receipt=_original_sync(self._source.query_turn(query,invocation=read_invocation))
        raw=self._receipt(receipt,TurnReceipt,turn,prompt,prepared.engineering_attempt_ref)
        if receipt.agent_operation_ref!=prepared.agent_operation_ref:
            raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')
        expected=Digest('sha256',hashlib.sha256(raw).hexdigest());authority=self._blobs.authority_id
        blob=self._blobs.put_verified(raw,expected,'application/json')
        if (type(blob) is not BlobRef or blob.digest!=expected or blob.byte_length!=len(raw)
                or blob.media_type!='application/json' or self._blobs.read_verified(blob)!=raw
                or self._blobs.authority_id!=authority):
            raise ApplicationError('EXECUTION_BLOB_CAPTURE_MISMATCH')
        return CapturedAgentObservation(prepared,receipt.state,receipt.revision,blob,authority)

    def capture_reference(self,execution_ref,*,read_invocation):
        """Authorized cold read from the same original turn, never send/recovery."""
        from ...domain.changes.agent_execution_ref import AgentExecutionRecordRef
        from ...application.contracts.execution_observations import AgentExecutionObservationRef
        from ordessa_agents.sdk.instances import AgentInstanceRef
        from ordessa_agents.sdk.interactions import TurnRef,TurnReceipt,BindingProvenance
        self._require_source(read_invocation)
        if type(execution_ref) is not AgentExecutionRecordRef:raise ApplicationError('AGENT_EXECUTION_RECORD_REQUIRED')
        instance=AgentInstanceRef.decode(decode_json(execution_ref.agent_ref_bytes))
        turn=TurnRef.decode(decode_json(execution_ref.turn_ref_bytes))
        provenance=_original_sync(self._source.read_binding(instance,invocation=read_invocation))
        if (type(provenance) is not BindingProvenance or provenance.instance_ref!=instance
                or provenance.source_revision!=execution_ref.source_revision):
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        query=_original_sync(self._source.turn_query(turn,'sha256:'+execution_ref.prompt_input_digest.hex))
        if query.query_digest!=execution_ref.query_digest:raise ApplicationError('AGENT_QUERY_DIGEST_MISMATCH')
        receipt=_original_sync(self._source.query_turn(query,invocation=read_invocation))
        if (type(receipt) is not TurnReceipt or receipt.turn_ref!=turn
                or receipt.agent_operation_ref!=execution_ref.operation_ref
                or receipt.engineering_attempt_ref!=execution_ref.engineering_attempt_ref
                or receipt.input_digest!='sha256:'+execution_ref.prompt_input_digest.hex):
            raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')
        raw=canonical_bytes(receipt.projection())
        if len(raw)>262144:raise ApplicationError('EXECUTION_RECEIPT_BOUND_EXCEEDED')
        blob=self._blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
        if blob!=execution_ref.captured_observation_ref or self._blobs.read_verified(blob)!=raw:
            raise ApplicationError('EXECUTION_BLOB_CAPTURE_MISMATCH')
        # This is the original observation's text, not asserted host test/effect
        # success. Preserve extension fields in raw BlobStore bytes unchanged.
        text=None
        if receipt.state=='completed':
            facts=decode_json(receipt.observation_bytes);chunks=[]
            for frame in facts.get('protocol',{}).get('frames',[]):
                if frame.get('method')!='session/update':continue
                params=frame.get('params',{});update=params.get('update',{});content=update.get('content',{})
                if (params.get('sessionId')==receipt.session_id and update.get('sessionUpdate')=='agent_message_chunk'
                        and content.get('type')=='text' and type(content.get('text')) is str):chunks.append(content['text'])
            text=''.join(chunks) if chunks else None
        return AgentExecutionObservationRef(execution_ref.agent_ref_bytes,execution_ref.turn_ref_bytes,
            receipt.agent_operation_ref,receipt.engineering_attempt_ref,receipt.input_digest,query.query_digest,
            receipt.state,receipt.revision,blob,self._blobs.authority_id,text)

    def capture_dispatch(self,binding,*,read_invocation):
        """F2 cold query from original persisted binding, without a fresh flow.

        The caller reads the binding from its original scoped repository first.
        No reservation, resolver, endpoint or send-capability call occurs here.
        The original Agent independently admits every read and supplies its own
        operation identity; the Engineering attempt is never substituted for it.
        """
        from ...domain.changes.agent_dispatch import AgentDispatchBinding, AgentWorkDispatchBinding
        from ...domain.changes.agent_dispatch_codec import encode_agent_dispatch,decode_agent_dispatch
        from ...domain.changes.agent_execution_ref import AgentExecutionRecordRef
        from ...domain.common.outcomes.diagnostics import ReferenceError
        from ordessa_agents.sdk.instances import AgentInstanceRef
        from ordessa_agents.sdk.interactions import TurnRef,TurnReceipt,BindingProvenance,TurnReadQuery
        self._require_source(read_invocation)
        if type(binding) not in (AgentDispatchBinding, AgentWorkDispatchBinding):raise ApplicationError('AGENT_DISPATCH_BINDING_REQUIRED')
        if decode_agent_dispatch(encode_agent_dispatch(binding))!=binding:raise ApplicationError('AGENT_DISPATCH_BINDING_INVALID')
        try:binding.require_turn_binding()
        except ReferenceError as exc:raise ApplicationError(exc.code) from exc
        instance=AgentInstanceRef.decode(decode_json(binding.agent_ref_bytes))
        turn=TurnRef.decode(decode_json(binding.turn_ref_bytes))
        provenance=_original_sync(self._source.read_binding(instance,invocation=read_invocation))
        if type(provenance) is not BindingProvenance or provenance.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        query=_original_sync(self._source.turn_query(turn,'sha256:'+binding.prompt_input_digest.hex))
        if type(query) is not TurnReadQuery or query.query_digest!=binding.expected_query_digest:
            raise ApplicationError('AGENT_QUERY_DIGEST_MISMATCH')
        receipt=_original_sync(self._source.query_turn(query,invocation=read_invocation))
        if (type(receipt) is not TurnReceipt or receipt.turn_ref!=turn
                or receipt.input_digest!='sha256:'+binding.prompt_input_digest.hex
                or receipt.engineering_attempt_ref!=binding.engineering_attempt_ref):
            raise ApplicationError('AGENT_RECEIPT_BINDING_MISMATCH')
        raw=canonical_bytes(receipt.projection())
        if len(raw)>262144:raise ApplicationError('EXECUTION_RECEIPT_BOUND_EXCEEDED')
        blob=self._blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
        if self._blobs.read_verified(blob)!=raw:raise ApplicationError('EXECUTION_BLOB_CAPTURE_MISMATCH')
        reference=AgentExecutionRecordRef(binding.agent_ref_bytes,binding.turn_ref_bytes,provenance.source_revision,
            receipt.agent_operation_ref,binding.engineering_attempt_ref,binding.prompt_input_digest,
            query.query_digest,blob)
        return reference,self.capture_reference(reference,read_invocation=read_invocation)


class AgentDispatchSources:
    """Current original-source read evidence, never checkout/commit authority.

    Trusted resolver supplies only the original opaque read invocation. The
    independent selection guard still owns actual current checkout selection.
    No borrowed Environment/Unit publication or invented source DTO is used.
    """
    def __init__(self,source,read_invocation_resolver):
        if not callable(getattr(source,'read_binding',None)) or not callable(read_invocation_resolver):
            raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
        self.source=source;self.resolver=read_invocation_resolver

    def _read(self,context,package,agent_ref):
        from ordessa_agents.sdk.instances import AgentInstanceRef
        from ordessa_agents.sdk.interactions import BindingProvenance
        if context.scope!=package.scope:raise ApplicationError('DISPATCH_SOURCE_PROFILE_MISMATCH')
        instance=AgentInstanceRef.decode(decode_json(agent_instance_ref_bytes(agent_ref)))
        invocation=self.resolver(context,package,instance)
        if invocation is None:raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        observed=_original_sync(self.source.read_binding(instance,invocation=invocation))
        if type(observed) is not BindingProvenance or observed.instance_ref!=instance:
            raise ApplicationError('AGENT_ORIGINAL_PROVENANCE_UNAVAILABLE')
        expected=package.payload.execution_profile_ref
        profile=observed.profile_ref
        if (profile.environment_namespace!=expected.environment_id or profile.environment_namespace!=instance.namespace
                or profile.profile_id!=expected.profile_id
                or profile.digest!='sha256:'+expected.profile_digest.hex):
            raise ApplicationError('DISPATCH_SOURCE_PROFILE_MISMATCH')
        return canonical_bytes(observed.projection())

    def guard_commit_snapshot(self,context,package,agent_ref):
        from contextlib import contextmanager
        @contextmanager
        def current_read():yield self._read(context,package,agent_ref)
        return current_read()

    def guard_history_read(self,context,package,agent_ref):
        return self.guard_commit_snapshot(context,package,agent_ref)
