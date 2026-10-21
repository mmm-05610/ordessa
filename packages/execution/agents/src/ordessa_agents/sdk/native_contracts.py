"""Closed native-operation/1 values; captured data never authenticates a caller."""
from dataclasses import dataclass
import hashlib,json,re
from .instances import AgentInstanceRef,EndpointRef
from .interactions import (_text,_digest,_digest_of,_canonical,_closed,_object_bytes,
    InteractionsRefused,STATES)

METHODS={'apply':'_ordessa/session/configuration/apply','query':'_ordessa/session/configuration/operation'}
MAX_PARAMS=65536
MAX_RECEIPT=524288
HEX=re.compile(r'[0-9a-f]{64}\Z')


def finite_native(value,depth=0):
    if depth>32:raise InteractionsRefused('NATIVE_VALUE_INVALID','depth')
    if value is None or type(value) is bool:return
    if type(value) is int:
        if abs(value)>(1<<53)-1:raise InteractionsRefused('NATIVE_VALUE_INVALID','safe integer')
        return
    if type(value) is str:
        try:value.encode('utf-8')
        except UnicodeError:raise InteractionsRefused('NATIVE_VALUE_INVALID','surrogate') from None
        return
    if type(value) is list:
        for item in value:finite_native(item,depth+1)
        return
    if type(value) is dict:
        for key,item in value.items():
            if type(key) is not str:raise InteractionsRefused('NATIVE_VALUE_INVALID','key')
            finite_native(key,depth+1);finite_native(item,depth+1)
        return
    raise InteractionsRefused('NATIVE_VALUE_INVALID','finite native JSON required')


def native_text(value,name,limit=4096):
    _text(value,name,limit)
    if value.strip()!=value:raise InteractionsRefused('NATIVE_VALUE_INVALID',name)
    return value


def _manifest(value,params):
    _closed(value,{'target','scope','actions'},'native manifest')
    if value['scope']!='session':raise InteractionsRefused('NATIVE_VALUE_INVALID','scope')
    target=_closed(value['target'],{'server_id','session_id','channel_id','runtime_generation'},'native target')
    for key in ('server_id','session_id','channel_id'):native_text(target[key],key)
    if type(target['runtime_generation']) is not int or target['runtime_generation']<0:
        raise InteractionsRefused('NATIVE_VALUE_INVALID','native generation')
    if type(value['actions']) is not list or len(value['actions'])!=1:
        raise InteractionsRefused('NATIVE_VALUE_INVALID','single native action')
    action=_closed(value['actions'][0],{'publicationOwner','publicationToken','source','actionId','schemaVersion','input','expectedObservation'},'native action')
    for key in ('publicationOwner','publicationToken','expectedObservation'):native_text(action[key],key)
    origin=_closed(action['source'],{'facet_id','item_id','contribution_version'},'native action source')
    for key,item in origin.items():native_text(item,key)
    expected=_closed(action['input'],{'configId','value'},'native action input')
    if (action['actionId']!='acp.session.set-config-option' or action['schemaVersion']!='1'
            or expected!={'configId':params['configId'],'value':params['value']}):
        raise InteractionsRefused('NATIVE_VALUE_INVALID','native manifest input')


def params_for(purpose,method,raw):
    if type(purpose) is not str or METHODS.get(purpose)!=method:
        raise InteractionsRefused('NATIVE_METHOD_UNSUPPORTED')
    if type(raw) is not bytes or not 0<len(raw)<=MAX_PARAMS:raise InteractionsRefused('NATIVE_VALUE_INVALID','params bytes')
    value=_object_bytes(raw);finite_native(value)
    keys={'sessionId','operationId'}
    if purpose=='apply':keys|={'expectedGeneration','expectedConfigDigest','configId','value'}
    if set(value)!=keys and not (purpose=='apply' and set(value)==keys|{'actionManifest'}):
        raise InteractionsRefused('NATIVE_VALUE_INVALID','closed params')
    native_text(value['sessionId'],'sessionId');native_text(value['operationId'],'operationId',128)
    if purpose=='apply':
        native_text(value['expectedGeneration'],'expectedGeneration')
        if type(value['expectedConfigDigest']) is not str or not HEX.fullmatch(value['expectedConfigDigest']):
            raise InteractionsRefused('NATIVE_VALUE_INVALID','expectedConfigDigest')
        if value['configId'] not in ('model','thinkingLevel'):raise InteractionsRefused('NATIVE_VALUE_INVALID','configId')
        native_text(value['value'],'value')
        if 'actionManifest' in value:_manifest(value['actionManifest'],value)
    return value


