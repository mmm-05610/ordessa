"""Controlled tests for the ONE native interaction runtime (agent-native/1).

They drive the real InteractionService/Records/runtime over a fake bound endpoint
and a fake protocol codec: no model, no subprocess, no network. The purpose is to
prove the envelope, idempotency, async accept, journal/cursor, reverse-request
reply, oversize failure and restart facts before real Codex/Pi runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ordessa_agents.instances.contracts import InstanceBindingMaterial
from ordessa_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_agents.sdk.endpoint import BoundEndpoint, ProtocolEvent, ProtocolEventPage
from ordessa_agents.sdk.harness import HarnessDescriptor
from ordessa_agents.sdk.instances import AgentInstanceRef, EndpointRef
from ordessa_agents.sdk.interactions import (BindingProvenance, GuardedSendObservation,
                                             InteractionService, InteractionsRefused,
                                             _digest_of, freeze_prompt)
from ordessa_agents.sdk.manager import Records
from ordessa_agents.sdk.native_envelope import PendingRequestRef

DIGEST = 'sha256:' + 'a' * 64
SCOPE = 'principal:test'
PROTOCOL = 'test-native/1'
PROFILE = ProfileRevisionRef('env-1', 'profile-1', 1, DIGEST)
ENDPOINT = EndpointRef('issuer', 'endpoint', '1', DIGEST)


class ProcessWaitTimeout(Exception):
    """Same class name the local output port raises on an idle read."""


class FakeCodec:
    protocol_id = PROTOCOL
    protocol_version = 1
    capabilities = frozenset({'request', 'notify', 'events', 'reverse_requests'})

    def encode_request(self, correlation_id, message):
        value = {'jsonrpc': '2.0', 'id': correlation_id,
                 'method': message['method'], 'params': message.get('params', {})}
        for key, item in message.items():
            if key not in ('method', 'params'):
                value[key] = item
        return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()

    def encode_notify(self, message):
        value = {'jsonrpc': '2.0', 'method': message['method'],
                 'params': message.get('params', {})}
        return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()

    def classify(self, value):
        if value.get('jsonrpc') != '2.0':
            raise ValueError('not jsonrpc')
        if 'method' in value and 'id' in value:
            return 'reverse_request', str(value['id']), str(value['method'])
        if 'method' in value:
            return 'notification', None, str(value['method'])
        return 'response', str(value.get('id')), None

    def terminal_state(self, value):
        return 'failed' if 'error' in value else 'completed'

    def encode_reply(self, correlation_id, reply):
        return (json.dumps({'jsonrpc': '2.0', 'id': correlation_id, **reply},
                           sort_keys=True, separators=(',', ':')) + '\n').encode()


class Channel:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.written = []

    async def send_guarded(self, frame, request_id, deadline, invocation, *,
                           binding, write_guard):
        # The endpoint port shape: an object exposing the synchronous cut.
        with write_guard.guard_write(binding, invocation):
            self.written.append(frame)
        return GuardedSendObservation('endpoint-op-' + str(len(self.written)),
                                      'confirmed', len(frame))

    async def receive(self, cursor, deadline, invocation):
        timeout = max(0.001, deadline - asyncio.get_running_loop().time())
        try:
            chunk = await asyncio.wait_for(self.incoming.get(), timeout)
        except TimeoutError:
            raise ProcessWaitTimeout('idle read') from None
        return ProtocolEventPage(
            (ProtocolEvent('bytes', 'sha256:' + hashlib.sha256(chunk).hexdigest(), chunk),),
            cursor=None, has_more=False)

    def push(self, value):
        """Queue one frame in bounded chunks, like a real byte stream."""
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        for index in range(0, len(raw), 65536):
            self.incoming.put_nowait(raw[index:index + 65536])


class Authority:
    def __init__(self):
        self.denied = set()

    def _allow(self, name):
        if name in self.denied:
            raise InteractionsRefused('DENIED')

    def principal_scope(self, invocation):
        return invocation.scope

    def check_read_binding(self, invocation, instance_ref):
        self._allow('read')

    def check_read_turn(self, invocation, query):
        self._allow('read')

    def check_send(self, invocation, binding):
        self._allow('write')

    def check_native_describe(self, invocation, instance_ref):
        self._allow('read')

    def check_native_dispatch(self, invocation, binding):
        self._allow('write')

    @contextmanager
    def guard_native_dispatch(self, invocation, binding):
        self._allow('write')
        yield

    def check_read_native_operation(self, invocation, operation_ref, digest):
        self._allow('read')

    def check_read_native_events(self, invocation, instance_ref):
        self._allow('read')

    def check_native_respond(self, invocation, pending_ref):
        self._allow('write')

    def check_cancel(self, invocation, binding):
        self._allow('write')


class WriteGuard:
    """Physical-cut stand-in for the Server native write guard."""

    def __init__(self, authority):
        self.authority = authority

    @contextmanager
    def guard_write(self, binding, invocation):
        self.authority._allow('write')
        yield


class Resolver:
    def __init__(self, channel):
        self.channel = channel

    async def resolve(self, ref, invocation):
        if ref != ENDPOINT:
            raise InteractionsRefused('ENDPOINT_UNAVAILABLE')
        return BoundEndpoint(ref=ENDPOINT,
                             descriptor={'members': ('communicate',),
                                         'capabilities': ('communicate',)},
                             communicate=self.channel)


def build(path, protocol=PROTOCOL, codec=None, prompt_handlers=None):
    material = InstanceBindingMaterial(
        PROFILE,
        HarnessDescriptor('fixture', {'environmentNamespace': 'env-1',
                                      'definitionId': 'fixture', 'revision': '1'},
                          DIGEST, protocol, (), ()),
        ENDPOINT, DIGEST, DIGEST, protocol, 'session-1', 'original-source')
    instance = AgentInstanceRef('ns-test', 'instance-1', material.digest)
    values = {'schemaVersion': 'agent-binding-provenance/1',
              'instanceRef': instance.projection(), 'revision': 1,
              'profileRef': encode_revision_ref(PROFILE),
              'preparedPlanDigest': DIGEST,
              'endpointRef': ENDPOINT.projection(),
              'directoryBindingDigest': DIGEST, 'sourceRevision': 'original-source',
              'configurationRefs': [], 'capturedAt': '2026-10-19T00:00:00Z'}
    provenance = BindingProvenance.decode({**values,
                                           'observationDigest': _digest_of(values)})
    records = Records(path)
    records.publish_instance_binding(provenance, 'session-1',
                                     principal_scope=SCOPE, protocol_id=protocol)
    if records.instance_control(instance)[0] is None:
        records.publish_instance_control(
            provenance, SimpleNamespace(operation_ref='fixture-prepared-start'),
            SCOPE, binding_material=material)
    channel = Channel()
    authority = Authority()
    service = InteractionService(records, authority, Resolver(channel),
                                 native_prompts=prompt_handlers or {},
                                 native_codecs={protocol: codec or FakeCodec()})
    invocation = SimpleNamespace(scope=SCOPE)
    return SimpleNamespace(records=records, channel=channel, authority=authority,
                           guard=WriteGuard(authority),
                           service=service, instance=instance, invocation=invocation,
                           material=material)


async def wait_state(service, invocation, operation_ref, expected, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        value = service.native().query(operation_ref, invocation=invocation)
        if value['state'] == expected:
            return value
        await asyncio.sleep(0.01)
    return service.native().query(operation_ref, invocation=invocation)


async def submit(case, request_id, message, kind='request'):
    return await case.service.native().submit(
        case.instance, kind=kind, request_id=request_id, message=message,
        invocation=case.invocation, write_guard=case.guard,
        deadline=asyncio.get_running_loop().time() + 5.0)


async def wait_writes(case, count, timeout=3.0):
    """Dispatch is asynchronous by design; await the physical write explicitly."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if len(case.channel.written) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError('expected %d dispatched frames, saw %d'
                         % (count, len(case.channel.written)))


