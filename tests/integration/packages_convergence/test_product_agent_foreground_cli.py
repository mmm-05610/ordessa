"""Actual current Product Agent start/prompt/query/get through foreground CLI.

Caller supplies an explicit fixture authority and original Profile/catalog/
endpoint sources. No production policy, model, hidden daemon or Use acquisition
is provided by the Agent capability adapter.
"""
import asyncio
from contextlib import contextmanager
import io
import json
from pathlib import Path

from ordessa_agents.sdk.interactions import TurnRef
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_agents.capability.instances import build_agent_capability
from ordessa_server.composition.packages_convergence import build_product_registry_runtime
from ordessa_server.entrypoints.foreground import run
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from test_agent_guarded_bootstrap import setup,PEER


def test_current_product_cli_start_get_prompt_query_uses_one_original_owner(tmp_path):
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        runtime=None;callers=[None];cuts=[];started=None
        scope=Scope('fixture-realm','fixture-project')
        operations=('agents.start','agents.get','agents.prompt','agents.query')
        issuer=InstanceAccessAuthority(lambda:'controlled-test-token',principal_id='existing-test-caller',
            grants=(AccessGrant(scope,operations),),legacy_principal=None)
        original_start=case.authority.check_start
        original_send=case.authority.check_send
        # Explicit fixture binding to ORIGINAL live identity/grants, not DTO auth.
        def check_start(invocation,request,descriptor):
            with issuer.guard(callers[0],scope,'agents.start'):
                return original_start(invocation,request,descriptor)
        def check_send(invocation,binding):
            with issuer.guard(callers[0],scope,'agents.prompt'):
                return original_send(invocation,binding)
        case.authority.check_start=check_start;case.authority.check_send=check_send
        class Guard:
            @contextmanager
            def guard_write(self,binding,invocation):
                with issuer.guard(callers[0],scope,'agents.prompt'):
                    assert invocation is case.fixture.invocation
                    cuts.append(binding.agent_operation_ref)
                    yield
        def capabilities(owner):
            return (build_agent_capability(owner.manager,owner.interactions,
                invocation_resolver=lambda ctx:case.fixture.invocation,write_guard=Guard()),)
        def context(caller,rid,deadline):
            issuer.verify(caller);callers[0]=caller
            return RequestContext({'id':caller.principal_id},rid,deadline)
        async def invoke(op,value,identity):
            out=io.StringIO();err=io.StringIO()
            code=await run(['call',op,'--input','-','--json','--request-id',identity],
                runtime=runtime,caller=caller,stdin=io.BytesIO(json.dumps(value).encode()),stdout=out,stderr=err)
            assert err.getvalue()==''
            lines=out.getvalue().splitlines();assert len(lines)==1
            return code,json.loads(lines[0])
        try:
            inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
                case.manager.preparation_resolver,case.authority,case.authority,capabilities)
            runtime=build_product_registry_runtime(tmp_path/'product',ServerProductComposition(agent_owner_inputs=inputs),issuer,
                context_factory=context,server_id='original-server')
            caller=issuer.authenticate('Bearer controlled-test-token')
            raw=case.request.projection();raw.pop('requestId')
            code,result=await invoke('agents.start',raw,case.request.request_id)
            assert code==0 and result['data']['state']=='running',result
            started=result['data'];ref=started['instanceRef']
            assert ref['instanceId']==started['instanceId']
            code,replayed=await invoke('agents.get',{'startRequestId':case.request.request_id},'get')
            assert code==0 and replayed['data']==started
            code,prompt=await invoke('agents.prompt',{'instanceRef':ref,
                'params':{'sessionId':started['sessionId'],'prompt':[]},
                'engineeringAttemptRef':'foreground-attempt'},'prompt')
            assert code==0 and prompt['data']['state']=='completed',prompt
            turn=TurnRef.decode(prompt['data']['turnRef'])
            query=runtime.agent_owner.interactions.turn_query(turn,prompt['data']['inputDigest'])
            code,observed=await invoke('agents.query',{'query':query.projection()},'query')
            assert code==0 and observed['data']==prompt['data'] and len(cuts)==1
            assert runtime.agent_owner.manager.records is runtime.agent_owner.interactions.records
            assert case.fixture.retained_use_count==1
            assert not (tmp_path/'product/state/core.sqlite').exists()
            # Public identity/Use lookalikes never reach a second resource owner.
            code,refused=await invoke('agents.stop',{'instanceRef':{'unitId':'old'}},'old-unit')
            assert code!=0 and refused['status']=='refused'
            assert case.fixture.retained_use_count==1
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
