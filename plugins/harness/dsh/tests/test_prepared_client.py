"""C: one-shot native ACP frames, controlled channels and temporary Python peers.

No dsh executable, model, production input owner or authority is involved.
"""
import copy
import hashlib
import json
import sys
from collections import deque

import pytest

from ordessa_harness_dsh.client import DshAcpClient, DshRpcError
from ordessa_agents.harness.transport import (
    ChannelClosed, LaunchSpec, LostReceipt, Message, PreparedFrameRefused,
    ProcessChannel, RequestTimeout, WriterLeaseRefused,
)


class Channel:
    def __init__(self, replies=()):
        self.replies = deque(replies)
        self.sent, self.fences, self.closed = [], 0, False
        self.write_error = None
        self.acks = []

    def send_frame(self, wire, *, before_write):
        before_write()
        if self.fences:
            raise WriterLeaseRefused("unresolved")
        self.sent.append(wire)
        if self.write_error:
            raise self.write_error

    def acknowledge_frame(self, request_id):
        self.acks.append(request_id)

    def mark_input_unknown(self):
        self.fences += 1

    def next_message(self, *, timeout):
        if self.replies:
            return Message(self.replies.popleft())
        raise RequestTimeout("controlled", None, timeout)

    def close(self):
        self.closed = True
        return 0


def prompt_frame(client):
    return client.prepare_request(
        "session/prompt",
        {"sessionId": "ses-original", "content": [{"type": "text", "text": "原输入\n"}]})


def receipt(native_id="req-1", stop="end_turn"):
    return {"jsonrpc": "2.0", "id": native_id, "result": {"stopReason": stop}}


def test_prepare_has_exact_native_bytes_digest_without_pending_or_send():
    channel = Channel()
    client = DshAcpClient(channel)
    params = {"sessionId": "ses-original", "content": [{"type": "text", "text": "原输入\n"}]}
    frame = client.prepare_request("session/prompt", params)
    original = frame.frame_bytes
    params["content"][0]["text"] = "changed"
    detached = frame.payload
    detached["params"]["content"][0]["text"] = "also changed"
    assert frame.protocol == "dsh-acp/1" and frame.request_id == "req-1"
    assert original == b'{"jsonrpc":"2.0","id":"req-1","method":"session/prompt","params":{"sessionId":"ses-original","content":[{"type":"text","text":"' + "原输入".encode() + b'\\n"}]}}\n'
    assert frame.frame_bytes == original
    assert frame.frame_digest == "sha256:" + hashlib.sha256(original).hexdigest()
    assert client._pending == {} and client._prompt_requests == {} and channel.sent == []


def test_dispatch_preserves_frame_original_session_and_one_shot_identity():
    channel = Channel([receipt()])
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    seen = []
    result = client.dispatch_prepared(frame, before_write=lambda _wire=None: seen.append(dict(client._pending)))
    assert seen == [{"req-1": "session/prompt"}]
    assert channel.sent == [frame.frame_bytes] and result == {"stopReason": "end_turn"}
    assert client._pending == {} and client._prompt_requests == {}
    with pytest.raises(PreparedFrameRefused):
        client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert len(channel.sent) == 1


@pytest.mark.parametrize("damage", ["copy", "deepcopy", "foreign", "tamper-bytes", "tamper-digest", "tamper-id", "tamper-protocol", "broken-json"])
def test_foreign_copied_and_tampered_frames_cannot_dispatch(damage):
    channel = Channel([receipt()])
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    if damage == "copy": frame = copy.copy(frame)
    elif damage == "deepcopy": frame = copy.deepcopy(frame)
    elif damage == "foreign": frame = prompt_frame(DshAcpClient(Channel()))
    elif damage == "tamper-bytes": object.__setattr__(frame, "_wire", frame.frame_bytes.replace(b"ses-original", b"ses-forged"))
    elif damage == "tamper-digest": object.__setattr__(frame, "_digest", "sha256:forged")
    elif damage == "tamper-protocol": object.__setattr__(frame, "_protocol", "foreign-native/1")
    elif damage == "broken-json": object.__setattr__(frame, "_wire", b'not-json\n')
    else: object.__setattr__(frame, "_request_id", "req-forged")
    with pytest.raises(PreparedFrameRefused):
        client.dispatch_prepared(frame, before_write=lambda _wire=None: pytest.fail("must not reach guard"))
    assert channel.sent == [] and client._pending == {}


def test_local_guard_argument_error_does_not_spend_original_frame():
    channel = Channel([receipt()])
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    with pytest.raises(ValueError): client.dispatch_prepared(frame, before_write=None)
    client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert channel.sent == [frame.frame_bytes]


