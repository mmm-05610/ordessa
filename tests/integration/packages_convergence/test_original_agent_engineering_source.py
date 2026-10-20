"""Original Agent Records -> Engineering SQLite bytes -> actual endpoint pipe.

The prepared profile/source and business binding are explicit controlled fixtures;
this qualifies original claim/query/protocol-response/capture and the physical row cut, not Profile
admission, session bootstrap or the original approval/method fence.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,threading,sys

import pytest
from endpoint_fixture import LocalEndpointFixture
from ordessa_execution_agents.sdk.manager import AgentManager,Records
from ordessa_execution_agents.sdk.interactions import InteractionService,BindingProvenance,InteractionsRefused
from ordessa_execution_agents.sdk.instances import AgentInstanceRef
from ordessa_execution_agents.sdk.prepare import canonical_digest
from ordessa_execution_agents.profiles import ProfileRevisionRef,encode_revision_ref
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.common.models.values import Digest


# A real long-lived controlled ACP peer over its owned pipes. It never calls a
# model. The original session/profile provenance below remains an explicit test
# fixture; this peer qualifies prompt framing/response/capture, not bootstrap.
ACP_PEER = """import sys,json,hashlib
request=json.loads(sys.stdin.buffer.readline())
params=request['params']
print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':params['sessionId'],'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'original-local-peer'}}}}),flush=True)
proof=hashlib.sha256(json.dumps(params,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'stopReason':'end_turn','_meta':{'paramsDigest':proof,'method':request['method']}}}),flush=True)
sys.stdin.buffer.readline()
"""


class ExternalAuthority:
    def __init__(self,sender):
        self.sender=sender;self.reader=object();self.read=True;self.send=True
    def principal_scope(self,invocation):
        if invocation is not self.sender and invocation is not self.reader:raise InteractionsRefused('FORGED_INVOCATION')
        return 'principal:existing-test-caller'
    def check_read_turn(self,invocation,query):
        self.principal_scope(invocation)
        if not self.read:raise InteractionsRefused('READ_NOT_AUTHORIZED')
    def check_read_binding(self,invocation,instance):self.check_read_turn(invocation,None)
    def check_send(self,invocation,binding):
        self.principal_scope(invocation)
        if invocation is not self.sender or not self.send:raise InteractionsRefused('SEND_NOT_AUTHORIZED')


# This fixture is the frozen V1 historical input from a23, not a current Work
# dispatch projection. Current binding_version/work/subject remain UNMAPPED;
# these tests do not qualify that newer recipe or its business write checks.
FROZEN_V1_FIELDS = frozenset((
    'scope', 'run_id', 'step_id', 'attempt', 'fence', 'package_ref', 'approval_ref',
    'intent_digest', 'control_version', 'action_instances', 'unit_ref_bytes',
    'execution_operation_ref', 'prompt_ref', 'prompt_input_digest',
    'expected_query_digest', 'required_results', 'digest',
))



def original_provenance(instance,process_ref,plan_digest):
    profile=ProfileRevisionRef('existing-namespace','controlled-profile',1,'sha256:'+'b'*64)
    value={'schemaVersion':'agent-binding-provenance/1','instanceRef':instance.projection(),
        'revision':1,'profileRef':encode_revision_ref(profile),'preparedPlanDigest':plan_digest,
        'endpointRef':process_ref.projection(),'directoryBindingDigest':'sha256:'+'c'*64,
        'sourceRevision':'controlled-source','configurationRefs':[],'capturedAt':'2026-10-19T00:00:00Z'}
    return BindingProvenance.decode({**value,'observationDigest':canonical_digest(value)})


def seed_controlled_instance(records,process_ref,plan_digest):
    # Existing explicit preparation fixture, now carrying its full original
    # immutable material. This still does NOT qualify Profile/bootstrap.
    from ordessa_execution_agents.instances.contracts import InstanceBindingMaterial
    from ordessa_execution_agents.sdk.harness import HarnessDescriptor
    profile=ProfileRevisionRef('existing-namespace','controlled-profile',1,'sha256:'+'b'*64)
    harness=HarnessDescriptor('controlled-fixture',{'environmentNamespace':'existing-namespace',
        'definitionId':'controlled-fixture','revision':'1'},'sha256:'+'d'*64,'acp',(),())
    material=InstanceBindingMaterial(profile,harness,process_ref,plan_digest,'sha256:'+'c'*64,
        'acp','controlled-session','controlled-source')
    instance=AgentInstanceRef('existing-namespace','instance',material.digest)
    provenance=original_provenance(instance,process_ref,plan_digest)
    records.publish_instance_binding(provenance,'controlled-session',
        principal_scope='principal:existing-test-caller',protocol_id='acp')
    records.publish_instance_control(provenance,SimpleNamespace(operation_ref='controlled-preparation'),
        'principal:existing-test-caller',binding_material=material)
    return instance


def test_original_manager_preclaim_engineering_binding_physical_send_and_full_blob_capture(tmp_path):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path/'environment')
        records=Records(tmp_path/'agent-records.sqlite');manager=AgentManager(fixture.resolver,records)
        authority=ExternalAuthority(fixture.invocation)
        source=InteractionService(records,authority,fixture.resolver)
        library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='original-engineering-library',schema_version=13)
        blobs=SQLiteBlobStore(library);factory=SQLiteUoWFactory(library)
        try:
            endpoint=await fixture.endpoint();plan=fixture.plan([sys.executable,'-u','-c',';'.join(ACP_PEER.strip().splitlines())])
            launch=await manager._launch_once('start',plan,endpoint.ref,fixture.invocation)
            assert launch.status=='completed'
            instance=seed_controlled_instance(records,launch.process_endpoint_ref,plan.plan_digest)
            consumer=AgentExecutionConsumer(source,blobs)
            raw=canonical_bytes({'sessionId':'controlled-session','prompt':[]})
            prepared=consumer.claim_and_prepare(instance.projection(),raw,request_id='original-request',
                engineering_attempt_ref='external-attempt',send_invocation=fixture.invocation,read_invocation=authority.reader)
            from ordessa_execution_agents.sdk.interactions import TurnRef
            turn=TurnRef.decode(json.loads(prepared.turn_ref_bytes))
            parent=records.turn(turn.turn_id)
            assert parent.status=='reserved' and parent.operation_ref==prepared.agent_operation_ref
            # Original Engineering byte binding/reservation, with fixture business
            # references only: no claim that an approval was granted/consumed.
            old=decode_dispatch((Path(__file__).parents[3]/'packages/engineering/tests/domain/fixtures/dispatch-v1-baseline.json').read_bytes())
            prompt_blob=blobs.put_verified(prepared.prompt_bytes,Digest('sha256',hashlib.sha256(prepared.prompt_bytes).hexdigest()),'application/json')
            values={f.name:getattr(old,f.name) for f in fields(old) if f.name in FROZEN_V1_FIELDS and f.init and f.name not in ('unit_ref_bytes','execution_operation_ref')}
            binding=AgentDispatchBinding(**{**values,'agent_ref_bytes':prepared.agent_ref_bytes,'turn_ref_bytes':prepared.turn_ref_bytes,
                'engineering_attempt_ref':prepared.engineering_attempt_ref,'prompt_ref':prompt_blob,
                'prompt_input_digest':Digest('sha256',prepared.prompt_input_digest[7:]),'expected_query_digest':prepared.query_digest})
            with library.transaction() as db:
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',('run','{}','{}','{}','running',0,None,'now','now'))
            with factory.begin(binding.scope) as uow:
                AgentDispatchBindings(uow.dispatch).reserve(binding)
                uow.dispatch.transition('run','step',1,binding.scope,expected_version=0,fence=1,phase='possibly_written')
                uow.commit()
            task,thread=asyncio.current_task(),threading.get_ident()
            class OriginalRowCut:
                calls=0
                @contextmanager
                def guard_write(self,write,invocation):
                    assert invocation is fixture.invocation and write.agent_operation_ref==prepared.agent_operation_ref
                    assert write.engineering_attempt_ref==prepared.engineering_attempt_ref and write.input_digest==prepared.prompt_input_digest
                    assert asyncio.current_task() is task and threading.get_ident()==thread
                    with factory.begin_effect_cut(binding.scope) as uow:
                        row,actual=AgentDispatchBindings(uow.dispatch).read('run','step',1,binding.scope)
                        assert actual==binding and row['dispatch_phase']=='possibly_written'
                        self.calls+=1
                        yield
                        uow.commit()
            guard=OriginalRowCut();prompt=source.freeze_prompt(instance,raw)
            sent=await manager.send_prompt('original-request',instance,fixture.invocation,prompt=prompt,
                interaction_service=source,engineering_attempt_ref='external-attempt',write_guard=guard,
                deadline=asyncio.get_running_loop().time()+3)
            assert sent.state=='completed' and guard.calls==1
            assert sent.endpoint_operation_ref!=sent.agent_operation_ref
            facts=json.loads(sent.observation_bytes)
            response=facts['protocol']['frames'][-1]
            assert response['id']==sent.agent_operation_ref
            assert response['result']['_meta']=={'paramsDigest':hashlib.sha256(raw).hexdigest(),'method':'session/prompt'}
            captured=consumer.capture(prepared,read_invocation=authority.reader)
            assert captured.state=='completed'
            assert blobs.read_verified(captured.blob_ref)==canonical_bytes(sent.projection())
            authority.send=False
            replay=await manager.send_prompt('original-request',instance,authority.reader,prompt=prompt,
                interaction_service=source,engineering_attempt_ref='external-attempt',write_guard=guard,
                deadline=asyncio.get_running_loop().time()+2)
            assert replay==sent and guard.calls==1
            authority.read=False
            with pytest.raises(InteractionsRefused):consumer.capture(prepared,read_invocation=authority.reader)
            assert fixture.retained_use_count==1
        finally:await fixture.cleanup()
    asyncio.run(scenario())


def test_original_preclaim_actual_send_and_original_engineering_blob_capture_without_business_uow(tmp_path):
    """Positive read/capture slice; deliberately does NOT qualify business UoW/approval."""
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path/'environment');records=Records(tmp_path/'agent.sqlite')
        manager=AgentManager(fixture.resolver,records);authority=ExternalAuthority(fixture.invocation)
        source=InteractionService(records,authority,fixture.resolver)
        library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='original-blob-library',schema_version=13)
        blobs=SQLiteBlobStore(library);consumer=AgentExecutionConsumer(source,blobs)
        try:
            endpoint=await fixture.endpoint();plan=fixture.plan([sys.executable,'-u','-c',';'.join(ACP_PEER.strip().splitlines())])
            launch=await manager._launch_once('start',plan,endpoint.ref,fixture.invocation)
            instance=seed_controlled_instance(records,launch.process_endpoint_ref,plan.plan_digest)
            raw=canonical_bytes({'sessionId':'controlled-session','prompt':[]})
            prepared=consumer.claim_and_prepare(instance.projection(),raw,request_id='request',engineering_attempt_ref='attempt',
                send_invocation=fixture.invocation,read_invocation=authority.reader)
            class PhysicalProbe:
                calls=0
                @contextmanager
                def guard_write(self,write,invocation):
                    assert invocation is fixture.invocation and write.agent_operation_ref==prepared.agent_operation_ref
                    self.calls+=1;yield
            probe=PhysicalProbe()
            result=await manager.send_prompt('request',instance,fixture.invocation,prompt=source.freeze_prompt(instance,raw),
                interaction_service=source,engineering_attempt_ref='attempt',write_guard=probe,
                deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='completed' and probe.calls==1
            captured=consumer.capture(prepared,read_invocation=authority.reader)
            assert blobs.read_verified(captured.blob_ref)==canonical_bytes(result.projection())
            assert captured.state=='completed' and captured.authority_id=='original-blob-library'
            authority.send=False
            assert await manager.send_prompt('request',instance,authority.reader,prompt=source.freeze_prompt(instance,raw),
                interaction_service=source,engineering_attempt_ref='attempt',write_guard=probe,
                deadline=asyncio.get_running_loop().time()+2)==result
            assert probe.calls==1
            authority.read=False
            with pytest.raises(InteractionsRefused):consumer.capture(prepared,read_invocation=authority.reader)
        finally:await fixture.cleanup()
    asyncio.run(scenario())
