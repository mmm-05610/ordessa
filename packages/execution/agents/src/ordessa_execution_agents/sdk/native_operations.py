"""Native operations on the SAME interaction/records/session/physical claim owners."""
import asyncio,hashlib,json,math,threading
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4
from .endpoint import BoundEndpoint
from .interactions import _check,_canonical,_digest,_digest_of,InteractionsRefused,GuardedSendObservation,_writer_epoch
from .native_contracts import (FrozenNativeRequest,NativeOperationRef,NativeWriteBinding,NativeOperationReceipt,
    params_for,finite_native,native_request_key,native_frame,native_endpoint_request_id)


def freeze_native_request(source,instance_ref,*,purpose,method,params_bytes):
    params_for(purpose,method,params_bytes)
    provenance,session=source._instance(instance_ref)
    unsigned={'schemaVersion':'agent-frozen-native-request/1','instanceRef':instance_ref.projection(),
        'endpointRef':provenance.endpoint_ref.projection(),'sessionId':session,'sourceRevision':provenance.source_revision,
        'protocolId':'acp','purpose':purpose,'method':method,'paramsBytes':json.loads(params_bytes)}
    return FrozenNativeRequest.decode({**unsigned,'inputDigest':_digest_of(unsigned)})


def _target(request):return _canonical({'instanceRef':request.instance_ref.projection(),
    'endpointRef':request.endpoint_ref.projection(),'sessionId':request.session_id})


def _native_state(request,ref,observation):
    """Native evidence validation, not Engineering confirmation or permission."""
    try:
        frames=observation['protocol']['frames']
        matches=[f for f in frames if f.get('id')==ref.agent_operation_ref and 'result' in f]
        if len(matches)!=1:return 'unknown'
        value=matches[0]['result'];finite_native(value)
        params=json.loads(request.params_bytes)
        if (type(value) is not dict or value.get('operationId')!=params['operationId']
                or value.get('sessionId')!=request.session_id):return 'unknown'
        if value.get('state')!='observed':return 'unknown'
        before,after=value['before'],value['after']
        if (type(before) is not dict or type(after) is not dict or before['busy'] is not False
                or after['busy'] is not False or before['sessionId']!=request.session_id
                or after['sessionId']!=request.session_id or before['generation']!=value['generation']
                or after['generation']!=value['generation']
                or hashlib.sha256(_canonical(before['configOptions']).encode()).hexdigest()!=value['beforeConfigDigest']
                or hashlib.sha256(_canonical(after['configOptions']).encode()).hexdigest()!=value['afterConfigDigest']
                or type(value['evidenceRef']) is not str or not value['evidenceRef']):return 'unknown'
        selected=[x for x in after['configOptions'] if type(x) is dict and x.get('id')==value['configId']]
        if (len(selected)!=1 or selected[0].get('currentValue')!=value['requestedValue']
                or value['observedValue']!=value['requestedValue']):return 'unknown'
        if request.purpose=='apply':
            if (value['inputDigest']!=hashlib.sha256(request.params_bytes).hexdigest()
                    or value['generation']!=params['expectedGeneration']
                    or value['beforeConfigDigest']!=params['expectedConfigDigest']
                    or value['configId']!=params['configId'] or value['requestedValue']!=params['value']):return 'unknown'
            if 'actionManifest' in params and (value.get('actionManifest')!=params['actionManifest']
                    or value.get('target')!=params['actionManifest'].get('target')
                    or value.get('manifestDigest')!=hashlib.sha256(_canonical(params['actionManifest']).encode()).hexdigest()):return 'unknown'
        return 'completed'
    except (KeyError,TypeError,ValueError,InteractionsRefused):return 'unknown'


def _row(record):
    try:
        receipt=NativeOperationReceipt.decode(record.payload['nativeReceipt'])
        binding=receipt.binding;ref=binding.operation_ref
        if (record.operation!='native-operation' or record.request_id!=ref.request_key
                or record.operation_ref!=ref.agent_operation_ref or record.status!=receipt.state
                or record.request_digest!=binding.request.input_digest or record.target!=_target(binding.request)
                or native_request_key(ref.instance_ref,record.payload['requestId'],record.principal)!=ref.request_key):
            raise ValueError()
        if receipt.state=='completed' and _native_state(binding.request,ref,json.loads(receipt.observation_bytes))!='completed':
            raise ValueError()
        return receipt
    except Exception as exc:raise InteractionsRefused('NATIVE_RECORD_CORRUPT') from exc


