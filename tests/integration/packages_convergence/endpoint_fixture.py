"""Test CALLER prepares resources and supplies only typed F1 endpoints to agents.

Import as endpoint_fixture after adding this directory to sys.path. No pytest
fixtures/conftest or model/service dependencies. Never registered in product.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from ordessa_environments import (EnvironmentManager, EnvironmentUseOperations, EnvironmentEndpoints,
    EnvironmentRefused, OwnerScope, ProcessRequest, SQLiteEnvironmentStore)
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_agents.sdk.prepare import BoundPath, LaunchPlan, SessionBootstrap
from ordessa_agents.bridges.environment_endpoints import EnvironmentEndpointResolver


class LocalEndpointFixture:
    """Test owns resources; agents receives endpoint/resolver/invocation only.

    Caller must `await cleanup()` in finally. Only this fixture's process handles
    are affected; no PID search, global services, model or network operations.
    """
    def __init__(self, state_dir, *, capabilities=('launcher','observe','communicate','terminate','detach','files')):
        self._root = Path(state_dir).absolute()
        self._root.mkdir(parents=True, exist_ok=True)
        work = self._root/'work'
        work.mkdir(exist_ok=True)
        for name in ('config','home','tmp'):
            (work/name).mkdir(exist_ok=True)
        provider = LocalEnvironmentResourceProvider(default_root=str(work))
        self._manager = EnvironmentManager(store=SQLiteEnvironmentStore(self._root/'environments.sqlite'),providers={'local':provider})
        self._environment = self._manager.create('local',{'root':str(work)})
        self._scope = OwnerScope('principal','existing-test-caller')
        self.invocation = SimpleNamespace(owner_scope=self._scope)
        self.denied = set()
        self._uses = EnvironmentUseOperations(self._manager,authorize=lambda scope,action,target,invocation:
            scope==self._scope and invocation is self.invocation and action not in self.denied)
        self._use_id = self._uses.acquire(self._environment.identity,self._scope,request_id='fixture/acquire',sharing=False,invocation=self.invocation)['useIdentity']
        self._endpoints = EnvironmentEndpoints(self._uses)
        result = self._endpoints.export(self._use_id,self._scope,capabilities=capabilities,
            request_id='fixture/export',invocation=self.invocation,
            roots={'work':'.','config':'config','home':'home','tmp':'tmp'})
        self._ref = result['endpointRef']
        self.resolver = EnvironmentEndpointResolver(self._endpoints,invocation_resolver=self._caller,
            process_request_factory=ProcessRequest.build,refusal=EnvironmentRefused)
        self._cleaned = False

    def _caller(self, invocation):
        if invocation is not self.invocation:
            raise ValueError('fixture cannot authenticate a foreign invocation')
        return self.invocation

    async def endpoint(self):
        """Exact sdk.endpoint.BoundEndpoint; contains no Use/env reference."""
        return await self.resolver.resolve(self._ref,self.invocation)

    @staticmethod
    def plan(argv, *, environment_values=None, configuration_artifacts=(), prepared_configuration_refs=()):
        required=('launcher','files') if configuration_artifacts else ('launcher',)
        return LaunchPlan(tuple(argv),BoundPath('work','.'),environment_values or {},(),
            tuple(configuration_artifacts),tuple(prepared_configuration_refs),(),SessionBootstrap('none'),required)

    @property
    def retained_use_count(self):
        """Caller-side observation; never passed into Agent runtime."""
        return self._environment.snapshot.active_uses

    async def wait_exit(self, process_endpoint_ref, *, timeout=3):
        ref=process_endpoint_ref.projection() if hasattr(process_endpoint_ref,'projection') else process_endpoint_ref
        view=self._endpoints.process(ref,self._scope,invocation=self.invocation)
        return await view.wait_exit(timeout=timeout)

    async def cleanup(self):
        """Explicit test caller cleanup, independent of Agent close/detach."""
        if self._cleaned:return
        self.denied.clear()  # test caller restores only its own cleanup rights.
        for (use_id,process_id) in tuple(self._manager._owned_process_handles):
            if use_id != self._use_id:continue
            view=self._uses.process(use_id,process_id,self._scope,invocation=self.invocation)
            if view.observe().state!='exited':
                result=await view.terminate(request_id='fixture/terminate/'+process_id)
                if result['status']!='completed':raise RuntimeError('test-owned process cleanup unresolved')
            await view.wait_exit(timeout=3)
            result=view.detach(request_id='fixture/detach/'+process_id)
            if result['status']!='completed':raise RuntimeError('test-owned detach unresolved')
        result=self._uses.release(self._use_id,self._scope,request_id='fixture/release',invocation=self.invocation)
        if result['status']!='completed':raise RuntimeError('test-owned Use cleanup unresolved')
        self._cleaned=True
