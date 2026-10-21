"""Formal product/root/capability pipeline without old Environment/Core state."""
import asyncio,sys,json
from pathlib import Path
import pytest
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_server.composition.packages_convergence import build_product_registry_runtime
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.agent_owner import AgentOwnerInputs,AgentOwnerUnavailable
from ordessa_agents.capability.profiles import build_profile_capability
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from test_agent_guarded_bootstrap import setup,PEER


def test_missing_product_bindings_refuses_before_root_or_core_creation(tmp_path):
    root=tmp_path/'unbound'
    issuer=InstanceAccessAuthority(lambda:'controlled-product-test-token',principal_id='fixture',grants=(),legacy_principal=None)
    with pytest.raises(AgentOwnerUnavailable):
        build_product_registry_runtime(root,ServerProductComposition(),issuer,
            context_factory=lambda *args:None,server_id='existing-server')
    assert not root.exists()


def test_product_original_root_records_profile_capability_and_empty_grants(tmp_path):
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        root=tmp_path/'product';runtime=None;caller=[None]
        scope=Scope('fixture-realm','fixture-project')
        issuer=InstanceAccessAuthority(lambda:'controlled-product-test-token',principal_id='existing-test-caller',
            grants=(AccessGrant(scope,('agents.profiles.list',)),),legacy_principal=None)
        access=OriginalProfileAccess(issuer,caller_resolver=lambda invocation:caller[0] if invocation is case.fixture.invocation else None,
            scope_for_service=lambda service:scope if service is case.owner.service else None,
            principal_scope_for_caller=lambda value:'principal:'+value.principal_id)
        seen=[]
        def capabilities(owner):
            seen.append(owner)
            return (build_profile_capability(owner.profile_service,invocation_resolver=lambda ctx:case.fixture.invocation,guard=access.guard),)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,case.authority,capabilities)
        product=ServerProductComposition(agent_owner_inputs=inputs)
        def context(principal,request_id,deadline):
            issuer.verify(principal);caller[0]=principal
            return RequestContext({'id':principal.principal_id},request_id,deadline)
        try:
            runtime=build_product_registry_runtime(root,product,issuer,context_factory=context,server_id='existing-server')
            assert seen==[runtime.agent_owner]
            assert runtime.agent_owner.manager.records is runtime.agent_owner.records
            assert runtime.agent_owner.interactions.records is runtime.agent_owner.records
            assert not (root/'state'/'core.sqlite').exists()
            assert (root/'state'/'agent-owner'/'agent-instances.sqlite').is_file()
            body={'jsonrpc':'2.0','id':'list','method':'operations.call','params':{'operationId':'agents.profiles.list','input':{}}}
            answer=await runtime.wire(body,'Bearer controlled-product-test-token')
            assert answer['result']['status']=='completed' and answer['result']['data']['entries'][0]['profileId']=='peer'
            before=case.owner.service._profile_store._conn.total_changes
            issuer.replace_grants(())
            refused=await runtime.wire({**body,'id':'no-grant'},'Bearer controlled-product-test-token')
            assert refused['result']['status']=='refused' and before==case.owner.service._profile_store._conn.total_changes
            runtime.close();runtime.close()
            with pytest.raises(Exception):runtime.agent_owner.records.operation('absent','turn')
            runtime=build_product_registry_runtime(root,product,issuer,context_factory=context,server_id='existing-server')
            assert runtime.agent_owner.records.operation('absent','turn') is None
            assert not (root/'state'/'core.sqlite').exists() and case.fixture.retained_use_count==1
            assert not any(name=='pacthold' or name.startswith('pacthold.') for name in sys.modules)
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('lose_root',[False,True])
def test_product_root_native_original_receiver_and_cold_reopen_no_second_use(tmp_path,lose_root):
    import hashlib,shutil
    from ordessa_server.composition.agent_bindings.native_access import OriginalNativeAccess,NATIVE_READ,NATIVE_CAPABILITIES
    from ordessa_agents.capability.native import build_native_capability
    from ordessa_infrastructure.encoding import canonical_bytes
    from test_recorded_native_configuration import PEER as NATIVE_PEER,OPTIONS,METHODS,ROOT
    async def scenario():
        module=(ROOT/'packages/execution/agents/src/ordessa_agents/harness/configuration/acp/operation.mjs').as_uri()
        peer=NATIVE_PEER.replace('MODULE',json.dumps(module)).replace('OPTIONS',json.dumps(OPTIONS))
        case=await setup(tmp_path/'fixture',peer,runner=(shutil.which('node'),),peer_name='peer.mjs')
        root=tmp_path/'product-native';runtime=None;caller=[None];started=[None]
        scope=Scope('fixture-realm','fixture-project')
        issuer=InstanceAccessAuthority(lambda:'controlled-product-test-token',principal_id='existing-test-caller',
            grants=(AccessGrant(scope,(NATIVE_READ,*NATIVE_CAPABILITIES.values())),),legacy_principal=None)
        access=OriginalNativeAccess(case.authority,issuer,caller_resolver=lambda invocation:caller[0] if invocation is case.fixture.invocation else None,
            scope_for_agent=lambda ref:scope if started[0] and ref==started[0].instance_ref else None,
            principal_scope_for_caller=lambda p:'principal:'+p.principal_id)
        from contextlib import contextmanager
        from ordessa_server.bootstrap.data_root import OWNER_MARKER_NAME
        marker=root/OWNER_MARKER_NAME;original_marker=[None]
        class Cut:
            @contextmanager
            def guard_write(self,binding,invocation):
                with access.guard_write(binding,invocation):
                    if lose_root:
                        original_marker[0]=marker.read_bytes();marker.write_bytes(b'invalid controlled root marker')
                    yield
        def capabilities(owner):
            return (build_native_capability(owner.interactions,invocation_resolver=lambda ctx:case.fixture.invocation,write_guard=Cut()),)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,access,capabilities)
        product=ServerProductComposition(agent_owner_inputs=inputs)
        def context(principal,request_id,deadline):
            issuer.verify(principal);caller[0]=principal
            return RequestContext({'id':principal.principal_id},request_id,deadline)
        async def call(op,data,identity):
            return (await runtime.wire({'jsonrpc':'2.0','id':identity,'method':'operations.call',
                'params':{'operationId':op,'input':data}},'Bearer controlled-product-test-token'))['result']
        try:
            runtime=build_product_registry_runtime(root,product,issuer,context_factory=context,server_id='existing-server')
            started[0]=await runtime.agent_owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started[0].state=='running'
            frozen=runtime.agent_owner.interactions.freeze_native_request(started[0].instance_ref,purpose='apply',method=METHODS['apply'],
                params_bytes=canonical_bytes({'sessionId':started[0].session_id,'operationId':'original-native-configuration',
                    'expectedGeneration':'generation-1','expectedConfigDigest':hashlib.sha256(canonical_bytes(OPTIONS)).hexdigest(),
                    'configId':'model','value':'m2'}))
            value=await call('agents.native.recorded',{'request':frozen.projection()},'native')
            effects=Path(case.prepared.native_working_directory)/'native-effects.log'
            if lose_root:
                assert value['status']=='refused' and value['error']['code']=='AUTHORITY_UNAVAILABLE' and not effects.exists()
                marker.write_bytes(original_marker[0])
                again=await call('agents.native.recorded',{'request':frozen.projection()},'native')
                assert again['data']['state']=='failed' and not effects.exists()
                repeated=await call('agents.native.recorded',{'request':frozen.projection()},'native')
                assert repeated['data']==again['data'] and not effects.exists()
                assert case.fixture.retained_use_count==1
                return
            assert value['status']=='completed' and value['data']['state']=='completed'
            assert effects.read_text()=='m2\n'
            runtime.close()
            issuer.replace_grants((AccessGrant(scope,(NATIVE_READ,)),))
            runtime=build_product_registry_runtime(root,product,issuer,context_factory=context,server_id='existing-server')
            rows=runtime.agent_owner.records._db.total_changes
            replay=await call('agents.native.recorded',{'request':frozen.projection()},'native')
            assert replay['data']==value['data'] and runtime.agent_owner.records._db.total_changes==rows
            cold=await call('agents.native.query',{'operationRef':value['data']['binding']['operationRef'],
                'expectedInputDigest':frozen.input_digest},'cold')
            assert cold['data']==value['data'] and effects.read_text()=='m2\n'
            assert case.fixture.retained_use_count==1 and not (root/'state'/'core.sqlite').exists()
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
