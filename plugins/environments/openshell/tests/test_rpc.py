"""Real official gRPC/SDK transport against a controlled peer, not OpenShell runtime."""
from concurrent.futures import ThreadPoolExecutor
import json
import asyncio
import functools
import queue
import re
import threading
import uuid
from types import SimpleNamespace

import grpc
import pytest
from openshell._proto import datamodel_pb2 as dm, openshell_pb2 as pb, openshell_pb2_grpc as services
from openshell.sandbox import SandboxClient
from ordessa_environments import (
    EnvironmentManager, SQLiteEnvironmentStore, EnvironmentRefused,
    EnvironmentOperationUnknown, ProcessRequest, BackendNotFound, FILE_AREA_CAPABILITY,
    PROCESS_CAPABILITY, TERMINAL_CAPABILITY, CapabilityReport, CapabilityStatus,
    OwnerScope,
)
from ordessa_environments.capability import (
    EnvironmentCapabilityService, InvalidEnvironmentInput, factory,
    descriptor as environment_descriptor,
)
from ordessa_environments_openshell import OpenShellConfiguration, OpenShellEnvironmentProvider
from ordessa_environments_openshell.configuration import create_spec
from ordessa_environments_openshell.execution import OpenShellProcess


def run_async(function):
    @functools.wraps(function)
    def run(*args,**kwargs):return asyncio.run(function(*args,**kwargs))
    return run


class Peer(services.OpenShellServicer):
    def __init__(self):
        self.sandboxes={}
        self.starts=[]
        self.deleted=[]
        self.files={}
        self.file_modes={}
        self.helper_calls=[]
        self.main_commands=[]
        self.request_ids=set()
        self.list_fail=False
        self.list_deadline=False
        self.version='0.1.3'
        self.create_lose_receipt=False
        self.helper_lose_receipt=False
        self.create_requests=[]

    def Health(self, request, context):
        return pb.HealthResponse(status=pb.SERVICE_STATUS_HEALTHY,version=self.version)

    def CreateSandbox(self, request, context):
        assert request.workspace_scope.workspace == 'workspace-test'
        assert request.request_id
        assert len(request.request_id)==36 and str(uuid.UUID(request.request_id))==request.request_id
        assert uuid.UUID(request.request_id).int != 0
        assert len(request.name) <= 19 and re.fullmatch('[a-z0-9]([-a-z0-9]*[a-z0-9])?',request.name)
        self.create_requests.append(request)
        if any(value.metadata.name == request.name for value in self.sandboxes.values()):
            context.abort(grpc.StatusCode.ALREADY_EXISTS,'sandbox name occupied')
        self.main_commands.append(tuple(request.spec.command))
        sandbox=pb.Sandbox(metadata=dm.ObjectMeta(id='backend-'+request.name,name=request.name,workspace='workspace-test',labels=request.labels),
            spec=request.spec, status=pb.SandboxStatus(phase=pb.SANDBOX_PHASE_READY,restart_count=0))
        sandbox.status.main_process_started_time.FromMilliseconds(1000)
        self.sandboxes[sandbox.metadata.id]=sandbox
        if self.create_lose_receipt:context.abort(grpc.StatusCode.UNAVAILABLE,'created without receipt')
        return pb.SandboxResponse(sandbox=sandbox)

    def ListSandboxes(self, request, context):
        if self.list_deadline:context.abort(grpc.StatusCode.DEADLINE_EXCEEDED,'controlled deadline')
        if self.list_fail:context.abort(grpc.StatusCode.UNAVAILABLE,'controlled list failure')
        return pb.ListSandboxesResponse(sandboxes=list(self.sandboxes.values()))

    def _named(self, name):
        return next(value for value in self.sandboxes.values() if value.metadata.name == name)

    def StopSandbox(self, request, context):
        value=self._named(request.name);value.status.phase=pb.SANDBOX_PHASE_STOPPED
        return pb.SandboxResponse(sandbox=value)

    def StartSandbox(self, request, context):
        value=self._named(request.name);value.status.phase=pb.SANDBOX_PHASE_READY
        value.status.restart_count+=1;value.status.main_process_started_time.FromMilliseconds(2000)
        return pb.SandboxResponse(sandbox=value)

    def DeleteSandbox(self, request, context):
        value=self._named(request.name);identity=value.metadata.id
        self.deleted.append(identity);del self.sandboxes[identity]
        return pb.DeleteSandboxResponse(sandbox_id=identity)

    def ExecSandbox(self, request, context):
        # Controlled helper implementation: verifies actual protobuf mapping,
        # not a claim that Python/helper/policy is available in a real image.
        args=json.loads(request.command[-1]);op=args['op']
        if self.helper_lose_receipt:context.abort(grpc.StatusCode.UNAVAILABLE,'helper outcome unknown')
        self.request_ids.add(request.request_id)
        self.helper_calls.append((op,args))
        if op == 'probe':result=True
        elif op == 'write':self.files[args['relative']]=args['content'];result=None
        elif op == 'write_atomic':
            self.files[args['relative']]=args['content']
            self.file_modes[args['relative']]=args.get('mode')
            result=None
        elif op == 'read':result=self.files[args['relative']]
        elif op == 'exists':result=args['relative'] in self.files
        elif op == 'list':result=sorted(self.files)
        elif op == 'ensure':result=args['root']+'/'+args['relative']
        yield pb.ExecSandboxEvent(stdout=pb.ExecSandboxStdout(data=json.dumps(result).encode()))
        yield pb.ExecSandboxEvent(exit=pb.ExecSandboxExit(exit_code=0))

    def ExecSandboxInteractive(self, requests, context):
        start=next(requests)
        assert start.WhichOneof('payload') == 'start'
        assert start.start.tty is False and start.start.no_login_shell is True
        assert start.start.request_id and start.start.request_id not in self.request_ids
        self.request_ids.add(start.start.request_id);self.starts.append(start.start)
        yield pb.ExecSandboxEvent(stderr=pb.ExecSandboxStderr(data=b'separate-stderr'))
        for item in requests:
            assert item.WhichOneof('payload') == 'stdin'
            if item.stdin == b'exit':
                yield pb.ExecSandboxEvent(exit=pb.ExecSandboxExit(exit_code=0))
                return
            yield pb.ExecSandboxEvent(stdout=pb.ExecSandboxStdout(data=item.stdin))
        # Closed stdin confirms this controlled peer exits. Abrupt cancellation
        # has no exit receipt and therefore cannot confirm remote termination.
        yield pb.ExecSandboxEvent(exit=pb.ExecSandboxExit(exit_code=0))


