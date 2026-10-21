"""Cancellation must get an event-loop turn before a ready ACP inbox drains."""
from contextlib import contextmanager
import hashlib
import json
from threading import Event, Thread, current_thread
import time

import pytest

from ordessa_environments import EnvironmentRefused
from ordessa_agents.harness.transport import RequestTimeout
from test_local_owner import live_owner


_BURST_SIZE = 160
_OPERATION_REF = 'timeout-ready-inbox-cancellation-once'
_PROMPT_TEXT = 'controlled ready-inbox cancellation race'
_CHECKPOINT_TEXT = 'post-denial-checkpoint'
_OUTER_WAIT_CAP_SECONDS = .15


_READY_BURST_PEER = r'''
import json, sys

options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low',
          'options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
sid='ready-inbox-race'
def send(value):
    sys.stdout.buffer.write((json.dumps(value,separators=(',',':'))+'\n').encode())
    sys.stdout.buffer.flush()

for line in sys.stdin:
    q=json.loads(line); method=q['method']; p=q.get('params',{})
    if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': r={'sessionId':sid,'configOptions':options}
    elif method=='session/load': r={}
    elif method=='_ordessa/session/configuration': r={'sessionId':sid,'configOptions':options}
    elif method=='session/prompt':
        sid=p['sessionId']; prompt_id=q['id']
        send({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':sid,'update':{
            'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'before-denial'}}}})
        permission_id=900
        send({'jsonrpc':'2.0','id':permission_id,'method':'session/request_permission','params':{
            'sessionId':sid,
            'toolCall':{'kind':'commandExecution','toolCallId':'command-once','title':'Run a controlled command'},
            'options':[{'kind':'allow_once','optionId':'allow-once'},
                       {'kind':'reject_once','optionId':'reject-once'}]}})
        permission_reply=json.loads(sys.stdin.readline())
        if (permission_reply.get('id') != permission_id
                or permission_reply.get('result',{}).get('outcome',{}).get('outcome') != 'cancelled'):
            raise RuntimeError('the original commandExecution permission was not denied')

        # One sub-64KiB write yields many complete frames in the Local process
        # reader's existing 64KiB buffer. No terminal prompt response follows.
        frames=[]
        for index in range(160):
            text='post-denial-checkpoint' if index == 0 else 'partial-%04d' % index
            frame={'jsonrpc':'2.0','method':'session/update','params':{'sessionId':sid,
                'update':{'sessionUpdate':'agent_message_chunk',
                          'content':{'type':'text','text':text}}}}
            frames.append((json.dumps(frame,separators=(',',':'))+'\n').encode())
        burst=b''.join(frames)
        if len(burst) >= 65536:
            raise RuntimeError('fixture burst no longer fits one bounded stdout read')
        sys.stdout.buffer.write(burst); sys.stdout.buffer.flush()
        # Stay alive, with no prompt response, until the authorized owner closes us.
        for ignored in sys.stdin:
            pass
        break
    elif method=='session/cancel':
        continue
    else:
        r={}
    if method!='session/prompt':
        send({'jsonrpc':'2.0','id':q.get('id'),'result':r})
'''


class _RejectCommandExecution:
    def __init__(self):
        self.calls = []

    def authorize(self, **request):
        self.calls.append(request)
        return False


class _ScaledOuterWait:
    """Shorten only the host wait; preserve the real SDK Future/cancel path."""

    def __init__(self, future):
        self.future = future

    def result(self, timeout=None):
        if timeout is None:
            timeout = _OUTER_WAIT_CAP_SECONDS
        else:
            timeout = min(timeout, _OUTER_WAIT_CAP_SECONDS)
        return self.future.result(timeout=timeout)

    def cancel(self):
        return self.future.cancel()


def _termination_rows(world, unit):
    return tuple(world.records.owner_read_termination(unit.identity['unitId'], action)
                 for action in ('stop', 'release'))


def _read_turn(world):
    with world.journal._connect() as db:
        return db.execute(
            'SELECT state,body_json FROM harness_acp_turn_attempts WHERE operation_ref=?',
            (_OPERATION_REF,)).fetchone()


def _wait_for_request_observation(instance, predicate, *, timeout=5):
    """Wait on read-only diagnostics instead of a guessed scheduling delay."""
    deadline = time.monotonic() + timeout
    observation = instance.quiescence_observation()
    while not predicate(observation) and time.monotonic() < deadline:
        Event().wait(.01)
        observation = instance.quiescence_observation()
    return observation


@pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True,
    'preparation_peer': _READY_BURST_PEER,
    'callback_approval': _RejectCommandExecution(),
}], indirect=True)
def test_outer_timeout_cancellation_yields_before_ready_message_batch(
        live_owner, monkeypatch):
    """A ready ACP burst cannot starve cancellation and exact-owner quiescence."""
    from ordessa_units.records import acp_turns

    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    record = instance.channel_factory.owned_record
    client = record.entry
    approval = instance.callbacks.approval
    lease = world.owner.authorize('interaction', unit, authorization)
    prompt_frames, prompt_errors, prompt_results = [], [], []
    checkpoint = Event()
    release_checkpoint = Event()
    active_zero = Event()
    zero_snapshots = []
    quiescence_snapshots = []
    client_quiesce_snapshots = []
    pending_quiescence_snapshots = []
    original_write = record.process.write_stdin
    original_observe = acp_turns.observe
    original_submit = client._submit
    original_admitted = client.admitted_operation
    original_instance_quiesce = instance.try_quiesce
    original_client_quiesce = client.try_quiesce

    async def observe_prompt_write(data, *, timeout=None):
        try:
            raw = json.loads(data)
        except (TypeError, ValueError):
            raw = None
        if isinstance(raw, dict) and raw.get('method') == 'session/prompt':
            prompt_frames.append(raw['id'])
        return await original_write(data, timeout=timeout)

    def scale_outer_wait(coroutine):
        # SdkAcpClient normally waits for request timeout+2 on the host thread.
        # Keep the original SDK coroutine's 30s timeout, but compress only the
        # host-side Future wait so this regression stays fast and exercises its
        # actual FutureTimeout -> fence -> Future.cancel branch.
        return _ScaledOuterWait(original_submit(coroutine))

    def observe_durable_event(records, operation_ref, raw):
        if (raw.get('method') == 'session/update'
                and raw.get('params', {}).get('update', {}).get('content', {}).get('text')
                == _CHECKPOINT_TEXT):
            # This is an observer checkpoint after the permission callback has
            # already returned its denial, not a held approval callback.
            checkpoint.set()
            if not release_checkpoint.wait(10):
                raise TimeoutError('ready-inbox observer checkpoint was not released')
        if raw.get('method') == 'session/update':
            # Deterministic finite synchronous work approximates the existing
            # per-event durable observation cost without making sleeps the race.
            encoded = json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()
            digest = encoded
            for _ in range(64):
                digest = hashlib.sha256(digest).digest()
        return original_observe(records, operation_ref, raw)

    @contextmanager
    def observe_admission_span():
        try:
            with original_admitted():
                yield
        finally:
            if client._active_native_operations == 0:
                zero_snapshots.append({
                    'active': client._active_native_operations,
                    'inbox_depth': len(record.channel._inbox),
                    'sdk_thread_alive': client._thread.is_alive(),
                })
                active_zero.set()

    def observe_client_quiesce():
        active_before = client._active_native_operations
        admission_open_before = client._native_admission_open
        same_thread = current_thread() is client._thread
        result = original_client_quiesce()
        client_quiesce_snapshots.append({
            'active_before': active_before,
            'admission_open_before': admission_open_before,
            'same_sdk_thread': same_thread,
            'result': result,
        })
        return result

    def observe_instance_quiesce():
        lock_available = instance._lifecycle_lock.acquire(blocking=False)
        if lock_available:
            instance._lifecycle_lock.release()
        fences_before = len(instance._selection_fences)
        active_before = client._active_native_operations
        result = original_instance_quiesce()
        quiescence_snapshots.append({
            'lifecycle_lock_available_before': lock_available,
            'selection_fences_before': fences_before,
            'active_before': active_before,
            'result': result,
        })
        return result

    monkeypatch.setattr(record.process, 'write_stdin', observe_prompt_write)
    monkeypatch.setattr(client, '_submit', scale_outer_wait)
    monkeypatch.setattr(acp_turns, 'observe', observe_durable_event)
    monkeypatch.setattr(client, 'admitted_operation', observe_admission_span)
    monkeypatch.setattr(client, 'try_quiesce', observe_client_quiesce)
    monkeypatch.setattr(instance, 'try_quiesce', observe_instance_quiesce)

    def send_prompt():
        try:
            prompt_results.append(instance.prompt(
                unit.identity, lease, operation_ref=_OPERATION_REF, timeout=30,
                prompt=[{'type': 'text', 'text': _PROMPT_TEXT}]))
        except BaseException as error:
            prompt_errors.append(error)

    prompt_thread = Thread(target=send_prompt)
    body_after_quiescence = None
    try:
        prompt_thread.start()
        assert checkpoint.wait(5), 'controlled peer did not reach the post-denial stream checkpoint'
        assert len(record.channel._inbox) >= 8
        assert len(prompt_frames) == 1
        prompt_thread.join(4)
        assert not prompt_thread.is_alive()
        assert len(prompt_errors) == 1 and isinstance(prompt_errors[0], RequestTimeout)
        assert prompt_results == []

        assert len(approval.calls) == 1
        assert approval.calls[0]['method'] == 'session/request_permission'
        assert approval.calls[0]['params']['toolCall']['kind'] == 'commandExecution'
        assert approval.calls[0]['params']['toolCall']['toolCallId'] == 'command-once'
        assert record.channel._unresolved is True
        timed_out = _read_turn(world)
        assert timed_out is not None and timed_out['state'] == 'unknown'
        timed_out_body = json.loads(timed_out['body_json'])
        assert timed_out_body['state'] == 'unknown'
        assert timed_out_body['request']['raw']['id'] == prompt_frames[0]
        assert timed_out_body['response'] is None
        assert timed_out_body['summary']['successfulRpcResponse'] is False

        # The live observer checkpoint holds the SDK loop after the permission
        # denial. Observe each close layer before releasing that deterministic
        # gate; no close may treat the fenced UNKNOWN turn as an idle client.
        for _ in range(25):
            outcome = unit.close(authorization)
            assert outcome['state'] == 'pending' and outcome['unresolved'] is True
            pending_quiescence_snapshots.append(outcome['quiescence'])
        assert len(quiescence_snapshots) == 25
        assert all(row['lifecycle_lock_available_before'] is True
                   and row['selection_fences_before'] == 0
                   and row['active_before'] > 0 and row['result'] is False
                   for row in quiescence_snapshots)
        assert len(client_quiesce_snapshots) == 25
        assert all(row['active_before'] > 0 and row['admission_open_before'] is True
                   and row['same_sdk_thread'] is False and row['result'] is False
                   for row in client_quiesce_snapshots)
        assert len(pending_quiescence_snapshots) == 25
        for observation in pending_quiescence_snapshots:
            assert observation['reason'] == 'sdk_operations_active'
            assert observation['pending_callback_responses'] == 0
            assert observation['io_loop_alive'] is True
            assert observation['native_admission_open'] is True
            request = observation['request']
            assert request['method'] == 'session/prompt'
            assert request['has_rpc_id'] is True and request['receipt_seen'] is False
            assert request['timeout_origin'] == 'host_waiter'
            assert request['cancel_requested'] is True
            assert request['cancellation_observed'] is False
            assert request['coroutine_finished'] is False
            assert request['writer_fenced'] is True
            incoming = observation['incoming']
            assert incoming['last_kind'] == 'session/update'
            assert incoming['durable_observer_active'] is True
        assert _termination_rows(world, unit) == (None, None)
        assert world.environment.snapshot.active_uses == 1

        release_checkpoint.set()
        assert active_zero.wait(8), 'original prompt admission did not quiesce after cancellation'
        assert zero_snapshots
        # Core race assertion: cancellation must run while the peer frames are
        # still queued, rather than only after the ready inbox has drained.
        zero = zero_snapshots[-1]
        assert zero['active'] == 0
        assert zero['inbox_depth'] > 0
        assert zero['sdk_thread_alive'] is True
        assert len(prompt_frames) == 1
        completed_observation = _wait_for_request_observation(
            instance,
            lambda value: (value.get('request') is not None
                           and value['request']['cancellation_observed'] is True
                           and value['request']['coroutine_finished'] is True
                           and value['active_native_operations'] == 0),
        )
        completed_request = completed_observation['request']
        assert completed_observation['reason'] == 'sdk_idle'
        assert completed_observation['pending_callback_responses'] == 0
        assert completed_observation['native_admission_open'] is True
        assert completed_request['timeout_origin'] == 'host_waiter'
        assert completed_request['cancel_requested'] is True
        assert completed_request['cancellation_observed'] is True
        assert completed_request['coroutine_finished'] is True
        assert completed_request['writer_fenced'] is True
        assert completed_observation['incoming']['durable_observer_active'] is False

        body_after_quiescence = _read_turn(world)
        assert body_after_quiescence is not None
        unknown_body = json.loads(body_after_quiescence['body_json'])
        assert body_after_quiescence['state'] == 'unknown'
        assert unknown_body['state'] == 'unknown'
        assert unknown_body['response'] is None
        assert body_after_quiescence['body_json'] == timed_out['body_json']

        closed = unit.close(authorization)
        assert closed['state'] == 'confirmed'
        assert _termination_rows(world, unit)[0]['state'] == 'confirmed'
        assert _termination_rows(world, unit)[1]['state'] == 'confirmed'
        assert world.environment.snapshot.active_uses == 0
        assert client.has_io_loop is False
        with pytest.raises(EnvironmentRefused, match='environment use is released'):
            record.process.observe()
        after_close = _read_turn(world)
        assert after_close['state'] == body_after_quiescence['state'] == 'unknown'
        assert after_close['body_json'] == body_after_quiescence['body_json']
        assert len(prompt_frames) == 1
    finally:
        release_checkpoint.set()
        prompt_thread.join(8)
        if client._active_native_operations == 0:
            # Preserve fixture hygiene if an earlier assertion fails; this is
            # the same exact owner and authorization used above.
            outcome = unit.close(authorization)
            if outcome.get('state') == 'pending':
                deadline = time.monotonic() + 5
                while outcome.get('state') == 'pending' and time.monotonic() < deadline:
                    Event().wait(.01)
                    outcome = unit.close(authorization)
    assert not prompt_thread.is_alive()
    assert body_after_quiescence is not None


@pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True,
    'preparation_peer': _READY_BURST_PEER,
}], indirect=True)
def test_quiescence_snapshot_reports_close_gates_without_quiescing(live_owner, monkeypatch):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    instance = unit._instance
    client = instance.channel_factory.owned_record.entry
    original_instance_quiesce = instance.try_quiesce
    original_client_quiesce = client.try_quiesce
    calls = {'instance': 0, 'client': 0}

    def instance_quiesce_spy():
        calls['instance'] += 1
        return original_instance_quiesce()

    def client_quiesce_spy():
        calls['client'] += 1
        return original_client_quiesce()

    monkeypatch.setattr(instance, 'try_quiesce', instance_quiesce_spy)
    monkeypatch.setattr(client, 'try_quiesce', client_quiesce_spy)

    before = _termination_rows(world, unit)
    assert before == (None, None)
    idle = instance.quiescence_observation()
    assert idle['reason'] == 'sdk_idle'
    assert idle['active_native_operations'] == 0
    assert idle['native_admission_open'] is True

    token = instance._acquire_selection_fence(lambda: None)
    try:
        fenced = instance.quiescence_observation()
        assert fenced == {'reason': 'selection_fence_active', 'selection_fences': 1}
    finally:
        instance._release_selection_fence(token)

    lock_held = Event()
    release_lock = Event()

    def hold_lifecycle_lock():
        with instance._lifecycle_lock:
            lock_held.set()
            if not release_lock.wait(5):
                raise TimeoutError('lifecycle lock diagnostic holder was not released')

    lock_thread = Thread(target=hold_lifecycle_lock)
    lock_thread.start()
    assert lock_held.wait(2)
    try:
        busy = instance.quiescence_observation()
        assert busy == {'reason': 'lifecycle_lock_busy'}
    finally:
        release_lock.set()
        lock_thread.join(5)
    assert not lock_thread.is_alive()

    assert calls == {'instance': 0, 'client': 0}
    assert _termination_rows(world, unit) == before
    assert world.environment.snapshot.active_uses == 1

    # Restore the gates before cleanup; the observation itself did not mutate them.
    monkeypatch.setattr(instance, 'try_quiesce', original_instance_quiesce)
    monkeypatch.setattr(client, 'try_quiesce', original_client_quiesce)
    closed = unit.close(authorization)
    assert closed['state'] == 'confirmed'
    assert _termination_rows(world, unit)[0]['state'] == 'confirmed'
    assert _termination_rows(world, unit)[1]['state'] == 'confirmed'
    assert world.environment.snapshot.active_uses == 0
