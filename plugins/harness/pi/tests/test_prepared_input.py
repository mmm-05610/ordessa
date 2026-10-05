"""Frozen native primitive C; no input authority, journal or model."""
import copy
import hashlib
import json
import sys
from collections import deque

import pytest

from ordessa_harness_pi.client import PiRpcClient
from ordessa_harness_transport import (PreparedFrameRefused, Message, RequestTimeout,
                                      LostReceipt, ChannelClosed, LaunchSpec, ProcessChannel)


class Channel:
    def __init__(self, *frames):
        self.frames, self.sent, self.unknown = deque(frames), [], 0
        self.error = None
        self.acks = []

    def send_frame(self, wire, *, before_write):
        before_write()
        self.sent.append(wire)
        if self.error:
            raise self.error

    def send_raw(self, payload):
        self.sent.append(payload)

    def next_message(self, *, timeout):
        if not self.frames:
            raise RequestTimeout('controlled-peer', None, timeout)
        return Message(raw=self.frames.popleft())

    def acknowledge_frame(self, request_id):
        self.acks.append(request_id)

    def mark_input_unknown(self):
        self.unknown += 1

    def close(self):
        return 0


def receipt(n=1, command='prompt', **fields):
    return {'id': f'req-{n}', 'type': 'response', 'command': command, 'success': True, **fields}


def test_prepare_freezes_actual_id_utf8_bytes_without_send_or_pending():
    channel = Channel(receipt())
    client = PiRpcClient(channel)
    fields = {'message': '你好\n原始', 'images': [{'future': 1}]}
    frame = client.prepare_request('prompt', fields)
    fields['images'][0]['future'] = 2
    assert frame.payload == {'id': 'req-1', 'type': 'prompt', 'message': '你好\n原始', 'images': [{'future': 1}]}
    assert frame.frame_digest == 'sha256:' + hashlib.sha256(frame.frame_bytes).hexdigest()
    assert frame.frame_bytes.endswith(b'\n') and client.pending == {} and channel.sent == []
    calls = []
    assert client.dispatch_prepared(frame, before_write=lambda _wire=None: calls.append(frame.request_id)) == receipt()
    assert calls == ['req-1'] and channel.sent == [frame.frame_bytes]
    assert client.pending == {} and client._run_state == 'accepted'
    with pytest.raises(PreparedFrameRefused):
        client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert len(channel.sent) == 1


@pytest.mark.parametrize('fields', [{'id': 'forged'}, {'type': 'prompt'}, None])
def test_prepare_rejects_identity_override_and_bad_fields(fields):
    client = PiRpcClient(Channel())
    with pytest.raises(ValueError): client.prepare_request('prompt', fields)
    assert client.pending == {}


@pytest.mark.parametrize('command', ['', None, 'prompt\n'])
def test_prepare_rejects_bad_method(command):
    with pytest.raises(ValueError): PiRpcClient(Channel()).prepare_request(command, {})


@pytest.mark.parametrize('damage', ['copy', 'deepcopy', 'other-client', 'bytes', 'id', 'digest', 'protocol'])
def test_copied_cross_client_and_tampered_frames_never_write(damage):
    channel = Channel(receipt())
    client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'fixed'})
    target = client
    if damage == 'copy': frame = copy.copy(frame)
    elif damage == 'deepcopy': frame = copy.deepcopy(frame)
    elif damage == 'other-client': target = PiRpcClient(Channel(receipt()))
    else:
        key, value = {'bytes': ('_wire', b'{"id":"req-1","type":"abort"}\n'),
                      'id': ('_request_id', 'req-2'), 'digest': ('_digest', 'sha256:' + '0' * 64),
                      'protocol': ('_protocol', 'forged/1')}[damage]
        object.__setattr__(frame, key, value)
    with pytest.raises(PreparedFrameRefused): target.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert channel.sent == []


def test_guard_failure_spends_frame_without_send_or_pending():
    channel = Channel(); client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'fixed'})
    def refuse(wire): raise PermissionError('original grant revoked')
    with pytest.raises(PermissionError): client.dispatch_prepared(frame, before_write=refuse)
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert channel.sent == [] and client.pending == {}


