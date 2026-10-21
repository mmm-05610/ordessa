"""F1.1 SDK values cross only stateless adapters into real local endpoints."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from ordessa_environments import (EnvironmentManager, EnvironmentUseOperations, EnvironmentEndpoints,
    EnvironmentRefused, OwnerScope, ProcessRequest, SQLiteEnvironmentStore)
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_agents.sdk.prepare import BoundPath, LaunchPlan, SessionBootstrap, ConfigurationArtifact
from ordessa_agents.bridges.environment_endpoints import EnvironmentEndpointResolver


def test_positive_sdk_launch_no_acp_observe_terminate_detach_and_no_use_release(tmp_path):
    async def scenario():
        provider = LocalEnvironmentResourceProvider(default_root=str(tmp_path/'work'))
        manager = EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'), providers={'local':provider})
        instance = manager.create('local', {'root':str(tmp_path/'work')})
        scope = OwnerScope('principal','existing-user')
        invocation = SimpleNamespace(owner_scope=scope)
        uses = EnvironmentUseOperations(manager, authorize=lambda s,a,t,i: s==scope and i is invocation)
        use = uses.acquire(instance.identity,scope,request_id='acquire',sharing=False,invocation=invocation)['useIdentity']
        endpoints = EnvironmentEndpoints(uses)
        ref = endpoints.export(use,scope,capabilities=['launcher','observe','communicate','terminate','detach'],request_id='export',invocation=invocation)['endpointRef']
        adapter = EnvironmentEndpointResolver(endpoints, invocation_resolver=lambda caller: invocation if caller is invocation else None,
            process_request_factory=ProcessRequest.build, refusal=EnvironmentRefused)
        bound = await adapter.resolve(ref, invocation)
        assert not any(k in vars(bound) for k in ('environment_ref','use_ref','use','environment'))
        plan = LaunchPlan(('/bin/cat',),BoundPath('work','.'),{},(),(),(),(),SessionBootstrap('none'),('launcher',))
        launch = await bound.launcher.launch(plan,'launch',invocation)
        assert launch.status=='completed' and launch.process_endpoint_ref
        assert 'useIdentity' not in launch.facts and 'environmentIdentity' not in launch.facts
        process = await adapter.resolve(launch.process_endpoint_ref, invocation)
        try:
            sent = await process.communicate.send('interaction/frame',b'adapter-positive\n',asyncio.get_running_loop().time()+2,invocation)
            assert sent.bytes_observed==17
            received = await process.communicate.receive(None,asyncio.get_running_loop().time()+2,invocation)
            assert tuple(event.payload_bytes for event in received.events)==(b'adapter-positive\n',)
            assert (await process.observe.observe(None,invocation)).state=='running'
        finally:
            terminated = await process.terminate.terminate('stop',False,None,invocation)
            assert terminated.facts['cancellation']=='requested'
            view = endpoints.process(launch.process_endpoint_ref.projection(),scope,invocation=invocation)
            await view.wait_exit(timeout=3)
            detached = await process.detach.detach('detach',invocation)
            assert detached.facts['exitClaimed'] is False
            assert instance.snapshot.active_uses==1  # Agent adapter NEVER releases Use.
            assert uses.release(use,scope,request_id='caller-release',invocation=invocation)['status']=='completed'
    asyncio.run(scenario())


def test_mutated_launch_plan_digest_is_refused_before_real_spawn(tmp_path):
    async def scenario():
        provider=LocalEnvironmentResourceProvider(default_root=str(tmp_path/'work'))
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'),providers={'local':provider})
        instance=manager.create('local',{'root':str(tmp_path/'work')})
        scope=OwnerScope('principal','existing-user');invocation=SimpleNamespace(owner_scope=scope)
        uses=EnvironmentUseOperations(manager,authorize=lambda s,a,t,i: s==scope and i is invocation)
        use=uses.acquire(instance.identity,scope,request_id='acquire',sharing=False,invocation=invocation)['useIdentity']
        endpoints=EnvironmentEndpoints(uses)
        ref=endpoints.export(use,scope,capabilities=['launcher'],request_id='export',invocation=invocation)['endpointRef']
        bound=await EnvironmentEndpointResolver(endpoints,invocation_resolver=lambda _:invocation,
            process_request_factory=ProcessRequest.build,refusal=EnvironmentRefused).resolve(ref,invocation)
        plan=LaunchPlan(('/bin/echo','must-not-launch'),BoundPath('work','.'),{},(),(),(),(),SessionBootstrap('none'),('launcher',))
        # Simulate foreign/compromised producer mutating after validation. Even if
        # SDK sealing changes, object.__setattr__ cannot bypass adapter recheck.
        object.__setattr__(plan,'environment_values',{'CHANGED':'after-digest'})
        result=await bound.launcher.launch(plan,'launch',invocation)
        assert result.status=='refused'
        assert manager._owned_process_handles=={}
        uses.release(use,scope,request_id='release',invocation=invocation)
    asyncio.run(scenario())


def test_materialize_verify_then_launch_configuration_without_adapter_orchestration(tmp_path):
    async def scenario():
        provider=LocalEnvironmentResourceProvider(default_root=str(tmp_path/'work'))
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'),providers={'local':provider})
        instance=manager.create('local',{'root':str(tmp_path/'work')})
        scope=OwnerScope('principal','existing-user');invocation=SimpleNamespace(owner_scope=scope)
        uses=EnvironmentUseOperations(manager,authorize=lambda s,a,t,i:s==scope and i is invocation)
        use=uses.acquire(instance.identity,scope,request_id='acquire',sharing=False,invocation=invocation)['useIdentity']
        endpoints=EnvironmentEndpoints(uses)
        ref=endpoints.export(use,scope,capabilities=['launcher','files','observe','communicate','detach'],request_id='export',invocation=invocation)['endpointRef']
        resolver=EnvironmentEndpointResolver(endpoints,invocation_resolver=lambda _:invocation,
            process_request_factory=ProcessRequest.build,refusal=EnvironmentRefused)
        bound=await resolver.resolve(ref,invocation)
        body='materialized-positive'
        digest='sha256:'+__import__('hashlib').sha256(body.encode()).hexdigest()
        artifact=ConfigurationArtifact(BoundPath('work','configuration.txt'),'text/plain',body,digest)
        receipt=await bound.files.materialize(artifact,'materialize',invocation)
        assert receipt['status']=='completed'
        plan=LaunchPlan(('/bin/cat','configuration.txt'),BoundPath('work','.'),{},(),(artifact,),(),(),SessionBootstrap('none'),('launcher','files'))
        launched=await bound.launcher.launch(plan,'launch',invocation)
        assert launched.status=='completed'
        process=await resolver.resolve(launched.process_endpoint_ref,invocation)
        native=endpoints.process(launched.process_endpoint_ref.projection(),scope,invocation=invocation)
        assert await native.read_stdout(timeout=2)==body.encode()
        assert (await native.wait_exit(timeout=2)).exit_code==0
        await process.detach.detach('detach',invocation)
        assert instance.snapshot.active_uses==1
        assert uses.release(use,scope,request_id='release',invocation=invocation)['status']=='completed'
    asyncio.run(scenario())
