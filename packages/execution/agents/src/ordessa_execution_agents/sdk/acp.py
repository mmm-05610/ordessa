"""One ACP prompt request and its original bounded response observations.

No spawn, authority, reverse-request answer, retry or bootstrap fallback. This
slice consumes an already established original fixed session. Initialize/new/load
remain the preparation owner's work; protocols needing another outbound frame
(permission/files/terminal replies included) are explicitly unsupported here.
"""
import asyncio
import hashlib
import json
from .endpoint import ProtocolEventPage
from .prepare import canonical_json

MAX_PROTOCOL_BYTES=192*1024
MAX_PROTOCOL_FRAMES=128


def prompt_frame(params_bytes,operation_ref):
    return (canonical_json({'jsonrpc':'2.0','id':operation_ref,'method':'session/prompt',
        'params':json.loads(params_bytes)})+'\n').encode('utf-8')


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate key')
        result[key]=value
    return result


async def _observe_rpc(receive, *, operation_ref,session_id,deadline,invocation,delivery,response_kind):
    frames=[];pending=b'';size=0;cursor=None;seen_cursors=set();terminal=None
    observation={**delivery,'protocol':{'protocolId':'acp','frames':frames}}
    def unknown(reason):
        observation['protocol']['reason']=reason
        return 'unknown',observation
    try:
        for _ in range(MAX_PROTOCOL_FRAMES):
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:return unknown('response_timeout')
            page=await asyncio.wait_for(receive(cursor,deadline,invocation),remaining)
            if type(page) is not ProtocolEventPage:return unknown('invalid_event_page')
            if not page.events:
                if terminal is not None and not page.has_more and not pending:return terminal,observation
                return unknown('response_unavailable')
            for event in page.events:
                if (event.kind!='bytes' or event.payload_digest!='sha256:'+hashlib.sha256(event.payload_bytes).hexdigest()):
                    return unknown('invalid_protocol_event')
                size+=len(event.payload_bytes)
                if size>MAX_PROTOCOL_BYTES:return unknown('protocol_observation_limit')
                pending+=event.payload_bytes
            while b'\n' in pending:
                raw,pending=pending.split(b'\n',1)
                if not raw:return unknown('invalid_protocol_frame')
                try:
                    value=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,
                        parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                    # Re-encode to reject non-JSON, excessive recursion and NaN.
                    canonical_json(value)
                except (ValueError,UnicodeDecodeError,RecursionError):return unknown('invalid_protocol_frame')
                if type(value) is not dict or value.get('jsonrpc')!='2.0':return unknown('invalid_protocol_frame')
                frames.append(value)
                if len(frames)>MAX_PROTOCOL_FRAMES:return unknown('protocol_observation_limit')
                if 'method' in value:
                    if 'id' in value:return unknown('reverse_request_unsupported')
                    params=value.get('params')
                    method=value['method']
                    if type(method) is not str or type(params) is not dict:return unknown('invalid_protocol_notification')
                    if method=='session/update':
                        if session_id is None or params.get('sessionId')!=session_id:return unknown('notification_session_mismatch')
                    elif method.startswith('_'):
                        if 'sessionId' in params and params['sessionId']!=session_id:return unknown('notification_session_mismatch')
                    else:return unknown('notification_unsupported')
                    continue  # preserve full notification and _meta/unknown extension fields
                if terminal is not None:return unknown('duplicate_protocol_response')
                if value.get('id')!=operation_ref:return unknown('response_id_mismatch')
                if ('result' in value)==('error' in value):return unknown('invalid_protocol_response')
                # Trailing bytes cannot be silently assigned to this or a later
                # turn. This minimal one-turn owner has no cross-turn spool.
                if 'error' in value:
                    error=value['error']
                    if (type(error) is not dict or type(error.get('code')) is not int
                            or type(error.get('message')) is not str):return unknown('invalid_protocol_error')
                    terminal='failed'
                    continue
                result=value['result']
                if type(result) is not dict:return unknown('invalid_protocol_result')
                if response_kind=='prompt':
                    stop=result.get('stopReason')
                    if type(stop) is not str or not stop:return unknown('invalid_prompt_result')
                    # Original DSH/Grok terminal fence: an error/cancelled
                    # result is a native failure, never successful dispatch.
                    # Future/nonterminal vocabulary cannot invent completion.
                    if stop in ('error','cancelled'):terminal='failed'
                    elif stop=='end_turn':terminal='completed'
                    else:return unknown('unknown_prompt_stop_reason')
                elif response_kind=='native':pass
                elif response_kind=='initialize':
                    if type(result.get('protocolVersion')) is not int or result['protocolVersion']!=1:return unknown('protocol_version_mismatch')
                elif response_kind=='session/new':
                    native=result.get('sessionId')
                    if type(native) is not str or not native or len(native)>512 or any(ord(c)<32 or ord(c)==127 for c in native):return unknown('invalid_native_session')
                    session_id=native
                else:return unknown('protocol_phase_unsupported')
                if response_kind!='prompt':terminal='completed'
            if page.has_more:
                if page.cursor in seen_cursors:return unknown('repeated_protocol_cursor')
                seen_cursors.add(page.cursor)
            elif terminal is not None:
                if pending:return unknown('trailing_protocol_bytes_unsupported')
                return terminal,observation
            cursor=page.cursor
        return unknown('protocol_observation_limit')
    except asyncio.CancelledError:
        raise
    except Exception:
        return unknown('protocol_receive_unavailable')


async def observe_prompt(receive, *, operation_ref,session_id,deadline,invocation,delivery):
    return await _observe_rpc(receive,operation_ref=operation_ref,session_id=session_id,deadline=deadline,
        invocation=invocation,delivery=delivery,response_kind='prompt')


async def observe_bootstrap(receive, *, operation_ref,phase,deadline,invocation,delivery):
    return await _observe_rpc(receive,operation_ref=operation_ref,session_id=None,deadline=deadline,
        invocation=invocation,delivery=delivery,response_kind=phase)


async def observe_native(receive,*,operation_ref,session_id,deadline,invocation,delivery):
    return await _observe_rpc(receive,operation_ref=operation_ref,session_id=session_id,deadline=deadline,
        invocation=invocation,delivery=delivery,response_kind='native')
