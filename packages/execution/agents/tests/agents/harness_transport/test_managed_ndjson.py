"""Actual owned Python stdin peers; transport barriers only, no native effects."""
import copy
from concurrent.futures import ThreadPoolExecutor
import pickle
import queue
import sys
import threading

import pytest

from ordessa_agents.harness.transport import NDJSONTransport, TransportClosed, WriterLease, WriterLeaseRefused

PEER = 'import sys\nfor line in sys.stdin:\n sys.stdout.write(line);sys.stdout.flush()\n'

@pytest.fixture
def peers(tmp_path):
    owned=[]
    def spawn(*, managed=True, code=PEER, limit=1024):
        lines=queue.Queue();exits=[];ended=threading.Event()
        def exited(code):exits.append(code);ended.set()
        transport=NDJSONTransport(argv=[sys.executable,'-u','-c',code],cwd=str(tmp_path),
            environment={'PATH':'/usr/bin:/bin'},on_line=lines.put,on_exit=exited,
            managed=managed,max_frame_bytes=limit).start()
        owned.append((transport,ended))
        return transport,lines,exits,ended
    yield spawn
    for transport,ended in owned:
        transport.terminate(timeout=2)
        assert transport._process.poll() is not None
        assert ended.wait(2), 'owned reader did not report its exit'
        transport._reader.join(timeout=2)
        assert not transport._reader.is_alive()
        if transport._process.stdout:transport._process.stdout.close()


def test_real_peer_verbatim_frame_and_managed_direct_bypass_refused(peers):
    transport,lines,_,_=peers()
    lease=transport.acquire_writer()
    frame=' {"unicode":"你好","future":{"x":1}} '
    with pytest.raises(WriterLeaseRefused):transport.send_line(frame)
    transport.send_line_for(lease,frame)
    assert lines.get(timeout=2)==frame
    with pytest.raises(WriterLeaseRefused):transport.acquire_writer()


def test_legacy_remains_unleased_and_does_not_enable_managed_api(peers):
    transport,lines,_,_=peers(managed=False)
    transport.send_line('opaque legacy frame')
    assert lines.get(timeout=2)=='opaque legacy frame'
    with pytest.raises(WriterLeaseRefused):transport.acquire_writer()
    with pytest.raises(WriterLeaseRefused):transport.fence_all()


@pytest.mark.parametrize('forge',['copy','deepcopy','dict','new-object','other-transport','epoch-tamper'])
def test_visible_lease_facts_do_not_authorize_writes(peers,forge):
    transport,lines,_,_=peers();lease=transport.acquire_writer()
    if forge=='copy':candidate=copy.copy(lease)
    elif forge=='deepcopy':candidate=copy.deepcopy(lease)
    elif forge=='dict':candidate={'epoch':lease.epoch}
    elif forge=='new-object':
        candidate=object.__new__(WriterLease);object.__setattr__(candidate,'_epoch',lease.epoch)
    elif forge=='other-transport':candidate=peers()[0].acquire_writer()
    else:
        candidate=lease;object.__setattr__(candidate,'_epoch',lease.epoch+1)
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(candidate,'must not arrive')
    with pytest.raises(WriterLeaseRefused):transport.fence_writer(candidate)
    assert lines.empty()


def test_lease_cannot_be_constructed_mutated_or_serialized(peers):
    transport,_,_,_=peers();lease=transport.acquire_writer()
    with pytest.raises(TypeError):WriterLease(epoch=lease.epoch)
    with pytest.raises(AttributeError):lease._epoch=999
    with pytest.raises(TypeError):pickle.dumps(lease)


def test_fence_revokes_old_actual_stdin_writer_before_new_acquire(peers):
    transport,lines,_,_=peers();old=transport.acquire_writer()
    transport.send_line_for(old,'before fence');assert lines.get(timeout=2)=='before fence'
    epoch=transport.fence_writer(old);assert epoch>old.epoch
    new=transport.acquire_writer();assert new.epoch==epoch
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(old,'revived')
    with pytest.raises(WriterLeaseRefused):transport.fence_writer(old)
    transport.send_line_for(new,'after fence');assert lines.get(timeout=2)=='after fence'


