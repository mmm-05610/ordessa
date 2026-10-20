"""Two independent HTTP client processes, one formal Product/Agent/OS owner."""
import asyncio
from contextlib import contextmanager
import json
import socket
import sys

import pytest
import uvicorn

from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_execution_agents.capability.instances import build_agent_capability
from ordessa_server.composition.packages_convergence import build_product_registry_runtime
from ordessa_interfaces.http.registry import create_registry_app
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from test_agent_guarded_bootstrap import setup

CLIENT='''import json,sys,httpx
with httpx.Client(timeout=5,trust_env=False) as client:
 response=client.post(sys.argv[1],headers={'Authorization':'Bearer controlled-http-client'},json=json.loads(sys.argv[2]))
 assert response.status_code==200,response.text
 print(json.dumps(response.json()))
'''


def test_two_client_processes_replay_one_lifecycle_claim_and_one_real_signal(tmp_path,monkeypatch):
    async def scenario():
        case=await setup(tmp_path/'fixture')
        runtime=None;server=None;task=None;listener=None;clients=[];signals=[]
        scope=Scope('fixture-realm','fixture-project')
        issuer=InstanceAccessAuthority(lambda:'controlled-http-client',principal_id='existing-test-caller',
            grants=(AccessGrant(scope,('agents.stop','agents.get')),),legacy_principal=None)
        caller=[issuer.authenticate('Bearer controlled-http-client')]
        original_read=case.authority.check_read_instance
        def read(invocation,instance_id):
            with issuer.guard(caller[0],scope,'agents.get'):
                return original_read(invocation,instance_id)
        def lifecycle(invocation,control,*,action):
            case.authority.principal_scope(invocation)
            with issuer.guard(caller[0],scope,'agents.'+action):
                assert control['principalScope']=='principal:existing-test-caller'
        case.authority.check_read_instance=read
        case.authority.check_instance_lifecycle=lifecycle
        case.authority.guard_instance_lifecycle=lambda invocation,control,*,action:issuer.guard(caller[0],scope,'agents.'+action)
        class NoPromptGrant:
            @contextmanager
            def guard_write(self,*args):
                with issuer.guard(caller[0],scope,'agents.prompt'):yield
        def capabilities(owner):
            return (build_agent_capability(owner.manager,owner.interactions,
                invocation_resolver=lambda context:case.fixture.invocation,write_guard=NoPromptGrant()),)
        def context(principal,rid,deadline):
            issuer.verify(principal);caller[0]=principal
            return RequestContext({'id':principal.principal_id},rid,deadline)
        try:
            inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
                case.manager.preparation_resolver,case.authority,case.authority,capabilities)
            runtime=build_product_registry_runtime(tmp_path/'product',ServerProductComposition(agent_owner_inputs=inputs),issuer,
                context_factory=context,server_id='original-server')
            started=await runtime.agent_owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            raw=next(iter(case.fixture._manager._owned_process_handles.values()))._target
            original=raw.popen.terminate
            def terminate():signals.append('signal');return original()
            monkeypatch.setattr(raw.popen,'terminate',terminate)
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
            port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(create_registry_app(runtime),lifespan='off',log_level='error',access_log=False))
            task=asyncio.create_task(server.serve(sockets=[listener]))
            for _ in range(200):
                if server.started:break
                if task.done():await task
                await asyncio.sleep(.01)
            assert server.started
            request={'jsonrpc':'2.0','id':'same-request','method':'operations.call',
                'params':{'operationId':'agents.stop','input':{'instanceRef':started.instance_ref.projection()}}}
            for _ in range(2):
                clients.append(await asyncio.create_subprocess_exec(sys.executable,'-c',CLIENT,
                    f'http://127.0.0.1:{port}/wire/v1/operations.call',json.dumps(request),
                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE))
            outputs=await asyncio.wait_for(asyncio.gather(*(p.communicate() for p in clients)),10)
            for process,(out,err) in zip(clients,outputs):assert process.returncode==0,err.decode()
            results=[json.loads(out)['result'] for out,_ in outputs]
            assert results[0]==results[1] and results[0]['status']=='completed'
            assert results[0]['data']['operationRef'].startswith('environment-operation/')
            assert signals==['signal']
            assert runtime.agent_owner.records._db.execute("SELECT count(*) FROM operations WHERE operation='stop'").fetchone()[0]==1
            control,_=runtime.agent_owner.records.instance_control(started.instance_ref)
            assert control.writer_epoch==1 and control.active_action=='stop'
            assert (await case.fixture.wait_exit(started.process_endpoint_ref)).state=='exited'
            assert case.fixture.retained_use_count==1 and not (tmp_path/'product/state/core.sqlite').exists()
        finally:
            for process in clients:
                if process.returncode is None:
                    process.terminate();await process.wait()
            if server is not None:server.should_exit=True
            if task is not None:await asyncio.wait_for(task,3)
            if listener is not None:listener.close()
            monkeypatch.undo()
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
