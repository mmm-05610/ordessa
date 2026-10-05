"""Pinned Pi 0.86.1 convenience guards; L1 fixtures, no native/model call.

Official types/rpc-mode.ts at 13cbf77df2396303013a41646bcfa77b4271ae56.
Raw command intentionally remains a native protocol escape hatch.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import pytest

from ordessa_agent_tools.native_clients.pi import PiRpcClient
from ordessa_agent_tools.native_clients._transport import (
    ChannelClosed, FramingError, LostReceipt, Message, RequestTimeout,
)


class Channel:
    def __init__(self, *frames):
        self.frames = deque(frames)
        self.sent = []
        self.write_error = None

    def send_raw(self, payload):
        self.sent.append(payload)
        if self.write_error:
            raise self.write_error

    def next_message(self, *, timeout):
        if not self.frames:
            raise RequestTimeout('fixture', None, timeout)
        frame = self.frames.popleft()
        if isinstance(frame, BaseException):
            raise frame
        return Message(raw=frame)


def dialog(method='confirm', **fields):
    native = {'type': 'extension_ui_request', 'id': 'ui-1',
              'method': method, 'title': 'Choice'}
    native.update({'confirm': {'message': 'Proceed?'}, 'select': {'options': ['x']}}
                  .get(method, {}))
    native.update(fields)
    return native


def observe(client, frame):
    client._channel.frames.append(frame)
    assert client.next_event(timeout=.01) == frame


def test_unknown_prompt_blocks_new_id_even_different_message_and_fields():
    channel = Channel()
    client = PiRpcClient(channel)
    with pytest.raises(RequestTimeout):
        client.send_prompt('first', timeout=.001)
    for fields in ({}, {'streamingBehavior': 'followUp'}, {'requestKey': 'different'}):
        with pytest.raises(LostReceipt, match='prior prompt'):
            client.send_prompt('different', timeout=.001, **fields)
    assert client.pending == {'req-1': 'prompt'}
    assert len(channel.sent) == 1
    assert client._request_seq == 1


@pytest.mark.parametrize('success', [True, False])
def test_late_receipt_clears_pending_but_does_not_clear_unknown(success):
    channel = Channel()
    client = PiRpcClient(channel)
    with pytest.raises(RequestTimeout):
        client.send_prompt('first', timeout=.001)
    receipt = {'type': 'response', 'id': 'req-1', 'command': 'prompt', 'success': success}
    observe(client, receipt)
    assert client.pending == {}
    assert client.wait_settled(timeout=.01)['outcome'] == 'unknown'
    with pytest.raises(LostReceipt):
        client.send_prompt('another')
    assert len(channel.sent) == 1


def test_raw_command_keeps_explicit_native_semantics_when_convenience_unknown():
    channel = Channel()
    client = PiRpcClient(channel)
    with pytest.raises(RequestTimeout):
        client.send_prompt('first', timeout=.001)
    native = {'type': 'response', 'id': 'req-2', 'command': 'prompt', 'success': True}
    channel.frames.append(native)
    assert client.command('prompt', message='explicit native choice') == native
    with pytest.raises(LostReceipt):
        client.send_prompt('still blocked')
    assert len(channel.sent) == 2


@pytest.mark.parametrize('method,payload', [
    ('select', {'value': 'x'}), ('confirm', {'confirmed': False}),
    ('input', {'value': ''}), ('editor', {'value': 'edited'}),
    ('confirm', {'cancelled': True}), ('input', {'cancelled': True}),
])
def test_reply_only_observed_dialog_native_shape_once(method, payload):
    channel = Channel()
    client = PiRpcClient(channel)
    observe(client, dialog(method))
    with pytest.raises(ValueError, match='pending'):
        client.reply_extension_ui('wrong-id', payload)
    client.reply_extension_ui('ui-1', payload)
    assert channel.sent == [{'id': 'ui-1', 'type': 'extension_ui_response', **payload}]
    with pytest.raises(ValueError, match='pending'):
        client.reply_extension_ui('ui-1', payload)
    assert len(channel.sent) == 1


@pytest.mark.parametrize('method', ['notify', 'setStatus', 'setWidget', 'setTitle',
                                  'set_editor_text', 'futureMethod', None])
def test_notifications_unknown_and_missing_method_do_not_grant_reply(method):
    channel = Channel()
    client = PiRpcClient(channel)
    frame = {'type': 'extension_ui_request', 'id': 'notice', 'method': method,
             'message': 'visible'}
    observe(client, frame)
    with pytest.raises(ValueError, match='pending'):
        client.reply_extension_ui('notice', {'confirmed': True})
    assert channel.sent == []


@pytest.mark.parametrize('fields', [
    {'id': None}, {'id': []}, {'id': ''}, {'title': None}, {'message': 7},
    {'timeout': True}, {'timeout': float('nan')}, {'timeout': -1},
])
def test_malformed_dialog_is_visible_but_not_replyable(fields):
    frame = dialog(**fields)
    channel = Channel(frame)
    client = PiRpcClient(channel)
    with pytest.raises(FramingError):
        client.next_event(timeout=.01)
    assert client.events() == (frame,)
    with pytest.raises(ValueError):
        client.reply_extension_ui('ui-1', {'confirmed': True})
    assert channel.sent == []


@pytest.mark.parametrize('method,fields', [
    ('select', {'options': None}), ('select', {'options': [1]}),
    ('input', {'placeholder': 1}), ('editor', {'prefill': False}),
])
def test_malformed_method_specific_fields_do_not_grant_reply(method, fields):
    channel = Channel(dialog(method, **fields))
    client = PiRpcClient(channel)
    with pytest.raises(FramingError):
        client.next_event(timeout=.01)
    assert channel.sent == []


@pytest.mark.parametrize('payload', [{}, {'confirmed': 1}, {'value': 'yes'},
                                    {'cancelled': False}, {'confirmed': True, 'extra': 1}])
def test_invalid_response_does_not_consume_pending_dialog(payload):
    channel = Channel()
    client = PiRpcClient(channel)
    observe(client, dialog())
    with pytest.raises(ValueError, match='native method'):
        client.reply_extension_ui('ui-1', payload)
    assert channel.sent == []
    client.reply_extension_ui('ui-1', {'confirmed': False})
    assert len(channel.sent) == 1


def test_duplicate_inbound_id_cannot_resurrect_consumed_response():
    channel = Channel()
    client = PiRpcClient(channel)
    observe(client, dialog())
    client.reply_extension_ui('ui-1', {'confirmed': True})
    channel.frames.append(dialog('input'))
    with pytest.raises(FramingError, match='duplicate'):
        client.next_event(timeout=.01)
    with pytest.raises(ValueError, match='pending'):
        client.reply_extension_ui('ui-1', {'value': 'replacement'})
    assert len(channel.sent) == 1


def test_lost_response_write_cannot_be_retried():
    channel = Channel()
    client = PiRpcClient(channel)
    observe(client, dialog())
    channel.write_error = ChannelClosed('partial write possible')
    with pytest.raises(ChannelClosed):
        client.reply_extension_ui('ui-1', {'confirmed': False})
    with pytest.raises(ValueError, match='pending'):
        client.reply_extension_ui('ui-1', {'confirmed': False})
    assert len(channel.sent) == 1


def test_parallel_reply_consumes_once():
    channel = Channel()
    client = PiRpcClient(channel)
    observe(client, dialog())
    def reply(_):
        try:
            client.reply_extension_ui('ui-1', {'confirmed': False})
            return 'sent'
        except ValueError:
            return 'refused'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reply, range(8)))
    assert results.count('sent') == 1
    assert len(channel.sent) == 1


def test_malformed_ui_after_prompt_write_marks_outcome_unknown():
    channel = Channel(dialog(title=None))
    client = PiRpcClient(channel)
    with pytest.raises(LostReceipt):
        client.send_prompt('first', timeout=.01)
    with pytest.raises(LostReceipt, match='prior prompt'):
        client.send_prompt('second')
    assert len(channel.sent) == 1
