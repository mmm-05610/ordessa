"""C: pure frame handles and real owned Python echo peers, no upstream/model."""
import copy
import hashlib
import json
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from ordessa_agents.harness.transport import (PreparedFrame, PreparedFramePool, PreparedFrameRefused,
    native_frame_bytes, ProcessChannel, LaunchSpec, ChannelClosed, FramingError, RequestTimeout, WriterLeaseRefused)


def test_original_request_and_bytes_frozen_before_capture_without_io():
    pool = PreparedFramePool('native-fixture/1')
    payload = {'id': 'req-1', 'type': 'prompt', 'message': '你好\n原生', 'extension': {'values': [1, True]}}
    ticket = pool.prepare(payload, 'req-1')
    wire = native_frame_bytes(payload)
    payload['extension']['values'].append('modified')
    assert ticket.frame_bytes == wire
    assert ticket.protocol == 'native-fixture/1' and ticket.request_id == 'req-1'
    assert ticket.frame_digest == 'sha256:' + hashlib.sha256(wire).hexdigest()
    detached = ticket.payload
    detached['extension']['values'].append('another')
    assert ticket.frame_bytes == wire and ticket.payload['extension']['values'] == [1, True]
    assert pool.consume(ticket) == ('req-1', wire)
    with pytest.raises(PreparedFrameRefused): pool.consume(ticket)


@pytest.mark.parametrize('damage', ['copy', 'deepcopy', 'dict', 'other-pool', 'wire', 'digest', 'id-bool', 'protocol'])
def test_visible_facts_never_supply_original_handle_identity(damage):
    pool = PreparedFramePool('native-fixture/1')
    frame = pool.prepare({'id': 1, 'method': 'native'}, 1)
    if damage == 'copy': candidate = copy.copy(frame)
    elif damage == 'deepcopy': candidate = copy.deepcopy(frame)
    elif damage == 'dict': candidate = {'id': 1, 'frameBytes': frame.frame_bytes}
    elif damage == 'other-pool': candidate = PreparedFramePool('native-fixture/1').prepare(frame.payload, 1)
    else:
        candidate = frame
        name, value = {'wire': ('_wire', b'{"id":1}\n'), 'digest': ('_digest', 'sha256:wrong'),
                       'id-bool': ('_request_id', True), 'protocol': ('_protocol', 'other/1')}[damage]
        object.__setattr__(candidate, name, value)
    with pytest.raises(PreparedFrameRefused): pool.consume(candidate)
    if damage in {'copy', 'deepcopy', 'dict', 'other-pool'}:
        assert pool.consume(frame)[0] == 1


def test_handle_construct_mutate_serialize_refused_and_close_revokes():
    pool = PreparedFramePool('native-fixture/1')
    frame = pool.prepare({'id': 'one'}, 'one')
    with pytest.raises(TypeError): PreparedFrame()
    with pytest.raises(AttributeError): frame._wire = b'changed'
    with pytest.raises(TypeError): pickle.dumps(frame)
    pool.close()
    with pytest.raises(PreparedFrameRefused): pool.consume(frame)
    with pytest.raises(PreparedFrameRefused): pool.prepare({'id': 'two'}, 'two')


def test_bounded_pending_frames_can_only_be_freed_explicitly():
    pool = PreparedFramePool('native-fixture/1', max_pending=1)
    first = pool.prepare({'id': 'one'}, 'one')
    with pytest.raises(PreparedFrameRefused): pool.prepare({'id': 'two'}, 'two')
    pool.discard(first)
    second = pool.prepare({'id': 'three'}, 'three')
    with pytest.raises(PreparedFrameRefused): pool.consume(first)
    assert pool.consume(second)[0] == 'three'


@pytest.mark.parametrize('payload,id', [({'id': True}, True), ({'id': True}, 1), ({'id': 1}, '1'),
                                      ({'id': ''}, ''), ({'id': 1, 'x': float('nan')}, 1),
                                      ({'id': 1, 'x': '\ud800'}, 1), ({'id': 1, 'x': object()}, 1)])
def test_bad_identity_or_frame_rejected_before_effects(payload, id):
    with pytest.raises((ValueError, FramingError)): PreparedFramePool('native-fixture/1').prepare(payload, id)


def test_only_one_consumer_of_original_frame_wins():
    pool = PreparedFramePool('native-fixture/1')
    frame = pool.prepare({'id': 'one'}, 'one')
    barrier = Barrier(8)
    def consume(_):
        barrier.wait(timeout=2)
        try: return pool.consume(frame)
        except PreparedFrameRefused: return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(consume, range(8)))
    assert sum(item is not None for item in results) == 1


@pytest.fixture
def peer(tmp_path):
    channel = ProcessChannel.launch(LaunchSpec.build(
        [sys.executable, '-u', '-c', 'import sys\nfor line in sys.stdin.buffer: sys.stdout.buffer.write(line); sys.stdout.buffer.flush()'],
        home=str(tmp_path / 'home'), cwd=str(tmp_path)), name='controlled-echo', managed=True)
    yield channel
    channel.close(timeout=2)
    assert channel._process.poll() is not None


