"""Codex app-server terminal classification (controlled frames).

The pinned app-server reports retryable transport failures as an ``error``
notification with ``willRetry: true`` (``Reconnecting... 2/5``). That frame is
informational: the turn is still alive, so an accepted operation must not end
with ``failed`` on it. Only a non-retryable error (or ``turn/completed`` with a
failed status) is terminal.
"""

from __future__ import annotations

import pytest

from ordessa_agents.profiles.definitions.models import (
    ConfigurationDeclaration, ProfileContent)
from ordessa_harness_codex.provider import CodexHarnessProvider, HarnessError


def _codec():
    provider = CodexHarnessProvider(
        {'environmentNamespace': 'test', 'definitionId': 'codex', 'revision': '1'},
        'sha256:' + 'a' * 64)
    return provider.native_codec()


def test_retryable_error_is_not_a_terminal_fact():
    codec = _codec()
    frame = {'method': 'error',
             'params': {'threadId': 'thread-1',
                        'error': {'message': 'Reconnecting... 2/5',
                                  'willRetry': True,
                                  'codexErrorInfo': {'responseStreamDisconnected':
                                                     {'httpStatusCode': None}}}}}
    assert codec.notification_state(frame, session_id='thread-1') is None


def test_non_retryable_error_ends_the_operation():
    codec = _codec()
    frame = {'method': 'error',
             'params': {'threadId': 'thread-1',
                        'error': {'message': 'turn failed', 'willRetry': False}}}
    assert codec.notification_state(frame, session_id='thread-1') == 'failed'


def test_turn_completed_is_terminal_and_keeps_its_status():
    codec = _codec()
    assert codec.notification_state(
        {'method': 'turn/completed',
         'params': {'threadId': 'thread-1', 'turn': {'id': 't', 'status': 'completed'}}},
        session_id='thread-1') == 'completed'
    assert codec.notification_state(
        {'method': 'turn/completed',
         'params': {'threadId': 'thread-1', 'turn': {'id': 't', 'status': 'interrupted'}}},
        session_id='thread-1') == 'failed'


def _provider():
    return CodexHarnessProvider(
        {'environmentNamespace': 'test', 'definitionId': 'codex', 'revision': '1'},
        'sha256:' + 'a' * 64)


def _content(payload):
    return ProfileContent(
        'profile-content/1',
        {'environmentNamespace': 'test', 'definitionId': 'codex', 'revision': '1'},
        (ConfigurationDeclaration(
            'cfg', 'codex.configuration', '1', 'value', 'required',
            dict(payload), ()),))


def test_codex_sandbox_mode_is_a_supported_configuration():
    provider = _provider()
    content = _content({'sandbox': 'danger-full-access'})
    assert provider._options(content)['thread_params']['sandbox'] == 'danger-full-access'
    with pytest.raises(HarnessError):
        provider._options(_content({'sandbox': 'yolo-imaginary'}))
