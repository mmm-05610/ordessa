"""Partial L1 assertion migration over formal original Agent assembly.

Maps original Gemini/Goose/Vibe initialize/session/update/extension assertions.
No standalone brand client/Unit channel; callback, generic command, load, cancel
and owned-only close assertions remain unported and are NOT qualified here.
"""
import asyncio,json
from contextlib import contextmanager
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from test_agent_guarded_bootstrap import setup
from ordessa_agents.public import InteractionService

PEER='''import json,sys
session=SESSION
for line in sys.stdin:
    request=json.loads(line);method=request['method'];params=request['params']
    if method=='initialize':result={'protocolVersion':1,'agentCapabilities':{'loadSession':LOAD}}
    elif method=='session/new':result={'sessionId':session}
    else:
        assert method=='session/prompt' and params['sessionId']==session
        print(json.dumps({'jsonrpc':'2.0','method':EXTENSION,'params':{'keep':'verbatim'}}),flush=True)
        print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':session,'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'hi'}}}}),flush=True)
        result={'stopReason':'end_turn'}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
'''


@pytest.mark.parametrize('brand,session,extension,load',[
    ('gemini','s-acp-1','_gemini/customEvent',True),
    ('goose','gs-1','_goose/telemetryLike',False),
    ('vibe','vb-1','_vibe/extensionNotice',False)])
def test_original_l1_native_session_capabilities_and_verbatim_extensions(tmp_path,brand,session,extension,load):
    async def scenario():
        peer=PEER.replace('SESSION',repr(session)).replace('LOAD',repr(load)).replace('EXTENSION',repr(extension))
        case=await setup(tmp_path,peer,brand=brand)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            assert started.state=='running' and started.session_id==session
            phases=[json.loads(r[0]) for r in case.records._db.execute("SELECT payload FROM operations WHERE operation='bootstrap-frame'")]
            frames=[frame for phase in phases for frame in phase['observation']['protocol']['frames']]
            initialized=next(frame['result'] for frame in frames if 'agentCapabilities' in frame.get('result',{}))
            assert initialized['protocolVersion']==1 and initialized['agentCapabilities']['loadSession'] is load
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            params=canonical_bytes({'sessionId':session,'prompt':[{'type':'text','text':'go'}]})
            class Cut:
                calls=0
                @contextmanager
                def guard_write(self,binding,invocation):
                    assert invocation is case.fixture.invocation
                    assert binding.session_id==session
                    self.calls+=1;yield
            cut=Cut();prompt=source.freeze_prompt(started.instance_ref,params)
            receipt=await case.manager.send_prompt('l1-prompt',started.instance_ref,case.fixture.invocation,
                prompt=prompt,interaction_service=source,engineering_attempt_ref=None,write_guard=cut,
                deadline=asyncio.get_running_loop().time()+2)
            assert receipt.state=='completed' and cut.calls==1
            captured=receipt.projection()['observationBytes']['protocol']['frames']
            notice=next(frame for frame in captured if frame.get('method')==extension)
            assert notice['params']=={'keep':'verbatim'}
            update=next(frame for frame in captured if frame.get('method')=='session/update')
            assert update['params']['sessionId']==session and update['params']['update']['content']['text']=='hi'
            assert next(frame['result'] for frame in captured if 'result' in frame)['stopReason']=='end_turn'
            assert case.fixture.retained_use_count==1
        finally:
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('brand',['gemini','goose','vibe'])
def test_l1_timeout_keeps_original_updates_unknown_and_does_not_resend(tmp_path,brand):
    async def scenario():
        peer=PEER.replace('SESSION',repr('l1-timeout')).replace('LOAD','False').replace('EXTENSION',repr('_'+brand+'/retained'))
        peer=peer.replace("result={'stopReason':'end_turn'}","continue")
        case=await setup(tmp_path,peer,brand=brand)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            class Cut:
                calls=0
                @contextmanager
                def guard_write(self,binding,invocation):self.calls+=1;yield
            cut=Cut();prompt=source.freeze_prompt(started.instance_ref,canonical_bytes({'sessionId':started.session_id,'prompt':[]}))
            async def send():
                return await case.manager.send_prompt('l1-timeout',started.instance_ref,case.fixture.invocation,
                    prompt=prompt,interaction_service=source,engineering_attempt_ref=None,write_guard=cut,
                    deadline=asyncio.get_running_loop().time()+.1)
            result=await send()
            assert result.state=='unknown' and cut.calls==1
            frames=result.projection()['observationBytes']['protocol']['frames']
            assert next(frame for frame in frames if frame.get('method')=='session/update')['params']['sessionId']=='l1-timeout'
            changes=case.records._db.total_changes;case.authority.send=False
            assert await send()==result and case.records._db.total_changes==changes and cut.calls==1
            assert case.records._db.execute("SELECT status FROM operations WHERE operation='protocol-session'").fetchone()==('unknown',)
            assert case.fixture.retained_use_count==1
        finally:
            case.records.close();case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())


def test_l1_close_respects_actual_external_owner_and_never_kills_other_use(tmp_path):
    from test_agent_guarded_bootstrap import PEER as SIMPLE_PEER
    async def scenario():
        a=await setup(tmp_path/'a',SIMPLE_PEER);b=await setup(tmp_path/'b',SIMPLE_PEER)
        try:
            for case in (a,b):
                started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
                assert started.state=='running'
            def process(case):
                handles=list(case.fixture._manager._owned_process_handles)
                assert len(handles)==1
                use_id,pid=handles[0]
                return case.fixture._uses.process(use_id,pid,case.fixture._scope,invocation=case.fixture.invocation)
            left,right=process(a),process(b)
            a.records.close() # Original SDK owns records, external owner retains Use/process.
            assert left.observe().state!='exited' and right.observe().state!='exited'
            await a.fixture.cleanup() # Original resource owner terminates only its own Use.
            assert right.observe().state!='exited' and b.fixture.retained_use_count==1
        finally:
            a.records.close();a.owner.close();await a.fixture.cleanup()
            b.records.close();b.owner.close();await b.fixture.cleanup()
    asyncio.run(scenario())
