"""Actual FastAPI/ASGI boundary + original controlled native owner, no sockets/model."""
import asyncio
from types import SimpleNamespace
import httpx
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_server.composition.registry_runtime import RegistryRuntime
from ordessa_server.composition.packages_convergence import build_agent_registry_host
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_interfaces.http.registry import create_registry_app
from native_case_fixture import native_case,request,close,wait_completed


def test_http_original_authority_zero_write_native_allow_and_cold_query(tmp_path):
    async def scenario():
        case=await native_case(tmp_path)
        try:
            profile=OriginalProfileAccess(case.issuer,caller_resolver=lambda inv:case.caller[0] if inv is case.fixture.invocation else None,
                scope_for_service=lambda service:case.scope,principal_scope_for_caller=lambda value:'principal:'+value.principal_id)
            owner=SimpleNamespace(manager=case.manager,records=case.records,interactions=case.native,profile_service=case.owner.service)
            host=build_agent_registry_host(owner,invocation_resolver=lambda context:case.fixture.invocation,
                native_write_guard=case.native_access,profile_guard=profile.guard)
            def context(caller,identity,deadline):
                case.issuer.verify(caller);case.caller[0]=caller
                return RequestContext({'id':caller.principal_id},identity,deadline)
            runtime=RegistryRuntime(host,case.issuer,context_factory=context,server_id='existing-http-fixture')
            app=create_registry_app(runtime)
            frozen=request(case)
            body={'jsonrpc':'2.0','id':'http-native','method':'operations.call',
                'params':{'operationId':'agents.native.request','input':frozen.projection()}}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
                changes=case.records._db.total_changes
                denied=await client.post('/wire/v1/operations.call',json=body)
                assert denied.status_code==401 and not case.effects.exists() and case.records._db.total_changes==changes
                blocked=await client.post('/wire/v1/operations.call',json=body,headers={'Host':'foreign.invalid'})
                assert blocked.status_code==403 and not case.effects.exists() and case.records._db.total_changes==changes
                headers={'Authorization':'Bearer synthetic-native-token'}
                applied=await client.post('/wire/v1/operations.call',json=body,headers=headers)
                assert applied.status_code==200
                value=applied.json()['result'];assert value['status']=='accepted' and value['data']['state']=='accepted'
                operation_ref=value['data']['operationRef']

                async def invoke(op,data,identity):
                    envelope={'jsonrpc':'2.0','id':identity,'method':'operations.call',
                              'params':{'operationId':op,'input':data}}
                    response=await client.post('/wire/v1/operations.call',json=envelope,headers=headers)
                    return response.json()['result']

                completed=await wait_completed(case,invoke,value['data'])
                assert completed['state']=='completed' and completed['response']['result']['ok'] is True
                case.issuer.replace_grants((AccessGrant(case.scope,('agents.operations.read','agents.native.query')),))
                query={'jsonrpc':'2.0','id':'cold','method':'operations.call','params':{'operationId':'agents.native.query',
                    'input':{'operationRef':operation_ref}}}
                cold=await client.post('/wire/v1/operations.call',json=query,headers=headers)
                assert cold.json()['result']['data']==completed
                forbidden={**body,'id':'new-refused'};changes=case.records._db.total_changes
                no_write=await client.post('/wire/v1/operations.call',json=forbidden,headers=headers)
                assert no_write.json()['result']['status']=='refused' and case.records._db.total_changes==changes
        finally:await close(case)
    asyncio.run(scenario())