def test_fence_all_cuts_writer_and_reacquire_has_new_epoch(peers):
    transport,_,_,_=peers();old=transport.acquire_writer();epoch=transport.fence_all()
    new=transport.acquire_writer();assert new.epoch==epoch>old.epoch
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(old,'old')


def test_unknown_blocks_reacquire_even_after_fence_all(peers):
    transport,_,_,_=peers();lease=transport.acquire_writer();transport.mark_unresolved(lease)
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(lease,'must not resend')
    with pytest.raises(WriterLeaseRefused):transport.acquire_writer()
    transport.fence_all()
    with pytest.raises(WriterLeaseRefused):transport.acquire_writer()
    transport.terminate(timeout=2)
    with pytest.raises(TransportClosed):transport.acquire_writer()
    with pytest.raises(RuntimeError):transport.start()


def test_competing_acquire_has_one_actual_writer(peers):
    transport,lines,_,_=peers();barrier=threading.Barrier(8)
    def compete(index):
        barrier.wait(timeout=2)
        try:return transport.acquire_writer()
        except WriterLeaseRefused:return None
    with ThreadPoolExecutor(max_workers=8) as pool:leases=list(pool.map(compete,range(8)))
    granted=[lease for lease in leases if lease is not None];assert len(granted)==1
    transport.send_line_for(granted[0],'one winner');assert lines.get(timeout=2)=='one winner'


def test_fence_is_barrier_for_write_already_holding_same_lock(peers,monkeypatch):
    transport,lines,_,_=peers();old=transport.acquire_writer()
    entered=threading.Event();release=threading.Event();fencing=threading.Event();fenced=threading.Event()
    original=transport._write_locked
    def delayed(payload):
        entered.set();assert release.wait(2);original(payload)
    monkeypatch.setattr(transport,'_write_locked',delayed)
    def write():transport.send_line_for(old,'accepted before barrier')
    def fence():
        fencing.set();transport.fence_writer(old);fenced.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer=pool.submit(write);assert entered.wait(2)
        cutter=pool.submit(fence);assert fencing.wait(2)
        assert not fenced.is_set()
        release.set();writer.result(timeout=2);cutter.result(timeout=2)
    assert fenced.is_set() and lines.get(timeout=2)=='accepted before barrier'
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(old,'after barrier')
    new=transport.acquire_writer();transport.send_line_for(new,'new writer');assert lines.get(timeout=2)=='new writer'


@pytest.mark.parametrize('frame',['a\nb','a\rb','\ud800','你好你好',None])
def test_invalid_or_oversize_frame_rejected_without_payload_change(peers,frame):
    transport,lines,_,_=peers(limit=8);lease=transport.acquire_writer()
    with pytest.raises(ValueError):transport.send_line_for(lease,frame)
    assert lines.empty()
    transport.send_line_for(lease,'12345678');assert lines.get(timeout=2)=='12345678'


def test_peer_exit_revokes_actual_writer_and_on_exit_once(peers):
    transport,lines,exits,ended=peers(code='import sys\nline=sys.stdin.readline();print(line.strip(),flush=True)\n')
    lease=transport.acquire_writer();transport.send_line_for(lease,'last')
    assert lines.get(timeout=2)=='last';assert ended.wait(2)
    with pytest.raises(TransportClosed):transport.send_line_for(lease,'lost')
    with pytest.raises(TransportClosed):transport.acquire_writer()
    transport.terminate(timeout=2);transport.terminate(timeout=2)
    assert len(exits)==1


def test_partial_write_failure_revokes_and_blocks_replacement(peers,monkeypatch):
    transport,_,_,_=peers();lease=transport.acquire_writer();original=transport._process.stdin
    class Partial:
        def write(self,payload):raise BrokenPipeError('fault after unknown partial delivery')
        def flush(self):pass
        def close(self):original.close()
    monkeypatch.setattr(transport._process,'stdin',Partial())
    with pytest.raises(TransportClosed):transport.send_line_for(lease,'unknown')
    with pytest.raises(WriterLeaseRefused):transport.acquire_writer()
    assert transport._unresolved


