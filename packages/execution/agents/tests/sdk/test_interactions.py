"""F1.2/a official DTOs and original parent source; no alternate send ports."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib,json
from types import SimpleNamespace
import pytest
from interaction_fixtures import original_service,provenance,INSTANCE,ENDPOINT,DIGEST
from ordessa_agents.sdk.interactions import (
    FrozenPrompt,TurnReadQuery,TurnReceipt,TurnRef,WriteBinding,BindingProvenance,
    GuardedSendObservation,InteractionsRefused,freeze_prompt,turn_query,InteractionService,
)
from ordessa_agents.sdk.endpoint import BoundEndpoint
from ordessa_agents.sdk.prepare import EndpointError

PARAMS_BYTES=b'{"prompt":[{"text":"hi","type":"text"}],"sessionId":"session-1"}'


def test_prompt_and_query_digests_follow_the_closed_projections():
    prompt=freeze_prompt(INSTANCE,PARAMS_BYTES);query=turn_query(TurnRef(INSTANCE,'turn'),prompt.input_digest)
    assert prompt.input_digest==prompt.input_projection_digest() and query.query_digest==query.query_projection_digest()
    assert prompt.projection()['paramsBytes']==json.loads(PARAMS_BYTES)
    with pytest.raises(InteractionsRefused):FrozenPrompt(INSTANCE,'session-1',PARAMS_BYTES,DIGEST)
    with pytest.raises(InteractionsRefused):TurnReadQuery(query.turn_ref,prompt.input_digest,DIGEST)
    with pytest.raises(InteractionsRefused):freeze_prompt(INSTANCE,b'{"prompt":[]}')
    with pytest.raises(InteractionsRefused):freeze_prompt(INSTANCE,b'{"sessionId": "session-1"}')
    with pytest.raises(InteractionsRefused):FrozenPrompt(INSTANCE,'other-session',PARAMS_BYTES,prompt.input_digest)


def test_closed_codecs_round_trip_and_reject_unknown_fields():
    prompt=freeze_prompt(INSTANCE,PARAMS_BYTES);query=turn_query(TurnRef(INSTANCE,'turn'),prompt.input_digest)
    receipt=TurnReceipt(query.turn_ref,'session-1','original-agent-op',None,None,'attempt',prompt.input_digest,'unknown',1,b'{}',hash_bytes(b'{}'))
    write=WriteBinding(query.turn_ref,'session-1','original-agent-op','child-request','attempt',prompt.input_digest,hash_bytes(PARAMS_BYTES))
    for value in (prompt,query,receipt,write,provenance(),GuardedSendObservation('child','not_sent',0,EndpointError('E','refused'))):
        assert type(value).decode(value.projection())==value
        with pytest.raises(Exception):type(value).decode({**value.projection(),'grant':'forged'})
        with pytest.raises(Exception):type(value).decode({**value.projection(),'schemaVersion':'retired/1'})
    assert receipt.projection()['schemaVersion']=='agent-protocol-turn/1'
    assert receipt.projection()['observationBytes']=={}


def hash_bytes(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()


def test_provenance_requires_profile_and_a_real_digest():
    value=provenance()
    assert BindingProvenance.decode(value.projection())==value
    with pytest.raises(Exception):replace(value,profile_ref=None)
    with pytest.raises(Exception):replace(value,source_revision='different-original-source')
    with pytest.raises(Exception):BindingProvenance.decode({**value.projection(),'profileRef':{}})


def test_query_turn_binds_the_receipt_to_its_query(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
    reservation=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender)
    query=source.turn_query(reservation.turn_ref,prompt.input_digest)
    assert source.query_turn(query,invocation=reader)==reservation
    with pytest.raises(InteractionsRefused):source.query_turn(turn_query(query.turn_ref,DIGEST),invocation=reader)
    with pytest.raises(InteractionsRefused):source.query_turn(query,invocation=authority.token('principal:foreign'))
    authority.denied.add('read')
    with pytest.raises(InteractionsRefused):source.query_turn(query,invocation=reader)


def test_read_binding_needs_its_own_read_authority(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    assert source.read_binding(INSTANCE,invocation=reader)==provenance()
    with pytest.raises(InteractionsRefused):source.read_binding(INSTANCE,invocation=authority.token(read=False))
    with pytest.raises(InteractionsRefused):source.read_binding(replace(INSTANCE,binding_digest='sha256:'+'b'*64),invocation=reader)
    row=source.records.operation(__import__('ordessa_agents.sdk.interactions',fromlist=['_digest_of'])._digest_of({'namespace':INSTANCE.namespace,'instanceId':INSTANCE.instance_id}),'instance-binding')
    payload=dict(row.payload);payload['provenance']={**payload['provenance'],'sourceRevision':'corrupt'}
    source.records._db.execute('UPDATE operations SET payload=? WHERE request_id=?',(json.dumps(payload),row.request_id))
    with pytest.raises(InteractionsRefused):source.read_binding(INSTANCE,invocation=reader)


class Guard:
    calls=0
    @contextmanager
    def guard_write(self,binding,invocation):self.calls+=1;yield

class Communicate:
    calls=0
    async def receive(self,cursor,deadline,invocation):raise TimeoutError()
    async def send_guarded(self,frame,request_id,deadline,invocation,*,binding,write_guard):
        self.calls+=1
        with write_guard.guard_write(binding,invocation):return GuardedSendObservation('original-child-op','confirmed',len(frame))

class Resolver:
    def __init__(self,communicate):self.communicate=communicate
    async def resolve(self,ref,invocation):return BoundEndpoint(ref,{},communicate=self.communicate)


def test_prompt_recorded_uses_the_endpoint_writer_and_guard_only(tmp_path):
    async def scenario():
        channel=Communicate();source,authority,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES);guard=Guard()
        reservation=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender)
        assert channel.calls==0 and reservation.endpoint_operation_ref is None
        result=await source.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',
            invocation=sender,write_guard=guard,deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='unknown'  # no protocol response: physical ack is NEVER completion
        assert result.endpoint_operation_ref=='original-child-op' and result.agent_operation_ref!=result.endpoint_operation_ref
        assert channel.calls==1 and guard.calls==1
        authority.denied.add('send')
        assert await source.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',
            invocation=reader,write_guard=guard,deadline=asyncio.get_running_loop().time()+2)==result
        assert channel.calls==1
        with pytest.raises(InteractionsRefused):
            await source.prompt_recorded(INSTANCE,prompt,request_id='fresh',engineering_attempt_ref='attempt',
                invocation=sender,write_guard=guard,deadline=asyncio.get_running_loop().time()+2)
    asyncio.run(scenario())


def test_not_sent_observation_needs_zero_bytes_and_an_error():
    with pytest.raises(InteractionsRefused):GuardedSendObservation('op','not_sent',0)
    with pytest.raises(InteractionsRefused):GuardedSendObservation('op','not_sent',4,EndpointError('E','x'))
    with pytest.raises(InteractionsRefused):GuardedSendObservation('op','not_sent',0,{'code':'E'})
    assert GuardedSendObservation('op','not_sent',0,EndpointError('E','x')).bytes_sent==0


def test_reservation_input_conflict_foreign_scope_and_restart_never_allocate_second_turn(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite')
    prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
    a=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender)
    assert source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=reader)==a
    for changed,attempt in ((source.freeze_prompt(INSTANCE,b'{"prompt":[],"sessionId":"session-1"}'),'attempt'),(prompt,'different')):
        with pytest.raises(InteractionsRefused):source.reserve_turn(INSTANCE,changed,request_id='request',engineering_attempt_ref=attempt,invocation=sender)
    with pytest.raises(InteractionsRefused):source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=authority.token('principal:foreign'))
    cold=InteractionService(type(source.records)(tmp_path/'records.sqlite'),authority,Resolver(Communicate()))
    query=cold.turn_query(a.turn_ref,prompt.input_digest)
    assert cold.query_turn(query,invocation=reader).state=='unknown'
    async def replay():return await cold.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
    assert asyncio.run(replay()).state=='unknown'
    assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==1


def test_fresh_capacity_expiry_and_operation_end_cannot_reconstruct_send(tmp_path,monkeypatch):
    import ordessa_agents.sdk.interactions as module
    clock=[100.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(module,'MAX_FRESH_TURNS',2)
    channel=Communicate();source,authority,sender,reader=original_service(tmp_path/'bounded.sqlite',Resolver(channel))
    prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
    receipts=[source.reserve_turn(INSTANCE,prompt,request_id=key,engineering_attempt_ref='attempt',invocation=sender)
        for key in ('one','two')]
    with pytest.raises(InteractionsRefused,match='FRESH_CAPACITY_EXHAUSTED'):
        source.reserve_turn(INSTANCE,prompt,request_id='overflow',engineering_attempt_ref='attempt',invocation=sender)
    assert len(source._fresh)==2
    assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==2
    clock[0]+=module.FRESH_TURN_SECONDS
    assert source.query_turn(turn_query(receipts[0].turn_ref,prompt.input_digest),invocation=reader).state=='unknown'
    assert source._fresh=={}
    again=source.reserve_turn(INSTANCE,prompt,request_id='one',engineering_attempt_ref='attempt',invocation=sender)
    assert again.turn_ref==receipts[0].turn_ref and again.state=='unknown'
    fresh=source.reserve_turn(INSTANCE,prompt,request_id='new',engineering_attempt_ref='attempt',invocation=sender)
    source.invalidate_invocation(reader)  # a different invocation cannot end this original flow
    assert source.query_turn(turn_query(fresh.turn_ref,prompt.input_digest),invocation=reader).state=='reserved'
    source.invalidate_invocation(sender)
    assert source._fresh=={}
    async def replay(key):
        return await source.prompt_recorded(INSTANCE,prompt,request_id=key,engineering_attempt_ref='attempt',
            invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
    assert asyncio.run(replay('one')).state=='unknown'
    assert asyncio.run(replay('new')).state=='unknown'
    assert channel.calls==0