def native_query(source,operation_ref,expected_input_digest,*,invocation):
    if type(operation_ref) is not NativeOperationRef:raise InteractionsRefused('NATIVE_REFERENCE_REQUIRED')
    NativeOperationRef.decode(operation_ref.projection())
    _digest(expected_input_digest)
    _check(source.authority,'check_read_native_operation',invocation,operation_ref,expected_input_digest)
    scope=source._scope(invocation)
    row=source.records.operation(operation_ref.request_key,'native-operation')
    if row is None or row.principal!=scope:raise InteractionsRefused('READ_NOT_AUTHORIZED')
    result=_row(row)
    if result.binding.operation_ref!=operation_ref or result.binding.request.input_digest!=expected_input_digest:
        raise InteractionsRefused('NATIVE_OBSERVATION_MISMATCH')
    # A process restart must not interpret an uncompleted reservation as fresh.
    return replace(result,state='unknown') if result.state in {'reserved','possibly-written'} else result


def _finish(source,row,state,observation,physical=None):
    current=_row(row);raw=_canonical(observation).encode()
    receipt=replace(current,state=state,revision=current.revision+1,
        observation_bytes=raw,observation_digest='sha256:'+hashlib.sha256(raw).hexdigest(),
        endpoint_operation_ref=physical if physical is not None else current.endpoint_operation_ref)
    source.records.advance_native(row,status=state,payload={**row.payload,'nativeReceipt':receipt.projection()})
    return receipt


