"""Original parent row advances only from original correlated ACP observations."""
import asyncio,hashlib,json
from dataclasses import replace
import pytest
from interaction_fixtures import original_service,INSTANCE
from test_interactions import Communicate,Resolver,Guard,PARAMS_BYTES
from ordessa_agents.sdk.endpoint import ProtocolEvent,ProtocolEventPage
from ordessa_agents.sdk.interactions import turn_query,InteractionsRefused
from ordessa_agents.sdk.manager import AgentManager,ManagerRefused


class Protocol(Communicate):
    def __init__(self,mode='complete'):self.mode=mode;self.calls=0;self.reads=0
    async def send_guarded(self,frame,*args,**kwargs):
        self.frame=json.loads(frame);self.raw=frame
        assert self.frame['jsonrpc']=='2.0' and self.frame['method']=='session/prompt'
        assert self.frame['params']==json.loads(PARAMS_BYTES)
        binding=kwargs['binding']
        assert binding.frame_digest=='sha256:'+hashlib.sha256(frame).hexdigest()
        assert binding.agent_operation_ref==self.frame['id']
        return await super().send_guarded(frame,*args,**kwargs)
    async def receive(self,cursor,deadline,invocation):
        self.reads+=1
        operation=self.frame['id']
        if self.mode=='cancel':
            await asyncio.Future()
        notification={'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'session-1',
            'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'original'}},'_meta':{'extension':'preserved'}}}
        response={'jsonrpc':'2.0','id':operation,'result':{'stopReason':'end_turn','_meta':{'original':'response'}}}
        if self.mode=='foreign':response['id']='foreign'
        if self.mode=='session':notification['params']['sessionId']='foreign'
        if self.mode=='error':response={'jsonrpc':'2.0','id':operation,'error':{'code':-32000,'message':'original failure'}}
        if self.mode=='reverse':response={'jsonrpc':'2.0','id':'permission','method':'session/request_permission','params':{'sessionId':'session-1'}}
        raw=b''.join((json.dumps(x,separators=(',',':'))+'\n').encode() for x in [notification,response])
        return ProtocolEventPage((ProtocolEvent('bytes','sha256:'+hashlib.sha256(raw).hexdigest(),raw),))


def test_original_protocol_result_advances_same_parent_and_cold_replay_never_sends(tmp_path):
    async def scenario():
        channel=Protocol();source,auth,sender,reader=original_service(tmp_path/'original.sqlite',Resolver(channel))
        manager=AgentManager(Resolver(channel),source.records);prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        reserved=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender)
        result=await manager.send_prompt('request',INSTANCE,sender,prompt=prompt,interaction_service=source,
            engineering_attempt_ref='attempt',write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='completed' and result.revision==3
        assert result.turn_ref==reserved.turn_ref and result.agent_operation_ref==reserved.agent_operation_ref
        facts=json.loads(result.observation_bytes)
        assert len(facts['protocol']['frames'])==2 and facts['protocol']['frames'][0]['params']['_meta']=={'extension':'preserved'}
        assert facts['delivery']=='confirmed' and channel.calls==1 and channel.reads==1
        row=source.records.turn(result.turn_ref.turn_id)
        with pytest.raises(ManagerRefused):source.records.advance_turn(row,status='failed',payload=row.payload)
        # Original manager finally actually clears other associations for the ended invocation.
        assert source._fresh=={} and source._receiving==set()
        auth.denied.add('send')
        assert await manager.send_prompt('request',INSTANCE,reader,prompt=prompt,interaction_service=source,
            engineering_attempt_ref='attempt',write_guard=None,deadline=None)==result
        assert channel.calls==1 and channel.reads==1
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,state',[('foreign','unknown'),('session','unknown'),('reverse','unknown'),('error','failed')])
def test_uncorrelated_or_reverse_frames_cannot_become_success_or_trigger_another_send(tmp_path,mode,state):
    async def scenario():
        channel=Protocol(mode);source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        result=await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),request_id='request',
            engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert result.state==state and result.revision==3 and channel.calls==1
        assert source.query_turn(turn_query(result.turn_ref,result.input_digest),invocation=reader)==result
    asyncio.run(scenario())


def test_send_only_execution_never_returns_original_response_facts_without_read_right(tmp_path):
    async def scenario():
        channel=Protocol();source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        sender.read=False;prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        reserved=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref=None,invocation=sender)
        with pytest.raises(InteractionsRefused,match='READ_NOT_AUTHORIZED'):
            await source.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref=None,
                invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert channel.calls==1
        receipt=source.query_turn(turn_query(reserved.turn_ref,prompt.input_digest),invocation=reader)
        assert receipt.state=='completed'
    asyncio.run(scenario())


