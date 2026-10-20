"""Golden native Pi frames from the actual request side, never ACP envelopes."""
import json
import math

import pytest

from ordessa_harness_pi.rpc_frames import (
    MAX_FRAME_BYTES,PiRpcFrameError,encode_request,decode_frame,validate_response,
)


@pytest.mark.parametrize('command,params',[
    ('new_session',{}),('get_state',{}),('abort',{}),
    ('prompt',{'message':'hello','images':[{'type':'image','data':'controlled','mimeType':'image/png'}]}),
    ('set_model',{'provider':'fixture','modelId':'model-1'}),
    ('set_thinking_level',{'level':'low'}),
    ('switch_session',{'sessionPath':'/controlled/session.jsonl'}),
])
def test_real_request_parameters_are_top_level_native_fields(command,params):
    raw=encode_request('caller-1',command,params)
    assert raw.endswith(b'\n') and raw.count(b'\n')==1
    value=json.loads(raw)
    assert value=={'id':'caller-1','type':command,**params}
    assert 'command' not in value and 'data' not in value and 'jsonrpc' not in value


def test_exact_get_state_golden_and_observed_session_identity():
    assert encode_request('pi-rpc-1','get_state')==b'{"id":"pi-rpc-1","type":"get_state"}\n'
    raw=b'{"type":"response","id":"pi-rpc-1","command":"get_state","success":true,"data":{"sessionId":"original-session","sessionFile":"/controlled/session.jsonl"}}\n'
    frame=validate_response(decode_frame(raw),'pi-rpc-1','get_state')
    assert frame['data']['sessionId']=='original-session'
    assert frame['data']['sessionFile']=='/controlled/session.jsonl'


def test_native_failure_response_preserved_instead_of_becoming_success():
    frame=decode_frame(b'{"type":"response","id":"x","command":"prompt","success":false,"error":"controlled refusal","extra":{"reason":"native"}}\n')
    result=validate_response(frame,'x','prompt')
    assert result==frame and result['success'] is False and result['extra']=={'reason':'native'}


@pytest.mark.parametrize('event',[
    {'type':'message_update','message':{'role':'assistant'},'assistantMessageEvent':{'type':'text_delta','delta':'native'}},
    {'type':'agent_end','messages':[]},
    {'type':'extension_ui_request','id':'extension-1','method':'confirm','title':'native permission','timeout':0.25},
])
def test_interleaved_native_events_are_not_responses_or_translated(event):
    frame=decode_frame(json.dumps(event,separators=(',',':')).encode()+b'\n')
    assert frame==event
    with pytest.raises(PiRpcFrameError):validate_response(frame,'command-1','prompt')


def test_unicode_separators_inside_strings_are_not_frame_delimiters():
    text='before\u2028middle\u2029after\nend'
    frame=encode_request('unicode','prompt',{'message':text})
    assert b'\xe2\x80\xa8' in frame and b'\xe2\x80\xa9' in frame
    assert frame.count(b'\n')==1 and decode_frame(frame)['message']==text


@pytest.mark.parametrize('raw',[
    b'',b'{}',b'{"type":"response"}',b'{}\n{}\n',b'[]\n',b'null\n',
    b'{"type":"response","id":"x","id":"other"}\n',
    b'{"type":"response","data":{"value":NaN}}\n',
    b'{"type":"response","data":{"value":1e999}}\n',
    b'{"type":"response","data":"\xff"}\n',b'{"type":"response","data":"\\ud800"}\n',
    b'{"type":"response","data":'+b'['*40+b'0'+b']'*40+b'}\n',
])
def test_malformed_incomplete_duplicate_nonfinite_and_deep_frames_refuse(raw):
    with pytest.raises(PiRpcFrameError):decode_frame(raw)


@pytest.mark.parametrize('changed',[
    {'id':'other'},{'command':'get_state'},{'success':1},{'success':None},{'type':'agent_end'},
])
def test_response_requires_exact_id_command_and_boolean_success(changed):
    frame={'type':'response','id':'original','command':'prompt','success':True,**changed}
    with pytest.raises(PiRpcFrameError):validate_response(frame,'original','prompt')


@pytest.mark.parametrize('params',[{'id':'override'},{'type':'response'},{'value':float('inf')},{'value':float('nan')},{1:'key'}])
def test_request_refuses_reserved_identity_or_nonfinite_values(params):
    with pytest.raises(PiRpcFrameError):encode_request('original','get_state',params)


def test_oversized_frames_refuse_without_truncation_or_partial_emit():
    with pytest.raises(PiRpcFrameError):encode_request('large','prompt',{'message':'x'*MAX_FRAME_BYTES})
    with pytest.raises(PiRpcFrameError):decode_frame(b' '*MAX_FRAME_BYTES+b'\n')


def test_command_response_does_not_assert_prompt_turn_completion():
    response={'type':'response','id':'prompt-1','command':'prompt','success':True}
    assert validate_response(decode_frame(json.dumps(response).encode()+b'\n'),'prompt-1','prompt')==response
    assert 'state' not in response and response['type']!='agent_end'
