"""Original Agent lifecycle data; none of these values grants resource access."""
from dataclasses import dataclass,field
from collections.abc import Mapping
from ..profiles import ProfileRevisionRef,encode_revision_ref
from ..sdk.instances import EndpointRef,AgentInstanceRef
from ..sdk.prepare import (PreparedConfigurationRef,MaterialRef,EndpointError,_text,_digest,
    _tuple_of,_sealed_map,_thaw,canonical_digest)
from ..sdk.harness import PrepareContext


def lifecycle_endpoint_request_id(operation,phase,endpoint,frame_digest):
    return canonical_digest({'schemaVersion':'agent-lifecycle-frame-request/1',
        'startOperationRef':operation,'phase':phase,'endpointRef':endpoint.projection(),
        'frameDigest':frame_digest,'frameOrdinal':{'initialize':0,'session/new':1}[phase]})


@dataclass(frozen=True)
class LifecycleWriteBinding:
    namespace:str
    instance_id:str
    start_operation_ref:str
    phase:str
    endpoint_ref:EndpointRef
    profile_ref:ProfileRevisionRef
    plan_digest:str
    directory_binding_digest:str
    frame_digest:str
    endpoint_request_id:str

    def __post_init__(self):
        for name in ('namespace','instance_id','start_operation_ref'):_text(getattr(self,name),name)
        if self.phase not in ('initialize','session/new'):raise ValueError('unsupported bootstrap phase')
        if type(self.endpoint_ref) is not EndpointRef or type(self.profile_ref) is not ProfileRevisionRef:raise ValueError('exact lifecycle references required')
        for name in ('plan_digest','directory_binding_digest','frame_digest'):_digest(getattr(self,name),name)
        if self.endpoint_request_id!=lifecycle_endpoint_request_id(self.start_operation_ref,self.phase,self.endpoint_ref,self.frame_digest):raise ValueError('lifecycle child request mismatch')

    def projection(self):
        return {'schemaVersion':'agent-lifecycle-write-binding/1','namespace':self.namespace,'instanceId':self.instance_id,
            'startOperationRef':self.start_operation_ref,'phase':self.phase,'endpointRef':self.endpoint_ref.projection(),
            'profileRef':encode_revision_ref(self.profile_ref),'planDigest':self.plan_digest,
            'directoryBindingDigest':self.directory_binding_digest,'frameDigest':self.frame_digest,
            'endpointRequestId':self.endpoint_request_id}


@dataclass(frozen=True)
class AgentStartRequest:
    request_id:str
    profile_revision_ref:ProfileRevisionRef
    endpoint_ref:EndpointRef
    session_mode:str='fresh'
    resume_ref:Mapping|None=None
    prepared_configuration_refs:tuple[PreparedConfigurationRef,...]=()
    material_refs:tuple[MaterialRef,...]=()
    limits:Mapping=field(default_factory=dict)

    def __post_init__(self):
        _text(self.request_id,'request id')
        if type(self.profile_revision_ref) is not ProfileRevisionRef or type(self.endpoint_ref) is not EndpointRef:raise ValueError('exact start references required')
        if self.session_mode not in ('fresh','resume','none'):raise ValueError('session mode invalid')
        if self.resume_ref is not None:object.__setattr__(self,'resume_ref',_sealed_map(self.resume_ref,'resume ref'))
        _tuple_of(self.prepared_configuration_refs,PreparedConfigurationRef,'prepared configurations')
        _tuple_of(self.material_refs,MaterialRef,'materials')
        limits=dict(self.limits)
        if set(limits)-{'timeoutSeconds'}:raise ValueError('unknown start limit')
        timeout=limits.get('timeoutSeconds',30)
        if type(timeout) not in (int,float) or not 0<timeout<=300:raise ValueError('bounded start deadline required')
        object.__setattr__(self,'limits',_sealed_map(limits,'limits'))

    def projection(self):
        return {'requestId':self.request_id,'profileRevisionRef':encode_revision_ref(self.profile_revision_ref),
            'endpointRef':self.endpoint_ref.projection(),'sessionMode':self.session_mode,
            'resumeRef':None if self.resume_ref is None else _thaw(self.resume_ref),
            'preparedConfigurationRefs':[v.projection() for v in self.prepared_configuration_refs],
            'materialRefs':[v.projection() for v in self.material_refs],'limits':_thaw(self.limits)}