def test_manager_cancel_records_original_unknown_and_drops_invocation_fresh_state(tmp_path):
    async def scenario():
        channel=Protocol('cancel');source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        manager=AgentManager(Resolver(channel),source.records);prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        first=source.reserve_turn(INSTANCE,prompt,request_id='first',engineering_attempt_ref=None,invocation=sender)
        second=source.reserve_turn(INSTANCE,prompt,request_id='second',engineering_attempt_ref=None,invocation=sender)
        task=asyncio.create_task(manager.send_prompt('first',INSTANCE,sender,prompt=prompt,interaction_service=source,
            engineering_attempt_ref=None,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+10))
        while not channel.reads:await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert source.query_turn(turn_query(first.turn_ref,prompt.input_digest),invocation=reader).state=='unknown'
        assert source.query_turn(turn_query(second.turn_ref,prompt.input_digest),invocation=reader).state=='unknown'
        assert source._fresh=={} and source._receiving==set() and channel.calls==1
    asyncio.run(scenario())


def test_direct_source_prewrite_refusal_ends_original_invocation_without_resend(tmp_path):
    async def scenario():
        channel=Protocol();source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        prompt=source.freeze_prompt(INSTANCE,PARAMS_BYTES)
        reserved=source.reserve_turn(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',invocation=sender)
        with pytest.raises(InteractionsRefused,match='WRITER_GUARD_UNSUPPORTED'):
            await source.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',
                invocation=sender,write_guard=None,deadline=asyncio.get_running_loop().time()+2)
        query=turn_query(reserved.turn_ref,prompt.input_digest)
        assert source.query_turn(query,invocation=reader).state=='unknown'
        replay=await source.prompt_recorded(INSTANCE,prompt,request_id='request',engineering_attempt_ref='attempt',
            invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert replay.state=='unknown' and channel.calls==0 and source._fresh=={}
        assert source.records.turn(reserved.turn_ref.turn_id).status=='reserved'
    asyncio.run(scenario())


def test_terminal_page_is_not_accepted_until_declared_following_pages_are_observed(tmp_path):
    class Paged(Protocol):
        def __init__(self):super().__init__();self.cursors=[]
        async def receive(self,cursor,deadline,invocation):
            self.cursors.append(cursor)
            if cursor is None:
                first=await super().receive(cursor,deadline,invocation)
                return ProtocolEventPage(first.events,cursor='unread-page',has_more=True)
            assert cursor=='unread-page'
            # A later reverse request must not be silently discarded after an
            # earlier terminal response. No second frame may be sent for it.
            raw=b'{"jsonrpc":"2.0","id":"permission","method":"session/request_permission","params":{}}\n'
            return ProtocolEventPage((ProtocolEvent('bytes','sha256:'+hashlib.sha256(raw).hexdigest(),raw),))
    async def scenario():
        channel=Paged();source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        result=await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),request_id='request',
            engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='unknown' and channel.cursors==[None,'unread-page'] and channel.calls==1
    asyncio.run(scenario())


def test_two_original_service_objects_share_the_original_session_cut(tmp_path):
    from ordessa_agents.sdk.interactions import InteractionService
    async def scenario():
        channel=Protocol('cancel');first,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        second=InteractionService(first.records,auth,Resolver(channel))
        prompt=first.freeze_prompt(INSTANCE,PARAMS_BYTES)
        running=asyncio.create_task(first.prompt_recorded(INSTANCE,prompt,request_id='one',engineering_attempt_ref=None,
            invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+10))
        while not channel.reads:await asyncio.sleep(0)
        with pytest.raises(ManagerRefused,match='SESSION_UNRESOLVED'):
            await second.prompt_recorded(INSTANCE,prompt,request_id='two',engineering_attempt_ref=None,
                invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert channel.calls==1
        running.cancel()
        with pytest.raises(asyncio.CancelledError):await running
        # A new service/request after uncertain response cannot infer idle from
        # the old service going away, reacquire, or send another frame.
        with pytest.raises(ManagerRefused,match='SESSION_UNRESOLVED'):
            await second.prompt_recorded(INSTANCE,prompt,request_id='three',engineering_attempt_ref=None,
                invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert channel.calls==1
    asyncio.run(scenario())


def _process_session_dispatch(path,write_fd,sent,release,queue,identity):
    import os
    class PipeProtocol(Protocol):
        async def send_guarded(self,frame,*args,**kwargs):
            result=await super().send_guarded(frame,*args,**kwargs)
            os.write(write_fd,frame);sent.set()
            return result
        async def receive(self,cursor,deadline,invocation):
            assert release.wait(5)  # isolated child only; no inherited executor thread
            return await super().receive(cursor,deadline,invocation)
    async def run():
        channel=PipeProtocol();source,auth,sender,reader=original_service(path,Resolver(channel))
        try:
            receipt=await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),request_id=identity,
                engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+8)
            queue.put((identity,receipt.state))
        except ManagerRefused as error:queue.put((identity,error.code))
        finally:source.records._db.close()
    asyncio.run(run())