def test_terminate_is_nested_safe_and_old_lease_stays_revoked(peers):
    transport,_,_,ended=peers();lease=transport.acquire_writer()
    with transport._write_lock:transport.terminate(timeout=2)
    assert ended.wait(2)
    with pytest.raises(TransportClosed):transport.send_line_for(lease,'old')
    with pytest.raises(TransportClosed):transport.acquire_writer()


def test_exit_callback_can_terminate_without_self_deadlock(tmp_path):
    ended=threading.Event();holder={}
    def exited(code):holder['transport'].terminate(timeout=2);ended.set()
    transport=NDJSONTransport(argv=[sys.executable,'-u','-c',PEER],cwd=str(tmp_path),
        on_line=lambda line:None,on_exit=exited,managed=True)
    holder['transport']=transport;transport.start();transport.terminate(timeout=2)
    assert ended.wait(2);transport._reader.join(timeout=2);assert not transport._reader.is_alive()
    transport._process.stdout.close()


def test_stdout_disconnect_while_owned_process_alive_stops_writes(peers):
    code='import os,sys\nprint("ready",flush=True);os.close(sys.stdout.fileno());sys.stdin.read()\n'
    transport,lines,_,ended=peers(code=code)
    assert lines.get(timeout=2)=='ready'
    assert transport._protocol_ended.wait(2)
    assert transport._process.poll() is None
    with pytest.raises(TransportClosed):transport.acquire_writer()
    assert transport._unresolved
    assert not ended.is_set()  # Protocol EOF does not invent process termination.
    transport.terminate(timeout=2)
    assert ended.wait(2)


@pytest.mark.parametrize('payload',[b'123456789\n',b'half frame',b'\xff\n'])
def test_managed_reader_bounds_and_utf8_fail_closed_without_rewritten_frame(peers,payload):
    code='import os,sys\nos.write(sys.stdout.fileno(),'+repr(payload)+');os.close(sys.stdout.fileno());sys.stdin.read()\n'
    transport,lines,_,ended=peers(code=code,limit=8)
    assert transport._protocol_ended.wait(2)
    assert lines.empty()
    assert transport._unresolved
    with pytest.raises(TransportClosed):transport.acquire_writer()
    assert transport._process.poll() is None
    transport.terminate(timeout=2);assert ended.wait(2)


def test_managed_crlf_framing_does_not_strip_extra_payload_carriage_return(peers):
    code='import os,sys\nos.write(sys.stdout.fileno(),b"abc\\r\\r\\n");sys.stdin.read()\n'
    transport,lines,_,_=peers(code=code)
    assert lines.get(timeout=2)=='abc\r'


def test_legacy_reader_keeps_previous_replacement_decoding(peers):
    code='import os,sys\nos.write(sys.stdout.fileno(),b"\\xff\\n");sys.stdin.read()\n'
    transport,lines,_,_=peers(code=code,managed=False)
    assert lines.get(timeout=2)=='\ufffd'


def test_unstarted_or_preterminated_managed_transport_cannot_grant_writer(tmp_path):
    transport=NDJSONTransport(argv=[sys.executable,'-u','-c',PEER],cwd=str(tmp_path),
        on_line=lambda line:None,on_exit=lambda code:None,managed=True)
    with pytest.raises(TransportClosed):transport.acquire_writer()
    transport.terminate()
    with pytest.raises(TransportClosed):transport.acquire_writer()
    with pytest.raises(RuntimeError):transport.start()
    assert transport.pid is None


def test_repeated_fence_never_revives_writer_and_epoch_cannot_roll_back(peers):
    transport,_,_,_=peers();old=transport.acquire_writer()
    first=transport.fence_all();second=transport.fence_all();assert second>first>old.epoch
    # Restoring visible old epoch does not restore opaque active identity.
    object.__setattr__(old,'_epoch',second)
    with pytest.raises(WriterLeaseRefused):transport.send_line_for(old,'revived')
    new=transport.acquire_writer();assert new.epoch==second
