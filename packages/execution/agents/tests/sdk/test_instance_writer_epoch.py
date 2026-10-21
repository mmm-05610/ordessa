"""Mandatory private instance epoch at original prompt/native physical cuts."""
import asyncio
from contextlib import contextmanager
import json
import sqlite3

import pytest

from interaction_fixtures import original_service,INSTANCE,DIGEST
from test_interactions import Resolver,Guard,PARAMS_BYTES
from test_acp_recorded_response import Protocol
from ordessa_agents.sdk.interactions import InteractionsRefused,GuardedSendObservation
from ordessa_agents.sdk.manager import Records,ManagerRefused
from ordessa_agents.sdk.native_contracts import METHODS


def lifecycle_claim(records,request='stop'):
    return records.claim_lifecycle(INSTANCE,'stop',request_id=request,
        principal_scope='principal:test',request_digest=DIGEST,force=False)


class CutPeer(Protocol):
    def __init__(self,before=None,inside=None,receive=None):
        super().__init__();self.before=before;self.inside=inside;self.on_receive=receive;self.frames=[]
    async def send_guarded(self,frame,request_id,deadline,invocation,*,binding,write_guard):
        if self.before is not None:self.before()
        with write_guard.guard_write(binding,invocation):
            if self.inside is not None:self.inside()
            self.frames.append(frame)
        self.frame=json.loads(frame);self.raw=frame
        return GuardedSendObservation('original-physical/'+request_id,'confirmed',len(frame))
    async def receive(self,*args):
        if self.on_receive is not None:self.on_receive()
        return await super().receive(*args)


def test_original_lifecycle_epoch_fences_reserved_prompt_at_physical_cut(tmp_path):
    async def scenario():
        peer=CutPeer();source,authority,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(peer))
        other=Records(tmp_path/'records.sqlite')
        try:
            prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
            reserved=source.reserve_turn(INSTANCE,prompt,request_id='old',engineering_attempt_ref='attempt',invocation=sender)
            peer.before=lambda:lifecycle_claim(other)
            result=await source.prompt_recorded(INSTANCE,prompt,request_id='old',engineering_attempt_ref='attempt',
                invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='unknown' and peer.frames==[]
            assert source.records.turn(reserved.turn_ref.turn_id).payload['controlEpoch']==0
            assert other.instance_control(INSTANCE)[0].writer_epoch==1
            replay=await source.prompt_recorded(INSTANCE,prompt,request_id='old',engineering_attempt_ref='attempt',
                invocation=reader,write_guard=None,deadline=None)
            assert replay==result and peer.frames==[]
            with pytest.raises(InteractionsRefused,match='INSTANCE_WRITER_FENCED'):
                source.reserve_turn(INSTANCE,prompt,request_id='new',engineering_attempt_ref='attempt',invocation=sender)
        finally:other.close();source.records.close()
    asyncio.run(scenario())


def test_epoch_and_physical_bytes_are_atomic_but_response_wait_holds_no_agent_tx(tmp_path):
    async def scenario():
        peer=CutPeer();source,authority,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(peer))
        other=Records(tmp_path/'records.sqlite');other._db.execute('PRAGMA busy_timeout=0')
        checks=[]
        def inside():
            assert source.records._db.in_transaction
            with pytest.raises(ManagerRefused,match='locked'):
                lifecycle_claim(other,'inside-cut')
            checks.append('cut-protected')
        def receive():
            assert not source.records._db.in_transaction
            assert lifecycle_claim(other,'during-response')[0]=='created'
            checks.append('response-unlocked')
        peer.inside=inside;peer.on_receive=receive
        try:
            prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
            result=await source.prompt_recorded(INSTANCE,prompt,request_id='prompt',engineering_attempt_ref='attempt',
                invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='completed' and len(peer.frames)==1
            assert checks==['cut-protected','response-unlocked']
            assert source.records.instance_control(INSTANCE)[0].active_action=='stop'
            assert not source.records._db.in_transaction
        finally:other.close();source.records.close()
    asyncio.run(scenario())


def test_historical_binding_without_control_is_readable_but_never_a_new_writer(tmp_path):
    source,authority,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(CutPeer()))
    try:
        before=source.read_binding(INSTANCE,invocation=reader)
        source.records._db.execute("DELETE FROM operations WHERE operation='instance-control'")
        assert source.read_binding(INSTANCE,invocation=reader)==before
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        with pytest.raises(InteractionsRefused,match='INSTANCE_CONTROL_UNAVAILABLE'):
            source.reserve_turn(INSTANCE,prompt,request_id='new',engineering_attempt_ref='attempt',invocation=sender)
        assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==0
    finally:source.records.close()


def test_native_operation_private_epoch_is_mandatory_and_fences_physical_dispatch(tmp_path):
    async def scenario():
        peer=CutPeer();source,authority,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(peer))
        other=Records(tmp_path/'records.sqlite')
        authority.check_native_dispatch=lambda token,binding:authority.check_send(token,binding)
        authority.check_read_native_operation=lambda token,*args:authority.check_read_turn(token,None)
        @contextmanager
        def admitted(token,binding):
            authority.check_send(token,binding);yield
        authority.guard_native_dispatch=admitted
        try:
            request=source.freeze_native_request(INSTANCE,purpose='query',method=METHODS['query'],
                params_bytes=b'{"operationId":"native-query","sessionId":"session-1"}')
            peer.before=lambda:lifecycle_claim(other)
            result=await source.native_recorded(request,request_id='native',invocation=sender,
                write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
            assert result.state=='unknown' and peer.frames==[]
            row=source.records.operation(result.binding.operation_ref.request_key,'native-operation')
            assert row.payload['controlEpoch']==0
            replay=await source.native_recorded(request,request_id='native',invocation=reader,write_guard=None,deadline=None)
            assert replay==result and peer.frames==[]
            assert other.instance_control(INSTANCE)[0].writer_epoch==1
        finally:other.close();source.records.close()
    asyncio.run(scenario())