def test_two_processes_cannot_concurrently_write_or_read_same_original_session(tmp_path):
    import multiprocessing,os
    context=multiprocessing.get_context('fork');sent=context.Event();release=context.Event();queue=context.Queue()
    path=tmp_path/'original.sqlite';read_fd,write_fd=os.pipe();workers=[]
    original,_,_,_=original_service(path);original.records._db.close()
    try:
        first=context.Process(target=_process_session_dispatch,args=(path,write_fd,sent,release,queue,'first'))
        workers.append(first);first.start();assert sent.wait(5)
        second=context.Process(target=_process_session_dispatch,args=(path,write_fd,sent,release,queue,'second'))
        workers.append(second);second.start();second.join(5);assert second.exitcode==0
        assert queue.get(timeout=2)==('second','SESSION_UNRESOLVED')
        release.set();first.join(5);assert first.exitcode==0
        assert queue.get(timeout=2)==('first','completed')
        raw=os.read(read_fd,65536)
        assert raw.count(b'\n')==1 and json.loads(raw)['method']=='session/prompt'
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            if worker.is_alive():worker.terminate();worker.join(2)
        os.close(read_fd);os.close(write_fd);queue.close()


def test_instance_alias_cannot_bypass_original_physical_stream_exclusion(tmp_path):
    from interaction_fixtures import provenance
    async def scenario():
        channel=Protocol('cancel');source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        alias=replace(INSTANCE,instance_id='second-instance')
        source.records.publish_instance_binding(provenance(instance=alias),'session-1',principal_scope='principal:test',protocol_id='acp')
        from types import SimpleNamespace
        from interaction_fixtures import MATERIAL
        source.records.publish_instance_control(provenance(instance=alias),SimpleNamespace(operation_ref='fixture-alias-start'),'principal:test',binding_material=MATERIAL)
        first=asyncio.create_task(source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),request_id='one',
            engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+10))
        while not channel.reads:await asyncio.sleep(0)
        with pytest.raises(ManagerRefused,match='SESSION_UNRESOLVED'):
            await source.prompt_recorded(alias,source.freeze_prompt(alias,PARAMS_BYTES),request_id='two',
                engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert channel.calls==1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):await first
    asyncio.run(scenario())


def test_custom_notifications_and_meta_survive_before_and_after_prompt_response(tmp_path):
    class Extended(Protocol):
        async def receive(self,cursor,deadline,invocation):
            original=await super().receive(cursor,deadline,invocation)
            custom={'jsonrpc':'2.0','method':'_gemini/customEvent','params':{'keep':'verbatim','_meta':{'nested':['unchanged']}}}
            wire=(json.dumps(custom)+'\n').encode()
            raw=wire+original.events[0].payload_bytes+wire
            return ProtocolEventPage((ProtocolEvent('bytes','sha256:'+hashlib.sha256(raw).hexdigest(),raw),))
    async def scenario():
        channel=Extended();source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        result=await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),request_id='request',
            engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),deadline=asyncio.get_running_loop().time()+2)
        assert result.state=='completed'
        frames=json.loads(result.observation_bytes)['protocol']['frames']
        assert len(frames)==4 and frames[0]==frames[-1]
        assert frames[0]['params']=={'keep':'verbatim','_meta':{'nested':['unchanged']}}
    asyncio.run(scenario())


@pytest.mark.parametrize('stop,state',[
    ('end_turn','completed'),('error','failed'),('cancelled','failed'),
    ('future','unknown'),('','unknown'),(1,'unknown'),
])
def test_original_terminal_vocabulary_retains_native_failure_and_unknown_without_resend(tmp_path,stop,state):
    """Equivalent original DSH/Grok outcome fences; not full brand L1 completion."""
    class Terminal(Protocol):
        async def receive(self,cursor,deadline,invocation):
            raw=(json.dumps({'jsonrpc':'2.0','id':self.frame['id'],
                'result':{'stopReason':stop,'_meta':{'verbatim':'original-terminal'}}})+'\n').encode()
            return ProtocolEventPage((ProtocolEvent('bytes','sha256:'+hashlib.sha256(raw).hexdigest(),raw),))
    async def scenario():
        channel=Terminal();source,auth,sender,reader=original_service(tmp_path/'records.sqlite',Resolver(channel))
        receipt=await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),
            request_id='terminal',engineering_attempt_ref=None,invocation=sender,write_guard=Guard(),
            deadline=asyncio.get_running_loop().time()+2)
        assert receipt.state==state and channel.calls==1
        frames=json.loads(receipt.observation_bytes)['protocol']['frames']
        assert frames[-1]['result']=={'stopReason':stop,'_meta':{'verbatim':'original-terminal'}}
        assert await source.prompt_recorded(INSTANCE,source.freeze_prompt(INSTANCE,PARAMS_BYTES),
            request_id='terminal',engineering_attempt_ref=None,invocation=reader,write_guard=None,
            deadline=None)==receipt
        assert channel.calls==1
    asyncio.run(scenario())
