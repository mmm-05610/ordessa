"""Current Product/root/authority/Profile CLI in an explicitly retained loop.

External setup is the established controlled Profile/catalog/endpoint fixture;
no production trust, complete CLI command matrix or installed wheel is claimed.
"""
import asyncio
import io
import json

from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_server.composition.packages_convergence import build_product_registry_runtime
from ordessa_server.entrypoints.foreground import run
from ordessa_execution_agents.capability.profiles import build_profile_capability
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from test_agent_guarded_bootstrap import setup,PEER


def test_product_foreground_cli_uses_original_context_authority_and_retains_owner(tmp_path):
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        runtime=None;selected=[None];mapped=[]
        scope=Scope('fixture-realm','fixture-project')
        issuer=InstanceAccessAuthority(lambda:'controlled-test-token',principal_id='existing-test-caller',
            grants=(AccessGrant(scope,('profiles.list',)),),legacy_principal=None)
        access=OriginalProfileAccess(issuer,
            caller_resolver=lambda invocation:selected[0] if invocation is case.fixture.invocation else None,
            scope_for_service=lambda service:scope if service is case.owner.service else None,
            principal_scope_for_caller=lambda caller:'principal:'+caller.principal_id)
        def capabilities(owner):
            return (build_profile_capability(owner.profile_service,
                invocation_resolver=lambda ctx:case.fixture.invocation,guard=access.guard),)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,case.authority,capabilities)
        def context(caller,request_id,deadline):
            issuer.verify(caller);selected[0]=caller;mapped.append(request_id)
            return RequestContext({'id':caller.principal_id},request_id,deadline)
        async def invoke(caller,request_id,op='profiles.list'):
            out=io.StringIO();err=io.StringIO()
            code=await run(['call',op,'--input','-','--json','--request-id',request_id],
                runtime=runtime,caller=caller,stdin=io.BytesIO(b'{}'),stdout=out,stderr=err)
            assert err.getvalue()==''
            lines=out.getvalue().splitlines();assert len(lines)==1
            return code,json.loads(lines[0])
        try:
            runtime=build_product_registry_runtime(tmp_path/'product',
                ServerProductComposition(agent_owner_inputs=inputs),issuer,
                context_factory=context,server_id='original-server')
            caller=issuer.authenticate('Bearer controlled-test-token')
            records=runtime.agent_owner.records
            first=await invoke(caller,'first')
            await asyncio.sleep(0)
            second=await invoke(caller,'second')
            assert first[0]==second[0]==0,(first,second)
            assert first[1]['data']==second[1]['data']
            assert first[1]['data']['entries'][0]['profileId']=='peer'
            assert mapped==['first','second'] and runtime.agent_owner.records is records
            assert case.fixture.retained_use_count==1 and not runtime._closed
            assert not (tmp_path/'product/state/core.sqlite').exists()
            issuer.revoke()
            code,refused=await invoke(caller,'revoked')
            assert code!=0 and refused['status']=='refused'
            assert mapped==['first','second']
            assert case.fixture.retained_use_count==1
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_retained_lifecycle_authority_method_rechecks_original_product_root(tmp_path):
    from ordessa_execution_agents.sdk.manager import ManagerRefused
    from ordessa_server.composition.root_ownership import OWNER_MARKER_NAME
    import pytest
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        runtime=None;calls=[]
        def check(invocation,control,*,action):
            case.authority.principal_scope(invocation)
            assert action=='stop'
            calls.append(control)
        case.authority.check_instance_lifecycle=check
        issuer=InstanceAccessAuthority(lambda:'controlled-test-token',principal_id='existing-test-caller',
            grants=(),legacy_principal=None)
        def capabilities(owner):
            # Existing current capability only; no fake lifecycle command.
            return (build_profile_capability(owner.profile_service,
                invocation_resolver=lambda ctx:case.fixture.invocation,
                guard=lambda *a:None),)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,case.authority,capabilities)
        try:
            root=tmp_path/'product'
            runtime=build_product_registry_runtime(root,ServerProductComposition(agent_owner_inputs=inputs),issuer,
                context_factory=lambda caller,rid,deadline:RequestContext({'id':caller.principal_id},rid,deadline),
                server_id='original-server')
            started=await runtime.agent_owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            control,_=runtime.agent_owner.records.instance_control(started.instance_ref)
            method=runtime.agent_owner.manager.lifecycle_authority.check_instance_lifecycle
            method(case.fixture.invocation,control.projection(),action='stop')
            marker=root/OWNER_MARKER_NAME;before=marker.read_bytes()
            try:
                marker.write_bytes(b'changed controlled root marker')
                with pytest.raises(ManagerRefused,match='PRODUCT_ROOT_CHANGED'):
                    method(case.fixture.invocation,control.projection(),action='stop')
                assert len(calls)==1
            finally:marker.write_bytes(before)
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