@pytest.mark.parametrize('failure', ['timeout', 'partial', 'wrong-command', 'bool-success', 'event-hook'])
def test_missing_confirmation_fences_unknown_and_all_input_paths(failure):
    channel = Channel(); client = PiRpcClient(channel)
    original = client.prepare_request('prompt', {'message': 'original'})
    later = client.prepare_request('follow_up', {'message': 'later'})
    if failure == 'partial': channel.error = ChannelClosed('partial write')
    elif failure == 'wrong-command': channel.frames.append(receipt(command='abort'))
    elif failure == 'bool-success': channel.frames.append(receipt(success=1))
    elif failure == 'event-hook': channel.frames.append({'type': 'agent_end'})
    def event(_): raise RuntimeError('receipt processing interrupted')
    with pytest.raises((RequestTimeout, LostReceipt, RuntimeError)):
        client.dispatch_prepared(original, before_write=lambda _wire=None: None, timeout=.001,
                                 on_event=event if failure == 'event-hook' else None)
    assert channel.unknown == 1 and client.pending == {'req-1': 'prompt'}
    with pytest.raises(LostReceipt): client.dispatch_prepared(later, before_write=lambda _wire=None: None)
    for command in ('prompt', 'steer', 'follow_up'):
        with pytest.raises(LostReceipt): client.command(command, message='bypass')
        with pytest.raises(LostReceipt): client.prepare_request(command, {'message': 'bypass'})
    assert len(channel.sent) == 1
    client._handle_frame(receipt(), waiting_id=None)
    assert client.pending == {}
    assert client.events() == (({"type": "agent_end"}, receipt()) if failure == "event-hook" else (receipt(),))
    assert channel.acks == ["req-1"]
    assert client._run_state == 'unknown'


def test_close_revokes_unused_prepared_frames():
    client = PiRpcClient(Channel()); frame = client.prepare_request('get_state', {})
    client.close()
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)


def test_real_temporary_python_peer_receives_original_guarded_frame(tmp_path):
    peer = tmp_path / 'peer.py'
    peer.write_text('import sys,json\nfor line in sys.stdin:\n p=json.loads(line)\n print(json.dumps(dict(id=p["id"],type="response",command=p["type"],success=True,data={"wire":line})),flush=True)\n')
    channel = ProcessChannel.launch(LaunchSpec(argv=(sys.executable, str(peer)), cwd=str(tmp_path), env={}), name='pi-prepared-C', managed=True)
    lease = channel.acquire_writer()
    client = PiRpcClient(channel.bind_writer(lease))
    try:
        frame = client.prepare_request('prompt', {'message': '原字节'})
        order = []
        result = client.dispatch_prepared(frame, before_write=lambda _wire=None: order.append('verified'), timeout=2)
        assert result['data']['wire'].encode() == frame.frame_bytes and order == ['verified']
        assert client._run_state == 'accepted'
    finally:
        client.close()
        channel.close()


def test_real_pipe_timeout_fences_original_managed_writer(tmp_path):
    peer = tmp_path / 'silent_prompt.py'
    transcript = tmp_path / 'received.jsonl'
    peer.write_text('import sys,json\nfor line in sys.stdin:\n p=json.loads(line)\n with open(sys.argv[1],"a") as f: f.write(line)\n if p["type"] != "prompt": print(json.dumps(dict(id=p["id"],type="response",command=p["type"],success=True,data={})),flush=True)\n')
    channel = ProcessChannel.launch(LaunchSpec((sys.executable, str(peer), str(transcript)), str(tmp_path), {}), name='pi-unknown-C', managed=True)
    client = PiRpcClient(channel.bind_writer(channel.acquire_writer()))
    try:
        hello = client.prepare_request('get_state', {})
        client.dispatch_prepared(hello, before_write=lambda _wire=None: None, timeout=2)
        frame = client.prepare_request('prompt', {'message': 'one original input'})
        later = client.prepare_request('prompt', {'message': 'never sent'})
        with pytest.raises(RequestTimeout): client.dispatch_prepared(frame, before_write=lambda _wire=None: None, timeout=.1)
        with pytest.raises(LostReceipt): client.dispatch_prepared(later, before_write=lambda _wire=None: None)
        from ordessa_harness_transport import WriterLeaseRefused
        with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
        assert transcript.read_bytes() == hello.frame_bytes + frame.frame_bytes
        assert client.pending == {frame.request_id: 'prompt'}
    finally:
        client.close()
        channel.close()