@pytest.fixture
def backend(tmp_path):
    peer=Peer();server=grpc.server(ThreadPoolExecutor(max_workers=12))
    services.add_OpenShellServicer_to_server(peer,server)
    port=server.add_insecure_port('127.0.0.1:0')
    assert port>0
    server.start()
    client=SandboxClient('127.0.0.1:'+str(port),timeout=2)
    channel=grpc.insecure_channel('127.0.0.1:'+str(port))
    rpc=services.OpenShellStub(channel)
    configuration=OpenShellConfiguration('workspace-test','/workspace','controlled-gateway',file_helper='python3',timeout_seconds=2)
    provider=OpenShellEnvironmentProvider(configuration,client=client,rpc=rpc)
    manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'environments.db'),providers={'openshell':provider})
    try:yield peer,provider,manager
    finally:
        client.close();channel.close();server.stop(0).wait(3)


REFERENCE={'image':'controlled-image@sha256:explicit','policy':{'version':1},'main_command':['sleep','infinity']}


def request():
    return ProcessRequest(('controlled-echo',),'/workspace',{'TEST':'value'})


@run_async
async def test_two_uses_two_nonpty_channels_release_a_preserves_b_and_resource(backend):
    peer,provider,manager=backend
    instance=manager.create('openshell',REFERENCE)
    assert peer.main_commands == [('sleep','infinity')]
    a=instance.acquire('unit-a',sharing=True);b=instance.acquire('unit-b',sharing=True)
    assert isinstance(a.capabilities, CapabilityReport)
    assert a.capabilities.values[FILE_AREA_CAPABILITY] is CapabilityStatus.SUPPORTED
    assert a.capabilities.values[PROCESS_CAPABILITY] is CapabilityStatus.SUPPORTED
    assert a.capabilities.values[TERMINAL_CAPABILITY] is CapabilityStatus.UNSUPPORTED
    pa=a.execution.start(request());pb_=b.execution.start(request())
    from contextlib import contextmanager
    cuts=[]
    @contextmanager
    def guard():
        cuts.append(1);yield
    assert pa.guarded_write_supported is True
    await pa.write_stdin_guarded(b'a-one',write_guard=guard);await pb_.write_stdin(b'b-one')
    assert len(cuts)==1
    assert await pa.read_stdout(100,timeout=2)==b'a-one'
    assert await pb_.read_stdout(100,timeout=2)==b'b-one'
    assert await pa.read_stderr(100,timeout=2)==b'separate-stderr'
    assert await pb_.read_stderr(100,timeout=2)==b'separate-stderr'
    assert len(peer.starts)==2 and peer.starts[0].request_id != peer.starts[1].request_id
    with pytest.raises(EnvironmentRefused):a.release()
    a.files.write_text('config','materialized');assert b.files.read_text('config')=='materialized'
    a.files.write_text_atomic('atomic-config','materialized-atomically');assert b.files.read_text('atomic-config')=='materialized-atomically'
    await pa.write_stdin(b'exit');assert (await pa.wait_exit(timeout=2)).exit_code==0;pa.release()
    cached=a.files;a.release()
    with pytest.raises(EnvironmentRefused):cached.read_text('config')
    with pytest.raises(EnvironmentRefused):a.execution.start(request())
    await pb_.write_stdin(b'b-two');assert await pb_.read_stdout(100,timeout=2)==b'b-two'
    assert instance.snapshot.active_uses==1 and not peer.deleted
    await pb_.close_stdin();assert (await pb_.wait_exit(timeout=2)).exit_code==0;pb_.release();b.release()
    assert instance.delete().confirmed
    assert not peer.sandboxes and peer.deleted