@dataclass(frozen=True)
class PreparedAgentContext:
    context:PrepareContext
    source_revision:str
    directory_binding_digest:str
    captured_at:str
    native_working_directory:str

    def __post_init__(self):
        if type(self.context) is not PrepareContext:raise ValueError('exact prepared context required')
        _text(self.source_revision,'original source revision');_text(self.captured_at,'capture time')
        _digest(self.directory_binding_digest)
        _text(self.native_working_directory,'approved native working directory')
        from pathlib import PurePosixPath
        if not PurePosixPath(self.native_working_directory).is_absolute() or '..' in PurePosixPath(self.native_working_directory).parts:raise ValueError('approved absolute native directory required')


@dataclass(frozen=True)
class AgentStartReceipt:
    instance_id:str
    operation_ref:str
    state:str
    instance_ref:AgentInstanceRef|None=None
    process_endpoint_ref:EndpointRef|None=None
    session_id:str|None=None
    error:EndpointError|None=None

    def __post_init__(self):
        _text(self.instance_id,'instance id');_text(self.operation_ref,'operation ref')
        if self.state not in ('preparing','starting','running','failed','unknown'):raise ValueError('start state invalid')
        if self.instance_ref is not None and type(self.instance_ref) is not AgentInstanceRef:raise ValueError('instance reference invalid')
        if self.process_endpoint_ref is not None and type(self.process_endpoint_ref) is not EndpointRef:raise ValueError('process reference invalid')
        if self.session_id is not None:_text(self.session_id,'native session id')
        if self.error is not None and type(self.error) is not EndpointError:raise ValueError('exact error required')
        if self.state=='running' and (self.instance_ref is None or self.process_endpoint_ref is None):raise ValueError('running requires original binding')

    def projection(self):
        return {'schemaVersion':'agent-start-receipt/1','instanceId':self.instance_id,'operationRef':self.operation_ref,'state':self.state,
            'instanceRef':None if self.instance_ref is None else self.instance_ref.projection(),
            'processEndpointRef':None if self.process_endpoint_ref is None else self.process_endpoint_ref.projection(),
            'sessionId':self.session_id,'error':None if self.error is None else self.error.projection()}

    @classmethod
    def decode(cls,value):
        if type(value) is not dict or set(value)!={'schemaVersion','instanceId','operationRef','state','instanceRef','processEndpointRef','sessionId','error'} or value['schemaVersion']!='agent-start-receipt/1':raise ValueError('closed start receipt required')
        error=value['error']
        if error is not None:
            if type(error) is not dict or set(error)!={'code','diagnostic'}:raise ValueError('exact endpoint error required')
            error=EndpointError(error['code'],error['diagnostic'])
        return cls(value['instanceId'],value['operationRef'],value['state'],
            None if value['instanceRef'] is None else AgentInstanceRef.decode(value['instanceRef']),
            None if value['processEndpointRef'] is None else EndpointRef.decode(value['processEndpointRef']),value['sessionId'],error)


LIFECYCLE_ACTIONS = ('stop', 'detach')


def instance_control_key(instance_ref):
    """Original instance key; the frozen AgentInstanceRef JSON stays untouched."""
    from ..sdk.prepare import canonical_digest
    return canonical_digest({'namespace': instance_ref.namespace,
                             'instanceId': instance_ref.instance_id})


def instance_control_request_key(action):
    if action not in LIFECYCLE_ACTIONS:
        raise ValueError('unsupported lifecycle action')
    return 'instance-control/' + action