class CancelPromptHandler:
    """Protocol prompt handler: cancel frame only (turn observation unused here)."""

    protocol_id = PROTOCOL

    def encode_cancel(self, session_id, operation_ref):
        return (json.dumps({'jsonrpc': '2.0', 'method': 'turn/interrupt',
                            'params': {'threadId': session_id,
                                       'operationId': operation_ref}},
                           sort_keys=True, separators=(',', ':')) + '\n').encode()

    def encode_prompt(self, *args, **kwargs):
        raise AssertionError('not used')

    def accept(self, value, *, session_id=None):
        return False

    def outcome(self, value, *, session_id=None):
        raise AssertionError('not used')


class PendingTurnCodec(FakeCodec):
    """A codec whose turn request is acknowledged before the turn terminal."""

    def response_state(self, method, value):
        if method == 'turn/start' and 'error' not in value:
            return 'pending'
        return self.terminal_state(value)

    def notification_state(self, value, *, session_id=None, request=None, response=None):
        if value.get('method') == 'turn/completed':
            return 'completed'
        if value.get('method') == 'turn/aborted':
            return 'failed'
        return None


def wire_id_for(case, request_id, kind='request'):
    operation = 'native-request' if kind == 'request' else 'native-notify'
    row = case.records.operation(case.service._key(case.instance, request_id, SCOPE),
                                 operation)
    return row.payload['wireId']