@pytest.mark.parametrize("method,params", [
    ("session/prompt", {}),
    ("session/prompt", {"sessionId": None}),
    ("session/prompt", {"sessionId": ""}),
    ("session/prompt", {"sessionId": True}),
    ("session/cancel", {}),
    ("session/resume", {"sessionId": ""}),
    ("session/close", {}),
    ("session/set_config_option", {"configId": "model"})])
def test_invalid_session_target_is_refused_before_frame_and_id_allocation(method, params):
    client = DshAcpClient(Channel())
    with pytest.raises(ValueError): client.prepare_request(method, params)
    assert client._request_seq == 0 and client._pending == {} and client._prepared_requests == {}


def test_guard_failure_spends_handle_preserves_error_and_fences_new_input():
    channel = Channel()
    client = DshAcpClient(channel)
    frame, later = prompt_frame(client), prompt_frame(client)
    error = RuntimeError("original permission revoked")
    def guard(wire): raise error
    with pytest.raises(RuntimeError) as caught: client.dispatch_prepared(frame, before_write=guard)
    assert caught.value is error and channel.sent == [] and channel.fences == 1
    assert client._pending == {"req-1": "session/prompt"}
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=guard)
    with pytest.raises(LostReceipt): client.dispatch_prepared(later, before_write=lambda _wire=None: None)


@pytest.mark.parametrize("failure", ["timeout", "partial-write", "malformed"])
def test_unknown_retains_original_pending_and_never_resends_even_after_late_receipt(failure):
    channel = Channel([{"jsonrpc": "2.0", "id": "req-1", "result": {}}] if failure == "malformed" else [])
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    if failure == "partial-write": channel.write_error = ChannelClosed("partial delivery")
    expected = {"timeout": RequestTimeout, "partial-write": ChannelClosed, "malformed": LostReceipt}[failure]
    with pytest.raises(expected): client.dispatch_prepared(frame, before_write=lambda _wire=None: None, timeout=.01)
    assert channel.sent == [frame.frame_bytes] and channel.fences == 1
    assert client._pending == {"req-1": "session/prompt"}
    channel.replies.append(receipt())
    assert client.recover_request("req-1", timeout=.1) == {"stopReason": "end_turn"}
    assert len(channel.sent) == 1 and client._pending == {}
    with pytest.raises(LostReceipt): client.dispatch_prepared(prompt_frame(client), before_write=lambda _wire=None: None)


def test_original_error_is_preserved_if_transport_unknown_cut_also_fails():
    channel = Channel()
    channel.mark_input_unknown = lambda: (_ for _ in ()).throw(WriterLeaseRefused("already revoked"))
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    error = RuntimeError("original guard error")
    with pytest.raises(RuntimeError) as caught:
        client.dispatch_prepared(frame, before_write=lambda _wire=None: (_ for _ in ()).throw(error))
    assert caught.value is error and client._prepared_unknown and channel.sent == []


def test_known_native_error_spends_frame_without_unknown_fence_or_auto_retry():
    channel = Channel([{"jsonrpc": "2.0", "id": "req-1", "error": {"code": -32601, "message": "refused"}},
                       receipt("req-2")])
    client = DshAcpClient(channel)
    first = prompt_frame(client)
    with pytest.raises(DshRpcError): client.dispatch_prepared(first, before_write=lambda _wire=None: None)
    assert channel.fences == 0 and client._pending == {}
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(first, before_write=lambda _wire=None: None)
    client.dispatch_prepared(prompt_frame(client), before_write=lambda _wire=None: None)
    assert len(channel.sent) == 2


def test_close_revokes_unused_frames_before_native_channel_close():
    channel = Channel()
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    assert client.close() == 0 and channel.closed
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    with pytest.raises(PreparedFrameRefused): prompt_frame(client)
    assert channel.sent == []


@pytest.mark.parametrize("method", ["session/prompt", "session/set_config_option"])
def test_preexisting_unknown_request_rejects_prepared_write_without_consuming(method):
    channel = Channel()
    client = DshAcpClient(channel)
    client._pending["original"] = method
    params = ({"sessionId": "ses-original"} if method == "session/prompt"
              else {"sessionId": "ses-original", "configId": "model", "value": "new"})
    frame = client.prepare_request(method, params)
    with pytest.raises(LostReceipt): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert client._prepared_requests[id(frame)] is frame and channel.sent == []


PEER = '''import json,sys
for line in sys.stdin.buffer:
    msg=json.loads(line)
    if msg['method']=='lost':
        reply={'jsonrpc':'2.0','method':'received','params':{'hex':line.hex()}}
    else:
        reply={'jsonrpc':'2.0','id':msg['id'],'result':{'hex':line.hex()}}
    sys.stdout.write(json.dumps(reply)+'\\n');sys.stdout.flush()
'''


