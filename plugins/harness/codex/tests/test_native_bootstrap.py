"""codex-app-server/1 native bootstrap and credential-binding admission."""
import asyncio
from types import SimpleNamespace

import pytest

from ordessa_agents.profiles import ConfigurationDeclaration
from ordessa_agents.sdk.harness import HarnessError, PrepareContext, ProfileContent, SessionBootstrap
from ordessa_harness_codex.provider import CodexHarnessProvider

REF = {'environmentNamespace': 'ns-1', 'definitionId': 'codex', 'revision': '0.1.0a1'}
DIGEST = 'sha256:' + 'a' * 64


class Channel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def exchange(self, label, encode, accept=None):
        self.calls.append(label)
        frame = encode('agent-start/op/' + label)
        assert frame.endswith(b'\n')
        return self.replies.pop(0)


def provider():
    return CodexHarnessProvider(dict(REF), DIGEST)


def context():
    return PrepareContext({'members': ['launcher', 'communicate']}, {},
                          ('/usr/bin/codex',), {}, (), (), (), SessionBootstrap('fresh', '/work'))


def content(declarations):
    return ProfileContent('1', REF, tuple(declarations))


def credential(declaration_id='c1', payload=None):
    return ConfigurationDeclaration(declaration_id, 'credentials.file', '1', 'value',
        'required', payload if payload is not None else
        {'sourcePath': '/home/u/.codex/auth.json', 'rootKey': 'home',
         'relativePath': 'auth.json'}, None)


def test_native_bootstrap_returns_the_thread_session_id():
    channel = Channel([
        {'jsonrpc': '2.0', 'id': 'a', 'result': {'userAgent': 'codex/0.157.1'}},
        {'jsonrpc': '2.0', 'id': 'b', 'result': {'thread': {'id': 't-1', 'sessionId': 't-1'}}},
    ])
    session = asyncio.run(provider().open_native_session(
        SimpleNamespace(native_channel=channel), context(),
        SimpleNamespace(argv=('/usr/bin/codex', 'app-server'))))
    assert session.session_id == 't-1'
    assert session.protocol_id == 'codex-app-server/1'
    assert channel.calls == ['initialize', 'thread/start'], 'exactly two guarded frames'


@pytest.mark.parametrize('replies', [
    [{'error': {'code': -1}}, {'result': {'thread': {'id': 't'}}}],
    [{'result': {}}, {'result': {}}],
    [{'result': {}}, {'result': {'thread': {'sessionId': ''}}}],
])
def test_invalid_replies_are_refused(replies):
    channel = Channel(replies)
    with pytest.raises(HarnessError):
        asyncio.run(provider().open_native_session(
            SimpleNamespace(native_channel=channel), context(), None))


def test_credential_binding_declaration_is_admitted_without_secrets():
    provider().validate_profile(content([credential()]))


@pytest.mark.parametrize('payload', [
    {'sourcePath': 'relative/path', 'rootKey': 'home', 'relativePath': 'auth.json'},
    {'sourcePath': '/abs', 'rootKey': 'home'},
    {'sourcePath': '', 'rootKey': 'home', 'relativePath': 'auth.json'},
])
def test_malformed_credential_binding_is_refused(payload):
    with pytest.raises(HarnessError, match='CONFIGURATION_INVALID'):
        provider().validate_profile(content([credential(payload=payload)]))