@dataclass(frozen=True)
class InstanceControl:
    """Durable Agent-owned writer fence and association state for one instance.

    Not a resource authority: the endpoint owner keeps process/Use state. This
    value only answers "which writer epoch is current and is a lifecycle
    operation pending", so a copied endpoint or a fresh manager cannot bypass
    lifecycle control.
    """

    namespace: str
    instance_id: str
    binding_digest: str
    principal_scope: str
    endpoint_ref: EndpointRef
    writer_epoch: int
    association: str
    active_operation_ref: str | None
    active_action: str | None

    def __post_init__(self):
        _text(self.namespace, 'namespace'); _text(self.instance_id, 'instance id')
        _digest(self.binding_digest, 'binding digest')
        _text(self.principal_scope, 'principal scope')
        if type(self.endpoint_ref) is not EndpointRef:
            raise ValueError('exact endpoint reference required')
        if type(self.writer_epoch) is not int or type(self.writer_epoch) is bool or self.writer_epoch < 0:
            raise ValueError('non-negative writer epoch required')
        if self.association not in ('running', 'stopped', 'detached'):
            raise ValueError('association state invalid')
        if self.active_operation_ref is not None:
            _text(self.active_operation_ref, 'active operation')
        if self.active_action is not None and self.active_action not in LIFECYCLE_ACTIONS:
            raise ValueError('active lifecycle action invalid')
        if (self.active_operation_ref is None) != (self.active_action is None):
            raise ValueError('incomplete active lifecycle operation')

    def projection(self):
        return {'schemaVersion': 'agent-instance-control/1', 'namespace': self.namespace,
                'instanceId': self.instance_id, 'bindingDigest': self.binding_digest,
                'principalScope': self.principal_scope,
                'endpointRef': self.endpoint_ref.projection(),
                'writerEpoch': self.writer_epoch, 'association': self.association,
                'activeOperationRef': self.active_operation_ref,
                'activeAction': self.active_action}

    @classmethod
    def decode(cls, value):
        if type(value) is not dict or set(value) != {
                'schemaVersion', 'namespace', 'instanceId', 'bindingDigest',
                'principalScope', 'endpointRef', 'writerEpoch', 'association',
                'activeOperationRef', 'activeAction'}:
            raise ValueError('closed instance control required')
        if value['schemaVersion'] != 'agent-instance-control/1':
            raise ValueError('instance control schema invalid')
        return cls(value['namespace'], value['instanceId'], value['bindingDigest'],
                   value['principalScope'], EndpointRef.decode(value['endpointRef']),
                   value['writerEpoch'], value['association'],
                   value['activeOperationRef'], value['activeAction'])

    def fenced(self, *, epoch: int):
        """A caller that captured an older epoch is stale; equality is current."""
        if type(epoch) is not int or type(epoch) is bool or epoch < 0:
            raise ValueError('invalid writer epoch')
        if epoch != self.writer_epoch:
            raise ValueError('stale writer epoch')
        return self