def peer(tmp_path, *, managed=False):
    script = tmp_path / "peer.py"
    script.write_text(PEER, encoding="utf-8")
    return ProcessChannel.launch(LaunchSpec.build([sys.executable, str(script)],
        home=str(tmp_path / "home"), cwd=str(tmp_path)), name="controlled-prepared", managed=managed)


def test_temporary_python_peer_receives_exact_prepared_utf8_lf(tmp_path):
    channel = peer(tmp_path)
    client = DshAcpClient(channel)
    try:
        frame = client.prepare_request("echo", {"text": "原输入\n", "nested": {"number": 1}})
        result = client.dispatch_prepared(frame, before_write=lambda _wire=None: None, timeout=5)
        assert bytes.fromhex(result["hex"]) == frame.frame_bytes
        assert client._pending == {}
    finally: client.close()


def test_temporary_python_peer_lost_receipt_retains_original_bytes_and_transport_fence(tmp_path):
    channel = peer(tmp_path)
    client = DshAcpClient(channel)
    try:
        frame = client.prepare_request("lost", {"text": "once"})
        with pytest.raises(RequestTimeout): client.dispatch_prepared(frame, before_write=lambda _wire=None: None, timeout=.2)
        received = next(event for event in client.events() if event.get("method") == "received")
        assert bytes.fromhex(received["params"]["hex"]) == frame.frame_bytes
        assert client._pending == {frame.request_id: "lost"}
        with pytest.raises(WriterLeaseRefused): channel.send_frame(frame.frame_bytes, before_write=lambda _wire=None: None)
        with pytest.raises(LostReceipt): client.dispatch_prepared(client.prepare_request("echo", {}), before_write=lambda _wire=None: None)
    finally: client.close()


def test_temporary_python_peer_guard_revokes_managed_lease_before_actual_write(tmp_path):
    channel = peer(tmp_path, managed=True)
    client = DshAcpClient(channel.bind_writer(channel.acquire_writer()))
    try:
        frame = client.prepare_request("echo", {})
        with pytest.raises(WriterLeaseRefused): client.dispatch_prepared(frame, before_write=lambda wire: channel.fence_all())
        assert client.events() == () and channel.poll_message(timeout=.05) is None
        assert client._pending == {frame.request_id: "echo"}
        with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
        # A guard-revoked writer cannot make the channel available by itself.
        with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
        with pytest.raises(LostReceipt): client.dispatch_prepared(client.prepare_request("echo", {}), before_write=lambda _wire=None: None)
    finally:
        client.close()
        channel.close()


def test_prepared_reverse_request_callback_preserves_original_rpc_id_and_caller_reply():
    channel = Channel([{"jsonrpc": "2.0", "id": 42, "method": "future/ask", "params": {"keep": True}}, receipt()])
    replies = []
    channel.reply = lambda native_id, result: replies.append((native_id, result))
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    seen = []
    def answer(message):
        seen.append(message.raw)
        client.reply_request(message.id, {"native": "answer"})
    client.dispatch_prepared(frame, before_write=lambda _wire=None: None, on_request=answer)
    assert seen == [{"jsonrpc": "2.0", "id": 42, "method": "future/ask", "params": {"keep": True}}]
    assert replies == [(42, {"native": "answer"})] and channel.sent == [frame.frame_bytes]


def test_ordinary_command_and_prepared_frame_share_actual_id_allocator():
    channel = Channel([{"jsonrpc": "2.0", "id": "req-2", "result": {"ordinary": True}}, receipt()])
    raw = []
    channel.send_raw = lambda payload: raw.append(payload)
    client = DshAcpClient(channel)
    first = prompt_frame(client)
    assert client.command("ordinary") == {"ordinary": True}
    assert raw == [{"jsonrpc": "2.0", "id": "req-2", "method": "ordinary"}]
    client.dispatch_prepared(first, before_write=lambda _wire=None: None)
    assert channel.sent == [first.frame_bytes] and client._pending == {}


@pytest.mark.parametrize('source', ['guard', 'callback'])
@pytest.mark.parametrize('identity', ['same', 'foreign'])
def test_rpc_error_class_from_callback_is_not_native_receipt(source, identity):
    channel = Channel([{'jsonrpc': '2.0', 'id': 'server-original', 'method': 'approval', 'params': {}}, receipt()])
    client = DshAcpClient(channel)
    frame = prompt_frame(client)
    error = DshRpcError('session/prompt', frame.request_id if identity == 'same' else 'foreign', {'code': -1})
    def refuse(_): raise error
    with pytest.raises(DshRpcError) as caught:
        client.dispatch_prepared(frame, before_write=refuse if source == 'guard' else lambda wire: None,
                                 on_request=refuse if source == 'callback' else None)
    assert caught.value is error and channel.fences == 1 and channel.acks == []
    assert client._pending == {frame.request_id: 'session/prompt'} and client._prepared_unknown
    assert len(channel.sent) == (source == 'callback')


