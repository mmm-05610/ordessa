"""Pure native Pi JSONL values; no ACP translation or session/runtime owner.

Pinned local evidence: acp-adapter/internal/pi/client.go request/writeJSON,
newSession/getState/prompt/abort and testdata/fake_pi_rpc rpcInput. Requests put
native parameters at the TOP LEVEL beside id/type; command/success/data belong
to responses. Caller supplies correlation and owns original guarded I/O.
"""
import json
import math

MAX_FRAME_BYTES=1048576
MAX_DEPTH=32


class PiRpcFrameError(ValueError):
    """Bounded codec refusal; diagnostics never include the input contents."""


def _text(value,limit):
    if (type(value) is not str or not value or value.strip()!=value or len(value)>limit
            or any(ord(char)<32 for char in value)):
        raise PiRpcFrameError('native identifier invalid')
    try:value.encode('utf-8')
    except UnicodeError:raise PiRpcFrameError('native identifier invalid') from None
    return value


def _finite(value,depth=0):
    if depth>MAX_DEPTH:raise PiRpcFrameError('native JSON depth exceeded')
    if value is None or type(value) in (bool,int):return
    if type(value) is str:
        try:value.encode('utf-8')
        except UnicodeError:raise PiRpcFrameError('native UTF8 invalid') from None
        return
    if type(value) is float and math.isfinite(value):return
    if type(value) is list:
        for item in value:_finite(item,depth+1)
        return
    if type(value) is dict:
        for key,item in value.items():
            if type(key) is not str:raise PiRpcFrameError('native JSON key invalid')
            _finite(key,depth+1);_finite(item,depth+1)
        return
    raise PiRpcFrameError('native finite JSON required')


def encode_request(request_id,command,params=None):
    """Encode an externally correlated native request, with exactly one LF."""
    _text(request_id,512);_text(command,128)
    if params is None:params={}
    if type(params) is not dict or {'id','type'} & set(params):
        raise PiRpcFrameError('native request parameters invalid')
    value={'id':request_id,'type':command,**params}
    _finite(value)
    try:raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')+b'\n'
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise PiRpcFrameError('native request encoding invalid') from None
    if len(raw)>MAX_FRAME_BYTES:raise PiRpcFrameError('native frame too large')
    return raw


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise PiRpcFrameError('native duplicate JSON key')
        result[key]=value
    return result


def _nonfinite(value):
    raise PiRpcFrameError('native finite JSON required')


def decode_frame(raw):
    """Decode exactly one complete LF frame; preserve native event fields."""
    if type(raw) is not bytes or not raw or len(raw)>MAX_FRAME_BYTES:
        raise PiRpcFrameError('native bounded byte frame required')
    if not raw.endswith(b'\n') or b'\n' in raw[:-1]:
        raise PiRpcFrameError('native single LF frame required')
    try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_nonfinite)
    except (UnicodeError,ValueError,TypeError,RecursionError):
        raise PiRpcFrameError('native frame JSON invalid') from None
    if type(value) is not dict:raise PiRpcFrameError('native object frame required')
    _text(value.get('type'),128);_finite(value)
    return value


def validate_response(frame,request_id,command):
    """Check exact native correlation, preserving success OR failure data.

    A successful prompt command response is not an agent_end event and this
    function does not complete an Agent turn or supply an execution permission.
    """
    _text(request_id,512);_text(command,128)
    if (type(frame) is not dict or frame.get('type')!='response'
            or frame.get('id')!=request_id or frame.get('command')!=command
            or type(frame.get('success')) is not bool):
        raise PiRpcFrameError('native response correlation invalid')
    _finite(frame)
    if frame['success'] is False and (type(frame.get('error')) is not str or not frame['error']):
        raise PiRpcFrameError('native failure response invalid')
    return dict(frame)


__all__=['MAX_FRAME_BYTES','PiRpcFrameError','encode_request','decode_frame','validate_response']
