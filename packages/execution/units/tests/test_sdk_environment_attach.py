"""Original ACP attach behavior on official SDK and opaque EnvironmentUse.

Legacy test captured byte-for-byte in Pi checkpoint; no model/network calls.
"""
import sys
import pytest
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore, ProcessRequest
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_execution_agents.harness.transport import ProcessChannel, LostReceipt, WriterLeaseRefused
from ordessa_units.sessions.sdk_client import SdkAcpClient

PEER = r'''
import json, sys
def send(message):
    print(json.dumps(message), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method, rid = request.get('method'), request.get('id')
    if method == 'initialize':
        result = {'protocolVersion': 1, 'agentCapabilities': {'loadSession': True},
                  'received': request['params']}
    elif method == 'session/new':
        result = {'sessionId': 'controlled-session', 'configOptions': []}
    elif method == 'session/load':
        result = {}  # Standard load response need not repeat sessionId.
    elif method == 'session/cancel':
        send({'jsonrpc': '2.0', 'method': 'controlled/cancelled',
              'params': request['params']})
        continue
    elif method == 'session/prompt':
        send({'jsonrpc': '2.0', 'method': 'session/update',
              'params': {'sessionId': request['params']['sessionId'],
                         'update': {'sessionUpdate': 'agent_message_chunk',
                                    'content': {'type': 'text', 'text': 'controlled'}}}})
        result = {'stopReason': 'end_turn'}
    elif method == '_ordessa/opaque_echo':
        send({'jsonrpc': '2.0', 'id': 'vendor-request-42',
              'method': '_vendor/opaque_request',
              'params': {'_meta': {'vendor': {'opaque': [None, False, 7, '原样']}},
                         'vendorPayload': {'keep': {'nested': True}}}})
        callback_reply = json.loads(sys.stdin.readline())
        assert callback_reply == {'jsonrpc': '2.0', 'id': 'vendor-request-42',
                                  'result': {'_meta': {'vendor': {'reply': ['kept', 9]}},
                                             'accepted': True}}
        send({'jsonrpc': '2.0', 'method': '_vendor/opaque_event',
              'params': {'_meta': {'vendor': {'opaque': ['通知', {'x': 1}]}},
                         'vendorPayload': {'extension': 'kept'}}})
        result = {'_meta': {'vendor': {'opaque': {'response': True}}},
                  'vendorPayload': request['params']}
    elif method == 'controlled/lost':
        sys.exit(0)
    else:
        result = request.get('params', {})
    send({'jsonrpc': '2.0', 'id': rid, 'result': result})
'''

@pytest.fixture(params=[False,True],ids=['original-handle','opaque-handle'])
def attached(tmp_path,monkeypatch,request):
    manager=EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'environment.sqlite'),
        providers={'local':LocalEnvironmentResourceProvider(default_root=str(tmp_path))})
    instance=manager.create('local',{'root':str(tmp_path)})
    use=instance.acquire('sdk-attach',sharing=True)
    process=use.execution.start(ProcessRequest.build([sys.executable,'-u','-c',PEER],
        cwd=str(tmp_path),env={'HOME':str(tmp_path),'PATH':'/usr/bin:/bin'}))
    class OpaqueProcess:
        identity=process.identity
        generation=process.generation
        async def read_stdout(self,*a,**k):return await process.read_stdout(*a,**k)
        async def read_stderr(self,*a,**k):return await process.read_stderr(*a,**k)
        async def write_stdin(self,*a,**k):return await process.write_stdin(*a,**k)
        async def close_stdin(self):return await process.close_stdin()
        async def wait_exit(self,*a,**k):return await process.wait_exit(*a,**k)
        async def cancel(self,*a,**k):return await process.cancel(*a,**k)
        def observe(self):return process.observe()
        def release(self):return process.release()
    handle=OpaqueProcess() if request.param else process
    assert not hasattr(handle,'pid') and not hasattr(handle,'returncode')
    def forbidden(*a,**k):raise AssertionError('SDK attach cannot spawn')
    monkeypatch.setattr(ProcessChannel,'launch',forbidden)
    channel=ProcessChannel.attach(handle,name='controlled-acp',managed=True)
    client=SdkAcpClient(channel.bind_writer(channel.acquire_writer()))
    try:yield instance,use,process,channel,client
    finally:
        if process.observe().state!='exited':
            client.run_process_operation(channel.close_async(timeout=2),timeout=10)
        assert process.observe().state=='exited'
        process.release();client.detach()
        receipt=use.release()
        assert receipt['useIdentity']==use.identity and receipt['resourcePreserved'] is True
        assert instance.snapshot.active_uses==0


