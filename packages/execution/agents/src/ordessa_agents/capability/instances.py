"""F1 projections of the sole original Agent manager/interaction owner.

No resource acquisition, session allocation, permission issuer, effect journal,
retry or alternate runtime. Trusted composition supplies original invocations
and the physical prompt guard; request JSON supplies values only.
"""
from ordessa_agents.public import (
    AgentManager,InteractionService,AgentInstanceRef,EndpointRef,AgentStartRequest,ManagerRefused,
)
from ordessa_agents.profiles import decode_revision_ref
from ordessa_agents.sdk import BoundPath,PreparedConfigurationRef,MaterialRef
from ordessa_agents.sdk.interactions import InteractionsRefused,TurnReadQuery
from ordessa_agents.sdk.prepare import canonical_json
from ordessa_interfaces_contracts import (
    Capability,CapabilityDescriptor,CapabilityError,OperationDescriptor,OperationResult,
    compute_descriptor_digest,validate_capability,
)


def _location(value):
    result=BoundPath(value['rootKey'],value['relativePath'])
    if result.projection()!=value:raise ValueError('closed path required')
    return result


def _reference(value,*,material=False):
    location=None if value['location'] is None else _location(value['location'])
    if material:
        result=MaterialRef(value['issuer'],value['materialId'],value['revision'],value['digest'],
                           value['mediaType'],value['byteLength'],location)
    else:
        result=PreparedConfigurationRef(value['issuer'],value['configurationId'],value['revision'],value['digest'],
                                        value['mediaType'],value['byteLength'],location)
    if result.projection()!=value:raise ValueError('closed resource evidence reference required')
    return result


def _start_input(value,request_id):
    return AgentStartRequest(request_id,decode_revision_ref(value['profileRevisionRef']),
        EndpointRef.decode(value['endpointRef']),value.get('sessionMode','fresh'),value.get('resumeRef'),
        tuple(_reference(ref) for ref in value.get('preparedConfigurationRefs',())),
        tuple(_reference(ref,material=True) for ref in value.get('materialRefs',())),value.get('limits',{}))


def _closed(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,
            'additionalProperties':False}


def _refused(code):
    if code in {'PRODUCT_ROOT_CHANGED','INVOCATION_PRINCIPAL_UNAVAILABLE','FORGED_INVOCATION'}:
        error='AUTHORITY_UNAVAILABLE'
    elif 'DEADLINE' in code:error='OBSERVATION_TIMEOUT'
    elif 'CONFLICT' in code or code=='LIFECYCLE_BUSY':error='CONFLICT'
    elif 'AUTHORIZED' in code or 'AUTHORITY_REFUSED' in code or 'DENIED' in code:error='PERMISSION_DENIED'
    elif 'UNSUPPORTED' in code or code=='GUARDED_LIFECYCLE_UNAVAILABLE':error='CAPABILITY_UNSUPPORTED'
    else:error='INVALID_INPUT'
    return OperationResult('refused',error=CapabilityError(error,'Original Agent invocation refused'))


_FLAGS={
    'profileRevisionRef':('--profile-ref','json-file'),'endpointRef':('--endpoint-ref','json-file'),
    'sessionMode':('--session-mode','string'),'resumeRef':('--resume-ref','json-file'),
    'preparedConfigurationRefs':('--prepared-configurations','json-file'),
    'materialRefs':('--materials','json-file'),'limits':('--limits','json-file'),
    'startRequestId':('--start-request-id','string'),'instanceRef':('--instance-ref','json-file'),
    'force':('--force','boolean'),'params':('--params','json-file'),
    'engineeringAttemptRef':('--engineering-attempt-ref','string'),'query':('--query','json-file')}


def _specs():
    obj={'type':'object'};text={'type':'string','minLength':1,'maxLength':512}
    return {
        'agents.start':_closed({'profileRevisionRef':obj,'endpointRef':obj,
            'sessionMode':{'enum':['fresh','resume','none']},'resumeRef':{'type':['object','null']},
            'preparedConfigurationRefs':{'type':'array','items':obj,'maxItems':128},
            'materialRefs':{'type':'array','items':obj,'maxItems':128},'limits':obj},
            ['profileRevisionRef','endpointRef']),
        'agents.get':_closed({'startRequestId':text}),
        'agents.stop':_closed({'instanceRef':obj,'force':{'type':'boolean'}},['instanceRef']),
        'agents.detach':_closed({'instanceRef':obj}),
        'agents.reconcile':_closed({'instanceRef':obj}),
        'agents.prompt':_closed({'instanceRef':obj,'params':obj,'engineeringAttemptRef':text},
            ['instanceRef','params']),
        'agents.query':_closed({'query':obj}),
    }


def descriptor(*, include_native=False, include_cancel=False):
    """Static operation/metadata surface; binding an owner opens no state."""
    obj={'type':'object'}
    specs=_specs()
    operations=tuple(OperationDescriptor(operation,schema,obj,cli={
        'command':'agents','operation':operation.split('.')[-1],
        'args':tuple({'name':name,'flags':(_FLAGS[name][0],),'type':_FLAGS[name][1]}
                     for name in schema['properties'])})
        for operation,schema in specs.items())
    if include_cancel:
        operations+=(OperationDescriptor('agents.cancel',
            _closed({'instanceRef':obj},['instanceRef']),obj,cli={
            'command':'agents','operation':'cancel',
            'args':({'name':'instanceRef','flags':('--instance-ref',),'type':'json-file'},)}),)
    if include_native:
        from .native import descriptor as native_descriptor
        operations+=native_descriptor().operations
    base=CapabilityDescriptor('agents','agent-instance-operations/1',operations,'')
    return CapabilityDescriptor(base.id,base.version,base.operations,
        compute_descriptor_digest(base))


