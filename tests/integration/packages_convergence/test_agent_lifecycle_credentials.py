"""Original instance credential rotation across preflight and actual OS cut."""
import asyncio
from types import SimpleNamespace

import pytest

from ordessa_agents.sdk.manager import ManagerRefused
from ordessa_environments import EnvironmentRefused,ProcessRequest
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_agents.bridges.environment_endpoints import EnvironmentEndpointResolver
from test_agent_guarded_bootstrap import setup


def test_actual_credential_rotation_refuses_old_cut_and_allows_new_same_owner(tmp_path,monkeypatch):
    async def scenario():
        case=await setup(tmp_path)
        credential=['controlled-original-credential']
        scope=Scope('fixture-realm','fixture-project')
        issuer=InstanceAccessAuthority(lambda:credential[0],principal_id='existing-test-caller',
            grants=(AccessGrant(scope,('agents.stop','agents.get')),),legacy_principal=None)
        issued=[];checks=[];signals=[];rotate=[True]
        def issue():
            caller=issuer.authenticate('Bearer '+credential[0])
            invocation=SimpleNamespace(owner_scope=case.fixture.invocation.owner_scope)
            issued.append((invocation,caller));return invocation
        def original_caller(invocation):
            for actual,caller in issued:
                if invocation is actual:
                    issuer.verify(caller);return caller
            raise ManagerRefused('FORGED_INVOCATION')
        class Authority:
            def guard_instance_lifecycle(self,invocation,control,*,action):
                return issuer.guard(original_caller(invocation),scope,'agents.'+action)
            def check_instance_lifecycle(self,invocation,control,*,action):
                checks.append(action)
                if len(checks)==2 and rotate[0]:
                    credential[0]='controlled-rotated-credential';rotate[0]=False
                with issuer.guard(original_caller(invocation),scope,'agents.'+action):
                    assert control['principalScope']=='principal:existing-test-caller'
            def check_read_instance(self,invocation,instance_id):
                with issuer.guard(original_caller(invocation),scope,'agents.get'):
                    assert instance_id==started.instance_id
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            case.manager.lifecycle_authority=Authority()
            def environment_caller(invocation):
                original_caller(invocation)
                return case.fixture.invocation  # SAME existing owner/capabilities
            case.manager.resolver=EnvironmentEndpointResolver(case.fixture._endpoints,invocation_resolver=environment_caller,
                process_request_factory=ProcessRequest.build,refusal=EnvironmentRefused)
            raw=next(iter(case.fixture._manager._owned_process_handles.values()))._target
            original=raw.popen.terminate
            def terminate():signals.append('signal');return original()
            monkeypatch.setattr(raw.popen,'terminate',terminate)
            old=issue()
            refused=await case.manager.stop('old-cut',started.instance_ref,old)
            assert refused.status=='refused' and signals==[] and raw.observe().state=='running'
            control,_=case.records.instance_control(started.instance_ref)
            assert control.writer_epoch==1 and control.active_operation_ref is None
            issuer.replace_grants((AccessGrant(scope,('agents.get',)),))
            readonly=issue()
            assert await case.manager.stop('old-cut',started.instance_ref,readonly)==refused
            before=case.records._db.total_changes
            with pytest.raises(ManagerRefused,match='LIFECYCLE_AUTHORITY_REFUSED'):
                await case.manager.stop('no-write-grant',started.instance_ref,readonly)
            assert case.records._db.total_changes==before and signals==[]
            issuer.replace_grants((AccessGrant(scope,('agents.stop','agents.get')),))
            fresh=issue()
            done=await case.manager.stop('fresh-cut',started.instance_ref,fresh)
            assert done.status=='completed' and done.facts['cancellation']=='requested' and signals==['signal']
            assert done.operation_ref.startswith('environment-operation/')
            assert (await case.fixture.wait_exit(started.process_endpoint_ref)).state=='exited'
            observed=await case.manager.reconcile(started.instance_ref,fresh)
            assert observed.state=='exited' and case.records.instance_control(started.instance_ref)[0].association=='stopped'
            assert case.fixture.retained_use_count==1 and signals==['signal']
            forged=SimpleNamespace(owner_scope=fresh.owner_scope)
            with pytest.raises(ManagerRefused):await case.manager.reconcile(started.instance_ref,forged)
            assert signals==['signal']
        finally:
            monkeypatch.undo()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
