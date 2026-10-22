"""Stateless F1.1 adapters for externally bound environment capabilities.

No acquisition, Use lifetime, instance registry, protocol journal or retry here.
Only private references to an env-owned endpoint service and current invocation
mapper. The Agent receives no EnvironmentRef/UseRef/EnvironmentUse value.

This module is owned by the agents distribution and depends on no concrete
environment owner. The caller injects the two owner-specific pieces it alone
may know: the factory that builds the owner's process request, and the owner's
refusal exception class. A refusal raised here therefore carries the caller's
own exception type and message; the bridge itself never names an environment
owner.
"""
import asyncio
from collections.abc import Mapping
import hashlib
from contextlib import contextmanager
from dataclasses import fields, is_dataclass

from ordessa_agents.sdk.prepare import (
    LaunchObservation, LaunchPlan, EndpointError, canonical_digest,
)
from ordessa_agents.sdk.instances import EndpointRef
from ordessa_agents.sdk.endpoint import (
    BoundEndpoint, ProcessObservation, SendObservation, ProtocolEvent, ProtocolEventPage,
)


class EndpointBridgeRefused(RuntimeError):
    """Typed refusal raised by the agents-owned endpoint bridge.

    The default refusal type for a caller that names no owner-specific one. It
    carries the same ``code``/detail shape the environment owner uses, so a
    caller that injects its own refusal class only changes the type and the
    code it already depends on.
    """

    code = 'ENDPOINT_REFUSED'

    def __init__(self, detail: str):
        super().__init__(f'{self.code}: {detail}')
        self.detail = detail


def _locator(ref):
    if isinstance(ref, Mapping):
        return dict(ref)
    # F1 EndpointRef has these exact value attributes; not a resource/Use ref.
    return {'schemaVersion': 'agent-endpoint/1', 'issuer': ref.issuer,
            'endpointId': ref.endpoint_id, 'revision': ref.revision,
            'descriptorDigest': ref.descriptor_digest}


class EnvironmentEndpointResolver:
    """Resolve bound endpoint capabilities for the Agent runtime.

    ``process_request_factory`` is called with the same arguments as the
    environment owner's own request builder (``argv`` plus the ``cwd``/``env``
    keywords) and returns that owner's process request object.
    ``refusal`` is the exception class raised for every refusal of this
    bridge; it takes the refusal message as its only argument.
    """

    def __init__(self, endpoints, *, invocation_resolver, process_request_factory,
                 refusal=EndpointBridgeRefused, process_observation_factory=None):
        self._endpoints = endpoints
        self._invocation_resolver = invocation_resolver
        self._process_request_factory = process_request_factory
        self._refusal = refusal
        self._process_observation_factory = process_observation_factory or ProcessObservation

    def _caller(self, invocation):
        trusted = self._invocation_resolver(invocation)
        return trusted.owner_scope, trusted

    async def resolve(self, ref, invocation):
        scope, trusted = self._caller(invocation)
        locator = _locator(ref)
        _, descriptor = self._endpoints.resolve(locator, scope, invocation=trusted)
        members = {'ref': EndpointRef.decode(locator), 'descriptor': descriptor, 'launcher': None, 'observe': None,
                   'communicate': None, 'terminate': None, 'detach': None, 'files': None}
        for name in descriptor['capabilities']:
            members[name] = _EndpointCapability(self, locator, name)
        # Structural BoundEndpoint carrier, not an execution entity or DTO copy.
        return BoundEndpoint(**members)


