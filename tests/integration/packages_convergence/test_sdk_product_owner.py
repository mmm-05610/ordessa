"""Current product owner construction with explicit controlled host-root proof.

One test uses an explicitly issued fixture proof; restart tests use the real DataRootOwner.
Real Profile, HarnessCatalog, AgentManager and SDK records are used; no model.
"""
import asyncio,sqlite3
from types import SimpleNamespace
from pathlib import Path
import pytest
from ordessa_execution_agents.public import ManagerRefused
from ordessa_execution_agents.sdk.interactions import InteractionsRefused
from ordessa_server.composition.root_ownership import _issue_owned_root_binding
from ordessa_server.composition.agent_owner import AgentOwnerInputs,AgentOwnerUnavailable,assemble_agent_owner,_expected_binding
from ordessa_server_product.composition import ServerProductComposition
from test_agent_guarded_bootstrap import setup,PEER
from ordessa_server.composition.root_ownership import DataRootOwner


def test_sdk_product_same_original_sources_and_history_not_reinterpreted(tmp_path):
    async def scenario():
        case=await setup(tmp_path/'fixture',PEER)
        root=tmp_path/'product';(root/'state'/'agent-owner').mkdir(parents=True,mode=0o700)
        store=root/'state'/'core.sqlite';new=root/'state'/'agent-owner'/'agent-instances.sqlite'
        old=new.with_name('operations.sqlite');old.write_bytes(b'historical-unit-journal-sentinel')
        current=[True];binding=_issue_owned_root_binding(root_path=root,store_path=store,child_path=new,validate_current=lambda:current[0])
        calls=[]
        def methods(actual):
            from ordessa_interfaces_contracts import Capability,CapabilityDescriptor,OperationDescriptor,OperationResult,compute_descriptor_digest
            calls.append(actual)
            async def read(request,context):return OperationResult('completed',data={})
            base=CapabilityDescriptor('profiles','owner-test/1',(OperationDescriptor('profiles.read',{'type':'object'},{'type':'object'}),),'')
            return (Capability(CapabilityDescriptor(base.id,base.version,base.operations,compute_descriptor_digest(base)),{'profiles.read':read}),)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,case.authority,methods)
        owner=None
        try:
            owner=assemble_agent_owner(SimpleNamespace(store_path=store),inputs,binding)
            assert owner.manager.records is owner.records
            assert owner.manager.profile_service is case.owner.service
            assert owner.manager.harness_resolver is case.manager.harness_resolver
            assert owner.interactions.records is owner.records
            assert not hasattr(owner,'issuer') and not hasattr(owner,'ports')
            assert old.read_bytes()==b'historical-unit-journal-sentinel' and not store.exists()
            product=ServerProductComposition(agent_owner_inputs=inputs)
            assert product.build_capabilities(owner)[0].descriptor.id=='profiles'
            assert calls==[owner] and calls[0].manager is owner.manager
            owner.revoke();owner.revoke()
            with pytest.raises(ManagerRefused,match='closed database'):owner.records.operation('absent','turn')
            with pytest.raises(AgentOwnerUnavailable):product.build_capabilities(owner)
            reopened=assemble_agent_owner(SimpleNamespace(store_path=store),inputs,binding)
            assert reopened.records.path==str(new) and reopened.records.operation('absent','turn') is None
            reopened.revoke()
            assert old.read_bytes()==b'historical-unit-journal-sentinel'
        finally:
            if owner is not None:owner.revoke()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_sdk_product_forged_root_or_incomplete_ports_refuse_without_files(tmp_path):
    root=tmp_path/'forged';store=root/'state'/'core.sqlite'
    class ForgedRoot:
        def bind_owned_root(self,**kwargs):return SimpleNamespace(validate_for=lambda **k:None)
    with pytest.raises(AgentOwnerUnavailable):_expected_binding(store,ForgedRoot())
    assert not root.exists()