@dataclass(frozen=True)
class FrozenNativeRequest:
    instance_ref:AgentInstanceRef
    endpoint_ref:EndpointRef
    session_id:str
    source_revision:str
    purpose:str
    method:str
    params_bytes:bytes
    input_digest:str
    protocol_id:str='acp'

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef or type(self.endpoint_ref) is not EndpointRef:
            raise InteractionsRefused('NATIVE_VALUE_INVALID','original references')
        _text(self.session_id,'session');_text(self.source_revision,'source revision')
        if self.protocol_id!='acp':raise InteractionsRefused('NATIVE_PROTOCOL_UNSUPPORTED')
        params=params_for(self.purpose,self.method,self.params_bytes)
        if params['sessionId']!=self.session_id:raise InteractionsRefused('FIXED_SESSION_MISMATCH')
        if self.input_digest!=_digest_of(self.unsigned()):raise InteractionsRefused('NATIVE_DIGEST_MISMATCH')

    def unsigned(self):
        return {'schemaVersion':'agent-frozen-native-request/1','instanceRef':self.instance_ref.projection(),
            'endpointRef':self.endpoint_ref.projection(),'sessionId':self.session_id,'sourceRevision':self.source_revision,
            'protocolId':self.protocol_id,'purpose':self.purpose,'method':self.method,'paramsBytes':json.loads(self.params_bytes)}

    def projection(self):return {**self.unsigned(),'inputDigest':self.input_digest}

    @classmethod
    def decode(cls,v):
        _closed(v,{'schemaVersion','instanceRef','endpointRef','sessionId','sourceRevision','protocolId','purpose','method','paramsBytes','inputDigest'},'native request')
        if v['schemaVersion']!='agent-frozen-native-request/1':raise InteractionsRefused('DECODE_INVALID')
        return cls(AgentInstanceRef.decode(v['instanceRef']),EndpointRef.decode(v['endpointRef']),v['sessionId'],
            v['sourceRevision'],v['purpose'],v['method'],_canonical(v['paramsBytes']).encode(),v['inputDigest'],v['protocolId'])


@dataclass(frozen=True)
class NativeOperationRef:
    instance_ref:AgentInstanceRef
    request_key:str
    agent_operation_ref:str

    def __post_init__(self):
        if type(self.instance_ref) is not AgentInstanceRef:raise InteractionsRefused('NATIVE_VALUE_INVALID','instance')
        _digest(self.request_key);_text(self.agent_operation_ref,'operation')

    def projection(self):return {'schemaVersion':'agent-native-operation-ref/1','instanceRef':self.instance_ref.projection(),
        'requestKey':self.request_key,'agentOperationRef':self.agent_operation_ref}

    @classmethod
    def decode(cls,v):
        _closed(v,{'schemaVersion','instanceRef','requestKey','agentOperationRef'},'native ref')
        if v['schemaVersion']!='agent-native-operation-ref/1':raise InteractionsRefused('DECODE_INVALID')
        return cls(AgentInstanceRef.decode(v['instanceRef']),v['requestKey'],v['agentOperationRef'])


def native_request_key(instance,request_id,scope):
    _text(request_id,'requestId');_text(scope,'scope')
    return _digest_of({'schemaVersion':'agent-native-request-key/1','scope':scope,
        'namespace':instance.namespace,'instanceId':instance.instance_id,'requestId':request_id})


def native_frame(request,ref):
    return (_canonical({'jsonrpc':'2.0','id':ref.agent_operation_ref,'method':request.method,
        'params':json.loads(request.params_bytes)})+'\n').encode()


