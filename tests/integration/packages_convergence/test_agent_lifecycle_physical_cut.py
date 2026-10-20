"""Stateless Agent adapter to original environment physical lifecycle cut.

Instance-control admission is an explicit callback peer here. Full manager
control/authority/fence acceptance remains a separate T018 owner gate.
"""
import asyncio
import sys
from dataclasses import replace

import pytest

from endpoint_fixture import LocalEndpointFixture
from ordessa_environments import EnvironmentRefused
from ordessa_execution_agents.instances.contracts import InstanceControl


@pytest.mark.parametrize('action',['stop','detach'])
def test_adapter_guard_crosses_original_use_to_actual_physical_effect(tmp_path,monkeypatch,action):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path)
        try:
            launcher=await fixture.endpoint()
            receipt=await launcher.launcher.launch(fixture.plan([sys.executable,'-c','import time;time.sleep(30)']),'launch',fixture.invocation)
            ref=receipt.process_endpoint_ref
            endpoint=await fixture.resolver.resolve(ref,fixture.invocation)
            raw=next(iter(fixture._manager._owned_process_handles.values()))._target
            control=InstanceControl('ns','instance','sha256:'+'a'*64,'principal:existing',ref,1,'running','lifecycle/op',action)
            checked=[];effects=[]
            from contextlib import contextmanager
            held=[False]
            @contextmanager
            def guard():
                checked.append('admitted');held[0]=True
                try:yield
                finally:held[0]=False
            if action=='stop':
                original=raw.popen.terminate
                def terminate():
                    assert checked==['admitted'] and held[0];effects.append('signal');return original()
                monkeypatch.setattr(raw.popen,'terminate',terminate)
                observed=await endpoint.terminate.terminate_guarded('stop',False,fixture.invocation,binding=control.projection(),guard=guard)
                assert observed.facts['cancellation']=='requested'
                assert (await fixture.wait_exit(ref)).state=='exited'
            else:
                original=type(raw).release
                def release(handle):
                    assert checked==['admitted'] and held[0];effects.append('detach');return original(handle)
                monkeypatch.setattr(type(raw),'release',release)
                observed=await endpoint.detach.detach_guarded('detach',fixture.invocation,binding=control.projection(),guard=guard)
                assert observed.facts['associationDetached'] is True
                assert observed.facts['exitClaimed'] is False and raw.observe().state=='running'
            assert observed.status=='completed' and len(effects)==1 and checked==['admitted']
            assert fixture.retained_use_count==1 and not held[0]
        finally:
            monkeypatch.undo()
            await fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('defect',['guard','action','endpoint'])
def test_adapter_refuses_missing_guard_or_mismatched_binding_before_effect(tmp_path,defect):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path)
        try:
            launcher=await fixture.endpoint()
            receipt=await launcher.launcher.launch(fixture.plan(['/bin/cat']),'launch',fixture.invocation)
            ref=receipt.process_endpoint_ref
            endpoint=await fixture.resolver.resolve(ref,fixture.invocation)
            control=InstanceControl('ns','instance','sha256:'+'a'*64,'principal:existing',ref,1,'running','lifecycle/op','stop')
            if defect=='action':control=replace(control,active_action='detach')
            if defect=='endpoint':control=replace(control,endpoint_ref=replace(ref,endpoint_id='foreign'))
            checks=[]
            with pytest.raises(EnvironmentRefused):
                await endpoint.terminate.terminate_guarded('same',False,fixture.invocation,
                    binding=control.projection(),guard=None if defect=='guard' else lambda:checks.append(True))
            assert checks==[]
            assert (await endpoint.observe.observe(None,fixture.invocation)).state=='running'
            assert fixture.retained_use_count==1
        finally:await fixture.cleanup()
    asyncio.run(scenario())
