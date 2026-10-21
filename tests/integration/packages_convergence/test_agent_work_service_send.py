"""Real Work/consent/SQLite -> Service -> Agent SDK -> controlled local pipe.

Source review, consent and external workspace authority are explicit controlled
fixtures. The original business predicates, opaque access handoff, original
Agent source and first-frame guard run unchanged. No real model is called.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest
from test_agent_guarded_bootstrap import setup, PEER
from agent_work_business_fixture import build_agent_work_package_approval
from ordessa_agents.public import InteractionService
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.work_context import decode_work_binding
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.changes.agent_dispatch import AgentWorkDispatchBinding
from ordessa_engineering.domain.changes.agent_dispatch_codec import decode_agent_dispatch
from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
from ordessa_engineering.adapters.native_records.agent_selection import OriginalAgentDispatchSelection
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority, AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess
from test_real_source_chain import NOW, PRINCIPAL, SCOPE


@pytest.mark.parametrize('terminal',['completed','unknown'])
def test_actual_service_agent_dispatch_original_write_cut_and_unknown_zero_resend(tmp_path, monkeypatch,terminal):
    async def scenario():
        peer=PEER if terminal=='completed' else PEER.replace("assert method=='session/prompt' and params['sessionId']==session","assert method=='session/prompt' and params['sessionId']==session;sys.exit(0)")
        case=await setup(tmp_path/'native',peer)
        cm=None
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            profile=case.request.profile_revision_ref
            environment=EnvironmentRef(profile.environment_namespace,profile.profile_id,
                                       Digest('sha256',profile.digest.removeprefix('sha256:')))
            # The existing synchronous fixture owns its own Decision event loops.
            # No open UoW crosses this worker boundary: the original library
            # explicitly shares its same guarded connection across fresh UoWs.
            cm=build_agent_work_package_approval(tmp_path/'business',issue_grant=True,environment_ref=environment)
            f=await asyncio.to_thread(cm.__enter__)
            env=f['env'];factory=f['factory']
            wire=WireScope(SCOPE.realm_id,SCOPE.project_id)
            issuer=InstanceAccessAuthority(lambda:'controlled-agent-business-token',principal_id=PRINCIPAL,
                grants=(AccessGrant(wire,('engineering.executions.dispatch','engineering.implementation.reconcile')),),
                legacy_principal=None)
            caller=issuer.authenticate('Bearer controlled-agent-business-token')
            access=EngineeringCommandAccess(issuer)
            class FixedClock(datetime):
                @classmethod
                def now(cls,tz=None):return datetime.fromisoformat(NOW.replace('Z','+00:00'))
            monkeypatch.setattr('ordessa_system_access_bindings.engineering_access.datetime',FixedClock)
            monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now',lambda:NOW)
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            execution=RecordedDispatchExecution(source,env.blobs,
                send_invocation_resolver=lambda *_:case.fixture.invocation,
                read_invocation_resolver=lambda *_:case.fixture.invocation,
                query_factory=lambda _:case.fixture.invocation,endpoint_resolver=case.fixture.resolver)
            service=EngineeringService(factory,access,review_admission=env.admission,blobs=env.blobs,
                conversation_admission=f['service']._packages.approvals._admission(),
                method_guard=env.controls,source_materials=env.materials,source_review_bindings=env.bindings,
                execution_records=execution.records,execution_query_factory=execution.query_factory)
            cuts=[]
            @contextmanager
            def workspace(ctx,package,agent,scopes):
                assert package==f['package_ref'] and agent==started.instance_ref.projection()
                assert tuple(a for a,_ in scopes)==f['authorization'].actions
                assert all(s.repository_scopes[0].repository_id=='test-repository' for _,s in scopes)
                cuts.append(tuple(a for a,_ in scopes));yield
            selection=OriginalAgentDispatchSelection(source,profile,
                read_invocation_resolver=lambda *_:case.fixture.invocation,workspace_scope_guard=workspace)
            from ordessa_server.composition.engineering_dispatch import bind_original_agent_work_dispatch
            from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
            from ordessa_engineering.application.contracts.errors import ApplicationError
            assert execution.records.blob_store is env.blobs
            with pytest.raises(AttributeError):
                execution.records.blob_store=SQLiteBlobStore(env.library)
            # A genuine second BlobStore object over even the same library is
            # not the injected identity of this Service/consumer graph.
            original_blob=execution.blobs
            execution.blobs=SQLiteBlobStore(env.library)
            try:
                with pytest.raises(ApplicationError,match='DISPATCH_OWNER_BINDING_MISMATCH'):
                    bind_original_agent_work_dispatch(service,execution=execution,selection=selection,
                        agent_ref_resolver=lambda *_:{'agent_ref':started.instance_ref.projection(),'session_id':started.session_id})
                assert service._execution_dispatch is None
            finally:execution.blobs=original_blob
            owner=bind_original_agent_work_dispatch(service,execution=execution,selection=selection,
                agent_ref_resolver=lambda *_:{'agent_ref':started.instance_ref.projection(),'session_id':started.session_id},
                implementation_timeout=5)
            with factory.begin(SCOPE,'read') as uow:work=decode_work_binding(uow.workflow.read(f['head']))
            auth=f['authorization']
            with access.admit(caller,wire,'engineering.executions.dispatch',request_id='actual-agent-send',trace_id='actual-agent') as ctx:
                envelope=owner.assemble_declared_work_dispatch(work,auth.action_id,auth.step_id,
                    {'package':asdict(f['package_ref']),'profile':{}},ctx)
                answer=await service._execute_declared_dispatch(envelope,ctx,work=work,
                    action_id=auth.action_id,step_id=auth.step_id)
                assert answer.outcome==terminal and answer.accepted is False
                assert type(answer.value['binding']) is AgentWorkDispatchBinding
                assert owner.dispatch_descriptor.interface_version=='2'
                assert len(cuts)>=3  # both original COMMITs and physical frame
                key=work_dispatch_key(work.work_id,auth.action_id,auth.step_id)
                with factory.begin(SCOPE,'read') as uow:
                    stored=uow.work_dispatch.get(key,auth.step_id,1,SCOPE)
                    binding=decode_agent_dispatch(stored['binding_bytes'])
                    assert stored['dispatch_phase']==terminal and stored['dispatch_version']==2
                    assert binding.agent_ref_bytes==answer.value['binding'].agent_ref_bytes
                    budget=uow.authorization.action_budget(binding.approval_ref)
                    assert all(item['consumed']==1 for item in budget['actions'])
                    assert uow._access.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
                before=case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]
                # Re-entry reads only the durable outcome. Unknown never
                # becomes a fresh source capability or another native turn.
                case.authority.send=False
                replay=await service._execute_declared_dispatch(envelope,ctx,work=work,
                    action_id=auth.action_id,step_id=auth.step_id)
                assert replay.outcome==terminal and replay.accepted is False
                assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==before==1
                assert source._fresh=={}
            # The public stored-format route chooses the Agent Work reader;
            # it has no Unit fallback and cannot obtain another send right.
            from ordessa_server.composition.engineering_dispatch import dispatch_routes_factory
            routes=dispatch_routes_factory(execution=execution,blobs=env.blobs,
                approvals_factory=None,selection=selection,method_guard=env.controls,
                source_materials=env.materials)(factory,access,wire)
            with access.admit(caller,wire,'engineering.implementation.reconcile',
                    request_id='actual-agent-cold',trace_id='actual-agent-cold') as read_ctx:
                cold=routes.invoke('engineering.implementation.reconcile',
                    {'run_id':key,'step_id':auth.step_id,'attempt':1},read_ctx)
                assert cold['phase']==terminal and cold['accepted'] is False
                assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1
        finally:
            if cm is not None:await asyncio.to_thread(cm.__exit__,None,None,None)
            case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