def test_actual_managed_writer_sends_exact_original_utf8_bytes_with_guard(peer):
    lease = peer.acquire_writer()
    view = peer.bind_writer(lease)
    wire = b' {"id":"one", "type":"prompt", "message":"\xe4\xbd\xa0\xe5\xa5\xbd", "future":[true]} \n'
    calls = []
    view.send_frame(wire, before_write=lambda: calls.append('original-guard'))
    assert calls == ['original-guard'] and peer.next_message(timeout=2).raw == json.loads(wire)
    with pytest.raises(WriterLeaseRefused): peer.send_frame(wire, before_write=lambda: None)
    view.close()
    assert peer._process.poll() is None  # disconnect is not stop


@pytest.mark.parametrize('failure', ['refuse', 'fence'])
def test_guard_failure_and_in_guard_fence_both_prevent_bytes(peer, failure):
    lease = peer.acquire_writer()
    view = peer.bind_writer(lease)
    wire = b'{"id":"one"}\n'
    def refuse(): raise PermissionError('controlled-refusal')
    with pytest.raises(PermissionError if failure == 'refuse' else WriterLeaseRefused):
        view.send_frame(wire, before_write=refuse if failure == 'refuse' else peer.fence_all)
    with pytest.raises(RequestTimeout): peer.next_message(timeout=0.02)
    assert peer._unresolved is True
    with pytest.raises(WriterLeaseRefused): peer.acquire_writer()


