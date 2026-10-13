"""Actual owned Python peer stdin barriers; no upstream Harness or model."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sys

import pytest

from ordessa_execution_agents.harness.transport import (
 ChannelClosed,FrameReader,FramingError,LaunchSpec,ProcessChannel,RequestTimeout,WriterLeaseRefused,
)


@pytest.fixture
def channel(tmp_path):
 peer=tmp_path/'peer.py'
 peer.write_text("import json,sys\nfor line in sys.stdin:\n msg=json.loads(line)\n print(json.dumps({'id':msg.get('id'),'result':msg}),flush=True)\n")
 value=ProcessChannel.launch(LaunchSpec.build([sys.executable,str(peer)],home=str(tmp_path/'home'),cwd=str(tmp_path)),name='controlled-peer',managed=True)
 try: yield value
 finally: value.close(timeout=1)


def test_no_unleased_write_or_forged_lease_and_one_writer(channel):
 lease=channel.acquire_writer()
 with pytest.raises(WriterLeaseRefused): channel.send_raw({'id':1})
 with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
 with pytest.raises(WriterLeaseRefused): channel.send_raw_for(copy.copy(lease),{'id':1})
 bound=channel.bind_writer(lease)
 assert bound.request('native/exact',{'unknown':'retained'},timeout=2)['params']=={'unknown':'retained'}


def test_disconnect_does_not_stop_unit_and_old_connection_cannot_send(channel):
 lease=channel.acquire_writer(); bound=channel.bind_writer(lease)
 bound.close()
 assert channel._process.poll() is None
 with pytest.raises(ChannelClosed): bound.send_raw({'id':1})
 with pytest.raises(WriterLeaseRefused): channel.send_raw_for(lease,{'id':1})
 replacement=channel.bind_writer(channel.acquire_writer())
 assert replacement.request('current',timeout=2)['method']=='current'


def test_unknown_fence_cannot_be_cleared_by_disconnect_or_new_writer(channel):
 lease=channel.acquire_writer(); bound=channel.bind_writer(lease)
 channel.mark_unresolved(lease)
 bound.close(); channel.fence_all()
 with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
 with pytest.raises(WriterLeaseRefused): channel.send_raw_for(lease,{'id':1})
 assert channel._process.poll() is None


@pytest.mark.parametrize('payload',[{'bad':float('nan')},{'bad':'\ud800'},'not-an-object'])
def test_invalid_json_rejected_before_native_write(channel,payload):
 lease=channel.acquire_writer()
 with pytest.raises(FramingError): channel.send_raw_for(lease,payload)
 assert channel.bind_writer(lease).request('still-current',timeout=2)['method']=='still-current'


def test_actual_write_and_revocation_share_one_barrier(channel):
 lease=channel.acquire_writer(); bound=channel.bind_writer(lease)
 entered=Event(); release=Event(); fenced=Event()
 stream=channel._process.stdin
 class ControlledStream:
  def write(self,data):
   entered.set(); assert release.wait(3)
   return stream.write(data)
  def flush(self): return stream.flush()
  def close(self): return stream.close()
 channel._process.stdin=ControlledStream()
 def fence():
  channel.fence_all(); fenced.set()
 with ThreadPoolExecutor(max_workers=2) as pool:
  writing=pool.submit(bound.send_raw,{'id':1,'unknown':'preserved'})
  assert entered.wait(3)
  fencing=pool.submit(fence)
  try: assert not fenced.wait(.05)
  finally: release.set()
  writing.result(timeout=3); fencing.result(timeout=3)
 assert bound.next_message(timeout=2).raw['result']=={'id':1,'unknown':'preserved'}
 with pytest.raises(WriterLeaseRefused): bound.send_raw({'id':2})


def test_interleaved_event_before_response_is_preserved_not_requeued_forever(tmp_path):
 peer=tmp_path/'interleave.py'
 peer.write_text("import json,sys\nm=json.loads(sys.stdin.readline())\nprint(json.dumps({'method':'future/event','params':{'x':1}}),flush=True)\nprint(json.dumps({'id':m['id'],'result':'done'}),flush=True)\nfor line in sys.stdin: pass\n")
 channel=ProcessChannel.launch(LaunchSpec.build([sys.executable,str(peer)],home=str(tmp_path/'home'),cwd=str(tmp_path)),name='interleaved',managed=True)
 try:
  bound=channel.bind_writer(channel.acquire_writer())
  assert bound.request('native/request',timeout=2)=='done'
  assert bound.drain()[0].raw=={'method':'future/event','params':{'x':1}}
 finally: channel.close(timeout=1)


def test_request_timeout_retains_unknown_and_blocks_another_writer(tmp_path):
 peer=tmp_path/'silent.py'; peer.write_text('import sys\nfor line in sys.stdin: pass\n')
 channel=ProcessChannel.launch(LaunchSpec.build([sys.executable,str(peer)],home=str(tmp_path/'home'),cwd=str(tmp_path)),name='silent',managed=True)
 try:
  bound=channel.bind_writer(channel.acquire_writer())
  with pytest.raises(RequestTimeout): bound.request('effect',timeout=.05)
  assert len(channel.inflight)==1
  bound.close()
  with pytest.raises(WriterLeaseRefused): channel.acquire_writer()
 finally: channel.close(timeout=1)


def test_utf8_cannot_borrow_continuation_bytes_across_native_frames():
 reader=FrameReader()
 with pytest.raises(FramingError): reader.feed(b'\xe4\n\xbd\xa0\n')