@dataclass(frozen=True)
class InstanceBindingMaterial:
    """The original immutable input to AgentInstanceRef.bindingDigest.

    No authority, current catalog lookup, process handle or writable state.
    Projection is the existing digest formula, not a new identity schema.
    """
    profile_ref:ProfileRevisionRef
    harness:object
    endpoint_ref:EndpointRef
    plan_digest:str
    directory_binding_digest:str
    protocol_id:str|None
    session_id:str|None
    source_revision:str
    configuration_refs:tuple[PreparedConfigurationRef,...]=()
    material_refs:tuple[MaterialRef,...]=()

    def __post_init__(self):
        from ..sdk.harness import HarnessDescriptor
        if (type(self.profile_ref) is not ProfileRevisionRef or type(self.harness) is not HarnessDescriptor
                or type(self.endpoint_ref) is not EndpointRef or self.protocol_id!=self.harness.protocol_id):
            raise ValueError('exact original binding values required')
        _digest(self.plan_digest);_digest(self.directory_binding_digest);_text(self.source_revision,'source revision')
        if self.protocol_id is None:
            if self.session_id is not None:raise ValueError('session without native protocol')
        else:_text(self.session_id,'original session id')
        _tuple_of(self.configuration_refs,PreparedConfigurationRef,'configuration refs')
        _tuple_of(self.material_refs,MaterialRef,'material refs')

    def projection(self):
        return {'profileRef':encode_revision_ref(self.profile_ref),'harness':self.harness.projection(),
            'endpointRef':self.endpoint_ref.projection(),'planDigest':self.plan_digest,
            'directoryBindingDigest':self.directory_binding_digest,'protocolId':self.protocol_id,
            'sessionId':self.session_id,'sourceRevision':self.source_revision,
            'configurationRefs':[ref.projection() for ref in self.configuration_refs],
            'materialRefs':[ref.projection() for ref in self.material_refs]}

    @property
    def digest(self):return canonical_digest(self.projection())

    @classmethod
    def decode(cls,value):
        from ..profiles import decode_revision_ref
        from ..sdk.harness import HarnessDescriptor
        from ..sdk.prepare import _prepared_from,_material_from
        expected={'profileRef','harness','endpointRef','planDigest','directoryBindingDigest',
                  'protocolId','sessionId','sourceRevision','configurationRefs','materialRefs'}
        if type(value) is not dict or set(value)!=expected:raise ValueError('closed binding material required')
        h=value['harness']
        harness=HarnessDescriptor(h['providerId'],h['definitionRef'],h['implementationDigest'],h['protocolId'],
            tuple(h['requiredRoots']),tuple(h['configurationKinds']))
        if harness.projection()!=h:raise ValueError('closed original harness descriptor required')
        result=cls(decode_revision_ref(value['profileRef']),harness,EndpointRef.decode(value['endpointRef']),
            value['planDigest'],value['directoryBindingDigest'],value['protocolId'],value['sessionId'],value['sourceRevision'],
            tuple(_prepared_from(ref) for ref in value['configurationRefs']),tuple(_material_from(ref) for ref in value['materialRefs']))
        if result.projection()!=value:raise ValueError('original binding material roundtrip differs')
        return result

def lifecycle_native_request_id(operation,phase,endpoint,frame_digest,ordinal):
    """Correlation id for one provider-neutral bootstrap exchange.

    The ordinal is assigned by the owner in exchange order (0,1,2,...): it never
    derives from a protocol dialect, so a non-ACP provider cannot smuggle ACP
    phase semantics through this value.
    """
    if type(ordinal) is not int or not 0 <= ordinal < 64: raise ValueError('bounded native frame ordinal required')
    return canonical_digest({'schemaVersion':'agent-lifecycle-native-frame-request/1',
        'startOperationRef':operation,'phase':phase,'endpointRef':endpoint.projection(),
        'frameDigest':frame_digest,'frameOrdinal':ordinal})


@dataclass(frozen=True)
class NativeFrameBinding:
    """Same guarded-write evidence as the ACP binding, protocol-neutral."""
    namespace:str
    instance_id:str
    start_operation_ref:str
    phase:str
    ordinal:int
    endpoint_ref:EndpointRef
    profile_ref:ProfileRevisionRef
    plan_digest:str
    directory_binding_digest:str
    frame_digest:str
    endpoint_request_id:str

    def __post_init__(self):
        for name in ('namespace','instance_id','start_operation_ref','phase'):_text(getattr(self,name),name)
        if type(self.ordinal) is not int or not 0 <= self.ordinal < 64:raise ValueError('bounded native frame ordinal required')
        if type(self.endpoint_ref) is not EndpointRef or type(self.profile_ref) is not ProfileRevisionRef:raise ValueError('exact lifecycle references required')
        for name in ('plan_digest','directory_binding_digest','frame_digest'):_digest(getattr(self,name),name)
        if self.endpoint_request_id!=lifecycle_native_request_id(self.start_operation_ref,self.phase,
                self.endpoint_ref,self.frame_digest,self.ordinal):raise ValueError('native child request mismatch')

    def projection(self):
        return {'schemaVersion':'agent-lifecycle-native-write-binding/1','namespace':self.namespace,
            'instanceId':self.instance_id,'startOperationRef':self.start_operation_ref,'phase':self.phase,
            'frameOrdinal':self.ordinal,'endpointRef':self.endpoint_ref.projection(),
            'profileRef':encode_revision_ref(self.profile_ref),'planDigest':self.plan_digest,
            'directoryBindingDigest':self.directory_binding_digest,'frameDigest':self.frame_digest,
            'endpointRequestId':self.endpoint_request_id}
