"""N005 Claude Code client tests — L1 fake upstream (scripted stream-json).

Proves client-side record handling only; no real claude binary exists here
(L2 untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport import (
    ChannelClosed,
    LaunchSpec,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_harness_claude_code.stream_json import ClaudeCodeClient

PEER = textwrap.dedent(
    """
    import json, sys, time
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    mode = sys.argv[1]
    send({"type": "system", "subtype": "init", "model": "fake", "capabilities": ["interrupt_receipt_v1"]})
    send({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 3})  # upstream retry fact
    send({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}, "parent_tool_use_id": None})
    send({"type": "stream_event", "event": {"type": "text_delta", "text": "h"}, "parent_tool_use_id": None})
    send({"type": "future/unknownRecord", "keep": "verbatim"})
    if mode == "finish":
        send({"type": "result", "subtype": "success", "is_error": False, "result": "done", "session_id": "sess-9"})
    elif mode == "hang":
        time.sleep(60)
    while True:
        line = sys.stdin.readline()
        if not line:
            break
    """
)


def launch_client(tmp_path, mode):
    script = tmp_path / "fake_claude.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build([sys.executable, str(script), mode], home=str(tmp_path / "home"), cwd=str(tmp_path))
    channel = ProcessChannel.launch(spec, name=f"fake-claude-{mode}")
    return ClaudeCodeClient(channel), channel


def test_l1_initialize_reads_system_init_and_capabilities(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        init = client.initialize(timeout=5)
        assert init["model"] == "fake"
        assert client.capabilities == ("interrupt_receipt_v1",)
    finally:
        channel.close()


def test_l1_result_is_terminal_and_keeps_session_id(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        client.initialize(timeout=5)
        result = client.wait_result(timeout=5)
        assert result["session_id"] == "sess-9"
        assert result["result"] == "done"
    finally:
        channel.close()


def test_l1_unknown_records_and_api_retry_are_surfaced_verbatim(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        client.initialize(timeout=5)
        client.wait_result(timeout=5)
        types = [r.get("type") for r in client.records()]
        assert "future/unknownRecord" in types  # G4 unknown preserved
        retry = next(r for r in client.records() if r.get("subtype") == "api_retry")
        assert retry["attempt"] == 1  # upstream retry surfaced as a fact (G11: not hidden, not ours)
    finally:
        channel.close()


def test_l1_timeout_is_unknown_and_never_resends(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "hang")
    try:
        client.initialize(timeout=5)
        with pytest.raises(RequestTimeout):
            client.wait_result(timeout=1)
    finally:
        exit_code = channel.close()
        assert exit_code is not None  # owned process boundary is the evidence (G6)


def test_l1_close_then_use_is_channel_closed(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    client.initialize(timeout=5)
    channel.close()
    with pytest.raises(ChannelClosed):
        client.next_record(timeout=1)

# Wire structures follow upstream SDK source pinned in claude_code.SOURCE_COMMIT.
# These are fixture-peer protocol checks, not installed Claude/SDK observations.
from ordessa_agents.harness.transport import ChannelFailure, LostReceipt
from ordessa_harness_claude_code.stream_json import ClaudePermissionPending, ClaudeStreamFailure

DUPLEX = textwrap.dedent(r'''
import json, sys
mode, log = sys.argv[1:]
def send(value):
    print(json.dumps(value), flush=True)
def result(**fields):
    value = {"type":"result", "subtype":"success", "is_error":False, "session_id":"session-a", "result":"done"}
    value.update(fields);send(value)
for line in sys.stdin:
    raw=json.loads(line)
    with open(log,'a') as out: out.write(json.dumps(raw)+'\n')
    if raw['type']=='control_request':
        subtype=raw['request']['subtype']
        if subtype=='initialize':
            if mode=='lost-initialize':sys.exit(0)
            if mode=='startup-error':
                result(is_error=True,subtype='error_during_execution');sys.exit(1)
            send({'type':'control_response','response':{'subtype':'success','request_id':'another-request','response':{'wrong':True}}})
            send({'type':'control_response','response':{'subtype':'success','request_id':raw['request_id'],'response':{'commands':[]}}})
        elif subtype=='interrupt':
            send({'type':'control_response','response':{'subtype':'success','request_id':raw['request_id'],'response':{'still_queued':[]}}})
            result(terminal_reason='aborted_tools')
    elif raw['type']=='user':
        send({'type':'system','subtype':'init','session_id':'session-a','capabilities':['interrupt_receipt_v1']})
        if mode=='lost-user':sys.exit(0)
        if mode=='error':result(is_error=True,subtype='error_during_execution',errors=['native error'])
        elif mode=='cross-session':result(session_id='session-b')
        elif mode=='malformed':result(is_error='false')
        elif mode=='background':
            result(origin={'kind':'task-notification'},result='background')
            result(result='user turn')
        elif mode in ['permission','replay','cancel-permission']:
            callback={'type':'control_request','request_id':'permission-1','request':{'subtype':'can_use_tool','tool_name':'Bash','tool_use_id':'tool-1','input':{'command':'fixture only'}}}
            send(callback)
            if mode=='replay':send(callback)
            if mode=='cancel-permission':send({'type':'control_cancel_request','request_id':'permission-1'})
        elif mode=='finish':result()
    elif raw['type']=='control_response':
        assert raw['response']['request_id']=='permission-1'
        assert raw['response']['response']['behavior'] in ['allow','deny']
        result()
''')

def duplex(tmp_path, mode):
    script=tmp_path/'duplex.py';script.write_text(DUPLEX)
    log=tmp_path/'requests.jsonl'
    spec=LaunchSpec.build([sys.executable,str(script),mode,str(log)],home=str(tmp_path/'home'),cwd=str(tmp_path))
    channel=ProcessChannel.launch(spec,name='fixture-duplex')
    return ClaudeCodeClient(channel,bidirectional=True),channel,log

def writes(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

def test_duplex_control_initialize_and_native_user_shape(tmp_path):
    client,channel,log=duplex(tmp_path,'finish')
    try:
        assert client.initialize_control(timeout=2)=={'commands':[]}
        client.submit_user('fixture')
        result=client.wait_result(timeout=2)
        assert result['session_id']=='session-a'
        assert client.session_id=='session-a'
        assert client.wait_result(timeout=2)==result
        sent=writes(log)
        assert sent[0]['request']=={'subtype':'initialize','hooks':None}
        assert sent[1]=={'type':'user','message':{'role':'user','content':'fixture'},'parent_tool_use_id':None,'session_id':'default'}
        assert any(r.get('response',{}).get('request_id')=='another-request' for r in client.records())
        assert len(sent)==2
    finally:channel.close()

@pytest.mark.parametrize('decision',[{'behavior':'allow','updatedInput':{'command':'fixture only'}},{'behavior':'deny','message':'caller refused','interrupt':True}])
def test_explicit_approval_native_nested_response_once(tmp_path,decision):
    client,channel,log=duplex(tmp_path,'permission')
    try:
        client.initialize_control(timeout=2);client.submit_user('fixture')
        with pytest.raises(ClaudePermissionPending):client.wait_result(timeout=2)
        assert len(writes(log))==2
        pending=client.pending_permissions();assert pending[0]['request']['tool_use_id']=='tool-1'
        with pytest.raises(ChannelFailure):client.respond_permission('permission-1',decision,session_id='other')
        client.respond_permission('permission-1',decision,session_id='session-a')
        with pytest.raises(ChannelFailure):client.respond_permission('permission-1',decision,session_id='session-a')
        assert client.wait_result(timeout=2)['result']=='done'
        response=writes(log)[-1]
        assert response=={'type':'control_response','response':{'subtype':'success','request_id':'permission-1','response':decision}}
    finally:channel.close()

@pytest.mark.parametrize('mode,exception',[('error',ClaudeStreamFailure),('cross-session',LostReceipt),('malformed',LostReceipt),('lost-user',LostReceipt)])
def test_result_failure_identity_shape_and_disconnect(tmp_path,mode,exception):
    client,channel,log=duplex(tmp_path,mode)
    try:
        client.initialize_control(timeout=2);client.submit_user('fixture')
        with pytest.raises(exception):client.wait_result(timeout=2)
        assert len(writes(log))==2
        if mode!='error':
            with pytest.raises(ChannelFailure):client.submit_user('must not resend')
    finally:channel.close()

def test_background_result_does_not_complete_user_turn(tmp_path):
    client,channel,_=duplex(tmp_path,'background')
    try:
        client.initialize_control(timeout=2);client.submit_user('fixture')
        assert client.wait_result(timeout=2)['result']=='user turn'
        assert any(r.get('result')=='background' for r in client.records())
    finally:channel.close()

def test_interrupt_receipt_does_not_complete_pending_turn(tmp_path):
    client,channel,log=duplex(tmp_path,'interrupt')
    try:
        client.initialize_control(timeout=2);client.submit_user('fixture');client.initialize(timeout=2)
        assert client.interrupt(timeout=2)=={'still_queued':[]}
        with pytest.raises(ChannelFailure):client.submit_user('must not resend')
        assert client.wait_result(timeout=2)['terminal_reason']=='aborted_tools'
        assert writes(log)[-1]['request']=={'subtype':'interrupt'}
    finally:channel.close()

def test_unknown_initialize_cannot_be_resent(tmp_path):
    client,channel,log=duplex(tmp_path,'lost-initialize')
    try:
        with pytest.raises(LostReceipt):client.initialize_control(timeout=2)
        with pytest.raises(ChannelFailure):client.initialize_control(timeout=2)
        assert len(writes(log))==1
    finally:channel.close()

@pytest.mark.parametrize('mode',['replay','cancel-permission'])
def test_replayed_and_cancelled_permission_never_authorizes(tmp_path,mode):
    client,channel,log=duplex(tmp_path,mode)
    try:
        client.initialize_control(timeout=2);client.submit_user('fixture')
        with pytest.raises(ClaudePermissionPending):client.wait_result(timeout=2)
        if mode=='replay':
            with pytest.raises(Exception) as caught:client.next_record(timeout=2)
            assert caught.value.code=='FRAMING_ERROR'
        else:
            client.next_record(timeout=2)
            with pytest.raises(ChannelFailure):client.respond_permission('permission-1',{'behavior':'deny','message':'no'},session_id='session-a')
        assert len(writes(log))==2
    finally:channel.close()

def test_output_only_cannot_write_and_invalid_deadline_does_not_send(tmp_path):
    client,channel=launch_client(tmp_path,'finish')
    try:
        with pytest.raises(ChannelFailure):client.initialize_control()
        with pytest.raises(ChannelFailure):client.submit_user('fixture')
    finally:channel.close()
    client,channel,log=duplex(tmp_path,'finish')
    try:
        with pytest.raises(ValueError):client.initialize_control(timeout=float('nan'))
        assert writes(log)==[]
        client.initialize_control(timeout=2)
        with pytest.raises(ValueError):client.interrupt(timeout=-1)
        assert len(writes(log))==1
    finally:channel.close()

def test_startup_native_error_not_flattened_into_timeout(tmp_path):
    client,channel,log=duplex(tmp_path,'startup-error')
    try:
        with pytest.raises(ClaudeStreamFailure) as failure:client.initialize_control(timeout=2)
        assert failure.value.raw['subtype']=='error_during_execution'
        assert len(writes(log))==1
    finally:channel.close()

@pytest.mark.parametrize('operation',['user','permission'])
def test_partial_write_stays_unknown_and_is_not_resent(tmp_path,monkeypatch,operation):
    client,channel,log=duplex(tmp_path,'permission')
    try:
        client.initialize_control(timeout=2)
        if operation=='permission':
            client.submit_user('fixture')
            with pytest.raises(ClaudePermissionPending):client.wait_result(timeout=2)
        calls=[]
        def partial(payload):
            calls.append(payload)
            raise OSError('partial write fault')
        monkeypatch.setattr(channel,'send_raw',partial)
        if operation=='user':
            with pytest.raises(LostReceipt):client.submit_user('fixture')
            with pytest.raises(ChannelFailure):client.submit_user('must not resend')
        else:
            decision={'behavior':'deny','message':'explicit refusal'}
            with pytest.raises(LostReceipt):client.respond_permission('permission-1',decision,session_id='session-a')
            with pytest.raises(ChannelFailure):client.respond_permission('permission-1',decision,session_id='session-a')
        assert len(calls)==1
    finally:channel.close()

def test_result_success_subtype_with_error_flag_is_failure(tmp_path):
    client,channel=launch_client(tmp_path,'finish')
    try:
        client.initialize(timeout=2)
        with pytest.raises(ClaudeStreamFailure):
            client._checked_result({'type':'result','session_id':'sess-9','subtype':'success','is_error':True})
    finally:channel.close()
