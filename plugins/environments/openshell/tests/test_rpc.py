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
        self.main_commands=[]
        self.request_ids=set()
        self.list_fail=False
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
        if op == 'probe':result=True
        elif op == 'write':self.files[args['relative']]=args['content'];result=None
        elif op == 'write_atomic':self.files[args['relative']]=args['content'];result=None
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