@pytest.mark.asyncio
async def test_describe_request_accept_and_events(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    described = case.service.native().describe(case.instance, invocation=case.invocation)
    assert described['protocolId'] == PROTOCOL
    assert described['categories'] == {'request': True, 'notify': True,
                                       'events': True, 'reverseRequests': True}
    loop = asyncio.get_running_loop()
    started = loop.time()
    accepted = await submit(case, 'req-1', {'method': 'thread/start',
                                            'params': {'cwd': '/tmp'}})
    assert loop.time() - started < 2.0, 'acceptance must not wait for the protocol'
    assert accepted['state'] == 'accepted'
    assert accepted['kind'] == 'request'

    await wait_writes(case, 1)
    wire = wire_id_for(case, 'req-1')
    assert json.loads(case.channel.written[0])['id'] == wire
    case.channel.push({'jsonrpc': '2.0', 'id': wire,
                       'result': {'thread': {'id': 'thread-1'}}})
    done = await wait_state(case.service, case.invocation,
                            accepted['operationRef'], 'completed')
    assert done['state'] == 'completed'
    assert done['response']['result']['thread']['id'] == 'thread-1'

    page = case.service.native().events(case.instance, cursor=None, limit=None,
                                        invocation=case.invocation)
    kinds = [event['kind'] for event in page['events']]
    assert 'response' in kinds
    assert page['nextCursor'] == 's%d' % page['events'][-1]['seq']
    # Pure read: no resend, no extra protocol write, no new state.
    assert len(case.channel.written) == 1
    again = case.service.native().query(accepted['operationRef'],
                                        invocation=case.invocation)
    assert again['state'] == 'completed'
    case.records.close()


@pytest.mark.asyncio
async def test_notify_is_sent_without_response(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    accepted = await submit(case, 'note-1', {'method': 'notifications/initialized'},
                            kind='notify')
    assert accepted['state'] == 'accepted'
    await wait_writes(case, 1)
    payload = json.loads(case.channel.written[0])
    assert 'id' not in payload and payload['method'] == 'notifications/initialized'
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    while loop.time() < deadline:
        value = case.service.native().query(accepted['operationRef'],
                                            invocation=case.invocation)
        if value['state'] == 'sent':
            break
        await asyncio.sleep(0.01)
    assert value['state'] == 'sent'
    case.records.close()


@pytest.mark.asyncio
async def test_duplicate_request_replays_and_conflict_refuses(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    first = await submit(case, 'dup-1', {'method': 'thread/start', 'params': {}})
    second = await submit(case, 'dup-1', {'method': 'thread/start', 'params': {}})
    assert first['operationRef'] == second['operationRef']
    await wait_writes(case, 1)
    await asyncio.sleep(0.05)
    assert len(case.channel.written) == 1, 'a replay must not dispatch twice'
    with pytest.raises(InteractionsRefused) as refused:
        await submit(case, 'dup-1', {'method': 'thread/start', 'params': {'other': 1}})
    assert refused.value.code == 'REQUEST_CONFLICT'
    assert len(case.channel.written) == 1
    case.channel.push({'jsonrpc': '2.0', 'id': wire_id_for(case, 'dup-1'),
                       'error': {'code': 1, 'message': 'boom'}})
    done = await wait_state(case.service, case.invocation,
                            first['operationRef'], 'failed')
    assert done['state'] == 'failed'
    assert done['response']['error']['message'] == 'boom'
    case.records.close()


@pytest.mark.asyncio
async def test_reverse_request_reply_once(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    accepted = await submit(case, 'turn-1', {'method': 'turn/start', 'params': {}})
    case.channel.push({'jsonrpc': '2.0', 'id': 'srv-req-1',
                       'method': 'session/request_permission',
                       'params': {'options': []}})
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    pending = []
    while loop.time() < deadline:
        page = case.service.native().events(case.instance, cursor=None, limit=50,
                                            invocation=case.invocation)
        pending = [row for row in page['events'] if row['kind'] == 'reverse_request']
        if pending:
            break
        await asyncio.sleep(0.01)
    assert pending, 'the reverse request must be journaled'
    row = case.records.pending_request(case.instance, 'srv-req-1')
    assert row['state'] == 'pending'
    ref = PendingRequestRef(case.instance, row['connectionGeneration'],
                            'srv-req-1', PROTOCOL)
    reply = await case.service.native().respond(
        ref, request_id='reply-1', response={'result': {'approved': False}},
        invocation=case.invocation, write_guard=case.guard,
        deadline=loop.time() + 5.0)
    assert reply['state'] == 'sent'
    assert case.records.pending_request(case.instance, 'srv-req-1')['state'] == 'answered'
    sent = [json.loads(frame) for frame in case.channel.written]
    replies = [frame for frame in sent if frame.get('id') == 'srv-req-1']
    assert replies and replies[0]['result'] == {'approved': False}
    # A repeated identical request id replays the receipt without a second write.
    writes = len(case.channel.written)
    again = await case.service.native().respond(
        ref, request_id='reply-1', response={'result': {'approved': False}},
        invocation=case.invocation, write_guard=case.guard,
        deadline=loop.time() + 5.0)
    assert again['state'] == 'sent' and len(case.channel.written) == writes
    # A different reply for the same pending request is a conflict.
    with pytest.raises(InteractionsRefused):
        await case.service.native().respond(
            ref, request_id='reply-2', response={'result': {'approved': True}},
            invocation=case.invocation, write_guard=case.guard,
            deadline=loop.time() + 5.0)
    assert len(case.channel.written) == writes
    case.records.close()


@pytest.mark.asyncio
async def test_stale_generation_reply_refused(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    await submit(case, 'turn-1', {'method': 'turn/start', 'params': {}})
    case.channel.push({'jsonrpc': '2.0', 'id': 'srv-req-1', 'method': 'x'})
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    while loop.time() < deadline:
        row = case.records.pending_request(case.instance, 'srv-req-1')
        if row is not None:
            break
        await asyncio.sleep(0.01)
    stale = PendingRequestRef(case.instance, row['connectionGeneration'] + 7,
                              'srv-req-1', PROTOCOL)
    with pytest.raises(InteractionsRefused) as refused:
        await case.service.native().respond(
            stale, request_id='reply-stale', response={'result': {}},
            invocation=case.invocation, write_guard=case.guard,
            deadline=loop.time() + 5.0)
    assert refused.value.code == 'NATIVE_PENDING_STALE'
    assert case.records.pending_request(case.instance, 'srv-req-1')['state'] == 'pending'
    case.records.close()


@pytest.mark.asyncio
async def test_oversize_frame_fails_explicitly(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    accepted = await submit(case, 'big-1', {'method': 'turn/start', 'params': {}})
    wire = wire_id_for(case, 'big-1')
    huge = {'jsonrpc': '2.0', 'id': wire, 'result': {'text': 'x' * (1024 * 1024)}}
    case.channel.push(huge)
    done = await wait_state(case.service, case.invocation,
                            accepted['operationRef'], 'failed')
    assert done['state'] == 'failed'
    assert done['error']['code'] == 'OUTPUT_LIMIT_EXCEEDED'
    page = case.service.native().events(case.instance, cursor=None, limit=None,
                                        invocation=case.invocation)
    assert any(event['kind'] == 'oversize' for event in page['events'])
    case.records.close()


@pytest.mark.asyncio
async def test_restart_reads_facts_and_marks_unconfirmed_unknown(tmp_path):
    path = tmp_path / 'records.sqlite'
    case = build(path)
    accepted = await submit(case, 'restart-1', {'method': 'a', 'params': {}})
    case.channel.push({'jsonrpc': '2.0', 'id': wire_id_for(case, 'restart-1'),
                       'result': {'ok': True}})
    await wait_state(case.service, case.invocation, accepted['operationRef'], 'completed')
    unconfirmed = await submit(case, 'restart-2', {'method': 'b', 'params': {}})
    await case.service.native().close_all()
    case.records.close()

    second = build(path)
    value = second.service.native().query(accepted['operationRef'],
                                          invocation=second.invocation)
    assert value['state'] == 'completed'
    assert value['response']['result'] == {'ok': True}
    pending = second.service.native().query(unconfirmed['operationRef'],
                                            invocation=second.invocation)
    assert pending['state'] == 'unknown', 'a restart must not pretend to be live'
    page = second.service.native().events(second.instance, cursor=None, limit=None,
                                          invocation=second.invocation)
    assert page['events'], 'stored events stay readable after restart'
    second.records.close()


@pytest.mark.asyncio
async def test_cursor_expiry_is_explicit(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    for index in range(6):
        case.records.append_event(case.instance, kind='notification', operation_ref=None,
                                  payload={'n': index}, connection_generation=0,
                                  observed_at='2026-10-22T00:00:00Z',
                                  max_events=2, max_bytes=1024 * 1024)
    first, last, dropped_events, dropped_bytes = case.records.journal_bounds(case.instance)
    assert dropped_events == 4 and first > 1
    with pytest.raises(InteractionsRefused) as refused:
        case.service.native().events(case.instance, cursor='s0', limit=None,
                                     invocation=case.invocation)
    assert refused.value.code == 'EVENT_CURSOR_EXPIRED'
    page = case.service.native().events(case.instance, cursor='s%d' % (first - 1),
                                        limit=1, invocation=case.invocation)
    assert page['completeness']['droppedEvents'] == 4
    assert page['hasMore'] is True
    case.records.close()


@pytest.mark.asyncio
async def test_turn_operation_finishes_on_the_turn_terminal_not_the_ack(tmp_path):
    case = build(tmp_path / 'records.sqlite', codec=PendingTurnCodec())
    accepted = await submit(case, 'turn-1', {'method': 'turn/start', 'params': {}})
    wire = wire_id_for(case, 'turn-1')
    # The protocol ack arrives first: the operation must stay open.
    case.channel.push({'jsonrpc': '2.0', 'id': wire, 'result': {'turn': {'id': 't1'}}})
    await asyncio.sleep(0.2)
    open_state = case.service.native().query(accepted['operationRef'],
                                             invocation=case.invocation)
    assert open_state['state'] == 'accepted'
    # The turn terminal notification finishes it.
    case.channel.push({'jsonrpc': '2.0', 'method': 'turn/completed',
                       'params': {'threadId': 'session-1',
                                  'turn': {'id': 't1', 'status': 'completed'}}})
    done = await wait_state(case.service, case.invocation,
                            accepted['operationRef'], 'completed')
    assert done['state'] == 'completed'
    assert done['response']['method'] == 'turn/completed'
    page = case.service.native().events(case.instance, cursor=None, limit=None,
                                        invocation=case.invocation)
    kinds = [event['kind'] for event in page['events']]
    assert kinds.count('response') == 1 and kinds.count('notification') == 1
    case.records.close()


@pytest.mark.asyncio
async def test_cancel_sends_one_guarded_notification_and_is_not_stop(tmp_path):
    case = build(tmp_path / 'records.sqlite',
                 prompt_handlers={PROTOCOL: CancelPromptHandler()})
    receipt = await case.service.cancel_session(
        case.instance, request_id='cancel-1', invocation=case.invocation,
        write_guard=case.guard,
        deadline=asyncio.get_running_loop().time() + 5.0)
    # Acceptance means the cancel frame was written; it is NOT a stopped process.
    assert receipt.state == 'accepted'
    await wait_writes(case, 1)
    frame = json.loads(case.channel.written[0])
    assert frame['method'] == 'turn/interrupt'
    assert frame['params']['threadId'] == 'session-1'
    # Same request id replays the stored receipt without a second write.
    again = await case.service.cancel_session(
        case.instance, request_id='cancel-1', invocation=case.invocation,
        write_guard=case.guard,
        deadline=asyncio.get_running_loop().time() + 5.0)
    assert again == receipt and len(case.channel.written) == 1
    case.records.close()


@pytest.mark.asyncio
async def test_query_refuses_a_foreign_owner_scope(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    accepted = await submit(case, 'owner-1', {'method': 'thread/start', 'params': {}})
    foreign = SimpleNamespace(scope='principal:other')
    with pytest.raises(InteractionsRefused) as refused:
        case.service.native().query(accepted['operationRef'], invocation=foreign)
    assert refused.value.code in ('READ_NOT_AUTHORIZED', 'AUTHORITY_REFUSED',
                                  'DENIED')
    case.records.close()


@pytest.mark.asyncio
async def test_two_turns_same_session_are_separate_operations(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    first = await submit(case, 'turn-a', {'method': 'turn/start', 'params': {}})
    second = await submit(case, 'turn-b', {'method': 'turn/start', 'params': {}})
    assert first['operationRef'] != second['operationRef']
    await wait_writes(case, 2)
    assert len(case.channel.written) == 2
    # A replay of the first turn never re-sends and never returns the second one.
    replay = await submit(case, 'turn-a', {'method': 'turn/start', 'params': {}})
    assert replay['operationRef'] == first['operationRef']
    assert len(case.channel.written) == 2
    case.records.close()


@pytest.mark.asyncio
async def test_a_new_owner_expires_accepted_operations(tmp_path):
    path = tmp_path / 'records.sqlite'
    case = build(path)
    accepted = await submit(case, 'crash-1', {'method': 'thread/start', 'params': {}})
    await wait_writes(case, 1)
    # Simulate a hard crash: no runtime close, no response, a NEW owner opens
    # the same records (same process here; the constructor is the restart hook).
    from ordessa_agents.sdk.interactions import InteractionService as Svc
    restarted = Svc(case.records, case.authority, Resolver(Channel()),
                    native_codecs={PROTOCOL: FakeCodec()})
    value = restarted.native().query(accepted['operationRef'],
                                     invocation=case.invocation)
    assert value['state'] == 'unknown'
    assert value['error']['code'] == 'RESTART_UNCONFIRMED'
    # The expired fact is not a new dispatch right.
    assert len(case.channel.written) == 1
    case.records.close()


@pytest.mark.asyncio
async def test_stopping_an_instance_expires_its_accepted_work(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    accepted = await submit(case, 'stop-1', {'method': 'thread/start', 'params': {}})
    await wait_writes(case, 1)
    case.service.expire_instance(case.instance)
    value = case.service.native().query(accepted['operationRef'],
                                        invocation=case.invocation)
    assert value['state'] == 'unknown'
    assert value['error']['code'] == 'PROCESS_STOPPED'
    # Same request key: a replayed submit reads the stored fact, no new frame.
    replay = await submit(case, 'stop-1', {'method': 'thread/start', 'params': {}})
    assert replay['state'] == 'unknown'
    assert replay['operationRef'] == accepted['operationRef']
    assert len(case.channel.written) == 1
    case.records.close()


@pytest.mark.asyncio
async def test_pending_reverse_request_expires_after_runtime_loss(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    await submit(case, 'live-1', {'method': 'turn/start', 'params': {}})
    case.channel.push({'jsonrpc': '2.0', 'id': 'srv-exp-1', 'method': 'x'})
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    while loop.time() < deadline:
        row = case.records.pending_request(case.instance, 'srv-exp-1')
        if row is not None:
            break
        await asyncio.sleep(0.01)
    await case.service.native().close_all()
    # A new runtime for the same instance expires the old pending request.
    await submit(case, 'live-2', {'method': 'thread/start', 'params': {}})
    row = case.records.pending_request(case.instance, 'srv-exp-1')
    assert row['state'] == 'expired'
    ref = PendingRequestRef(case.instance, row['connectionGeneration'],
                            'srv-exp-1', PROTOCOL)
    with pytest.raises(InteractionsRefused) as refused:
        await case.service.native().respond(
            ref, request_id='reply-exp', response={'result': {}},
            invocation=case.invocation, write_guard=case.guard,
            deadline=asyncio.get_running_loop().time() + 5.0)
    assert refused.value.code in ('NATIVE_PENDING_CLOSED', 'NATIVE_PENDING_STALE')
    case.records.close()


@pytest.mark.asyncio
async def test_prompt_refused_while_runtime_owns_receive(tmp_path):
    case = build(tmp_path / 'records.sqlite')
    await submit(case, 'live-1', {'method': 'turn/start', 'params': {}})
    assert case.service.native().has_live(case.instance)
    params = json.dumps({'sessionId': 'session-1',
                         'prompt': [{'type': 'text', 'text': 'hello'}]},
                        sort_keys=True, separators=(',', ':')).encode()
    prompt = freeze_prompt(case.instance, params)
    with pytest.raises(InteractionsRefused) as refused:
        await case.service._prompt_recorded(
            case.instance, prompt, request_id='prompt-1',
            engineering_attempt_ref=None, invocation=case.invocation,
            write_guard=case.authority,
            deadline=asyncio.get_running_loop().time() + 5.0)
    assert refused.value.code == 'SESSION_BUSY'
    await wait_writes(case, 1)
    assert len(case.channel.written) == 1
    case.records.close()


@pytest.mark.asyncio
async def test_turn_notification_does_not_complete_an_unrelated_request(tmp_path):
    case = build(tmp_path / 'records.sqlite', codec=PendingTurnCodec())
    read = await submit(case, 'read', {'method': 'thread/read', 'params': {}})
    turn = await submit(case, 'turn', {'method': 'turn/start', 'params': {}})
    await wait_writes(case, 2)
    case.channel.push({'jsonrpc': '2.0', 'id': wire_id_for(case, 'turn'),
                       'result': {'turn': {'id': 't1'}}})
    case.channel.push({'jsonrpc': '2.0', 'method': 'turn/completed',
                       'params': {'threadId': 'session-1',
                                  'turn': {'id': 't1', 'status': 'completed'}}})
    done = await wait_state(case.service, case.invocation, turn['operationRef'],
                            'completed', timeout=0.5)
    unrelated = case.service.native().query(read['operationRef'], invocation=case.invocation)
    await case.service.native().close_all()
    case.records.close()
    assert unrelated['state'] == 'accepted'
    assert done['state'] == 'completed'


@pytest.mark.asyncio
async def test_codex_terminals_match_acknowledged_turn_ids_out_of_order(tmp_path):
    from ordessa_harness_codex.provider import CodexNativeCodec
    codec = CodexNativeCodec()
    case = build(tmp_path / 'records.sqlite', protocol=codec.protocol_id, codec=codec)
    first = await submit(case, 'first', {'method': 'turn/start',
                                        'params': {'threadId': 'session-1'}})
    second = await submit(case, 'second', {'method': 'turn/start',
                                          'params': {'threadId': 'session-1'}})
    await wait_writes(case, 2)
    for request_id, turn_id in [('first', 't1'), ('second', 't2')]:
        case.channel.push({'id': wire_id_for(case, request_id),
                           'result': {'turn': {'id': turn_id}}})
    case.channel.push({'method': 'turn/completed', 'params': {
        'threadId': 'session-1', 'turn': {'id': 't2', 'status': 'completed'}}})
    done = await wait_state(case.service, case.invocation, second['operationRef'], 'completed')
    assert done['state'] == 'completed'
    assert case.service.native().query(first['operationRef'],
        invocation=case.invocation)['state'] == 'accepted'
    # A delayed duplicate terminal must not end the remaining turn either.
    case.channel.push(done['response'])
    await asyncio.sleep(0.05)
    assert case.service.native().query(first['operationRef'],
        invocation=case.invocation)['state'] == 'accepted'
    case.channel.push({'method': 'turn/completed', 'params': {
        'threadId': 'session-1', 'turn': {'id': 't1', 'status': 'completed'}}})
    assert (await wait_state(case.service, case.invocation,
                            first['operationRef'], 'completed'))['state'] == 'completed'
    await case.service.native().close_all()
    case.records.close()


@pytest.mark.asyncio
async def test_ambiguous_session_terminal_never_guesses_a_completed_operation(tmp_path):
    case = build(tmp_path / 'records.sqlite', codec=PendingTurnCodec())
    accepted = [await submit(case, key, {'method': 'turn/start', 'params': {}})
                for key in ('first', 'second')]
    await wait_writes(case, 2)
    for key in ('first', 'second'):
        case.channel.push({'jsonrpc': '2.0', 'id': wire_id_for(case, key), 'result': {}})
    case.channel.push({'jsonrpc': '2.0', 'method': 'turn/completed', 'params': {}})
    for item in accepted:
        result = await wait_state(case.service, case.invocation, item['operationRef'], 'unknown')
        assert result['state'] == 'unknown'
        assert result['error']['code'] == 'NATIVE_TERMINAL_AMBIGUOUS'
    await case.service.native().close_all()
    case.records.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('lose_receipt', [False, True])
async def test_concurrent_reverse_replies_never_write_twice(tmp_path, lose_receipt):
    case = build(tmp_path / 'records.sqlite')
    await submit(case, 'live', {'method': 'turn/start', 'params': {}})
    await wait_writes(case, 1)
    runtime = case.service.native().live(case.instance)
    runtime._handle_frame({'jsonrpc': '2.0', 'id': 'approval', 'method': 'permission'})
    pending = case.records.pending_request(case.instance, 'approval')
    ref = PendingRequestRef(case.instance, pending['connectionGeneration'], 'approval', PROTOCOL)
    original = case.channel.send_guarded

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(0.03)
        result = await original(*args, **kwargs)
        if lose_receipt:
            raise OSError('receipt lost after write')
        return result

    case.channel.send_guarded = slow_send
    async def reply(key):
        return await case.service.native().respond(ref, request_id=key,
            response={'result': {'approved': False}}, invocation=case.invocation,
            write_guard=case.guard, deadline=asyncio.get_running_loop().time() + 5)

    replies = await asyncio.gather(reply('reply-a'), reply('reply-b'), return_exceptions=True)
    assert sum(isinstance(item, InteractionsRefused) for item in replies) == 1
    written = [json.loads(frame) for frame in case.channel.written]
    assert sum(frame.get('id') == 'approval' for frame in written) == 1
    with pytest.raises(InteractionsRefused):
        await reply('reply-c')
    await case.service.native().close_all()
    case.records.close()
