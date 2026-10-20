"""Current product root -> explicit Agent/Engineering wire ports -> SDK.

Uses original 2.7.3 Work/consent/source review fixtures and original root proof.
External preparation, source identity, workspace scopes and consent are explicit
controlled test inputs, never production default rights or real model evidence.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
import pytest
from test_agent_guarded_bootstrap import setup, PEER
from test_original_access_handoff import other_thread
from agent_work_business_fixture import build_agent_work_package_approval
from test_real_source_chain import NOW, PRINCIPAL, SCOPE
from ordessa_execution_agents.profiles import encode_revision_ref
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import decode_work_binding
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access import RequestContext
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_wire import EngineeringWireBinding,EngineeringApplicationPorts
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from ordessa_server.composition.agent_bindings.native_access import OriginalNativeAccess
from ordessa_server.composition.agent_bindings.profile_access import OriginalProfileAccess
from ordessa_execution_agents.capability.profiles import build_profile_capability
from ordessa_server.composition.engineering_agent_work_assembly import (
    RootAgentWorkDispatchInputs, root_agent_application_ports_factory)
from ordessa_server.composition.packages_convergence import build_product_registry_runtime
from ordessa_server_product.composition import ServerProductComposition


@pytest.mark.parametrize('mode',['completed','unknown','preparation-revoked'])
def test_default_root_supplies_same_agent_to_explicit_wire_work_ports_and_missing_inputs_refuse(tmp_path,monkeypatch,mode):
    async def scenario():
        line="assert method=='session/prompt' and params['sessionId']==session"
        observed=line+";open('agent-work-prompt-count','a').write('prompt\\n')"
        peer=PEER.replace(line,observed+(';sys.exit(0)' if mode=='unknown' else ''))
        case=await setup(tmp_path/'native',peer);cm=None;runtime=None
        try:
            scope=Scope(SCOPE.realm_id,SCOPE.project_id)
            issuer=InstanceAccessAuthority(lambda:'controlled-root-work-token',principal_id=PRINCIPAL,
                grants=(AccessGrant(scope,('engineering.executions.dispatch','engineering.implementation.reconcile')),),
                legacy_principal=None)
            caller=issuer.authenticate('Bearer controlled-root-work-token')
            native_access=OriginalNativeAccess(case.authority,issuer,
                caller_resolver=lambda inv:caller if inv is case.fixture.invocation else None,
                scope_for_agent=lambda ref:scope,
                principal_scope_for_caller=lambda selected:'principal:existing-test-caller')
            block=[False]
            original_resolver=case.fixture.resolver
            class ResolverBarrier:
                async def resolve(self,ref,invocation):
                    resolved=await original_resolver.resolve(ref,invocation)
                    if block[0]:
                        await other_thread(issuer.revoke)
                    return resolved
            endpoint_resolver=ResolverBarrier()
            profile=case.request.profile_revision_ref
            environment=EnvironmentRef(profile.environment_namespace,profile.profile_id,Digest('sha256',profile.digest[7:]))
            cm=build_agent_work_package_approval(tmp_path/'business',issue_grant=True,environment_ref=environment)
            f=await asyncio.to_thread(cm.__enter__);env=f['env'];factory=f['factory']
            class FixedClock(datetime):
                @classmethod
                def now(cls,tz=None):return datetime.fromisoformat(NOW.replace('Z','+00:00'))
            monkeypatch.setattr('ordessa_system_access_bindings.engineering.datetime',FixedClock)
            monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',lambda:NOW)
            selected=[None];wires=[];ports_seen=[];inputs_seen=[]
            @contextmanager
            def workspace(ctx,package,agent,scopes):
                assert package==f['package_ref'] and agent==selected[0]['agent_ref']
                assert tuple(a for a,_ in scopes)==f['authorization'].actions
                yield
            def base_ports(actual,access,selected_scope):
                assert actual is factory and access.authority is issuer and selected_scope==scope
                return EngineeringApplicationPorts(blobs=env.blobs,method_guard=env.controls,
                    source_materials=env.materials,review_admission=env.admission,
                    conversation_admission=f['service']._packages.approvals._admission())
            def capabilities(owner):
                inputs=RootAgentWorkDispatchInputs(issuer,profile,
                    lambda *_:case.fixture.invocation,lambda *_:case.fixture.invocation,
                    lambda _:case.fixture.invocation,lambda *_:selected[0],workspace,5)
                factory_ports=root_agent_application_ports_factory(owner=owner,inputs=inputs,base_ports_factory=base_ports)
                binding=EngineeringWireBinding(factory,issuer,scope=scope,application_ports_factory=factory_ports)
                wires.append(binding);ports_seen.append(factory_ports);inputs_seen.append(inputs)
                profile_access=OriginalProfileAccess(issuer,
                    caller_resolver=lambda inv:caller if inv is case.fixture.invocation else None,
                    scope_for_service=lambda service:scope if service is owner.profile_service else None,
                    principal_scope_for_caller=lambda value:'principal:existing-test-caller')
                return (build_profile_capability(owner.profile_service,
                    invocation_resolver=lambda ctx:case.fixture.invocation,guard=profile_access.guard),)
            product=ServerProductComposition(agent_owner_inputs=AgentOwnerInputs(
                case.owner.service,case.manager.harness_resolver,endpoint_resolver,
                case.manager.preparation_resolver,case.authority,native_access,capabilities))
            runtime=build_product_registry_runtime(tmp_path/'product',product,issuer,
                context_factory=lambda caller,request,deadline:RequestContext({'id':caller.principal_id},request,deadline),
                server_id='controlled-existing-server')
            owner=runtime.agent_owner;wire=wires[0]
            assert owner.records is owner.interactions.records is owner.manager.records
            assert wire.execution_dispatch.dispatch.execution.source is owner.interactions
            assert wire.ports.submission_report_source is None
            assert wire.ports.execution_records is None and wire.ports.execution_query_factory is None
            assert wire.ports.agent_execution_records is wire.execution_dispatch.records
            capabilities_value=wire.capabilities()
            assert capabilities_value['supports']['dispatch'] is True
            assert 'engineering.submissions.record_report' not in capabilities_value['supported_methods']
            assert any(c['operation']=='engineering.executions.dispatch' and c['interface_version']=='2'
                       for c in capabilities_value['commands'])
            # Missing real external ports refuse before base business construction
            # or turn allocation. They are never inferred from the root or Unit.
            for name,code in (
                ('send_invocation_resolver','AGENT_WORK_SEND_INVOCATION_UNBOUND'),
                ('read_invocation_resolver','AGENT_WORK_READ_INVOCATION_UNBOUND'),
                ('query_invocation_resolver','AGENT_WORK_QUERY_INVOCATION_UNBOUND'),
                ('agent_ref_resolver','AGENT_WORK_EXISTING_INSTANCE_UNBOUND'),
                ('workspace_scope_guard','AGENT_WORK_WORKSPACE_AUTHORITY_UNBOUND')):
                with pytest.raises(ApplicationError,match=code):
                    root_agent_application_ports_factory(owner=owner,inputs=replace(inputs_seen[0],**{name:None}),
                        base_ports_factory=lambda *a,**kw:pytest.fail('missing port entered business assembly'))
            assert owner.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==0
            started=await owner.manager.start(case.request,case.endpoint,case.fixture.invocation)
            selected[0]={'agent_ref':started.instance_ref.projection(),'session_id':started.session_id}
            assert case.fixture.retained_use_count==1
            auth=f['authorization']
            with factory.begin(SCOPE,'read') as uow:work=decode_work_binding(uow.workflow.read(f['head']))
            with wire.access.admit(caller,scope,'engineering.executions.dispatch',request_id='root-work-send',trace_id='root-work') as ctx:
                envelope=wire.execution_dispatch.assemble_declared_work_dispatch(work,auth.action_id,auth.step_id,
                    {'package':asdict(f['package_ref']),'profile':encode_revision_ref(profile)},ctx)
                if mode=='preparation-revoked':
                    block[0]=True
                    with pytest.raises(ApplicationError,match='ACCESS_DENIED'):
                        await wire.service._execute_declared_dispatch(envelope,ctx,work=work,
                            action_id=auth.action_id,step_id=auth.step_id)
                    with factory.begin(SCOPE,'read') as uow:
                        assert uow._access.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()[0]==0
                        assert uow._access.execute('SELECT count(*) FROM work_step_log').fetchone()[0]==0
                    assert owner.interactions._fresh=={}
                    assert owner.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
                    assert case.fixture.retained_use_count==1
                    assert not (Path(case.prepared.native_working_directory)/'agent-work-prompt-count').exists()
                    return
                answer=await wire.service._execute_declared_dispatch(envelope,ctx,work=work,
                    action_id=auth.action_id,step_id=auth.step_id)
                assert answer.outcome==mode and answer.accepted is False
                case.authority.send=False
                replay=await wire.service._execute_declared_dispatch(envelope,ctx,work=work,
                    action_id=auth.action_id,step_id=auth.step_id)
                assert replay.outcome==mode
                assert (Path(case.prepared.native_working_directory)/'agent-work-prompt-count').read_text()=='prompt\n'
                assert owner.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==0
            assert not (tmp_path/'product/state/core.sqlite').exists()
            runtime.close();runtime=None
            with pytest.raises(ApplicationError,match='AGENT_WORK_ROOT_OWNER_UNAVAILABLE'):
                root_agent_application_ports_factory(owner=owner,inputs=inputs_seen[0],base_ports_factory=base_ports)
        finally:
            if runtime is not None:runtime.close()
            if cm is not None:await asyncio.to_thread(cm.__exit__,None,None,None)
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