def build_agent_capability(manager,source,*,invocation_resolver,write_guard,native_write_guard=None):
    """Bind only public original ports, optionally including existing native ops."""
    if (type(manager) is not AgentManager or type(source) is not InteractionService
            or manager.records is not source.records or manager.resolver is not source.endpoint_resolver
            or not callable(invocation_resolver) or not callable(getattr(write_guard,'guard_write',None))):
        raise TypeError('single original Agent owner, invocation resolver and physical guard required')
    obj={'type':'object'}
    specs=_specs()
    cancel_supported=(callable(getattr(source.authority,'check_cancel',None))
                      and source.endpoint_resolver is not None)
    if cancel_supported:
        specs['agents.cancel']=_closed({'instanceRef':obj},['instanceRef'])
    handlers={}
    for operation in specs:
        async def invoke(request,context,_operation=operation):
            invocation=invocation_resolver(context)
            if invocation is None:return _refused('FORGED_INVOCATION')
            # Decode every value before making any call that can claim/write.
            try:
                if _operation=='agents.start':value=_start_input(request,context.request_id)
                elif _operation in {'agents.stop','agents.detach','agents.prompt','agents.reconcile','agents.cancel'}:
                    value=AgentInstanceRef.decode(request['instanceRef'])
                elif _operation=='agents.query':value=TurnReadQuery.decode(request['query'])
                else:value=request['startRequestId']
            except (ValueError,TypeError,KeyError):return _refused('INVALID_INPUT')
            try:
                if _operation=='agents.start':
                    endpoint=await manager.resolver.resolve(value.endpoint_ref,invocation)
                    result=await manager.start(value,endpoint,invocation)
                elif _operation=='agents.get':result=manager.get(value,invocation)
                elif _operation=='agents.stop':
                    result=await manager.stop(context.request_id,value,invocation,force=request.get('force',False),deadline=context.deadline)
                elif _operation=='agents.detach':result=await manager.detach(context.request_id,value,invocation,deadline=context.deadline)
                elif _operation=='agents.query':result=source.query_turn(value,invocation=invocation)
                elif _operation=='agents.cancel':
                    if context.deadline is None:return _refused('DEADLINE_REQUIRED')
                    receipt=await source.cancel_session(value,request_id=context.request_id,
                        invocation=invocation,write_guard=write_guard,deadline=context.deadline)
                    status=receipt.state
                    error=(None if status=='accepted' else CapabilityError(
                        'EFFECT_UNKNOWN' if status=='unknown' else 'CAPABILITY_UNSUPPORTED',
                        'Original cancel outcome requires inspection' if status=='unknown'
                        else 'Original cancel notification was not sent'))
                    return OperationResult(status,data=receipt.projection(),error=error)
                elif _operation=='agents.reconcile':result=await manager.reconcile(value,invocation,deadline=context.deadline)
                else:
                    if context.deadline is None:return _refused('DEADLINE_REQUIRED')
                    source.read_binding(value,invocation=invocation)
                    prompt=source.freeze_prompt(value,canonical_json(request['params']).encode('utf-8'))
                    result=await manager.send_prompt(context.request_id,value,invocation,prompt=prompt,
                        interaction_service=source,engineering_attempt_ref=request.get('engineeringAttemptRef'),
                        write_guard=write_guard,deadline=context.deadline)
                projection=result.projection()
                if _operation in {'agents.stop','agents.detach'}:
                    status=result.status
                    error=(None if result.error is None else CapabilityError(
                        'EFFECT_UNKNOWN' if status=='unknown' else 'PERMISSION_DENIED',
                        'Original lifecycle outcome requires inspection' if status=='unknown' else 'Original lifecycle refused'))
                else:
                    state=result.state
                    status=('unknown' if state in {'unknown','possibly-written'} else
                            'accepted' if state in {'preparing','starting','reserved'} else 'completed')
                    error=None
                    if _operation=='agents.start' and state=='failed':
                        status='refused';error=CapabilityError('INVALID_INPUT','Original Agent start did not publish an instance')
                return OperationResult(status,data=projection,error=error)
            except (ManagerRefused,InteractionsRefused) as exc:
                if _operation not in {'agents.get','agents.query'} and exc.code in {
                        'OPERATION_UNCONFIRMED','OBSERVATION_INVALID','RECORD_CHANGED','RECORDS_UNAVAILABLE'}:
                    return OperationResult('unknown',error=CapabilityError('EFFECT_UNKNOWN','Original Agent outcome requires inspection'))
                return _refused(exc.code)
        handlers[operation]=invoke
    declared=descriptor(include_native=native_write_guard is not None,
                        include_cancel=cancel_supported)
    if native_write_guard is not None:
        from .native import build_native_capability
        native=build_native_capability(source,invocation_resolver=invocation_resolver,write_guard=native_write_guard)
        handlers.update(native.handlers)
    capability=Capability(declared,handlers)
    validate_capability(capability)
    return capability
