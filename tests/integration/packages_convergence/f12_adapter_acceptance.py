"""Exact F1.2 SDK/app/physical-child gate; BLOCKED is never reported as PASS."""
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from ordessa_environments import EnvironmentRefused
from ordessa_execution_agents.sdk.instances import AgentInstanceRef
from ordessa_execution_agents.sdk.prepare import canonical_digest
from endpoint_fixture import LocalEndpointFixture


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--receipt');args=parser.parse_args()
    try:
        from ordessa_execution_agents.sdk.interactions import TurnRef, WriteBinding, GuardedSendObservation
    except ImportError:
        report={'status':'BLOCKED','reason':'F1.2 interaction DTOs absent','physicalEffects':0}
    else:
        expected={'operation_ref','status','bytes_sent','error'}
        actual={f.name for f in fields(GuardedSendObservation)}
        if actual!=expected:
            report={'status':'BLOCKED','reason':'GuardedSendObservation differs from DESIGN §12.2',
                    'expected':sorted(expected),'actual':sorted(actual),'physicalEffects':0}
        else:
            async def scenario(root):
                fixture=LocalEndpointFixture(root)
                try:
                    endpoint=await fixture.endpoint()
                    launched=await endpoint.launcher.launch(fixture.plan(['/bin/cat']),'launch',fixture.invocation)
                    assert launched.status=='completed'
                    process=await fixture.resolver.resolve(launched.process_endpoint_ref,fixture.invocation)
                    # Synthetic Agent identity tests this transport adapter only;
                    # it is not original Manager provenance or an authorized turn.
                    turn=TurnRef(AgentInstanceRef('test','instance','sha256:'+'a'*64),'turn')
                    frame=b'f12-child\n';frame_digest='sha256:'+hashlib.sha256(frame).hexdigest()
                    request_id=canonical_digest({'schemaVersion':'agent-endpoint-frame-request/1',
                        'agentOperationRef':'original-agent-operation',
                        'endpointRef':launched.process_endpoint_ref.projection(),
                        'frameDigest':frame_digest,'frameOrdinal':0})
                    binding=WriteBinding(turn,'fixed-session','original-agent-operation',request_id,
                        'external-engineering-attempt','sha256:'+'b'*64,frame_digest)
                    task,thread=asyncio.current_task(),threading.get_ident()
                    class Guard:
                        calls=0
                        @contextmanager
                        def guard_write(self,received,invocation):
                            assert received is binding and invocation is fixture.invocation
                            assert asyncio.current_task() is task and threading.get_ident()==thread
                            self.calls+=1
                            yield
                    guard=Guard();deadline=asyncio.get_running_loop().time()+3
                    sent=await process.communicate.send_guarded(frame,request_id,deadline,fixture.invocation,binding=binding,write_guard=guard)
                    assert type(sent) is GuardedSendObservation and sent.status=='confirmed' and sent.bytes_sent==len(frame)
                    assert sent.operation_ref not in (binding.agent_operation_ref,binding.engineering_attempt_ref,request_id)
                    received=await process.communicate.receive(None,deadline,fixture.invocation)
                    assert b''.join(e.payload_bytes for e in received.events)==frame
                    fixture.denied.add('communicate')
                    replay=await process.communicate.send_guarded(frame,request_id,deadline,fixture.invocation,binding=binding,write_guard=guard)
                    assert replay==sent and guard.calls==1
                    assert fixture.retained_use_count==1
                    return {'status':'PASS','guardCalls':1,'physicalFrameEffects':1,
                        'endpointOperationRef':sent.operation_ref,'currentReadReplay':True,
                        'scope':'exact SDK DTO/app adapter/real pipe child; not Manager/session/provenance acceptance'}
                finally:await fixture.cleanup()
            with tempfile.TemporaryDirectory(prefix='ordessa-f12-adapter-') as root:
                report=asyncio.run(scenario(root))
    if args.receipt:Path(args.receipt).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