def native_endpoint_request_id(ref,endpoint,digest):
    return _digest_of({'schemaVersion':'agent-native-endpoint-request/1','operationRef':ref.projection(),
        'endpointRef':endpoint.projection(),'frameDigest':digest,'frameOrdinal':0})


@dataclass(frozen=True)
class NativeWriteBinding:
    operation_ref:NativeOperationRef
    request:FrozenNativeRequest
    frame_digest:str
    endpoint_request_id:str

    def __post_init__(self):
        if (type(self.operation_ref) is not NativeOperationRef or type(self.request) is not FrozenNativeRequest
                or self.operation_ref.instance_ref!=self.request.instance_ref):raise InteractionsRefused('NATIVE_BINDING_INVALID')
        _digest(self.frame_digest)
        if self.frame_digest!='sha256:'+hashlib.sha256(native_frame(self.request,self.operation_ref)).hexdigest():
            raise InteractionsRefused('NATIVE_BINDING_INVALID','frame')
        if self.endpoint_request_id!=native_endpoint_request_id(self.operation_ref,self.request.endpoint_ref,self.frame_digest):
            raise InteractionsRefused('NATIVE_BINDING_INVALID','endpoint request')

    def projection(self):return {'schemaVersion':'agent-native-write-binding/1','operationRef':self.operation_ref.projection(),
        'request':self.request.projection(),'frameDigest':self.frame_digest,'endpointRequestId':self.endpoint_request_id}

    @classmethod
    def decode(cls,v):
        _closed(v,{'schemaVersion','operationRef','request','frameDigest','endpointRequestId'},'native write')
        if v['schemaVersion']!='agent-native-write-binding/1':raise InteractionsRefused('DECODE_INVALID')
        return cls(NativeOperationRef.decode(v['operationRef']),FrozenNativeRequest.decode(v['request']),v['frameDigest'],v['endpointRequestId'])


@dataclass(frozen=True)
class NativeOperationReceipt:
    binding:NativeWriteBinding
    state:str
    revision:int
    endpoint_operation_ref:str|None
    observation_bytes:bytes
    observation_digest:str

    def __post_init__(self):
        if type(self.binding) is not NativeWriteBinding or type(self.state) is not str or self.state not in STATES:
            raise InteractionsRefused('NATIVE_RECEIPT_INVALID')
        if type(self.revision) is not int or self.revision<1:raise InteractionsRefused('NATIVE_RECEIPT_INVALID','revision')
        if self.endpoint_operation_ref is not None:_text(self.endpoint_operation_ref,'physical operation')
        if type(self.observation_bytes) is not bytes or len(self.observation_bytes)>262144:
            raise InteractionsRefused('NATIVE_RECEIPT_INVALID','observation')
        _object_bytes(self.observation_bytes)
        if self.observation_digest!='sha256:'+hashlib.sha256(self.observation_bytes).hexdigest():
            raise InteractionsRefused('NATIVE_RECEIPT_INVALID','digest')
        if len(_canonical(self.projection()).encode())>MAX_RECEIPT:raise InteractionsRefused('NATIVE_RECEIPT_INVALID','bound')

    def projection(self):return {'schemaVersion':'agent-native-operation-receipt/1','binding':self.binding.projection(),
        'state':self.state,'revision':self.revision,'endpointOperationRef':self.endpoint_operation_ref,
        'observationBytes':json.loads(self.observation_bytes),'observationDigest':self.observation_digest}

    @classmethod
    def decode(cls,v):
        _closed(v,{'schemaVersion','binding','state','revision','endpointOperationRef','observationBytes','observationDigest'},'native receipt')
        if v['schemaVersion']!='agent-native-operation-receipt/1':raise InteractionsRefused('DECODE_INVALID')
        return cls(NativeWriteBinding.decode(v['binding']),v['state'],v['revision'],v['endpointOperationRef'],
            _canonical(v['observationBytes']).encode(),v['observationDigest'])
