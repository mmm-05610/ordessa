"""F1 projection over the original native InteractionService; no extra state.

Trusted composition supplies original invocation resolution and the physical
write guard. Published data never supplies either capability.
"""
from ordessa_agents.public import InteractionService,AgentInstanceRef
from ordessa_agents.sdk.native_contracts import FrozenNativeRequest,NativeOperationRef
from ordessa_agents.sdk.native_schemas import native_contract_schema
from ordessa_agents.sdk.interactions import InteractionsRefused
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_interfaces_contracts import (Capability,CapabilityDescriptor,OperationDescriptor,
    OperationResult,CapabilityError,compute_descriptor_digest,validate_capability)


def _closed(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def _schemas():
    obj={'type':'object'}
    text={'type':'string','minLength':1,'maxLength':512}
    return {
        'agents.native.freeze':_closed({'instanceRef':obj,'purpose':{'enum':['apply','query']},'method':text,'params':obj}),
        'agents.native.recorded':_closed({'request':native_contract_schema('FrozenNativeRequest')}),
        'agents.native.query':_closed({'operationRef':native_contract_schema('NativeOperationRef'),'expectedInputDigest':{'type':'string','pattern':'^sha256:[0-9a-f]{64}$'}})}


def descriptor():
    """Static native-operation surface; no owner or store is bound."""
    obj={'type':'object'}
    operations=tuple(OperationDescriptor(name,schema,obj) for name,schema in _schemas().items())
    base=CapabilityDescriptor('agents','agent-native-operations/1',operations,'')
    return CapabilityDescriptor(base.id,base.version,base.operations,
        compute_descriptor_digest(base))


def build_native_capability(source,*,invocation_resolver,write_guard):
    if type(source) is not InteractionService or not callable(invocation_resolver):
        raise TypeError('original InteractionService and authenticated invocation resolver required')
    if not callable(getattr(write_guard,'guard_write',None)):
        raise TypeError('original physical write guard required')
    if any(not callable(getattr(source.authority,n,None)) for n in (
        'check_native_dispatch','check_read_native_operation','guard_native_dispatch')):
        raise TypeError('original native authority binding required')
    schemas=_schemas()
    handlers={}
    for operation in schemas:
        async def invoke(request,context,_operation=operation):
            try:
                invocation=invocation_resolver(context)
                if invocation is None:raise InteractionsRefused('ACCESS_DENIED')
                if _operation=='agents.native.freeze':
                    instance=AgentInstanceRef.decode(request['instanceRef'])
                    source.read_binding(instance,invocation=invocation)
                    value=source.freeze_native_request(instance,purpose=request['purpose'],method=request['method'],
                        params_bytes=canonical_bytes(request['params']))
                elif _operation=='agents.native.query':
                    value=source.native_query(NativeOperationRef.decode(request['operationRef']),
                        request['expectedInputDigest'],invocation=invocation)
                else:
                    if context.deadline is None:raise InteractionsRefused('DEADLINE_REQUIRED')
                    value=await source.native_recorded(FrozenNativeRequest.decode(request['request']),
                        request_id=context.request_id,invocation=invocation,write_guard=write_guard,deadline=context.deadline)
                state=getattr(value,'state',None)
                status='unknown' if state in ('unknown','possibly-written') else ('accepted' if state=='reserved' else 'completed')
                return OperationResult(status,data=value.projection())
            except InteractionsRefused as exc:
                code='AUTHORITY_UNAVAILABLE' if exc.code=='PRODUCT_ROOT_CHANGED' else 'CONFLICT' if exc.code=='REQUEST_CONFLICT' else ('PERMISSION_DENIED' if 'DENIED' in exc.code or 'AUTHORIZED' in exc.code else 'INVALID_INPUT')
                return OperationResult('refused',error=CapabilityError(code,'Original native invocation refused'))
            except (ValueError,TypeError,KeyError):
                return OperationResult('refused',error=CapabilityError('INVALID_INPUT','Invalid native operation input'))
        handlers[operation]=invoke
    result=Capability(descriptor(),handlers)
    validate_capability(result)
    return result