@pytest.mark.parametrize('missing', ['send_frame', 'mark_input_unknown', 'acknowledge_frame'])
def test_missing_actual_write_cut_refuses_before_consuming_original_frame(missing):
    channel = Channel(receipt())
    client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'fixed'})
    original = getattr(channel, missing)
    setattr(channel, missing, None)
    with pytest.raises(PreparedFrameRefused): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert channel.sent == [] and client.pending == {}
    setattr(channel, missing, original)
    assert client.dispatch_prepared(frame, before_write=lambda _wire=None: None) == receipt()
    assert channel.sent == [frame.frame_bytes]


@pytest.mark.parametrize('timeout', [True, 0, -1, float('nan'), float('inf'), '1'])
def test_invalid_wait_policy_rejected_before_frame_consumption(timeout):
    channel = Channel(receipt())
    client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'fixed'})
    with pytest.raises(ValueError): client.dispatch_prepared(frame, before_write=lambda _wire=None: None, timeout=timeout)
    assert channel.sent == [] and client.pending == {}
    assert client.dispatch_prepared(frame, before_write=lambda _wire=None: None) == receipt()


def test_correlated_pi_native_error_is_receipt_and_does_not_fence_transport():
    from ordessa_harness_pi.client import PiCommandError
    channel = Channel(dict(receipt(), success=False, error='controlled-native-rejection'), receipt(2))
    client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'rejected'})
    with pytest.raises(PiCommandError): client.dispatch_prepared(frame, before_write=lambda _wire=None: None)
    assert client.pending == {} and channel.unknown == 0
    another = client.prepare_request('prompt', {'message': 'different-request'})
    assert client.dispatch_prepared(another, before_write=lambda _wire=None: None) == receipt(2)
    assert len(channel.sent) == 2


@pytest.mark.parametrize('source', ['guard', 'callback'])
@pytest.mark.parametrize('identity', ['same', 'foreign'])
def test_command_error_class_from_callback_is_not_native_receipt(source, identity):
    from ordessa_harness_pi.client import PiCommandError
    channel = Channel({'type': 'agent_end'}, receipt())
    client = PiRpcClient(channel)
    frame = client.prepare_request('prompt', {'message': 'original'})
    error = PiCommandError('prompt', frame.request_id if identity == 'same' else 'foreign', 'callback refused')
    def refuse(_): raise error
    with pytest.raises(PiCommandError) as caught:
        client.dispatch_prepared(frame, before_write=refuse if source == 'guard' else lambda wire: None,
                                 on_event=refuse if source == 'callback' else None)
    assert caught.value is error and channel.unknown == 1 and channel.acks == []
    assert client._run_state == 'unknown' and len(channel.sent) == (source == 'callback')
    assert client.pending == ({} if source == 'guard' else {frame.request_id: 'prompt'})


@pytest.mark.parametrize('path', ['prepared', 'raw'])
@pytest.mark.parametrize('late_receipt', [False, True])
def test_late_settled_never_concludes_original_missing_input_receipt(path, late_receipt):
    channel = Channel(); client = PiRpcClient(channel)
    with pytest.raises(RequestTimeout):
        if path == 'prepared':
            frame = client.prepare_request('prompt', {'message': 'one original'})
            client.dispatch_prepared(frame, before_write=lambda wire: None, timeout=.001)
        else:
            client.send_prompt('one original', timeout=.001)
    if late_receipt: client._handle_frame(receipt(), waiting_id=None)
    settled = {'type': 'agent_settled', 'reason': 'late native event'}
    client._handle_frame(settled, waiting_id=None)
    assert client.events() == ((receipt(), settled) if late_receipt else (settled,))
    assert client.wait_settled(timeout=.01)['outcome'] == 'unknown'
    assert client._run_state == 'unknown' and len(channel.sent) == 1
    with pytest.raises(LostReceipt): client.command('prompt', message='cannot resend')