def test_unknown_fences_actual_old_writer_and_no_new_prepared_dispatch(peer):
    view = peer.bind_writer(peer.acquire_writer())
    view.send_frame(b'{"id":"one"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw['id'] == 'one'
    view.mark_input_unknown()
    with pytest.raises(WriterLeaseRefused): view.send_frame(b'{"id":"two"}\n', before_write=lambda: None)
    peer.fence_all()
    with pytest.raises(WriterLeaseRefused): peer.acquire_writer()
    assert peer._process.poll() is None


@pytest.mark.parametrize('wire', [b'{"id":1}\n{"id":2}\n', b'{"id":1}\r\n', b'{"id":1}', b'[]\n',
                                  b'{"id":NaN}\n', b'{"id":"\xff"}\n', 'not-bytes'])
def test_invalid_frozen_frame_never_enters_guard_or_peer(peer, wire):
    view = peer.bind_writer(peer.acquire_writer())
    calls = []
    with pytest.raises(FramingError): view.send_frame(wire, before_write=lambda: calls.append(1))
    assert calls == []
    with pytest.raises(RequestTimeout): peer.next_message(timeout=0.01)


def test_write_guard_and_external_fence_share_actual_transport_barrier(peer):
    view = peer.bind_writer(peer.acquire_writer())
    guarded, allow, fencing, cut = Event(), Event(), Event(), Event()
    def guard(): guarded.set(); assert allow.wait(2)
    def send(): view.send_frame(b'{"id":"one"}\n', before_write=guard)
    def fence(): fencing.set(); peer.fence_all(); cut.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(send)
        assert guarded.wait(2)
        cutter = executor.submit(fence)
        assert fencing.wait(2) and not cut.is_set()
        allow.set()
        writer.result(timeout=2); cutter.result(timeout=2)
    assert cut.is_set() and peer.next_message(timeout=2).raw['id'] == 'one'
    with pytest.raises(WriterLeaseRefused): view.send_frame(b'{"id":"two"}\n', before_write=lambda: None)


@pytest.mark.parametrize('send', ['raw', 'request', 'notify', 'prepared'])
def test_unmanaged_unknown_has_no_old_write_api_bypass(tmp_path, send):
    channel = ProcessChannel.launch(LaunchSpec.build(
        [sys.executable, '-u', '-c', 'import sys\nfor line in sys.stdin: print(line.strip(),flush=True)'],
        home=str(tmp_path / 'home'), cwd=str(tmp_path)), name='controlled-unmanaged')
    try:
        channel.mark_input_unknown()
        with pytest.raises(WriterLeaseRefused):
            if send == 'raw': channel.send_raw({'id': 'forbidden'})
            elif send == 'request': channel.request('forbidden', timeout=0.01)
            elif send == 'notify': channel.notify('forbidden')
            else: channel.send_frame(b'{"id":"forbidden"}\n', before_write=lambda: None)
        with pytest.raises(RequestTimeout): channel.next_message(timeout=0.01)
    finally:
        channel.close(timeout=2)
        assert channel._process.poll() is not None


@pytest.mark.parametrize('number', ['1e309', '-1e309', '1e100000'])
def test_overflow_json_number_rejected_before_guard_and_write(peer, number):
    calls = []
    view = peer.bind_writer(peer.acquire_writer())
    with pytest.raises(FramingError):
        view.send_frame(('{"id":1,"x":' + number + '}\n').encode(), before_write=lambda: calls.append(1))
    assert calls == []
    with pytest.raises(RequestTimeout): peer.next_message(timeout=0.01)


def test_real_peer_reports_hash_of_exact_original_stdin_bytes(tmp_path):
    code = 'import sys,json,hashlib\nfor line in sys.stdin.buffer:\n print(json.dumps({"digest":hashlib.sha256(line).hexdigest(),"size":len(line)}),flush=True)\n'
    channel = ProcessChannel.launch(LaunchSpec.build([sys.executable, '-u', '-c', code],
        home=str(tmp_path / 'home'), cwd=str(tmp_path)), name='controlled-byte-proof', managed=True)
    try:
        view = channel.bind_writer(channel.acquire_writer())
        wire = b' {"id":"one", "message":"\xe4\xbd\xa0\xe5\xa5\xbd", "nativeFuture":true} \n'
        view.send_frame(wire, before_write=lambda: None)
        response = view.next_message(timeout=2).raw
        assert response == {'digest': hashlib.sha256(wire).hexdigest(), 'size': len(wire)}
    finally:
        channel.close(timeout=2)
        assert channel._process.poll() is not None


def test_initial_stale_writer_cannot_poison_a_new_valid_writer(peer):
    old = peer.bind_writer(peer.acquire_writer())
    peer.fence_all()
    new = peer.bind_writer(peer.acquire_writer())
    called = []
    with pytest.raises(WriterLeaseRefused): old.send_frame(b'{"id":"stale"}\n', before_write=lambda: called.append(1))
    assert called == [] and peer._unresolved is False
    new.send_frame(b'{"id":"current"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw['id'] == 'current'


def test_guard_close_and_partial_pipe_write_keep_transport_cut(peer, monkeypatch):
    view = peer.bind_writer(peer.acquire_writer())
    original = peer._process.stdin
    class Partial:
        def write(self, value):
            self.delivered = value[:len(value) // 2]
            original.write(self.delivered); original.flush()
            return len(self.delivered)
        def flush(self): raise AssertionError('partial write must not flush again')
    partial = Partial()
    monkeypatch.setattr(peer._process, 'stdin', partial)
    try:
        with pytest.raises(ChannelClosed): view.send_frame(b'{"id":"partial-frame"}\n', before_write=lambda: None)
        assert partial.delivered and peer._unresolved and peer._process.poll() is None
        with pytest.raises(WriterLeaseRefused): peer.acquire_writer()
        with pytest.raises(WriterLeaseRefused): view.send_frame(b'{"id":"retry"}\n', before_write=lambda: None)
    finally:
        monkeypatch.setattr(peer._process, 'stdin', original)


def test_guard_closing_original_transport_cannot_write_after_close(peer):
    view = peer.bind_writer(peer.acquire_writer())
    with pytest.raises((WriterLeaseRefused, ChannelClosed)):
        view.send_frame(b'{"id":"after-close"}\n', before_write=lambda: peer.close(timeout=2))
    assert peer._process.poll() is not None and peer._unresolved is True


def test_original_receipt_ack_allows_explicit_handoff_only_after_known_rpc(peer):
    view = peer.bind_writer(peer.acquire_writer())
    view.send_frame(b'{"id":"one"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw == {'id': 'one'}
    view.acknowledge_frame('one')
    assert peer._prepared_inflight == {} and peer._unresolved is False
    peer.fence_all()
    replacement = peer.bind_writer(peer.acquire_writer())
    replacement.send_frame(b'{"id":"two"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw == {'id': 'two'}
    replacement.acknowledge_frame('two')


def test_receipt_wait_revocation_and_late_ack_never_allow_new_writer(peer):
    view = peer.bind_writer(peer.acquire_writer())
    view.send_frame(b'{"id":"one"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw == {'id': 'one'}
    peer.fence_all()
    with pytest.raises(WriterLeaseRefused): peer.acquire_writer()
    with pytest.raises(WriterLeaseRefused): peer.acknowledge_frame('one')
    with pytest.raises(WriterLeaseRefused): view.acknowledge_frame('foreign')
    assert len(peer._prepared_inflight) == 1
    view.acknowledge_frame('one')  # original stale writer may clean its own IO metadata
    assert peer._prepared_inflight == {} and peer._unresolved is True
    with pytest.raises(WriterLeaseRefused): peer.acquire_writer()
    with pytest.raises(WriterLeaseRefused): view.send_frame(b'{"id":"two"}\n', before_write=lambda: None)


def test_original_pending_native_id_cannot_be_written_twice(peer):
    view = peer.bind_writer(peer.acquire_writer())
    view.send_frame(b'{"id":"one"}\n', before_write=lambda: None)
    assert peer.next_message(timeout=2).raw == {'id': 'one'}
    with pytest.raises(WriterLeaseRefused):
        view.send_frame(b'{"id":"one"}\n', before_write=lambda: pytest.fail('duplicate reached guard'))
    assert peer.poll_message(timeout=.02) is None
    view.acknowledge_frame('one')