@pytest.mark.parametrize('missing', ['send_frame', 'mark_input_unknown', 'acknowledge_frame'])
def test_command_once_missing_actual_barrier_refuses_before_identity_or_bind(missing):
    channel = Channel([{'jsonrpc': '2.0', 'id': 'req-1', 'result': {}}])
    setattr(channel, missing, None)
    client = DshAcpClient(channel)
    with pytest.raises(PreparedFrameRefused):
        client.command_once('session/set_config_option',
                            {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'},
                            before_send=lambda payload: pytest.fail('no barrier'))
    assert client._request_seq == 0 and client._pending == {} and channel.sent == []


@pytest.mark.parametrize('identity', ['same', 'foreign'])
def test_command_once_guard_error_class_without_pending_is_not_native_receipt(identity):
    channel = Channel(); client = DshAcpClient(channel)
    error = DshRpcError('session/set_config_option', 'req-1' if identity == 'same' else 'foreign', {'code': -1})
    def refuse(payload): raise error
    with pytest.raises(DshRpcError) as caught:
        client.command_once('session/set_config_option',
                            {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'}, before_send=refuse)
    assert caught.value is error and client._pending == {} and channel.sent == []
    assert channel.acks == [] and channel.fences == 1 and client._prepared_unknown
    with pytest.raises(LostReceipt):
        client.command_once('session/set_config_option',
                            {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'},
                            before_send=lambda payload: None)


def test_command_once_actual_native_rejection_acks_original_receipt_only():
    channel = Channel([{'jsonrpc': '2.0', 'id': 'req-1', 'error': {'code': -1, 'message': 'native rejection'}},
                       {'jsonrpc': '2.0', 'id': 'req-2', 'result': {'configOptions': []}}])
    client = DshAcpClient(channel); bindings = []
    with pytest.raises(DshRpcError):
        client.command_once('session/set_config_option',
                            {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'}, before_send=bindings.append)
    assert channel.acks == ['req-1'] and channel.fences == 0 and not client._prepared_unknown
    assert client._pending == {} and len(channel.sent) == 1 and bindings[0]['id'] == 'req-1'
    assert client.command_once('session/set_config_option',
                               {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'},
                               before_send=bindings.append) == {'configOptions': []}
    assert channel.acks == ['req-1', 'req-2'] and len(channel.sent) == 2


def test_command_once_actual_guard_revokes_writer_without_native_write(tmp_path):
    channel = peer(tmp_path, managed=True)
    client = DshAcpClient(channel.bind_writer(channel.acquire_writer()))
    seen = []
    def guard(payload):
        seen.append(payload)
        channel.fence_all()
    try:
        with pytest.raises(WriterLeaseRefused):
            client.command_once('session/set_config_option',
                                {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'}, before_send=guard)
        assert len(seen) == 1 and seen[0]['id'] == 'req-1'
        assert channel.poll_message(timeout=.02) is None
        assert client._pending == {'req-1': 'session/set_config_option'} and channel._unresolved
        with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    finally:
        client.close(); channel.close()


def test_command_once_revoke_while_waiting_and_late_ack_cannot_handoff(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    channel = peer(tmp_path, managed=True)
    view = channel.bind_writer(channel.acquire_writer())
    client = DshAcpClient(view)
    waiting, observe = Event(), Event()
    next_message = view.next_message
    def hold_receipt(*, timeout):
        waiting.set()
        assert observe.wait(2)
        return next_message(timeout=timeout)
    view.next_message = hold_receipt
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.command_once, 'session/set_config_option',
                                 {'sessionId': 'ses-1', 'configId': 'model', 'value': 'new'},
                                 before_send=lambda payload: None)
            assert waiting.wait(2)
            channel.fence_all()
            with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
            observe.set()
            result = future.result(timeout=2)
        received = bytes.fromhex(result['hex'])
        assert json.loads(received)['id'] == 'req-1'
        assert channel._prepared_inflight == {} and channel._unresolved
        with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
    finally:
        observe.set()
        client.close(); channel.close()


@pytest.mark.parametrize('params', [{}, {'sessionId': None}, {'sessionId': ''}, {'sessionId': True}])
def test_command_once_invalid_session_target_refuses_before_binding_or_identity(params):
    channel = Channel(); client = DshAcpClient(channel)
    with pytest.raises(ValueError):
        client.command_once('session/prompt', params, before_send=lambda payload: pytest.fail('invalid target bound'))
    assert client._request_seq == 0 and client._pending == {} and channel.sent == []
    assert channel.acks == [] and channel.fences == 0