async def native_recorded(source,request,*,request_id,invocation,write_guard,deadline):
    if type(request) is not FrozenNativeRequest:raise InteractionsRefused('NATIVE_REQUEST_REQUIRED')
    FrozenNativeRequest.decode(request.projection())
    scope=source._scope(invocation);key=native_request_key(request.instance_ref,request_id,scope)
    existing=source.records.operation(key,'native-operation')
    if existing is not None:
        receipt=_row(existing)
        found=native_query(source,receipt.binding.operation_ref,receipt.binding.request.input_digest,invocation=invocation)
        if receipt.binding.request!=request:raise InteractionsRefused('REQUEST_CONFLICT')
        return found
    if (not callable(getattr(write_guard,'guard_write',None)) or type(deadline) not in (int,float)
            or not math.isfinite(deadline) or deadline<=asyncio.get_running_loop().time()):
        raise InteractionsRefused('WRITER_GUARD_UNSUPPORTED')
    provenance,session=source._instance(request.instance_ref,scope)
    if (provenance.endpoint_ref!=request.endpoint_ref or session!=request.session_id
            or provenance.source_revision!=request.source_revision):raise InteractionsRefused('NATIVE_ORIGINAL_BINDING_MISMATCH')
    ref=NativeOperationRef(request.instance_ref,key,'native-operation/'+uuid4().hex)
    frame=native_frame(request,ref);digest='sha256:'+hashlib.sha256(frame).hexdigest()
    binding=NativeWriteBinding(ref,request,digest,native_endpoint_request_id(ref,request.endpoint_ref,digest))
    _check(source.authority,'check_native_dispatch',invocation,binding)
    if not callable(getattr(source.authority,'guard_native_dispatch',None)):
        raise InteractionsRefused('NATIVE_AUTHORITY_GUARD_UNAVAILABLE')
    # Capability failures are known before the original parent reservation.
    try:bound=await source.endpoint_resolver.resolve(request.endpoint_ref,invocation)
    except Exception:raise InteractionsRefused('NATIVE_ENDPOINT_UNAVAILABLE') from None
    if (type(bound) is not BoundEndpoint or bound.ref!=request.endpoint_ref
            or not callable(getattr(bound.communicate,'send_guarded',None))
            or not callable(getattr(bound.communicate,'receive',None))):raise InteractionsRefused('NATIVE_ENDPOINT_UNAVAILABLE')
    _check(source.authority,'check_native_dispatch',invocation,binding)
    if deadline<=asyncio.get_running_loop().time():raise InteractionsRefused('NATIVE_DEADLINE_ELAPSED')
    epoch=_writer_epoch(source.records,request.instance_ref,scope)
    empty=b'{}';receipt=NativeOperationReceipt(binding,'reserved',1,None,empty,'sha256:'+hashlib.sha256(empty).hexdigest())
    state,row=source.records.claim(key,'native-operation',principal=scope,target=_target(request),
        request_digest=request.input_digest,operation_ref=ref.agent_operation_ref,
        payload={'nativeReceipt':receipt.projection(),'requestId':request_id,'controlEpoch':epoch})
    if state!='created':
        stored=_row(row)
        return native_query(source,stored.binding.operation_ref,request.input_digest,invocation=invocation)
    task,thread=asyncio.current_task(),threading.get_ident()
    expected_binding=_canonical(binding.projection());session_record=None;entered=False
    class Guard:
        @contextmanager
        def guard_write(self,actual,caller):
            if (caller is not invocation or asyncio.current_task() is not task or threading.get_ident()!=thread
                    or type(actual) is not NativeWriteBinding or _canonical(actual.projection())!=expected_binding):
                raise InteractionsRefused('NATIVE_WRITE_BINDING_MISMATCH')
            NativeWriteBinding.decode(actual.projection())
            _check(source.authority,'check_native_dispatch',caller,actual)
            with source.authority.guard_native_dispatch(caller,actual):
                with write_guard.guard_write(actual,caller):
                    if deadline<=asyncio.get_running_loop().time():
                        raise InteractionsRefused('NATIVE_DEADLINE_ELAPSED')
                    with source.records.guard_writer_epoch(request.instance_ref,scope,row.payload.get('controlEpoch')):
                        _check(source.authority,'check_native_dispatch',caller,actual)
                        if _canonical(actual.projection())!=expected_binding:
                            raise InteractionsRefused('NATIVE_WRITE_BINDING_MISMATCH')
                        current=source.records.operation(key,'native-operation')
                        if current is None or current.status!='reserved' or current.operation_ref!=ref.agent_operation_ref:
                            raise InteractionsRefused('NATIVE_OPERATION_CHANGED')
                        previous=source.records._db.execute('PRAGMA busy_timeout').fetchone()[0]
                        source.records._db.execute('PRAGMA busy_timeout=0')
                        try:_finish(source,current,'possibly-written',{})
                        finally:source.records._db.execute('PRAGMA busy_timeout='+str(previous))
                        yield
    try:
        with source._fresh_lock:
            if request.instance_ref in source._receiving:raise InteractionsRefused('SESSION_BUSY')
            target=_canonical({'endpointRef':request.endpoint_ref.projection(),'protocolId':'acp'})
            session_record=source.records.enter_protocol_session(_digest_of({'protocolSession':target}),principal=scope,target=target,turn=row)
            source._receiving.add(request.instance_ref);entered=True
        try:
            sent=await bound.communicate.send_guarded(frame,binding.endpoint_request_id,deadline,invocation,
                binding=binding,write_guard=Guard())
            current=source.records.operation(key,'native-operation')
            if type(sent) is not GuardedSendObservation:raise InteractionsRefused('NATIVE_PHYSICAL_RECEIPT_INVALID')
            delivery={'delivery':sent.status,'bytesSent':sent.bytes_sent}
            if sent.status=='not_sent':
                result=_finish(source,current,'failed',delivery,sent.operation_ref)
            elif current.status!='possibly-written':
                result=_finish(source,current,'unknown',{'reason':'writer_not_guarded'},sent.operation_ref)
            else:
                from .acp import observe_native
                protocol_state,observation=await observe_native(bound.communicate.receive,operation_ref=ref.agent_operation_ref,
                    session_id=request.session_id,deadline=deadline,invocation=invocation,delivery=delivery)
                semantic=_native_state(request,ref,observation) if protocol_state=='completed' else protocol_state
                result=_finish(source,current,semantic,observation,sent.operation_ref)
        except BaseException as exc:
            current=source.records.operation(key,'native-operation')
            if current is not None and current.status in ('reserved','possibly-written'):
                result=_finish(source,current,'unknown',{'reason':'native_dispatch_interrupted'})
            if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        return native_query(source,ref,request.input_digest,invocation=invocation)
    except BaseException:
        current=source.records.operation(key,'native-operation')
        if current is not None and current.status=='reserved':_finish(source,current,'failed',{'reason':'session_not_admitted'})
        raise
    finally:
        if session_record is not None:
            current=source.records.operation(key,'native-operation')
            source.records.leave_protocol_session(session_record,resolved=current.status in ('completed','failed'))
        if entered:
            with source._fresh_lock:source._receiving.discard(request.instance_ref)
