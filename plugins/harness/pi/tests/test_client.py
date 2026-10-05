"""L1 exact Pi v0.86.1 RPC shapes, not an actual native process test.

Source: earendil-works/pi commit 13cbf77df2396303013a41646bcfa77b4271ae56,
packages/coding-agent/src/modes/rpc/rpc-mode.ts:394-415,428-443,450-465.
The older test_pi_client fixture's disposition field is an extension shape;
upstream success(id, 'prompt') has no data. These tests do not use a model.
"""
from collections import deque

import pytest

from ordessa_harness_pi.client import PiRpcClient, PiCommandError
from ordessa_harness_transport import (
    ChannelClosed, LostReceipt, Message, RequestTimeout,
)


class Channel:
    def __init__(self, *frames, write_error=None):
        self.frames = deque(frames)
        self.sent = []
        self.write_error = write_error

    def send_raw(self, payload):
        self.sent.append(payload)
        if self.write_error:
            raise self.write_error

    def next_message(self, *, timeout):
        if not self.frames:
            raise RequestTimeout('fixture', None, timeout)
        value = self.frames.popleft()
        if isinstance(value, BaseException):
            raise value
        return Message(raw=value)


def response(n=1, command='prompt', **fields):
    return {'id': f'req-{n}', 'type': 'response', 'command': command,
            'success': True, **fields}


def test_pinned_success_is_accepted_and_only_settle_concludes():
    accepted = response()
    end = {'type': 'agent_end', 'willRetry': True, 'messages': []}
    settle = {'type': 'agent_settled'}
    channel = Channel(accepted, end, settle)
    client = PiRpcClient(channel)
    assert client.send_prompt('hello') == accepted
    assert client.events() == ()
    assert client.wait_settled(timeout=.1) == settle
    assert client.events() == (end, settle)
    assert len(channel.sent) == 1


def test_agent_end_does_not_fake_completion():
    channel = Channel(response(), {'type': 'agent_end', 'willRetry': False})
    client = PiRpcClient(channel)
    client.send_prompt('hello')
    with pytest.raises(RequestTimeout):
        client.wait_settled(timeout=.001)
    assert len(channel.sent) == 1


def test_old_settle_cannot_conclude_second_prompt():
    first_settle = {'type': 'agent_settled'}
    channel = Channel(response(), first_settle, response(2))
    client = PiRpcClient(channel)
    client.send_prompt('first')
    assert client.wait_settled(timeout=.1) == first_settle
    client.send_prompt('second')
    with pytest.raises(RequestTimeout):
        client.wait_settled(timeout=.001)
    assert len(channel.sent) == 2


def test_settle_arriving_before_receipt_is_preserved():
    settle = {'type': 'agent_settled', 'futureField': 7}
    client = PiRpcClient(Channel(settle, response()))
    assert client.send_prompt('hello') == response()
    assert client.wait_settled(timeout=.1) == settle


@pytest.mark.parametrize('bad', [
    response(command='abort'), response(success=1),
    {'id': 'req-1', 'type': 'response', 'command': 'prompt'},
])
def test_wrong_command_or_invalid_receipt_retains_unknown(bad):
    channel = Channel(bad)
    client = PiRpcClient(channel)
    with pytest.raises(LostReceipt):
        client.send_prompt('hello')
    assert client.pending == {'req-1': 'prompt'}
    assert client.wait_settled(timeout=.1)['outcome'] == 'unknown'
    assert len(channel.sent) == 1


@pytest.mark.parametrize('fields', [{'id': 'forged'}, {'type': 'prompt'}])
def test_generic_fields_cannot_replace_wire_identity(fields):
    channel = Channel()
    with pytest.raises(ValueError, match='identity'):
        PiRpcClient(channel).command('get_state', **fields)
    assert channel.sent == []


@pytest.mark.parametrize('payload', [{'id': 'forged'}, {'type': 'prompt'}])
def test_callback_fields_cannot_replace_wire_identity(payload):
    channel = Channel()
    with pytest.raises(ValueError, match='identity'):
        PiRpcClient(channel).reply_extension_ui('actual-ui-id', payload)
    assert channel.sent == []


def test_partial_write_stays_unknown_without_resend():
    channel = Channel(write_error=ChannelClosed('partial write possible'))
    client = PiRpcClient(channel)
    with pytest.raises(LostReceipt):
        client.send_prompt('hello')
    assert client.pending == {'req-1': 'prompt'}
    assert client.wait_settled(timeout=.1)['outcome'] == 'unknown'
    assert len(channel.sent) == 1


def test_disconnect_after_acceptance_is_unknown():
    channel = Channel(response(), ChannelClosed('peer disconnected'))
    client = PiRpcClient(channel)
    client.send_prompt('hello')
    with pytest.raises(LostReceipt):
        client.wait_settled(timeout=.1)
    assert client.wait_settled(timeout=.1)['outcome'] == 'unknown'
    assert len(channel.sent) == 1


def test_rejection_is_not_settled_or_success():
    client = PiRpcClient(Channel(response(success=False, error='no model')))
    with pytest.raises(PiCommandError) as caught:
        client.send_prompt('hello')
    assert caught.value.raw['error'] == 'no model'
    assert client.events() == ()


def test_cancel_clear_queue_is_two_native_commands_not_task_success():
    queued = response(command='clear_queue', data={'steering': ['x'], 'followUp': []})
    aborted = response(2, command='abort')
    channel = Channel(queued, aborted)
    assert PiRpcClient(channel).cancel(clear_queue=True) == aborted
    assert [v['type'] for v in channel.sent] == ['clear_queue', 'abort']


def test_unknown_event_survives_native_prompt_receipt():
    event = {'type': 'future-native-event', 'opaque': {'a': [1, 2]}}
    client = PiRpcClient(Channel(event, response(), {'type': 'agent_settled'}))
    client.send_prompt('hello')
    client.wait_settled(timeout=.1)
    assert client.events()[0] == event