@run_async
async def test_cancel_is_unknown_and_never_stops_whole_shared_sandbox(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    a=instance.acquire('unit-a',sharing=True);b=instance.acquire('unit-b',sharing=True)
    pa=a.execution.start(request());pb_=b.execution.start(request())
    await pa.write_stdin(b'connected');assert await pa.read_stdout(100,timeout=2)==b'connected'
    # Termination is a sandbox-local kill plus a stdin half-close so the
    # supervisor finalizes the exec session; the controlled peer then confirms
    # the exit receipt, while the whole shared sandbox is never stopped.
    cancellation=await pa.cancel(force=True)
    assert cancellation.outcome=='requested' and cancellation.observation.state=='exited'
    assert (await pa.wait_exit(timeout=2)).state=='exited'
    facts=pa.release();assert facts['processState']=='exited' and facts['exitCode']=='0'
    assert pa.release()==facts
    # A confirmed exit lets the Use be released; the shared sandbox and the
    # sibling Use remain intact because cancellation never stops the sandbox.
    a.release()
    with pytest.raises(EnvironmentRefused):instance.delete()
    await pb_.write_stdin(b'survives');assert await pb_.read_stdout(100,timeout=2)==b'survives'
    assert instance.inspect().observation.state=='running' and not peer.deleted
    # Explicit administrative stop affects all; not invoked by Use cancellation.
    await pb_.close_stdin();(await pb_.wait_exit(timeout=2)).exit_code;pb_.release();b.release()
    assert instance.stop(allow_in_use=True).confirmed


def test_stop_start_stales_old_use_and_observed_external_restart(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    use=instance.acquire('unit',sharing=True);cached=use.files
    instance.stop(allow_in_use=True)
    instance.start()
    with pytest.raises(EnvironmentRefused):cached.exists('config')
    fresh=instance.acquire('new-unit',sharing=True)
    peer.sandboxes[instance.snapshot.backend_id].status.restart_count+=1
    assert instance.inspect().generation==3
    with pytest.raises(EnvironmentRefused):fresh.files.exists('config')


def test_full_census_failure_is_not_deletion_confirmation(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    old_delete=provider._client.delete
    def delete(*args,**kwargs):
        result=old_delete(*args,**kwargs);peer.list_fail=True;return result
    provider._client.delete=delete
    with pytest.raises(EnvironmentOperationUnknown):instance.delete()
    assert instance.snapshot.phase=='unknown'
    peer.list_fail=False
    assert instance.inspect().phase=='deleted'


def test_name_reuse_cannot_rebind_registered_immutable_id(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    identity=instance.snapshot.backend_id;value=peer.sandboxes.pop(identity)
    value.metadata.id='replacement';peer.sandboxes['replacement']=value
    with pytest.raises(BackendNotFound):instance.acquire('unit',sharing=True)
    assert instance.snapshot.backend_id==identity and not peer.deleted


def test_missing_file_helper_is_explicit_no_files_capability(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    provider.configuration=OpenShellConfiguration('workspace-test','/workspace','controlled-gateway',timeout_seconds=2)
    use=instance.acquire('unit',sharing=False)
    assert use.capabilities.values[FILE_AREA_CAPABILITY] is CapabilityStatus.CONDITIONAL
    assert FILE_AREA_CAPABILITY not in use.capabilities.provides
    with pytest.raises(EnvironmentRefused):use.files.exists('config')
    use.release()


@pytest.mark.parametrize('reference',[
    {}, {**REFERENCE,'sharing':True}, {**REFERENCE,'image':''},
    {**REFERENCE,'main_command':[]}, {**REFERENCE,'policy':{'inventedPolicyKey':True}},
])
def test_explicit_configuration_rejects_unknown_or_missing_settings(reference):
    with pytest.raises(EnvironmentRefused):create_spec(reference)


@run_async
async def test_unsupported_process_signal_is_not_sandbox_lifecycle(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    use=instance.acquire('unit',sharing=False);process=use.execution.start(request())
    assert not hasattr(process,'terminate') and not hasattr(process,'send_signal')
    cancellation=await process.cancel(force=True)
    assert cancellation.outcome=='requested' and cancellation.observation.state=='exited'
    process.release()
    assert not peer.deleted


def test_gateway_version_mismatch_refuses_before_create(backend):
    peer,provider,manager=backend;peer.version='0.1.2'
    with pytest.raises(EnvironmentRefused):manager.create('openshell',REFERENCE)
    assert not peer.sandboxes and not peer.main_commands
    assert manager.list()[0].phase=='refused'


def test_replaced_name_rejects_existing_use_before_new_exec(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    use=instance.acquire('unit',sharing=True)
    identity=instance.snapshot.backend_id;value=peer.sandboxes.pop(identity)
    value.metadata.id='replacement';peer.sandboxes['replacement']=value
    with pytest.raises(BackendNotFound):use.execution.start(request())
    assert not peer.starts


def test_create_lost_receipt_reconciles_by_persisted_operation_without_replay(backend):
    peer,provider,manager=backend;peer.create_lose_receipt=True
    with pytest.raises(EnvironmentOperationUnknown) as caught:manager.create('openshell',REFERENCE)
    assert caught.value.backend_id is None
    instance=manager.reconcile_creation(caught.value.identity)
    assert len(peer.main_commands)==1 and instance.snapshot.backend_id in peer.sandboxes
    assert instance.delete().confirmed


def _capability_services(manager,tmp_path):
    """The public capability over the same controlled manager and store."""
    scope=OwnerScope('principal','controlled-reconcile')
    invocation=SimpleNamespace(owner_scope=scope)
    services=EnvironmentCapabilityService(manager,
        authorize=lambda scope,action,target,invocation: True,
        provider_catalog=[{'id':'openshell','available':True},
                          {'id':'local','available':False,'status':'UNAVAILABLE',
                           'reason':'not configured in this state directory'}],
        aliases_path=tmp_path/'aliases.json')
    return services,invocation


def test_public_reconcile_binds_the_same_sandbox_without_a_second_create(backend,tmp_path):
    peer,provider,manager=backend;peer.create_lose_receipt=True
    services,invocation=_capability_services(manager,tmp_path)
    assert 'environments.reconcile' in {operation.id for operation in environment_descriptor().operations}
    created=asyncio.run(services.invoke('create',
        {'provider':'openshell','reference':REFERENCE},invocation,'controlled-create'))
    assert created.status=='unknown', created
    identity=created.data['identity']
    assert len(peer.create_requests)==1 and len(peer.main_commands)==1
    reconciled=asyncio.run(services.invoke('reconcile',
        {'reference':identity},invocation,'controlled-reconcile'))
    assert reconciled.status=='completed', reconciled
    # The reconciled resource is the sandbox the lost receipt created: no
    # second create was dispatched and no other sandbox appeared.
    assert len(peer.create_requests)==1 and len(peer.main_commands)==1
    assert list(peer.sandboxes)==[reconciled.data['backendId']]
    assert reconciled.data['phase']=='ready'
    assert reconciled.data['backendId'] not in (None,'')


def test_public_reconcile_refuses_a_resource_without_an_uncertain_creation(backend,tmp_path):
    peer,provider,manager=backend
    services,invocation=_capability_services(manager,tmp_path)
    instance=manager.create('openshell',REFERENCE)
    refused=asyncio.run(services.invoke('reconcile',
        {'reference':instance.identity},invocation,'controlled-no-uncertainty'))
    assert refused.status=='refused', refused
    assert refused.error.code=='INVALID_INPUT'
    assert len(peer.create_requests)==1


def test_atomic_configuration_write_forwards_the_requested_mode(backend):
    peer,provider,manager=backend
    instance=manager.create('openshell',REFERENCE)
    use=instance.acquire('unit',sharing=False)
    use.files.write_text_atomic('config/credential.json','{}',mode=0o600)
    assert peer.file_modes['config/credential.json']==0o600
    use.files.write_text_atomic('config/public.json','{}',mode=0o644)
    assert peer.file_modes['config/public.json']==0o644
    # The default is the private mode a prepared credential needs.
    use.files.write_text_atomic('config/default.json','{}')
    assert peer.file_modes['config/default.json']==0o600
    assert peer.files['config/credential.json']=='{}'
    use.release()


@pytest.mark.parametrize('mode',[0o777,0o640,0o000,511,'384',None,True,384.0])
def test_invalid_atomic_mode_is_refused_before_any_helper_dispatch(backend,mode):
    peer,provider,manager=backend
    instance=manager.create('openshell',REFERENCE)
    use=instance.acquire('unit',sharing=False)
    with pytest.raises(EnvironmentRefused):use.files.write_text_atomic('config/credential.json','{}',mode=mode)
    assert not [call for call in peer.helper_calls if call[0]=='write_atomic']
    use.release()


def test_creation_name_is_bounded_deterministic_and_full_id_correlated(backend):
    peer,provider,manager=backend
    operation='0123456789abcdef0123456789abcdef'
    name=provider._creation_name(operation)
    assert len(name)==19 and re.fullmatch('oe-[a-z2-7]{16}',name)
    assert provider._creation_name(operation)==name
    other=OpenShellEnvironmentProvider(OpenShellConfiguration('other','/workspace','controlled-gateway'),client=provider._client,rpc=provider._rpc)
    assert other._creation_name(operation)!=name
    result=provider.create(REFERENCE,operation_id=operation)
    sent=peer.create_requests[0]
    assert sent.name==name and sent.request_id==str(uuid.UUID(hex=operation))
    assert sent.labels['ordessa.creation-operation']==operation
    assert provider.recover_creation(operation).backend_id==result.backend_id
    assert len(peer.create_requests)==1


@pytest.mark.parametrize('operation',['short','A'*32,'g'*32,'0'*32,None])
def test_invalid_operation_identity_refuses_before_dispatch(backend,operation):
    peer,provider,manager=backend
    with pytest.raises(EnvironmentRefused):provider.create(REFERENCE,operation_id=operation)
    assert not peer.create_requests


def test_creation_alias_collision_never_adopts_or_replays_existing(backend,monkeypatch):
    peer,provider,manager=backend
    first='1'*32;second='2'*32
    original=provider.create(REFERENCE,operation_id=first)
    name=provider._creation_name(first)
    monkeypatch.setattr(provider,'_creation_name',lambda _:name)
    for operation in [first,second]:
        with pytest.raises(EnvironmentRefused):provider.create(REFERENCE,operation_id=operation)
    with pytest.raises(EnvironmentRefused):provider.recover_creation(second)
    assert provider.recover_creation(first).backend_id==original.backend_id
    assert len(peer.create_requests)==1 and len(peer.sandboxes)==1


def test_creation_census_failure_refuses_without_remote_dispatch(backend):
    peer,provider,manager=backend;peer.list_fail=True
    with pytest.raises(EnvironmentRefused):manager.create('openshell',REFERENCE)
    assert not peer.create_requests and manager.list()[0].phase=='refused'


def test_name_occupied_after_census_never_overwrites_or_adopts(backend,monkeypatch):
    peer,provider,manager=backend
    operation='3'*32;name=provider._creation_name(operation)
    occupied=pb.Sandbox(metadata=dm.ObjectMeta(id='existing',name=name,workspace='workspace-test',labels={'ordessa.creation-operation':'4'*32}))
    real_create=provider._rpc.CreateSandbox
    def raced_create(*args,**kwargs):
        peer.sandboxes['existing']=occupied
        return real_create(*args,**kwargs)
    monkeypatch.setattr(provider._rpc,'CreateSandbox',raced_create)
    with pytest.raises(EnvironmentOperationUnknown,match='ALREADY_EXISTS') as caught:provider.create(REFERENCE,operation_id=operation)
    assert 'sandbox name occupied' not in str(caught.value)
    with pytest.raises(EnvironmentRefused):provider.recover_creation(operation)
    assert list(peer.sandboxes)==['existing'] and not peer.main_commands


def test_uncorrelated_create_receipt_is_not_saved_as_backend_mapping(backend,monkeypatch):
    peer,provider,manager=backend
    real_create=provider._rpc.CreateSandbox
    def changed_receipt(*args,**kwargs):
        response=real_create(*args,**kwargs)
        response.sandbox.metadata.labels['ordessa.creation-operation']='5'*32
        return response
    monkeypatch.setattr(provider._rpc,'CreateSandbox',changed_receipt)
    with pytest.raises(EnvironmentOperationUnknown) as caught:manager.create('openshell',REFERENCE)
    assert caught.value.backend_id is None and manager.list()[0].backend_id is None
    recovered=manager.reconcile_creation(caught.value.identity)
    assert recovered.snapshot.backend_id in peer.sandboxes and len(peer.create_requests)==1


def test_recovery_refuses_ambiguous_same_alias_even_with_one_matching_label(backend):
    peer,provider,manager=backend;operation='6'*32
    provider.create(REFERENCE,operation_id=operation);name=provider._creation_name(operation)
    peer.sandboxes['other']=pb.Sandbox(metadata=dm.ObjectMeta(id='other',name=name,workspace='workspace-test',labels={'ordessa.creation-operation':'7'*32}))
    with pytest.raises(EnvironmentRefused):provider.recover_creation(operation)


def test_unknown_use_acquisition_keeps_persistent_hold(backend):
    peer,provider,manager=backend;instance=manager.create('openshell',REFERENCE)
    peer.helper_lose_receipt=True
    with pytest.raises(EnvironmentOperationUnknown):instance.acquire('unit',sharing=True)
    assert instance.snapshot.active_uses==1
    with pytest.raises(EnvironmentRefused):instance.delete()
    assert not peer.deleted
    assert instance.stop(allow_in_use=True).confirmed
    assert instance.snapshot.active_uses==0


@run_async
async def test_async_cancelled_read_preserves_future_echo_and_releases_reader(backend):
    from ordessa_environments import ProcessWaitTimeout
    peer,provider,manager=backend
    instance=manager.create('openshell',REFERENCE);use=instance.acquire('unit',sharing=False)
    process=use.execution.start(request());raw=process._target
    pending=asyncio.create_task(process.read_stdout(100))
    await asyncio.sleep(0.01)
    with pytest.raises(EnvironmentRefused):await process.read_stdout(1,timeout=0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):await pending
    with pytest.raises(ProcessWaitTimeout):await process.read_stdout(1,timeout=0.01)
    assert process.observe().state=='running'
    assert await process.read_stderr(100,timeout=2)==b'separate-stderr'
    assert await process.write_stdin(b'future',timeout=0)==6
    assert await process.read_stdout(100,timeout=2)==b'future'
    await process.close_stdin();assert (await process.wait_exit(timeout=2)).exit_code==0
    assert await process.read_stdout(1,timeout=0)==b''
    facts=process.release();assert process.release()==facts and facts['transportReleased']
    assert not raw._reader.is_alive() and not raw._stdout.watchers and not raw._finish_watchers
    use.release();assert instance.delete().confirmed


@run_async
async def test_generation_fences_process_operations_after_stop_start(backend):
    peer,provider,manager=backend
    instance=manager.create('openshell',REFERENCE);use=instance.acquire('unit',sharing=True)
    process=use.execution.start(request())
    await process.write_stdin(b'exit');assert (await process.wait_exit(timeout=2)).state=='exited'
    instance.stop(allow_in_use=True);instance.start()
    with pytest.raises(EnvironmentRefused):await process.read_stdout(1)
    with pytest.raises(EnvironmentRefused):await process.cancel()
    with pytest.raises(EnvironmentRefused):process.observe()
    process._target.release()  # Test fixture disposal, no stale managed authority.


def test_stdin_admission_cancellation_has_no_future_dispatch():
    class Call:
        def __init__(self):self.done=threading.Event()
        def __iter__(self):self.done.wait(3);return iter(())
        def cancel(self):self.done.set()
    class RPC:
        def ExecSandboxInteractive(self,requests):
            self.requests=requests;self.call=Call();return self.call
    async def exercise():
        from ordessa_environments import ProcessWaitTimeout
        rpc=RPC();process=OpenShellProcess(rpc,workspace='w',sandbox_name='n',request=request())
        try:
            payload=b'x'*1048576
            for _ in range(4):assert await process.write_stdin(payload)==len(payload)
            with pytest.raises(ProcessWaitTimeout):await process.write_stdin(b'late',timeout=0)
            pending=asyncio.create_task(process.write_stdin(b'cancelled'))
            await asyncio.sleep(0)
            with pytest.raises(EnvironmentRefused):await process.write_stdin(b'other')
            with pytest.raises(EnvironmentRefused):await process.close_stdin()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):await pending
            # Native generator was deliberately withheld: start+4 accepted
            # frames only, no late/cancelled write dispatched after cancellation.
            assert process._input.qsize()==5 and process._queued_bytes==4*1048576
            frames=[next(rpc.requests) for _ in range(5)]
            assert frames[0].WhichOneof('payload')=='start'
            assert all(frame.stdin==payload for frame in frames[1:])
            assert process._input.empty() and process._queued_bytes==0
            assert process.observe().state=='running'
        finally:
            assert process.release()['transportReleased']
            assert not process._reader.is_alive()
    asyncio.run(exercise())


# -- the thin native management entry ----------------------------------------
#
# These cases run against the same controlled peer: no real gateway and no
# sandbox but the ones made here. The native entry is a bounded, read-only
# view over the provider's own control plane; it shares the manager, the store
# and the authority with the normal lifecycle.

NATIVE_IDS = frozenset({'environments.native.describe', 'environments.native.request',
                        'environments.native.query', 'environments.native.events'})


def _counted(provider):
    """Count the provider's native dispatches without changing its behaviour."""
    calls = []
    original = provider.native_request
    def counted(action, *, target=None, request_id=None):
        calls.append({'action': action, 'target': target, 'requestId': request_id})
        return original(action, target=target, request_id=request_id)
    provider.native_request = counted
    return calls


def _public_call(services, invocation, operation_id, request, request_id):
    """One call through the public capability, as a client sees it."""
    from ordessa_interfaces.system_access import CapabilityHost, RequestContext, build_registry
    capability = factory.build({'services': services,
                                'invocation_resolver': lambda context: invocation})
    host = CapabilityHost(build_registry([capability]), ('environments',))
    context = RequestContext({'id': 'controlled-reconcile'}, request_id)
    return asyncio.run(host.call(operation_id, request, context))


def test_the_native_operations_are_published_with_their_own_command_path():
    published = {operation.id: operation for operation in environment_descriptor().operations}
    assert NATIVE_IDS <= set(published)
    for identifier in NATIVE_IDS:
        assert published[identifier].cli['command'] == 'environments native'


def test_native_describe_reports_availability_and_binding_facts(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    described = asyncio.run(services.invoke('native.describe', {}, invocation, 'native-describe'))
    assert described.status == 'completed', described
    entries = {entry['id']: entry for entry in described.data['providers']}
    assert set(entries) == {'openshell', 'local'}
    management = entries['openshell']['management']
    assert management['available'] is True
    assert management['gateway'] == 'controlled-gateway'
    assert management['workspace'] == 'workspace-test'
    assert management['binding'] == provider.binding_id
    assert management['actions'] == ['health', 'inspect', 'list']
    # A provider this instance cannot use is named with its reason, not hidden.
    assert entries['local']['available'] is False
    assert entries['local']['management'] is None
    assert entries['local']['reason'] == 'not configured in this state directory'


def test_native_list_and_inspect_address_the_same_backend_identity(backend, tmp_path):
    peer, provider, manager = backend
    instance = manager.create('openshell', REFERENCE)
    services, invocation = _capability_services(manager, tmp_path)
    calls = _counted(provider)
    listed = asyncio.run(services.invoke('native.request',
        {'provider': 'openshell', 'action': 'list', 'requestId': 'native-list'},
        invocation, 'transport-list'))
    assert listed.status == 'completed', listed
    assert listed.data['state'] == 'completed'
    assert listed.data['correlationId'] == 'native-list'
    items = listed.data['result']['items']
    assert [item['backendId'] for item in items] == [instance.snapshot.backend_id]
    assert items[0]['state'] == 'running'
    inspected = asyncio.run(services.invoke('native.request',
        {'provider': 'openshell', 'action': 'inspect', 'reference': instance.identity,
         'requestId': 'native-inspect'}, invocation, 'transport-inspect'))
    assert inspected.status == 'completed', inspected
    assert inspected.data['result']['backendId'] == instance.snapshot.backend_id
    assert inspected.data['result']['present'] is True
    assert inspected.data['environmentIdentity'] == instance.identity
    # The inspected resource is the same registry row with the same immutable
    # backend id: the native entry adds no second resource and no mirror state.
    assert len(manager.list()) == 1
    assert manager.get(instance.identity).snapshot.backend_id == instance.snapshot.backend_id
    assert [call['action'] for call in calls] == ['list', 'inspect']
    assert calls[1]['target'] == instance.snapshot.backend_id


def test_native_health_reports_the_gateway_facts(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    healthy = asyncio.run(services.invoke('native.request',
        {'provider': 'openshell', 'action': 'health', 'requestId': 'native-health'},
        invocation, 'transport-health'))
    assert healthy.status == 'completed', healthy
    assert healthy.data['result'] == {'action': 'health', 'gatewayVersion': '0.1.3',
                                      'status': 'healthy'}


def test_native_request_is_idempotent_by_request_id_and_conflicts_on_a_different_input(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    calls = _counted(provider)
    request = {'provider': 'openshell', 'action': 'list', 'requestId': 'native-replay'}
    first = asyncio.run(services.invoke('native.request', request, invocation, 'transport-one'))
    replay = asyncio.run(services.invoke('native.request', request, invocation, 'transport-two'))
    assert first.status == 'completed', first
    assert replay.status == 'completed', replay
    assert replay.data == first.data
    assert replay.operation_ref == first.operation_ref
    # The second call replayed the stored fact; the provider was called once.
    assert len(calls) == 1
    # The same request id with a different canonical input conflicts. The
    # conflict is a refusal of the public capability, not an exception.
    conflict = _public_call(services, invocation, 'environments.native.request',
                            {'provider': 'openshell', 'action': 'health',
                             'requestId': 'native-replay'}, 'transport-three')
    assert conflict.status == 'refused', conflict
    assert conflict.error.code == 'CONFLICT'
    assert len(calls) == 1


def test_native_timeout_is_stored_as_unknown_and_never_dispatched_again(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    calls = _counted(provider)
    peer.list_deadline = True
    unknown = asyncio.run(services.invoke('native.request',
        {'provider': 'openshell', 'action': 'list', 'requestId': 'native-timeout'},
        invocation, 'transport-timeout'))
    assert unknown.status == 'unknown', unknown
    assert unknown.error.code == 'EFFECT_UNKNOWN'
    assert unknown.data['state'] == 'unknown'
    assert unknown.data['correlationId'] == 'native-timeout'
    # The uncertain outcome is stored once; a replay never dispatches again.
    peer.list_deadline = False
    replay = asyncio.run(services.invoke('native.request',
        {'provider': 'openshell', 'action': 'list', 'requestId': 'native-timeout'},
        invocation, 'transport-timeout-replay'))
    assert replay.status == 'unknown', replay
    assert replay.data['correlationId'] == 'native-timeout'
    assert len(calls) == 1
    # The stored fact is readable through the query entry.
    queried = asyncio.run(services.invoke('native.query', {'requestId': 'native-timeout'},
                                          invocation, 'transport-query'))
    assert queried.status == 'unknown', queried
    assert queried.data['observation']['state'] == 'unknown'
    assert queried.data['observation']['correlationId'] == 'native-timeout'


def test_native_events_page_states_its_completeness(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    empty = asyncio.run(services.invoke('native.events', {}, invocation, 'transport-events-empty'))
    assert empty.status == 'completed', empty
    assert empty.data['events'] == []
    assert empty.data['complete'] is True
    for index in range(2):
        asyncio.run(services.invoke('native.request',
            {'provider': 'openshell', 'action': 'list', 'requestId': 'native-event-%d' % index},
            invocation, 'transport-event-%d' % index))
    page = asyncio.run(services.invoke('native.events', {'limit': 1}, invocation, 'transport-events'))
    assert page.status == 'completed', page
    assert len(page.data['events']) == 1
    assert page.data['complete'] is False
    assert page.data['nextCursor'] is not None
    rest = asyncio.run(services.invoke('native.events', {'cursor': page.data['nextCursor']},
                                       invocation, 'transport-events-rest'))
    assert len(rest.data['events']) == 1
    assert rest.data['complete'] is True


def test_the_native_entry_never_creates_or_deletes_a_sandbox(backend, tmp_path):
    peer, provider, manager = backend
    instance = manager.create('openshell', REFERENCE)
    services, invocation = _capability_services(manager, tmp_path)
    for action, extra in (('list', {}), ('health', {}), ('inspect', {'reference': instance.identity})):
        request = {'provider': 'openshell', 'action': action,
                   'requestId': 'native-read-' + action, **extra}
        result = asyncio.run(services.invoke('native.request', request, invocation,
                                             'transport-' + action))
        assert result.status == 'completed', result
    described = asyncio.run(services.invoke('native.describe', {}, invocation, 'transport-describe'))
    assert described.status == 'completed', described
    # Exactly the one sandbox that existed before the native reads.
    assert len(peer.create_requests) == 1
    assert list(peer.sandboxes) == [instance.snapshot.backend_id]
    assert peer.deleted == []


def test_an_action_outside_the_closed_set_is_refused(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    with pytest.raises(EnvironmentRefused):
        provider.native_request('create', target=None, request_id='closed-set')
    with pytest.raises(EnvironmentRefused):
        provider.native_request('delete', target='backend-any', request_id='closed-set')
    with pytest.raises(InvalidEnvironmentInput):
        asyncio.run(services.invoke('native.request',
            {'provider': 'openshell', 'action': 'create', 'requestId': 'native-create'},
            invocation, 'transport-create'))
    assert not peer.create_requests and not peer.deleted


def test_an_unknown_provider_is_refused_without_a_dispatch(backend, tmp_path):
    peer, provider, manager = backend
    services, invocation = _capability_services(manager, tmp_path)
    refused = asyncio.run(services.invoke('native.request',
        {'provider': 'absent', 'action': 'list', 'requestId': 'native-absent'},
        invocation, 'transport-absent'))
    assert refused.status == 'refused', refused
    assert refused.error.code == 'CAPABILITY_UNSUPPORTED'
