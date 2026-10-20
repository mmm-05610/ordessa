"""Real SDK DTO/app/owned local writer, including pre-cut refusal and post-cut unknown."""
import asyncio
from contextlib import contextmanager
import hashlib

import pytest

from endpoint_fixture import LocalEndpointFixture
from ordessa_environments import EnvironmentRefused
from ordessa_execution_agents.sdk.instances import AgentInstanceRef
from ordessa_execution_agents.sdk.interactions import TurnRef,WriteBinding,GuardedSendObservation
from ordessa_execution_agents.sdk.prepare import canonical_digest


def fixed_binding(process_ref,frame,agent_operation='original-agent-operation'):
    frame_digest='sha256:'+hashlib.sha256(frame).hexdigest()
    request=canonical_digest({'schemaVersion':'agent-endpoint-frame-request/1','agentOperationRef':agent_operation,
        'endpointRef':process_ref.projection(),'frameDigest':frame_digest,'frameOrdinal':0})
    return WriteBinding(TurnRef(AgentInstanceRef('test','instance','sha256:'+'a'*64),'original-turn'),
        'fixed-session',agent_operation,request,'external-engineering-attempt','sha256:'+'b'*64,frame_digest)


def test_real_prewrite_refusal_is_typed_not_sent_with_original_endpoint_operation(tmp_path):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path)
        try:
            endpoint=await fixture.endpoint()
            launch=await endpoint.launcher.launch(fixture.plan(['/bin/cat']),'launch',fixture.invocation)
            process=await fixture.resolver.resolve(launch.process_endpoint_ref,fixture.invocation)
            frame=b'must-not-write\n';binding=fixed_binding(launch.process_endpoint_ref,frame)
            class RefusedGuard:
                @contextmanager
                def guard_write(self,b,invocation):
                    assert b is binding and invocation is fixture.invocation
                    raise EnvironmentRefused('controlled original effect fence refusal')
                    yield
            result=await process.communicate.send_guarded(frame,binding.endpoint_request_id,None,fixture.invocation,binding=binding,write_guard=RefusedGuard())
            assert type(result) is GuardedSendObservation
            assert result.status=='not_sent' and result.bytes_sent==0 and result.error is not None
            assert result.operation_ref.startswith('environment-operation/')
            replay=await process.communicate.send_guarded(frame,binding.endpoint_request_id,None,fixture.invocation,binding=binding,write_guard=RefusedGuard())
            assert replay==result and fixture.retained_use_count==1
        finally:await fixture.cleanup()
    asyncio.run(scenario())


def test_real_postwrite_failure_returns_typed_possible_delivery_and_never_second_frame(tmp_path):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path);log=tmp_path/'physical-child-lines.txt'
        try:
            endpoint=await fixture.endpoint()
            argv=['/bin/sh','-c','while IFS= read -r line; do printf "%s\\n" "$line" >> "$1"; done','sh',str(log)]
            launch=await endpoint.launcher.launch(fixture.plan(argv),'launch',fixture.invocation)
            process=await fixture.resolver.resolve(launch.process_endpoint_ref,fixture.invocation)
            native=next(iter(fixture._manager._owned_process_handles.values()))
            io=native._target._get_io();await io.bind()
            original_drain=io.writer.drain
            async def uncertain_drain():raise OSError('controlled post-write transport failure')
            io.writer.drain=uncertain_drain
            frame=b'one-uncertain-effect\n';binding=fixed_binding(launch.process_endpoint_ref,frame)
            class Guard:
                calls=0
                @contextmanager
                def guard_write(self,b,invocation):
                    assert b is binding and invocation is fixture.invocation
                    self.calls+=1;yield
            guard=Guard()
            result=await process.communicate.send_guarded(frame,binding.endpoint_request_id,None,fixture.invocation,binding=binding,write_guard=guard)
            assert type(result) is GuardedSendObservation
            assert result.status=='possibly_sent' and result.bytes_sent is None
            assert result.error is None  # no fabricated pre-effect refusal
            replay=await process.communicate.send_guarded(frame,binding.endpoint_request_id,None,fixture.invocation,binding=binding,write_guard=guard)
            assert replay==result and guard.calls==1
            deadline=asyncio.get_running_loop().time()+2
            while not log.exists() and asyncio.get_running_loop().time()<deadline:await asyncio.sleep(.01)
            assert log.read_bytes()==frame
            io.writer.drain=original_drain
        finally:await fixture.cleanup()
    asyncio.run(scenario())


def test_missing_guard_or_wrong_endpoint_request_is_rejected_before_child_claim(tmp_path):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path)
        try:
            endpoint=await fixture.endpoint()
            launch=await endpoint.launcher.launch(fixture.plan(['/bin/cat']),'launch',fixture.invocation)
            process=await fixture.resolver.resolve(launch.process_endpoint_ref,fixture.invocation)
            frame=b'blocked\n';binding=fixed_binding(launch.process_endpoint_ref,frame)
            with pytest.raises(EnvironmentRefused):
                await process.communicate.send_guarded(frame,binding.endpoint_request_id,None,fixture.invocation,binding=binding,write_guard=None)
            class Guard:
                @contextmanager
                def guard_write(self,*args):raise AssertionError('wrong request reached writer');yield
            with pytest.raises(EnvironmentRefused):
                await process.communicate.send_guarded(frame,'caller-substituted-key',None,fixture.invocation,binding=binding,write_guard=Guard())
            with fixture._manager.store.transaction() as db:
                assert db.execute("SELECT count(*) FROM environment_use_requests WHERE action='send-frame'").fetchone()[0]==0
        finally:await fixture.cleanup()
    asyncio.run(scenario())
