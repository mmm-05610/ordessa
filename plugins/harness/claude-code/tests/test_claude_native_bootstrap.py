"""claude-stream-json/1 native bootstrap (pinned session id + control handshake)."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.profiles import ConfigurationDeclaration
from ordessa_execution_agents.sdk.harness import HarnessError, PrepareContext, ProfileContent, SessionBootstrap
from ordessa_harness_claude_code.client import ClaudeHarnessProvider

REF = {'environmentNamespace': 'ns-1', 'definitionId': 'claude-code', 'revision': '0.1.0a1'}
DIGEST = 'sha256:' + 'a' * 64
SESSION = 'aab7def5-cb8d-4df8-a251-9f496d3c9554'


class Channel:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.sent = reply, error, []

    async def exchange(self, label, encode, accept=None):
        frame = encode('agent-start/op/' + label)
        self.sent.append(json.loads(frame))
        if self.error is not None:
            raise self.error
        return self.reply


def provider():
    return ClaudeHarnessProvider(dict(REF), DIGEST)


def context():
    return PrepareContext({'members': ['launcher', 'communicate']}, {},
                          ('/usr/bin/claude',), {}, (), (), (), SessionBootstrap('fresh', '/work'))


def plan(session_id=SESSION):
    argv = ('/usr/bin/claude', '-p', '--session-id', session_id) if session_id else ('/usr/bin/claude', '-p')
    return SimpleNamespace(argv=argv)


def test_bootstrap_pins_the_native_id_and_proves_the_control_handshake():
    channel = Channel({'type': 'control_response',
                       'response': {'subtype': 'success', 'request_id': 'x'}})
    session = asyncio.run(provider().open_native_session(
        SimpleNamespace(native_channel=channel), context(), plan()))
    assert session.session_id == SESSION
    assert session.protocol_id == 'claude-stream-json/1'
    assert channel.sent and channel.sent[0]['type'] == 'control_request'
    assert channel.sent[0]['request'] == {'subtype': 'initialize'}


def test_a_plan_without_a_pinned_session_id_is_refused():
    with pytest.raises(HarnessError, match='NATIVE_SESSION_INVALID'):
        asyncio.run(provider().open_native_session(
            SimpleNamespace(native_channel=Channel({})), context(), plan(None)))


def test_the_bootstrap_refuses_without_a_native_channel():
    with pytest.raises(HarnessError, match='NATIVE_BOOTSTRAP_UNAVAILABLE'):
        asyncio.run(provider().open_native_session(SimpleNamespace(), context(), plan()))


def credential(payload):
    return ConfigurationDeclaration('c1', 'credentials.file', '1', 'value', 'required', payload, None)


def test_credential_binding_declaration_is_admitted():
    provider().validate_profile(ProfileContent('1', REF, (credential({
        'sourcePath': '/home/u/.claude/.credentials.json', 'rootKey': 'config',
        'relativePath': '.credentials.json'}),)))


def test_malformed_credential_binding_is_refused():
    with pytest.raises(HarnessError, match='CONFIGURATION_INVALID'):
        provider().validate_profile(ProfileContent('1', REF, (credential({
            'sourcePath': '/home/u/x', 'rootKey': 'config'}),)))
