"""Current owner/registry cut; no legacy RPC/client equivalence claim."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ordessa_interfaces.system_access import CapabilityHost,build_registry
from ordessa_interfaces.system_access.operations import RequestContext
from ordessa_agents.public import ProfileService
from ordessa_agents.sdk.contract_catalog import contract_catalog,contract_catalog_digest
from ordessa_agents.capability.native import build_native_capability
from native_case_fixture import native_case,request,close,wait_completed
from test_agent_guarded_bootstrap import setup,PEER

ROOT=Path(__file__).parents[3]


def test_registry_native_actual_original_receiver_and_empty_grants(tmp_path):
    async def scenario():
        for allowed in (True,False):
            case=await native_case(tmp_path/str(allowed),grants=allowed)
            try:
                capability=build_native_capability(case.native,invocation_resolver=lambda ctx:case.fixture.invocation,
                    write_guard=case.native_access)
                host=CapabilityHost(build_registry([capability]),('agents',))
                call=request(case)
                context=RequestContext({'kind':'controlled-original-caller'},'registry-native',asyncio.get_running_loop().time()+5)
                result=await host.call('agents.native.request',call.projection(),context)
                if allowed:
                    assert result.status=='accepted' and result.data['state']=='accepted'
                    completed=await wait_completed(case,
                        lambda op,data,identity: host.call(op,data,context),result.data)
                    assert completed['state']=='completed'
                    assert case.effects.exists() and 'ordessa/probe' in case.effects.read_text()
                    before=case.records._db.total_changes
                    cold=await host.call('agents.native.query',{'operationRef':result.data['operationRef']},context)
                    assert cold.status=='completed' and cold.data==completed
                    assert before==case.records._db.total_changes
                    bad=await host.call('agents.native.request',{**call.projection(),'requestId':'bad-1',
                        'nativeMessage':{'params':{}}},context)
                    assert bad.status=='refused'
                else:
                    assert result.status=='refused' and not case.effects.exists()
                    assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='native-request'").fetchone()==(0,)
            finally:await close(case)
    asyncio.run(scenario())


def test_current_schema_catalog_is_data_only_detached_and_not_runtime_v3():
    value=contract_catalog()
    assert value['schemaVersion']=='agent-sdk-contract-catalog/1'
    assert value['profileFormat']['profileRef']['properties']['manifestRevision']['minimum']==1
    from ordessa_agents.sdk.native_schemas import KINDS
    assert set(value['native'])==set(KINDS)
    assert 'agent-native-operation-ref/2' in json.dumps(value)
    assert 'RuntimeProvider' not in json.dumps(value) and 'agent-assembly/3' not in json.dumps(value)
    digest=contract_catalog_digest()
    value['profileFormat']['profileRef']['properties'].clear()
    assert contract_catalog()['profileFormat']['profileRef']['properties'] and contract_catalog_digest()==digest


def test_codex_probe_uses_real_compiler_without_old_graph_or_environment():
    path=ROOT/'tooling/checks/decision-runtime/evaluation/codex_flow_probe.py'
    spec=importlib.util.spec_from_file_location('current_compile_probe',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    value=module.compile_plan({'model':'controlled-model','offline':True})
    assert value['compiled']=={'thread_params':{'model':'controlled-model'},'args':[],'deferred':{'offline':True}}
    assert value['executionObserved'] is False and value['engineeringAccepted'] is False
    with pytest.raises(ValueError):module.compile_plan({'invented_parameter':True})


def test_foreground_deployment_uses_original_product_owner_and_root(tmp_path):
    from ordessa_server.composition.agent_tools import AgentToolsDeployment,AgentServiceConfiguration
    from ordessa_server.composition.agent_owner import AgentOwnerInputs
    from ordessa_interfaces_contracts import Capability,CapabilityDescriptor,OperationDescriptor,OperationResult,compute_descriptor_digest
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        runtime=None
        try:
            def capabilities(owner):
                async def read(request,context):
                    # Actual original ProfileService and admission, not fixture result.
                    return OperationResult('completed',data={'entries':len(owner.profile_service.list())})
                base=CapabilityDescriptor('agents','controlled-profile-read/1',(
                    OperationDescriptor('agents.profiles.list',{'type':'object','additionalProperties':False},{'type':'object'}),),'')
                return (Capability(CapabilityDescriptor(base.id,base.version,base.operations,compute_descriptor_digest(base)),{'agents.profiles.list':read}),)
            inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
                case.manager.preparation_resolver,case.authority,case.authority,capabilities)
            root=tmp_path/'deployment'
            runtime=AgentToolsDeployment(agent_owner_inputs=inputs,authenticate=lambda command:{}).build_runtime(AgentServiceConfiguration(root))
            assert runtime.owner.records is runtime.owner.manager.records
            assert type(runtime.owner.profile_service) is ProfileService
            result=await runtime.host.call('agents.profiles.list',{},RequestContext({},'actual-read'))
            assert result.status=='completed' and result.data['entries']==1
            assert (root/'state'/'agent-owner'/'agent-instances.sqlite').exists()
            assert not (root/'state'/'core.sqlite').exists()
            started=await runtime.owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running'
            runtime.close();runtime.close()
            # Real root lock can be reacquired and the SAME SDK records reopened.
            runtime=AgentToolsDeployment(agent_owner_inputs=inputs,authenticate=lambda command:{}).build_runtime(AgentServiceConfiguration(root))
            assert runtime.owner.manager.get(case.request.request_id,case.fixture.invocation)==started
        finally:
            if runtime is not None:runtime.close()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