def test_product_original_start_read_projection_and_unknown_restart_never_resends(tmp_path):
    from contextlib import contextmanager
    from ordessa_infrastructure.encoding import canonical_bytes
    from ordessa_server.composition.configuration.model.live_service import create_agent_read_service
    async def scenario():
        # Deliberately withhold the prompt terminal response after one update.
        peer=PEER.replace("        result={'stopReason':","        continue\n        result={'stopReason':")
        assert peer!=PEER
        case=await setup(tmp_path/'fixture',peer)
        root=tmp_path/'product';host_owner=DataRootOwner(root);host_owner.acquire()
        (root/'state'/'agent-owner').mkdir(parents=True,mode=0o700)
        store=root/'state'/'core.sqlite';path=root/'state'/'agent-owner'/'agent-instances.sqlite'
        binding=host_owner.bind_owned_root(root_path=root,store_path=store,child_path=path)
        inputs=AgentOwnerInputs(case.owner.service,case.manager.harness_resolver,case.fixture.resolver,
            case.manager.preparation_resolver,case.authority,case.authority,lambda owner:{})
        owner=None
        try:
            owner=assemble_agent_owner(SimpleNamespace(store_path=store),inputs,binding)
            started=await owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running' and started.session_id
            projection=create_agent_read_service(source=owner.interactions,profiles=owner.profile_service,catalog=owner.harness_catalog)
            desired=projection.read_desired_configuration(started.instance_ref,invocation=case.fixture.invocation)
            assert desired['nativeApplied']=='unobserved'
            assert desired['binding']['instanceRef']==started.instance_ref.projection()
            prompt=owner.interactions.freeze_prompt(started.instance_ref,canonical_bytes({'sessionId':started.session_id,'prompt':[]}))
            class Cut:
                calls=0
                @contextmanager
                def guard_write(self,value,invocation):
                    assert invocation is case.fixture.invocation
                    self.calls+=1;yield
            cut=Cut()
            result=await owner.manager.send_prompt('unknown-product-turn',started.instance_ref,case.fixture.invocation,
                prompt=prompt,interaction_service=owner.interactions,engineering_attempt_ref=None,write_guard=cut,
                deadline=asyncio.get_running_loop().time()+.15)
            assert result.state=='unknown' and cut.calls==1
            before=owner.records._db.execute('SELECT request_id,operation,status,payload FROM operations ORDER BY request_id,operation').fetchall()
            owner.revoke();host_owner.release();case.authority.send=False
            with pytest.raises(Exception):binding.validate_for(root_path=root,store_path=store,child_path=path)
            host_owner=DataRootOwner(root);host_owner.acquire()
            binding=host_owner.bind_owned_root(root_path=root,store_path=store,child_path=path)
            owner=assemble_agent_owner(SimpleNamespace(store_path=store),inputs,binding)
            assert owner.manager.get(case.request.request_id,case.fixture.invocation)==started
            assert await owner.manager.start(case.request,case.endpoint,case.fixture.invocation)==started
            replay=await owner.manager.send_prompt('unknown-product-turn',started.instance_ref,case.fixture.invocation,
                prompt=prompt,interaction_service=owner.interactions,engineering_attempt_ref=None,write_guard=cut,
                deadline=asyncio.get_running_loop().time()+1)
            assert replay==result and replay.state=='unknown' and cut.calls==1
            after=owner.records._db.execute('SELECT request_id,operation,status,payload FROM operations ORDER BY request_id,operation').fetchall()
            assert after==before and case.fixture.retained_use_count==1
            case.authority.read=False
            with pytest.raises(ManagerRefused,match='READ_NOT_AUTHORIZED'):
                owner.manager.get(case.request.request_id,case.fixture.invocation)
            with pytest.raises(InteractionsRefused,match='READ_NOT_AUTHORIZED'):
                create_agent_read_service(source=owner.interactions,profiles=owner.profile_service,catalog=owner.harness_catalog).read_desired_configuration(started.instance_ref,invocation=case.fixture.invocation)
        finally:
            if owner is not None:owner.revoke()
            host_owner.release()
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind',['old-schema','symlink','orphan-sidecar','stale-root'])
def test_product_restart_rejects_foreign_or_unowned_records_before_writes(tmp_path,kind):
    from ordessa_server.composition.agent_owner import preflight_records
    root=tmp_path/kind;(root/'state'/'agent-owner').mkdir(parents=True,mode=0o700)
    store=root/'state'/'core.sqlite';path=root/'state'/'agent-owner'/'agent-instances.sqlite'
    if kind=='old-schema':
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE operations (operation_id TEXT PRIMARY KEY,state TEXT)')
        path.chmod(0o600)
    elif kind=='symlink':
        target=root/'sentinel';target.write_bytes(b'old history');path.symlink_to(target)
    elif kind=='orphan-sidecar':
        Path(str(path)+'-wal').write_bytes(b'orphan unknown bytes');Path(str(path)+'-wal').chmod(0o600)
    binding=_issue_owned_root_binding(root_path=root,store_path=store,child_path=path,validate_current=lambda:kind!='stale-root')
    before={p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    with pytest.raises(AgentOwnerUnavailable):preflight_records(store,binding)
    assert not store.exists()
    assert {p.name:p.read_bytes() for p in path.parent.iterdir() if p.is_file()}==before


def test_product_native_configuration_adapter_uses_original_recorded_owner(tmp_path):
    import json
    from ordessa_infrastructure.encoding import canonical_bytes
    from ordessa_server.composition.configuration.model.live_service import create_model_service
    from ordessa_server.composition.configuration.model.backend import NativeModelServices
    from test_recorded_native_configuration import native_case, request, close

    async def scenario():
        case = await native_case(tmp_path)
        try:
            service = create_model_service(source=case.native)
            expected = request(case)
            frozen = service.freeze(case.started.instance_ref, purpose='apply',
                                    params_bytes=expected.params_bytes)
            assert frozen == expected and service.source.records is case.manager.records
            result = await service.execute(frozen, request_id='product-native-apply',
                invocation=case.fixture.invocation, write_guard=case.native_access,
                deadline=asyncio.get_running_loop().time()+2)
            assert result.state == 'completed'
            assert case.effects.read_text() == 'm2\n'
            assert service.read_operation(result.binding.operation_ref, frozen.input_digest,
                                          invocation=case.fixture.invocation) == result
            assert await service.execute(frozen, request_id='product-native-apply',
                invocation=case.fixture.invocation, write_guard=case.native_access,
                deadline=asyncio.get_running_loop().time()+1) == result
            assert case.effects.read_text() == 'm2\n'
            assert case.native.records._db.execute(
                "SELECT count(*) FROM operations WHERE operation='native-operation'").fetchone() == (1,)
            services = NativeModelServices(roots={}, source=case.native)
            assert services.create_service() is services.create_service()
            assert services.create_service().source is case.native
            assert not hasattr(services, 'restoration')
            with pytest.raises(InteractionsRefused):
                service.read_operation(result.binding.operation_ref, frozen.input_digest,
                                       invocation=object())
            with pytest.raises(InteractionsRefused):
                service.freeze(case.started.instance_ref, purpose='apply', params_bytes=canonical_bytes({
                    **json.loads(frozen.params_bytes), 'sessionId':'foreign'}))
        finally:
            await close(case)
    asyncio.run(scenario())


def test_current_agent_tools_deployment_owns_one_sdk_records_and_releases_root(tmp_path):
    from ordessa_server.composition.agent_tools import AgentToolsDeployment, AgentServiceConfiguration

    async def scenario():
        case = await setup(tmp_path/'fixture', PEER)
        runtime = None
        from contextlib import contextmanager
        from ordessa_execution_agents.capability.instances import build_agent_capability
        class Guard:
            @contextmanager
            def guard_write(self, binding, invocation):
                case.authority.check_send(invocation, binding)
                yield
        def capabilities(owner):
            return (build_agent_capability(owner.manager, owner.interactions,
                invocation_resolver=lambda ctx: case.fixture.invocation, write_guard=Guard()),)
        inputs = AgentOwnerInputs(case.owner.service, case.manager.harness_resolver,
            case.fixture.resolver, case.manager.preparation_resolver,
            case.authority, case.authority, capabilities)
        authenticate = lambda token: None
        deployment = AgentToolsDeployment(agent_owner_inputs=inputs, authenticate=authenticate)
        config = AgentServiceConfiguration(tmp_path/'foreground')
        try:
            runtime = deployment.build_runtime(config)
            assert runtime.authenticate is authenticate
            assert runtime.owner.manager.records is runtime.owner.interactions.records
            assert runtime.owner.profile_service is case.owner.service
            assert not (config.data_root/'state/core.sqlite').exists()
            path = config.data_root/'state/agent-owner/agent-instances.sqlite'
            assert Path(runtime.owner.records.path) == path
            runtime.close()
            runtime.close()
            runtime = deployment.build_runtime(config)
            assert Path(runtime.owner.records.path) == path
            assert runtime.owner.records.operation('absent', 'turn') is None
        finally:
            if runtime is not None:
                runtime.close()
            case.records.close()
            case.owner.close()
            await case.fixture.cleanup()
    asyncio.run(scenario())
