"""Profile-aware lifecycle on the ORIGINAL Agent Records and external endpoint.

No environment/Use access, hidden launch client, permission issuer or recovery
resend. Every native session fact originates in the original guarded bootstrap.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass,replace
import hashlib,inspect,json,threading
from uuid import uuid4

from .contracts import (AgentStartRequest,AgentStartReceipt,PreparedAgentContext,
    LifecycleWriteBinding,NativeFrameBinding,lifecycle_endpoint_request_id,lifecycle_native_request_id)
from ..profiles import ProfileService,encode_revision_ref
from ..sdk.endpoint import BoundEndpoint
from ..sdk.harness import HarnessDescriptor
from ..sdk.instances import AgentInstanceRef
from ..sdk.prepare import LaunchPlan,EndpointError,canonical_digest,canonical_json,validate_launch_observation
from ..sdk.manager import ManagerRefused
from ..sdk.interactions import BindingProvenance,GuardedSendObservation,_check as _external_check,_text,InteractionsRefused
from ..sdk.acp import observe_bootstrap


def _check(authority,name,*args):
    try:return _external_check(authority,name,*args)
    except InteractionsRefused as error:raise ManagerRefused(error.code) from None


def _scope(manager,invocation):
    authority=manager.lifecycle_authority
    if not all(callable(getattr(authority,name,None)) for name in
            ('principal_scope','check_start','check_lifecycle_write','check_read_instance')):
        raise ManagerRefused('LIFECYCLE_AUTHORITY_UNAVAILABLE')
    try:return _text(authority.principal_scope(invocation),'verified principal scope')
    except Exception:raise ManagerRefused('LIFECYCLE_AUTHORITY_REFUSED') from None


def _start_key(scope,request_id):return canonical_digest({'scope':scope,'startRequestId':request_id})


def _read(manager,row,invocation):
    scope=_scope(manager,invocation)
    if row.principal!=scope:raise ManagerRefused('READ_NOT_AUTHORIZED')
    try:receipt=AgentStartReceipt.decode(row.payload['agentStartReceipt'])
    except Exception:raise ManagerRefused('RECORD_CORRUPT') from None
    _check(manager.lifecycle_authority,'check_read_instance',invocation,receipt.instance_id)
    if receipt.operation_ref!=row.operation_ref:raise ManagerRefused('RECORD_CORRUPT')
    if row.status=='reserved':return replace(receipt,state='unknown')
    if row.status!=receipt.state:raise ManagerRefused('RECORD_CORRUPT')
    if receipt.state=='running':
        key=canonical_digest({'namespace':receipt.instance_ref.namespace,'instanceId':receipt.instance_id})
        binding=manager.records.operation(key,'instance-binding')
        if binding is None or binding.payload.get('sourceStartRequestKey')!=row.request_id:raise ManagerRefused('INSTANCE_ORIGIN_CORRUPT')
        manager.records.validate_instance_origin(binding)
    return receipt


def read_start(manager,request_id,invocation):
    scope=_scope(manager,invocation);_text(request_id,'request id')
    row=manager.records.operation(_start_key(scope,request_id),'agent-start')
    if row is None:raise ManagerRefused('INSTANCE_NOT_FOUND')
    return _read(manager,row,invocation)


@dataclass(frozen=True)
class _Session:
    session_id:str
    protocol_id:str='acp'


class _ProcessView:
    __slots__=('_open','_native')
    def __init__(self,open_session,native_channel=None):
        self._open=open_session;self._native=native_channel
    async def open_acp_session(self,bootstrap):return await self._open(bootstrap)
    @property
    def native_channel(self):
        """Protocol-neutral guarded exchange; None for ACP-only compositions."""
        return self._native


class _NativeChannel:
    """One guarded request/response exchange on the original endpoint.

    The provider owns its protocol: it receives the exact correlation id to
    embed and returns the bytes for one request frame. This owner only claims,
    guards the physical write, observes bounded frames until the matching
    response, and records the outcome. It never parses a provider dialect.
    """

    __slots__=('_bootstrap',)

    def __init__(self,bootstrap):self._bootstrap=bootstrap

    async def exchange(self,label,encode,accept=None):
        return await self._bootstrap.exchange(label,encode,accept)

    async def await_event(self,label,accept):
        """Observe one unsolicited native frame that matches *accept*.

        Some protocols announce their session first (for example a ``system/init``
        event). Nothing is written in this phase: it can only observe.
        """
        return await self._bootstrap.await_event(label,accept)


class _NativeBootstrap:
    def __init__(self,manager,start,request,plan,prepared,endpoint,invocation,deadline):
        self.manager,self.start,self.request,self.plan,self.prepared=manager,start,request,plan,prepared
        self.endpoint,self.invocation,self.deadline=endpoint,invocation,deadline
        self.task=asyncio.current_task();self.thread=threading.get_ident()
        self._ordinal=0

    def channel(self):return _NativeChannel(self)

    def _phase_id(self,label):
        _text(label,'bootstrap phase')
        return self.start.operation_ref+'/'+label

    async def exchange(self,label,encode,accept=None):
        if accept is not None and not callable(accept):raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
        if asyncio.current_task() is not self.task or threading.get_ident()!=self.thread:
            raise ManagerRefused('BOOTSTRAP_WRITE_BINDING_MISMATCH')
        phase_id=self._phase_id(label)
        try:frame=encode(phase_id)
        except Exception:raise ManagerRefused('BOOTSTRAP_FRAME_INVALID') from None
        if type(frame) is not bytes or not frame or len(frame)>1048576:
            raise ManagerRefused('BOOTSTRAP_FRAME_INVALID')
        frame_digest='sha256:'+hashlib.sha256(frame).hexdigest()
        ordinal=self._ordinal;self._ordinal+=1
        child=lifecycle_native_request_id(self.start.operation_ref,label,self.endpoint.ref,frame_digest,ordinal)
        binding=NativeFrameBinding(self.request.profile_revision_ref.environment_namespace,
            self.start.payload['agentStartReceipt']['instanceId'],self.start.operation_ref,label,ordinal,
            self.endpoint.ref,self.request.profile_revision_ref,self.plan.plan_digest,
            self.prepared.directory_binding_digest,frame_digest,child)
        _check(self.manager.lifecycle_authority,'check_lifecycle_write',self.invocation,binding)
        created,phase_row=self.manager.records.claim(phase_id,'bootstrap-frame',principal=self.start.principal,
            target=canonical_json(binding.projection()),request_digest=frame_digest,
            operation_ref=phase_id,payload={'binding':binding.projection()})
        if created!='created':raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
        owner=self
        class Guard:
            @contextmanager
            def guard_write(self,actual,invocation):
                if (actual!=binding or invocation is not owner.invocation
                        or asyncio.current_task() is not owner.task or threading.get_ident()!=owner.thread):
                    raise ManagerRefused('BOOTSTRAP_WRITE_BINDING_MISMATCH')
                _check(owner.manager.lifecycle_authority,'check_lifecycle_write',invocation,binding)
                parent=owner.manager.records.operation(owner.start.request_id,'agent-start')
                if parent is None or parent.status!='reserved' or parent.operation_ref!=owner.start.operation_ref:
                    raise ManagerRefused('START_OPERATION_CHANGED')
                current=owner.manager.records.operation(phase_id,'bootstrap-frame')
                if current is None or current.status!='reserved' or current.request_digest!=frame_digest:
                    raise ManagerRefused('BOOTSTRAP_OPERATION_CHANGED')
                previous=owner.manager.records._db.execute('PRAGMA busy_timeout').fetchone()[0]
                owner.manager.records._db.execute('PRAGMA busy_timeout=0')
                try:owner.manager.records.complete(phase_id,'bootstrap-frame',
                    status='possibly-written',operation_ref=phase_id,payload=current.payload)
                finally:owner.manager.records._db.execute('PRAGMA busy_timeout='+str(previous))
                yield
        try:
            sent=await self.endpoint.communicate.send_guarded(frame,child,self.deadline,self.invocation,
                binding=binding,write_guard=Guard())
            if type(sent) is not GuardedSendObservation:raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
            delivery={'delivery':sent.status,'endpointOperationRef':sent.operation_ref,'bytesSent':sent.bytes_sent}
            current=self.manager.records.operation(phase_id,'bootstrap-frame')
            if sent.status=='not_sent':
                self.manager.records.finish_bootstrap_phase(current,status='failed',payload={**current.payload,**delivery})
                raise ManagerRefused('BOOTSTRAP_NOT_SENT')
            if current.status!='possibly-written':raise ManagerRefused('BOOTSTRAP_WRITER_NOT_GUARDED')
            response=await self._observe(phase_id,accept,delivery)
            self.manager.records.finish_bootstrap_phase(current,status='completed',
                payload={**current.payload,'observation':{'delivery':delivery,'nativeResponse':bool(response)}})
            return response
        except BaseException:
            current=self.manager.records.operation(phase_id,'bootstrap-frame')
            if current is not None and current.status in ('reserved','possibly-written'):
                self.manager.records.finish_bootstrap_phase(current,status='unknown',payload=current.payload)
            raise

    async def await_event(self,label,accept):
        if asyncio.current_task() is not self.task or threading.get_ident()!=self.thread:
            raise ManagerRefused('BOOTSTRAP_WRITE_BINDING_MISMATCH')
        if not callable(accept):raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
        phase_id=self._phase_id(label)
        marker='sha256:'+hashlib.sha256(('observe:'+label).encode()).hexdigest()
        created,phase_row=self.manager.records.claim(phase_id,'bootstrap-observe',
            principal=self.start.principal,target=canonical_json({'phase':label}),
            request_digest=marker,operation_ref=phase_id,payload={'phase':label})
        if created!='created':raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
        try:
            value=await self._observe(phase_id,accept)
            self.manager.records.finish_bootstrap_observe(
                self.manager.records.operation(phase_id,'bootstrap-observe'),
                status='completed',payload={'phase':label,'observed':True})
            return value
        except BaseException:
            current=self.manager.records.operation(phase_id,'bootstrap-observe')
            if current is not None and current.status=='reserved':
                self.manager.records.finish_bootstrap_observe(current,status='unknown',payload=current.payload)
            raise

    async def _observe(self,phase_id,accept=None,delivery=None):
        loop=asyncio.get_running_loop();pending=b'';cursor=None;seen=set();size=0
        for _ in range(256):
            remaining=self.deadline-loop.time()
            if remaining<=0:raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
            page=await asyncio.wait_for(self.endpoint.communicate.receive(cursor,self.deadline,self.invocation),remaining)
            if type(page).__name__!='ProtocolEventPage':raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
            if not page.events:
                if not page.has_more:raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
                cursor=page.cursor;continue
            for event in page.events:
                if event.kind!='bytes' or event.payload_digest!='sha256:'+hashlib.sha256(event.payload_bytes).hexdigest():
                    raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
                size+=len(event.payload_bytes)
                if size>1048576:raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
                pending+=event.payload_bytes
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    if not line:continue
                    try:value=json.loads(line.decode('utf-8'))
                    except (ValueError,UnicodeDecodeError):raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID') from None
                    if type(value) is dict:
                        matched = (value.get('id')==phase_id) if accept is None else bool(accept(value))
                        if matched:return value
            if page.has_more:
                if page.cursor in seen:raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
                seen.add(page.cursor);cursor=page.cursor
        raise ManagerRefused('BOOTSTRAP_OBSERVATION_LIMIT')


class _Bootstrap:
    def __init__(self,manager,start,request,plan,prepared,endpoint,invocation,deadline):
        self.manager,self.start,self.request,self.plan,self.prepared=manager,start,request,plan,prepared
        self.endpoint,self.invocation,self.deadline=endpoint,invocation,deadline
        self.session=None;self.called=False
        self.task=asyncio.current_task();self.thread=threading.get_ident()

    async def _phase(self,phase,params):
        manager=self.manager;records=manager.records
        phase_id=self.start.operation_ref+'/'+phase
        frame=(canonical_json({'jsonrpc':'2.0','id':phase_id,'method':phase,'params':params})+'\n').encode()
        frame_digest='sha256:'+hashlib.sha256(frame).hexdigest()
        child=lifecycle_endpoint_request_id(self.start.operation_ref,phase,self.endpoint.ref,frame_digest)
        binding=LifecycleWriteBinding(self.request.profile_revision_ref.environment_namespace,
            self.start.payload['agentStartReceipt']['instanceId'],self.start.operation_ref,phase,
            self.endpoint.ref,self.request.profile_revision_ref,self.plan.plan_digest,
            self.prepared.directory_binding_digest,frame_digest,child)
        _check(manager.lifecycle_authority,'check_lifecycle_write',self.invocation,binding)
        created,phase_row=records.claim(phase_id,'bootstrap-frame',principal=self.start.principal,
            target=canonical_json(binding.projection()),request_digest=frame_digest,
            operation_ref=phase_id,payload={'binding':binding.projection()})
        if created!='created':raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
        owner=self
        class Guard:
            @contextmanager
            def guard_write(self,actual,invocation):
                if (actual!=binding or invocation is not owner.invocation
                        or asyncio.current_task() is not owner.task or threading.get_ident()!=owner.thread):
                    raise ManagerRefused('BOOTSTRAP_WRITE_BINDING_MISMATCH')
                _check(manager.lifecycle_authority,'check_lifecycle_write',invocation,binding)
                parent=records.operation(owner.start.request_id,'agent-start')
                if parent is None or parent.status!='reserved' or parent.operation_ref!=owner.start.operation_ref:
                    raise ManagerRefused('START_OPERATION_CHANGED')
                current=records.operation(phase_id,'bootstrap-frame')
                if current is None or current.status!='reserved' or current.request_digest!=frame_digest:
                    raise ManagerRefused('BOOTSTRAP_OPERATION_CHANGED')
                # Fail fast at the actual physical cut; no await or response wait
                # occurs while this synchronous metadata update owns its DB lock.
                previous=records._db.execute('PRAGMA busy_timeout').fetchone()[0]
                records._db.execute('PRAGMA busy_timeout=0')
                try:records.complete(phase_id,'bootstrap-frame',status='possibly-written',operation_ref=phase_id,payload=current.payload)
                finally:records._db.execute('PRAGMA busy_timeout='+str(previous))
                yield
        try:
            sent=await self.endpoint.communicate.send_guarded(frame,child,self.deadline,self.invocation,
                binding=binding,write_guard=Guard())
            if type(sent) is not GuardedSendObservation:raise ManagerRefused('BOOTSTRAP_OBSERVATION_INVALID')
            current=records.operation(phase_id,'bootstrap-frame')
            delivery={'delivery':sent.status,'endpointOperationRef':sent.operation_ref,'bytesSent':sent.bytes_sent}
            if sent.status=='not_sent':
                records.finish_bootstrap_phase(current,status='failed',payload={**current.payload,**delivery})
                raise ManagerRefused('BOOTSTRAP_NOT_SENT')
            if current.status!='possibly-written':raise ManagerRefused('BOOTSTRAP_WRITER_NOT_GUARDED')
            state,observation=await observe_bootstrap(self.endpoint.communicate.receive,operation_ref=phase_id,
                phase=phase,deadline=self.deadline,invocation=self.invocation,delivery=delivery)
            records.finish_bootstrap_phase(current,status=state,payload={**current.payload,'observation':observation})
            if state!='completed':raise ManagerRefused('BOOTSTRAP_UNRESOLVED')
            responses=[frame for frame in observation['protocol']['frames'] if frame.get('id')==phase_id and 'result' in frame]
            if len(responses)!=1:raise ManagerRefused('BOOTSTRAP_RESPONSE_INVALID')
            return responses[0]['result']
        except BaseException:
            current=records.operation(phase_id,'bootstrap-frame')
            if current is not None and current.status in ('reserved','possibly-written'):
                records.finish_bootstrap_phase(current,status='unknown',payload=current.payload)
            raise

    async def open(self,bootstrap):
        if self.called or bootstrap!=self.prepared.context.session_bootstrap or bootstrap.mode!='fresh':
            raise ManagerRefused('BOOTSTRAP_MODE_UNSUPPORTED')
        self.called=True
        await self._phase('initialize',{'protocolVersion':1,'clientCapabilities':{}})
        response=await self._phase('session/new',{'cwd':self.prepared.native_working_directory,'mcpServers':[]})
        self.session=_Session(response['sessionId'])
        return self.session


async def start_agent(manager,request,endpoint,invocation):
    if type(request) is not AgentStartRequest or type(endpoint) is not BoundEndpoint or endpoint.ref!=request.endpoint_ref:
        raise ManagerRefused('START_REQUEST_INVALID')
    scope=_scope(manager,invocation);key=_start_key(scope,request.request_id)
    digest=canonical_digest(request.projection());target=canonical_json(request.projection())
    existing=manager.records.operation(key,'agent-start')
    if existing is not None:
        if (existing.principal,existing.target,existing.request_digest)!=(scope,target,digest):raise ManagerRefused('REQUEST_CONFLICT')
        return _read(manager,existing,invocation)
    if (type(manager.profile_service) is not ProfileService or not callable(getattr(manager.harness_resolver,'resolve',None))
            or not callable(getattr(manager.preparation_resolver,'resolve',None))):raise ManagerRefused('AGENT_PREPARATION_UNAVAILABLE')
    if manager.profile_service.principal_scope!=scope:raise ManagerRefused('PROFILE_SCOPE_MISMATCH')
    if request.session_mode=='resume' or request.resume_ref is not None:raise ManagerRefused('RESUME_UNAVAILABLE')
    # Resolve the ORIGINAL externally bound endpoint; caller-supplied port objects
    # cannot replace the trusted resolver or acquire a new resource/Use.
    bound=await manager._bound(request.endpoint_ref,invocation)
    revision=manager.profile_service.get_revision(request.profile_revision_ref)
    provider=manager.harness_resolver.resolve(revision.content.harness_definition_ref)
    descriptor=getattr(provider,'descriptor',None)
    if type(descriptor) is not HarnessDescriptor or dict(descriptor.definition_ref)!=dict(revision.content.harness_definition_ref):raise ManagerRefused('HARNESS_PIN_MISMATCH')
    # ACP and session-less providers are the default path. Any other protocol is
    # admitted only when the provider exports its own native bootstrap, so an
    # unsupported brand stays an explicit refusal rather than an ACP translation.
    if descriptor.protocol_id not in (None,'acp') and not callable(
            getattr(provider,'open_native_session',None)):
        raise ManagerRefused('PROTOCOL_UNSUPPORTED')
    if (descriptor.protocol_id is None)!=(request.session_mode=='none'):raise ManagerRefused('SESSION_MODE_UNSUPPORTED')
    _check(manager.lifecycle_authority,'check_start',invocation,request,descriptor)
    prepared=manager.preparation_resolver.resolve(request,bound,invocation)
    if inspect.isawaitable(prepared) or type(prepared) is not PreparedAgentContext:raise ManagerRefused('PREPARED_CONTEXT_REQUIRED')
    context=prepared.context
    if (context.session_bootstrap.mode!=request.session_mode or context.prepared_configuration_refs!=request.prepared_configuration_refs
            or context.materials!=request.material_refs):raise ManagerRefused('PREPARATION_INPUT_MISMATCH')
    initial=AgentStartReceipt('instance-'+uuid4().hex,'agent-start/'+uuid4().hex,'preparing')
    state,row=manager.records.claim(key,'agent-start',principal=scope,target=target,request_digest=digest,
        operation_ref=initial.operation_ref,payload={'agentStartReceipt':initial.projection()})
    if state!='created':return _read(manager,row,invocation)
    process_ref=None;launch_attempted=False;stream=None;resolved=False
    try:
        provider.validate_profile(revision.content)
        plan=provider.prepare(revision.content,context)
        if type(plan) is not LaunchPlan:raise ManagerRefused('LAUNCH_PLAN_INVALID')
        LaunchPlan.decode(plan.projection())
        if (plan.session_bootstrap!=context.session_bootstrap or plan.prepared_configuration_refs!=request.prepared_configuration_refs
                or plan.material_refs!=request.material_refs):raise ManagerRefused('PREPARED_PLAN_MISMATCH')
        if plan.configuration_artifacts:raise ManagerRefused('CONFIGURATION_MATERIALIZATION_UNAVAILABLE')
        if any(getattr(bound,member) is None for member in plan.required_capabilities) or bound.launcher is None:raise ManagerRefused('ENDPOINT_CAPABILITY_UNAVAILABLE')
        allowed=bound.descriptor.get('preparedConfigurations',())
        if any(ref.projection() not in allowed for ref in plan.prepared_configuration_refs):raise ManagerRefused('PREPARED_CONFIGURATION_NOT_BOUND')
        _check(manager.lifecycle_authority,'check_start',invocation,request,descriptor)
        launch_attempted=True
        launched=await bound.launcher.launch(plan,initial.operation_ref+'/launch',invocation)
        validate_launch_observation(launched)
        process_ref=launched.process_endpoint_ref
        if launched.status!='completed':
            outcome='failed' if launched.status=='refused' else 'starting' if launched.status=='accepted' else 'unknown'
            receipt=replace(initial,state=outcome,process_endpoint_ref=process_ref,error=launched.error)
            manager.records.complete(key,'agent-start',status=outcome,operation_ref=initial.operation_ref,payload={'agentStartReceipt':receipt.projection()})
            return _read(manager,manager.records.operation(key,'agent-start'),invocation)
        process=await manager._bound(process_ref,invocation)
        session=None;bootstrap=None
        if descriptor.protocol_id is not None:
            if process.communicate is None:raise ManagerRefused('PROTOCOL_UNSUPPORTED')
            stream_target=canonical_json({'endpointRef':process_ref.projection(),'protocolId':descriptor.protocol_id})
            stream=manager.records.enter_protocol_session(canonical_digest({'protocolSession':stream_target}),principal=scope,target=stream_target,turn=row)
            deadline=asyncio.get_running_loop().time()+request.limits.get('timeoutSeconds',30)
            if descriptor.protocol_id=='acp':
                bootstrap=_Bootstrap(manager,row,request,plan,prepared,process,invocation,deadline)
                supplied=provider.open_session(_ProcessView(bootstrap.open),context)
                session=await supplied if inspect.isawaitable(supplied) else supplied
                if session is None or session is not bootstrap.session:raise ManagerRefused('ORIGINAL_SESSION_REQUIRED')
            else:
                # A non-ACP protocol is supported only when the provider exports
                # its own native bootstrap; otherwise this stays an explicit
                # refusal instead of an ACP translation.
                open_native=getattr(provider,'open_native_session',None)
                if not callable(open_native):raise ManagerRefused('PROTOCOL_UNSUPPORTED')
                native=_NativeBootstrap(manager,row,request,plan,prepared,process,invocation,deadline)
                supplied=open_native(_ProcessView(None,native.channel()),context,plan)
                session=await supplied if inspect.isawaitable(supplied) else supplied
                native_session_id=getattr(session,'session_id',None)
                native_protocol=getattr(session,'protocol_id',None)
                if (type(native_session_id) is not str or not native_session_id
                        or len(native_session_id)>512
                        or native_protocol!=descriptor.protocol_id):
                    raise ManagerRefused('ORIGINAL_SESSION_REQUIRED')
                bootstrap=session
        elif request.session_mode!='none':raise ManagerRefused('SESSION_MODE_UNSUPPORTED')
        from .contracts import InstanceBindingMaterial
        material=InstanceBindingMaterial(revision.ref,descriptor,process_ref,plan.plan_digest,
            prepared.directory_binding_digest,descriptor.protocol_id,None if session is None else session.session_id,
            prepared.source_revision,plan.prepared_configuration_refs,plan.material_refs)
        fixed=material.digest
        instance=AgentInstanceRef(revision.ref.environment_namespace,initial.instance_id,fixed)
        facts={'schemaVersion':'agent-binding-provenance/1','instanceRef':instance.projection(),'revision':1,
            'profileRef':encode_revision_ref(revision.ref),'preparedPlanDigest':plan.plan_digest,'endpointRef':process_ref.projection(),
            'directoryBindingDigest':prepared.directory_binding_digest,'sourceRevision':prepared.source_revision,
            'configurationRefs':[ref.projection() for ref in plan.prepared_configuration_refs],'capturedAt':prepared.captured_at}
        provenance=BindingProvenance.decode({**facts,'observationDigest':canonical_digest(facts)})
        receipt=AgentStartReceipt(initial.instance_id,initial.operation_ref,'running',instance,process_ref,
            None if session is None else session.session_id)
        manager.records.publish_started_instance(row,provenance,receipt.session_id,descriptor.protocol_id,receipt,
            binding_material=material)
        resolved=True
        return _read(manager,manager.records.operation(key,'agent-start'),invocation)
    except BaseException as error:
        current=manager.records.operation(key,'agent-start')
        if current is not None and current.status=='reserved':
            state='unknown' if launch_attempted else 'failed'
            receipt=replace(initial,state=state,process_endpoint_ref=process_ref,
                error=EndpointError('START_UNRESOLVED' if launch_attempted else 'PREPARATION_REFUSED','Original Agent start did not complete'))
            manager.records.complete(key,'agent-start',status=state,operation_ref=initial.operation_ref,payload={'agentStartReceipt':receipt.projection()})
        if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        return _read(manager,manager.records.operation(key,'agent-start'),invocation)
    finally:
        if stream is not None:manager.records.leave_protocol_session(stream,resolved=resolved)