class _EndpointCapability:
    def __init__(self, resolver, locator, capability):
        self._resolver, self._locator, self._capability = resolver, dict(locator), capability

    def _refuse(self, message):
        return self._resolver._refusal(message)

    def _binding(self, invocation, capability):
        if self._capability != capability:
            raise self._refuse('separate endpoint capability required')
        scope, trusted = self._resolver._caller(invocation)
        binding, descriptor = self._resolver._endpoints.resolve(self._locator, scope,
            invocation=trusted, capability=capability)
        return scope, trusted, binding, descriptor

    async def launch(self, plan, request_id, invocation):
        refusal_ref = 'endpoint-request:' + hashlib.sha256(str(request_id).encode()).hexdigest()
        try:
            scope, trusted, _, descriptor = self._binding(invocation, 'launcher')
            if type(plan) is not LaunchPlan or canonical_digest(plan.projection(without_digest=True)) != plan.plan_digest:
                raise self._refuse('launch plan digest differs')
            if not set(plan.required_capabilities) <= set(descriptor['capabilities']):
                raise self._refuse('required independent endpoint capability unavailable')
            for name in plan.required_capabilities:
                self._resolver._endpoints.resolve(self._locator, scope, invocation=trusted, capability=name)
            # Secret resolution/material import requires an externally supplied
            # implementation; never substitute ambient credentials or files.
            if plan.secret_bindings or plan.material_refs:
                raise self._refuse('this launcher requires an external secret/material resolver')
            for artifact in plan.configuration_artifacts:
                self._resolver._endpoints.verify_materialized(self._locator, scope, artifact.projection(), invocation=trusted)
            cwd = self._resolver._endpoints.directory(self._locator, scope, plan.cwd_ref.projection(), invocation=trusted)
            request = self._resolver._process_request_factory(plan.argv, cwd=cwd, env=dict(plan.environment_values))
            data = self._resolver._endpoints.launch(self._locator, scope, request,
                request_id=request_id, invocation=trusted,
                prepared_configurations=[r.projection() for r in plan.prepared_configuration_refs])
        except self._resolver._refusal:
            return LaunchObservation(refusal_ref, 'refused', facts={'action': 'launch'},
                error=EndpointError('CAPABILITY_UNSUPPORTED', 'Bound launcher or prepared input unavailable'))
        except Exception:
            return LaunchObservation(refusal_ref, 'unknown', facts={'action': 'launch'},
                error=EndpointError('EFFECT_UNKNOWN', 'Launch outcome requires resource inspection'))
        return _observation(data, action='launch', process_ref=data.get('processEndpointRef'))

    def _process(self, invocation, capability):
        scope, trusted, _, _ = self._binding(invocation, capability)
        return self._resolver._endpoints.process(self._locator, scope, invocation=trusted)

    async def observe(self, deadline, invocation):
        if deadline is not None and deadline <= asyncio.get_running_loop().time():
            raise self._refuse('observation deadline elapsed')
        result = self._process(invocation, 'observe').observe()
        # Native identity is opaque evidence; a PID is never reconnect proof.
        digest = 'sha256:' + hashlib.sha256(result.identity.encode()).hexdigest()
        return self._resolver._process_observation_factory(state=result.state,
            observed_at=result.observed_at, native_identity_digest=digest,
            exit_code=result.exit_code, evidence_refs=())

    async def terminate(self, request_id, force, deadline, invocation):
        if deadline is not None and deadline <= asyncio.get_running_loop().time():
            raise self._refuse('termination deadline elapsed')
        data = await self._process(invocation, 'terminate').terminate(request_id=request_id, force=force)
        return _observation(data, action='terminate', process_ref=self._locator)

    async def detach(self, request_id, invocation):
        data = self._process(invocation, 'detach').detach(request_id=request_id)
        return _observation(data, action='detach', process_ref=self._locator)

    def _lifecycle_cut(self, binding, guard, action):
        from ordessa_agents.instances.contracts import InstanceControl
        if not callable(guard):
            raise self._refuse('mandatory instance lifecycle guard required')
        try:
            control=InstanceControl.decode(binding)
        except (ValueError,TypeError,KeyError):
            raise self._refuse('closed instance lifecycle binding required') from None
        if (control.endpoint_ref.projection()!=self._locator
                or control.active_action!=action or control.active_operation_ref is None):
            raise self._refuse('instance lifecycle endpoint/action binding differs')
        @contextmanager
        def admitted_cut():
            # The provider invokes this around its actual synchronous signal or
            # association mutation. Agent owns the current instance epoch/claim;
            # environments independently rechecks the original resource ACL.
            with guard():
                yield
        return admitted_cut

    async def terminate_guarded(self,request_id,force,invocation,*,binding,guard):
        cut=self._lifecycle_cut(binding,guard,'stop')
        data=await self._process(invocation,'terminate').terminate_guarded(
            request_id=request_id,force=force,guard_effect=cut)
        return _observation(data,action='terminate',process_ref=self._locator)

    async def detach_guarded(self,request_id,invocation,*,binding,guard):
        cut=self._lifecycle_cut(binding,guard,'detach')
        data=self._process(invocation,'detach').detach_guarded(
            request_id=request_id,guard_effect=cut)
        return _observation(data,action='detach',process_ref=self._locator)

    async def send(self, effect_id, frame, deadline, invocation):
        if type(frame) is not bytes or len(frame) > 1048576:
            raise self._refuse('bounded protocol frame required')
        remaining = None if deadline is None else deadline-asyncio.get_running_loop().time()
        if remaining is not None and remaining <= 0:
            raise self._refuse('protocol send deadline elapsed')
        count = await self._process(invocation, 'communicate').write_stdin(frame, timeout=remaining)
        # This is byte dispatch evidence, not remote consumption/interaction success.
        return SendObservation('completed', count, 'possibly_sent')

    async def send_guarded(self, frame, request_id, deadline, invocation, *, binding, write_guard):
        if self._capability != 'communicate':
            raise self._refuse('separate communicate capability required')
        # No second DTO family: until agents delivers the exact F1.2 public
        # module this operation is explicitly unavailable before a child claim.
        try:
            from ordessa_agents.sdk.interactions import (WriteBinding, CancelBinding,
                GuardedSendObservation, cancel_endpoint_request_id)
            from ordessa_agents.instances.contracts import (LifecycleWriteBinding,NativeFrameBinding,
                lifecycle_endpoint_request_id,lifecycle_native_request_id)
            from ordessa_agents.sdk.native_runtime import (NativeDispatchBinding,
                native_dispatch_request_id)
        except ImportError:
            raise self._refuse('F1.2 interaction contracts unavailable') from None
        if (not is_dataclass(GuardedSendObservation)
                or {f.name for f in fields(GuardedSendObservation)} != {'operation_ref','status','bytes_sent','error'}):
            raise self._refuse('exact F1.2 guarded observation contract unavailable')
        if (type(binding) not in (WriteBinding,CancelBinding,LifecycleWriteBinding,NativeDispatchBinding,NativeFrameBinding) or type(frame) is not bytes or not frame
                or len(frame) > 1048576 or not callable(getattr(write_guard, 'guard_write', None))):
            raise self._refuse('exact F1.2 binding, bounded frame and guard required')
        if (binding.endpoint_request_id != request_id
                or binding.frame_digest != 'sha256:' + hashlib.sha256(frame).hexdigest()):
            raise self._refuse('guarded frame or endpoint request binding differs')
        if type(binding) is WriteBinding:
            expected = canonical_digest({'schemaVersion':'agent-endpoint-frame-request/1',
                'agentOperationRef': binding.agent_operation_ref, 'endpointRef': self._locator,
                'frameDigest': binding.frame_digest, 'frameOrdinal': 0})
        elif type(binding) is NativeDispatchBinding:
            if binding.endpoint_ref.projection()!=self._locator:
                raise self._refuse('native endpoint binding differs')
            expected=native_dispatch_request_id(binding.endpoint_ref,binding.frame_digest)
        elif type(binding) is CancelBinding:
            expected=cancel_endpoint_request_id(binding.agent_operation_ref,
                EndpointRef.decode(self._locator),binding.frame_digest)
        elif type(binding) is NativeFrameBinding:
            # Provider-neutral bootstrap frame: the owner assigns the ordinal and
            # the plugin owns the frame bytes; no dialect is interpreted here.
            if binding.endpoint_ref.projection()!=self._locator:
                raise self._refuse('native bootstrap endpoint binding differs')
            expected=lifecycle_native_request_id(binding.start_operation_ref,binding.phase,
                binding.endpoint_ref,binding.frame_digest,binding.ordinal)
        else:
            if binding.endpoint_ref.projection()!=self._locator:
                raise self._refuse('lifecycle endpoint binding differs')
            expected=lifecycle_endpoint_request_id(binding.start_operation_ref,binding.phase,binding.endpoint_ref,binding.frame_digest)
        if request_id != expected:
            raise self._refuse('child request must bind original endpoint and agent operation')
        scope, trusted = self._resolver._caller(invocation)
        remaining = None if deadline is None else deadline - asyncio.get_running_loop().time()
        if remaining is not None and remaining <= 0:
            raise self._refuse('guarded send deadline elapsed')
        if type(binding) is WriteBinding:
            correlation = {'instanceRef': binding.turn_ref.instance_ref.projection(),
                'turnId': binding.turn_ref.turn_id, 'sessionId': binding.session_id,
                'agentOperationRef': binding.agent_operation_ref,
                'engineeringAttemptRef': binding.engineering_attempt_ref,
                'inputDigest': binding.input_digest, 'frameDigest': binding.frame_digest}
        elif type(binding) is NativeDispatchBinding:
            correlation={'schemaVersion':'agent-native-dispatch-correlation/1',
                'instanceRef':binding.instance_ref.projection(),'kind':binding.kind,
                'protocolId':binding.protocol_id,'sessionId':binding.session_id,
                'inputDigest':binding.input_digest,'frameDigest':binding.frame_digest,
                'wireId':binding.wire_id}
        elif type(binding) is CancelBinding:
            correlation={'schemaVersion':'agent-cancel-child-correlation/1',
                'instanceRef':binding.instance_ref.projection(),'sessionId':binding.session_id,
                'agentOperationRef':binding.agent_operation_ref,'frameDigest':binding.frame_digest}
        else:
            correlation=binding.projection()
        @contextmanager
        def admitted_cut():
            # This callback is invoked by the provider's physical writer, never
            # here around an outer await. No raw writer escapes the callback.
            with write_guard.guard_write(binding, invocation):
                yield
        data = await self._resolver._endpoints.send_guarded(self._locator, scope, frame,
            request_id=request_id, invocation=trusted, correlation=correlation,
            write_guard=admitted_cut, timeout=remaining)
        delivery = data.get('delivery', 'possibly_sent')
        # Possibly-sent is already delivery uncertainty, not an unsent
        # refusal. Do not fabricate an unsent error or a completed protocol fact.
        error = (EndpointError('WRITE_REFUSED', 'Original physical child effect was not sent')
                 if delivery == 'not_sent' else None)
        return GuardedSendObservation(operation_ref=data['operationRef'], status=delivery,
            bytes_sent=data.get('bytesObserved'), error=error)

    async def receive(self, cursor, deadline, invocation):
        if cursor is not None:
            raise self._refuse('local transport has no historical cursor replay')
        remaining = None if deadline is None else deadline-asyncio.get_running_loop().time()
        if remaining is not None and remaining <= 0:
            raise self._refuse('protocol receive deadline elapsed')
        chunk = await self._process(invocation, 'communicate').read_stdout(65536, timeout=remaining)
        events = (ProtocolEvent('bytes', 'sha256:'+hashlib.sha256(chunk).hexdigest(), chunk),) if chunk else ()
        return ProtocolEventPage(events, cursor=None, has_more=False)

    async def verify(self, prepared_ref, invocation):
        scope, trusted, _, _ = self._binding(invocation, 'files')
        return self._resolver._endpoints.verify(self._locator, scope, prepared_ref.projection(), invocation=trusted)

    async def materialize(self, artifact, request_id, invocation):
        scope, trusted, _, _ = self._binding(invocation, 'files')
        return self._resolver._endpoints.materialize(self._locator, scope, artifact.projection(),
            request_id=request_id, invocation=trusted)


def _observation(data, *, action, process_ref=None):
    state = data['status']
    if state == 'pending': state = 'accepted'
    facts = {'action': action}
    if action == 'launch' and state == 'completed':
        # Confirmed spawn is not a continuous observe permission.
        facts['processState'] = 'unknown'
    if action == 'terminate':
        facts.update(cancellation=data.get('cancellation', 'unknown'), processState=data.get('processState', 'unknown'))
    if action == 'detach':
        facts.update(associationDetached=state == 'completed', exitClaimed=False)
    error = None
    if state in ('refused', 'unknown'):
        error = EndpointError('CAPABILITY_UNSUPPORTED' if state == 'refused' else 'EFFECT_UNKNOWN',
                              'Original endpoint operation requires inspection')
    if process_ref is not None and not isinstance(process_ref, EndpointRef):
        process_ref = EndpointRef.decode(dict(process_ref))
    if state == 'refused': process_ref = None
    return LaunchObservation(data['operationRef'], state, process_endpoint_ref=process_ref,
                             facts=facts, error=error)