def test_same_environment_process_session_cancel_stop(attached):
    instance,use,process,channel,client=attached
    assert channel._process.identity==process.identity and instance.snapshot.active_uses==1
    assert client.initialize(timeout=2)['agentCapabilities']['loadSession'] is True
    assert client.session_id is None
    session=client.new_session(timeout=2,cwd=use.files.root(),mcpServers=[])
    assert session['configOptions']==[] and client.session_id==session['sessionId']
    assert client.prompt(timeout=2,sessionId=client.session_id,
        prompt=[{'type':'text','text':'controlled'}])=={'stopReason':'end_turn'}
    assert client.events()[0].raw['method']=='session/update'
    assert client.next_event(timeout=2).raw['method']=='session/update'
    client.cancel(sessionId=client.session_id)
    assert client.next_event(timeout=2).raw['method']=='controlled/cancelled'
    assert process.observe().state=='running'
    assert client.run_process_operation(channel.close_async(timeout=2),timeout=10)==0
    assert process.observe().state=='exited' and process.observe().exit_code==0
    assert client.run_process_operation(channel.close_async(timeout=2),timeout=10)==0


def test_initialize_integer_version_capabilities(attached):
    client=attached[-1]
    params=client.initialize(timeout=2,fs={'readTextFile':True})['received']
    assert type(params['protocolVersion']) is int
    assert params=={'protocolVersion':1,'clientCapabilities':{'fs':{'readTextFile':True}}}


def test_successful_load_remembers_original_requested_identity(attached):
    client=attached[-1]
    assert client.load_session(timeout=2,sessionId='existing-session',cwd='/controlled',mcpServers=[])=={}
    assert client.session_id=='existing-session'


def test_lost_receipt_retains_original_id_and_fences_no_relaunch(attached):
    instance,use,process,channel,client=attached
    sent=[]
    client.sdk_connection.add_observer(lambda event:sent.append(dict(event.message))
        if event.direction.value=='outgoing' and event.message.get('method')=='controlled/lost' else None)
    with pytest.raises(LostReceipt):client.command('controlled/lost',timeout=2)
    assert len(sent)==1 and set(channel._prepared_inflight)=={(type(sent[0]['id']).__name__,sent[0]['id'])}
    assert channel._unresolved and instance.snapshot.active_uses==1
    with pytest.raises(WriterLeaseRefused):channel.acquire_writer()


def test_unknown_fields_preserved_without_host_identity(attached):
    client=attached[-1]
    assert client.command('controlled/echo',timeout=2,unknown='preserved')=={'unknown':'preserved'}


def test_native_extension_payloads_and_original_request_ids_survive_sdk(attached):
    client=attached[-1]
    request_params={'_meta': {'vendor': {'opaque': [None, False, 7, '原样']}},
                    'vendorPayload': {'nested': [1, {'keep': True}]}}
    reverse_request={'jsonrpc':'2.0','id':'vendor-request-42',
        'method':'_vendor/opaque_request',
        'params':{'_meta':{'vendor':{'opaque':[None,False,7,'原样']}},
                  'vendorPayload':{'keep':{'nested':True}}}}
    extension_reply={'_meta':{'vendor':{'reply':['kept',9]}},'accepted':True}
    observed=[]
    client.sdk_connection.add_observer(lambda event:observed.append((event.direction.value,dict(event.message))))

    def answer_original_request(message):
        assert message.raw==reverse_request
        client.reply_request(message.id,extension_reply)

    result=client.command('_ordessa/opaque_echo',timeout=2,on_request=answer_original_request,
                          **request_params)

    outgoing=next(message for direction,message in observed
                  if direction=='outgoing' and message.get('method')=='_ordessa/opaque_echo')
    reverse_reply=next(message for direction,message in observed
                       if direction=='outgoing' and message.get('result')==extension_reply)
    assert outgoing['params']==request_params
    assert type(outgoing['id']) is int
    assert reverse_reply=={'jsonrpc':'2.0','id':'vendor-request-42','result':extension_reply}
    assert result=={'_meta':{'vendor':{'opaque':{'response':True}}},
                    'vendorPayload':request_params}
    notification=client.next_event(timeout=2).raw
    assert notification=={'jsonrpc':'2.0','method':'_vendor/opaque_event',
        'params':{'_meta':{'vendor':{'opaque':['通知',{'x':1}]}},
                  'vendorPayload':{'extension':'kept'}}}


def test_missing_async_process_surface_refused():
    with pytest.raises(ValueError):ProcessChannel.attach(object(),name='invalid')
