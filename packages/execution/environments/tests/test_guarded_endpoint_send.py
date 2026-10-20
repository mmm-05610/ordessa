"""Physical guarded child writes over real local pipes and original env ledger."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from ordessa_environments import (
    EnvironmentManager, EnvironmentUseOperations, EnvironmentEndpoints, OwnerScope,
    SQLiteEnvironmentStore, EnvironmentRefused, EnvironmentOperationUnknown, ProcessRequest,
)
from ordessa_environments_local import LocalEnvironmentResourceProvider


class LocalChild:
    def __init__(self, root, argv=None):
        self.root=root
        self.manager=EnvironmentManager(store=SQLiteEnvironmentStore(root/'env.sqlite'),
            providers={'local':LocalEnvironmentResourceProvider(default_root=str(root/'work'))})
        self.instance=self.manager.create('local',{'root':str(root/'work')})
        self.scope=OwnerScope('principal','subject')
        self.invocation=SimpleNamespace(owner_scope=self.scope)
        self.denied=set()
        self.authorize=lambda s,a,t,i:s==self.scope and i is self.invocation and a not in self.denied
        self.uses=EnvironmentUseOperations(self.manager,authorize=self.authorize)
        self.use=self.uses.acquire(self.instance.identity,self.scope,request_id='acquire',sharing=False,invocation=self.invocation)['useIdentity']
        self.service=EnvironmentEndpoints(self.uses)
        exported=self.service.export(self.use,self.scope,request_id='export',invocation=self.invocation,
            capabilities=['launcher','communicate','observe','terminate','detach'])['endpointRef']
        self.launched=self.service.launch(exported,self.scope,
            ProcessRequest.build(argv or ['/bin/cat'],cwd=str(root/'work'),env={}),
            request_id='launch',invocation=self.invocation)
        self.ref=self.launched['processEndpointRef']
        self.process=self.service.process(self.ref,self.scope,invocation=self.invocation)
        self.native=self.manager._owned_process_handles[(self.use,self.launched['processIdentity'])]
        self.guard_calls=0
        self.active=False

    @contextmanager
    def guard(self):
        self.guard_calls+=1
        self.active=True
        try:yield
        finally:self.active=False

    async def send(self,frame=b'once\n',request_id='frame-0',guard=None,correlation=None):
        return await self.service.send_guarded(self.ref,self.scope,frame,request_id=request_id,
            invocation=self.invocation,correlation=correlation or {'parentAgentOperation':'agent-operation','engineeringAttempt':'attempt'},
            write_guard=guard or self.guard,timeout=2)

    async def cleanup(self):
        self.denied.clear()
        view=self.uses.process(self.use,self.launched['processIdentity'],self.scope,invocation=self.invocation)
        if view.observe().state!='exited':await view.terminate(request_id='cleanup-stop')
        await view.wait_exit(timeout=3)
        view.detach(request_id='cleanup-detach')
        assert self.uses.release(self.use,self.scope,request_id='cleanup-release',invocation=self.invocation)['status']=='completed'


def test_real_physical_write_runs_inside_same_task_thread_guard_and_drain_outside(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            raw=child.native._target;io=raw._get_io();await io.bind()
            original_write,original_drain=io.writer.write,io.writer.drain
            task,thread=asyncio.current_task(),threading.get_ident()
            writes=[]
            def checked_write(data):
                assert child.active and asyncio.current_task() is task and threading.get_ident()==thread
                writes.append(data);return original_write(data)
            async def checked_drain():
                assert not child.active
                await asyncio.sleep(0)
                assert not child.active
                return await original_drain()
            io.writer.write=checked_write;io.writer.drain=checked_drain
            result=await child.send()
            assert result['delivery']=='confirmed' and result['bytesObserved']==5
            assert result['operationRef'].startswith('environment-operation/')
            assert result['operationRef'] not in ('frame-0','agent-operation','attempt')
            assert await child.process.read_stdout(timeout=2)==b'once\n'
            assert await child.send()==result
            assert writes==[b'once\n'] and child.guard_calls==1
            assert child.instance.snapshot.active_uses==1
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_changed_input_or_parent_correlation_conflicts_without_new_write(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            await child.send()
            with pytest.raises(EnvironmentRefused):await child.send(b'different\n')
            with pytest.raises(EnvironmentRefused):await child.send(correlation={'parentAgentOperation':'other'})
            assert child.guard_calls==1
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_replay_uses_read_permission_never_restores_revoked_send_and_send_does_not_grant_read(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            original=await child.send()
            child.denied.add('communicate')
            assert await child.send()==original
            with pytest.raises(EnvironmentRefused):await child.send(request_id='fresh')
            child.denied={'observe'}
            with pytest.raises(EnvironmentRefused):await child.send()
            with pytest.raises(EnvironmentRefused):child.service.send_result(child.ref,child.scope,request_id='frame-0',invocation=child.invocation)
            assert (await child.send(request_id='send-only'))['delivery']=='confirmed'
            assert child.guard_calls==2
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_physical_guard_revocation_is_known_not_sent_and_never_left_reserved(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        @contextmanager
        def refused_guard():
            raise EnvironmentRefused('original effect fence refused')
            yield
        try:
            result=await child.send(guard=refused_guard)
            assert result['status']=='refused' and result['delivery']=='not_sent' and result['bytesObserved']==0
            assert await child.send()==result
            fresh=await child.send(b'fresh\n',request_id='fresh')
            assert fresh['delivery']=='confirmed'
            assert await child.process.read_stdout(timeout=2)==b'fresh\n'
            assert child.guard_calls==1
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_current_resource_right_rechecked_after_async_pipe_binding(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        raw=child.native._target;io=raw._get_io();bind=io.bind
        async def revoke_while_binding():
            await bind();child.denied.add('communicate')
        io.bind=revoke_while_binding
        try:
            result=await child.send()
            assert result['delivery']=='not_sent' and child.guard_calls==0
            child.denied.clear();io.bind=bind
            assert (await child.send(request_id='fresh'))['delivery']=='confirmed'
            assert await child.process.read_stdout(timeout=2)==b'once\n'
        finally:
            io.bind=bind
            await child.cleanup()
    asyncio.run(scenario())


def test_crash_window_after_actual_send_before_publication_stays_unknown_no_resend(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path);finish=child.uses._finish
        def publication_fault(*args,**kwargs):raise OSError('injected post-effect publication crash')
        try:
            child.uses._finish=publication_fault
            with pytest.raises(OSError):await child.send()
            child.uses._finish=finish
            assert await child.process.read_stdout(timeout=2)==b'once\n'
            replay=await child.send()
            assert replay['status']=='unknown' and child.guard_calls==1
            cold_manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'),providers={'local':LocalEnvironmentResourceProvider(default_root=str(tmp_path/'work'))})
            cold=EnvironmentEndpoints(EnvironmentUseOperations(cold_manager,authorize=child.authorize))
            assert cold.send_result(child.ref,child.scope,request_id='frame-0',invocation=child.invocation)==replay
            assert cold_manager._owned_use_handles=={} and cold_manager._owned_process_handles=={}
        finally:
            child.uses._finish=finish
            await child.cleanup()
    asyncio.run(scenario())


def test_concurrent_same_request_claims_once_while_original_writer_binds(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            first,second=await asyncio.gather(child.send(),child.send())
            assert {first['status'],second['status']}=={'completed','unknown'}
            assert child.guard_calls==1
            assert await child.process.read_stdout(timeout=2)==b'once\n'
            assert (await child.send())['status']=='completed'
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_foreign_subject_cannot_read_or_replay_original_child(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            await child.send()
            with pytest.raises(EnvironmentRefused):
                child.service.send_result(child.ref,OwnerScope('principal','foreign'),request_id='frame-0',invocation=child.invocation)
            with pytest.raises(EnvironmentRefused):
                await child.service.send_guarded(child.ref,OwnerScope('principal','foreign'),b'once\n',request_id='frame-0',invocation=child.invocation,correlation={},write_guard=child.guard)
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_missing_original_guarded_provider_is_unavailable_before_claim(tmp_path,monkeypatch):
    async def scenario():
        child=LocalChild(tmp_path)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(type(child.native._target),'write_stdin_guarded',None)
                with pytest.raises(EnvironmentRefused):await child.send()
            with child.manager.store.transaction() as db:
                assert db.execute("SELECT count(*) FROM environment_use_requests WHERE action='send-frame'").fetchone()[0]==0
        finally:await child.cleanup()
    asyncio.run(scenario())


def test_cancel_before_physical_cut_is_not_sent_and_queryable(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path);raw=child.native._target;io=raw._get_io();original=io.bind
        waiting=asyncio.Event();blocked=asyncio.Event()
        async def wait_before_cut():
            waiting.set();await blocked.wait()
        io.bind=wait_before_cut
        try:
            task=asyncio.create_task(child.send())
            await waiting.wait();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            result=child.service.send_result(child.ref,child.scope,request_id='frame-0',invocation=child.invocation)
            assert result['delivery']=='not_sent' and result['status']=='refused' and child.guard_calls==0
        finally:
            io.bind=original
            await child.cleanup()
    asyncio.run(scenario())


def test_cancel_after_write_during_drain_is_unknown_without_a_second_frame(tmp_path):
    async def scenario():
        child=LocalChild(tmp_path);raw=child.native._target;io=raw._get_io();await io.bind()
        original=io.writer.drain;started=asyncio.Event();blocked=asyncio.Event()
        async def block_after_write():
            assert not child.active
            started.set();await blocked.wait()
        io.writer.drain=block_after_write
        try:
            task=asyncio.create_task(child.send())
            await started.wait();task.cancel()
            # Existing provider converts post-dispatch cancellation to original
            # EnvironmentOperationUnknown; endpoint returns that durable outcome.
            returned=await task
            result=child.service.send_result(child.ref,child.scope,request_id='frame-0',invocation=child.invocation)
            assert returned==result
            assert result['delivery']=='possibly_sent' and result['status']=='unknown'
            assert await child.send()==result and child.guard_calls==1
        finally:
            io.writer.drain=original
            await child.cleanup()
    asyncio.run(scenario())


def _forked_original_handle_send(child, barrier, connection):
    try:
        barrier.wait(timeout=5)
        result=asyncio.run(child.send())
        connection.send({'result':result,'guardCalls':child.guard_calls})
    except BaseException as error:
        connection.send({'error':type(error).__name__})
    finally:
        connection.close()


def test_two_processes_inheriting_original_handle_claim_one_real_frame(tmp_path):
    # Both test workers inherit the SAME original owned pipe descriptors via
    # fork. This is not a cold reconnect, handle discovery or reacquisition.
    import multiprocessing
    import time
    log=tmp_path/'physical-frames.txt'
    child=LocalChild(tmp_path,['/bin/sh','-c','while IFS= read -r line; do printf "%s\\n" "$line" >> "$1"; done','sh',str(log)])
    context=multiprocessing.get_context('fork');barrier=context.Barrier(2)
    workers=[];readers=[]
    try:
        for _ in range(2):
            reader,writer=context.Pipe(duplex=False)
            worker=context.Process(target=_forked_original_handle_send,args=(child,barrier,writer))
            worker.start();writer.close();workers.append(worker);readers.append(reader)
        outcomes=[]
        for reader in readers:
            assert reader.poll(8),'bounded original-handle worker timed out'
            outcomes.append(reader.recv())
        for worker in workers:
            worker.join(timeout=5)
            assert worker.exitcode==0
        assert all('error' not in item for item in outcomes),outcomes
        assert sum(item['guardCalls'] for item in outcomes)==1
        assert all(item['result']['status'] in ('completed','unknown') for item in outcomes)
        assert len({item['result']['operationRef'] for item in outcomes})==1
        deadline=time.monotonic()+3
        while not log.exists() and time.monotonic()<deadline:time.sleep(0.01)
        assert log.read_bytes()==b'once\n'
        original=child.service.send_result(child.ref,child.scope,request_id='frame-0',invocation=child.invocation)
        assert original['status']=='completed'
    finally:
        for reader in readers:reader.close()
        # Only these explicitly created test workers may be terminated on failure.
        for worker in workers:
            if worker.is_alive():worker.terminate();worker.join(timeout=3)
        asyncio.run(child.cleanup())
