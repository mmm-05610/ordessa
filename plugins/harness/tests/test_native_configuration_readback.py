"""Owner RPC must not borrow client IDs, infer sessions, or leak relay frames."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ordessa_harness.server_acp.registry import (
    _Channel, _ObservedTransport, AcpChannelRegistry, NativeConfigurationUnavailable,
)


class ImmediateLoop:
    def call_soon_threadsafe(self, callback, item):
        callback(item)


def rig(query=None):
    channel = _Channel(connection_id='channel', harness_id='pi', workspace_id='project',
                       profile_id='native-profile', cwd='/project')
    channel.session_id = 'canonical-ledger-session'
    channel.execution_id = 'execution'
    sent = []
    class Transport:
        def send_line(self, line):
            frame = json.loads(line)
            sent.append(frame)
            if frame['method'] == 'session/new':
                channel.deliver(json.dumps({'jsonrpc': '2.0', 'id': frame['id'],
                                            'result': {'sessionId': 'native'}}))
            elif query:
                query(channel, frame)
            else:
                answer(channel, frame)
    channel.transport = _ObservedTransport(channel, Transport())
    channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': 'client-new',
                                           'method': 'session/new', 'params': {}}))
    received = []
    channel.attach(ImmediateLoop(), received.append)
    return channel, sent, received


def answer(channel, frame, **replace):
    result = {'sessionId': 'native', 'generation': 'live-instance', 'busy': False,
              'configOptions': [{'id': 'model', 'currentValue': 'provider/model'}]}
    result.update(replace)
    channel.deliver(json.dumps({'jsonrpc': '2.0', 'id': frame['id'], 'result': result}))


def test_query_uses_confirmed_owner_and_does_not_leak_into_relay():
    channel, sent, received = rig()
    observation = channel.query_native_configuration('native')
    assert observation.owner.ledger_session_id == 'canonical-ledger-session'
    assert observation.owner.execution_id == 'execution'
    assert observation.native_generation == 'live-instance'
    assert observation.config_options[0]['currentValue'] == 'provider/model'
    observation.config_options[0]['currentValue'] = 'forged'
    assert observation.config_options[0]['currentValue'] == 'provider/model'
    assert sent[-1]['params'] == {'sessionId': 'native'}
    assert received == []
    channel.deliver(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {}}))
    assert len(received) == 1


def test_unknown_session_sends_zero_frames():
    channel, sent, _ = rig()
    with pytest.raises(NativeConfigurationUnavailable, match='owner unavailable'):
        channel.query_native_configuration('guessed')
    assert len(sent) == 1


@pytest.mark.parametrize('method', [
    '_ordessa/session/configuration', '_ordessa/session/configuration/apply',
    '_ordessa/session/configuration/operation',
])
def test_client_relay_cannot_issue_native_owner_configuration_methods(method):
    channel, sent, _ = rig()
    with pytest.raises(NativeConfigurationUnavailable, match='reserved'):
        channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': 'client-action',
            'method': method, 'params': {'sessionId': 'native'}}))
    assert len(sent) == 1


def test_internal_operation_reply_is_correlated_data_not_a_receipt():
    def operation(channel, frame):
        assert frame['method'] == '_ordessa/session/configuration/operation'
        assert frame['params'] == {'sessionId': 'native', 'operationId': 'operation'}
        channel.deliver(json.dumps({'jsonrpc': '2.0', 'id': frame['id'], 'result': {
            'sessionId': 'native', 'operationId': 'operation', 'state': 'unknown'}}))
    channel, _, received = rig(operation)
    owner, result = channel._configuration_rpc('native',
        '_ordessa/session/configuration/operation',
        {'sessionId': 'native', 'operationId': 'operation'})
    assert owner is channel.native_session_observation('native')
    assert result['state'] == 'unknown'
    assert received == []
    with pytest.raises(ValueError, match='unsupported'):
        channel._configuration_rpc('native', 'session/prompt', {'sessionId': 'native'})


def test_query_rejects_equal_id_replacement_while_waiting():
    def replace_owner(channel, frame):
        previous = channel.native_session_observation('native')
        channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': 'new-owner',
                                               'method': 'session/new', 'params': {}}))
        assert channel.native_session_observation('native') == previous
        assert channel.native_session_observation('native') is not previous
        answer(channel, frame)
    channel, _, _ = rig(replace_owner)
    with pytest.raises(NativeConfigurationUnavailable, match='owner changed'):
        channel.query_native_configuration('native')


@pytest.mark.parametrize('replacement', [
    {'sessionId': 'another-session'}, {'generation': ''}, {'busy': 'false'},
    {'configOptions': [{'id': 'model'}]}, {'configOptions': {}},
])
def test_malformed_or_cross_session_readback_is_never_evidence(replacement):
    channel, _, received = rig(lambda c, f: answer(c, f, **replacement))
    with pytest.raises(NativeConfigurationUnavailable, match='malformed'):
        channel.query_native_configuration('native')
    assert received == []
    assert not channel._configuration_queries


def test_timeout_does_not_retry_or_leak_late_reply():
    channel, sent, received = rig(lambda c, f: None)
    with pytest.raises(NativeConfigurationUnavailable, match='timed out'):
        channel.query_native_configuration('native', timeout=.01)
    assert len(sent) == 2
    answer(channel, sent[-1])
    assert received == []
    assert not channel._configuration_queries


def test_exit_wakes_pending_query_without_promoting_a_reply():
    started = threading.Event()
    channel, _, _ = rig(lambda c, f: started.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(channel.query_native_configuration, 'native')
        assert started.wait(1)
        channel.finish()
        with pytest.raises(NativeConfigurationUnavailable, match='owner changed'):
            result.result(timeout=1)
    assert not channel._configuration_queries


def test_client_cannot_reuse_reserved_owner_id_and_is_not_forwarded():
    attempts = []
    def query(channel, frame):
        with pytest.raises(NativeConfigurationUnavailable, match='conflicts'):
            channel.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': frame['id'],
                'method': 'session/new', 'params': {}}))
        attempts.append(True)
        answer(channel, frame)
    channel, sent, received = rig(query)
    channel.query_native_configuration('native')
    assert attempts == [True]
    assert len(sent) == 2 and received == []


def test_agent_error_is_unavailable_not_success():
    def error(channel, frame):
        channel.deliver(json.dumps({'jsonrpc': '2.0', 'id': frame['id'],
                                   'error': {'code': -32601, 'message': 'unsupported'}}))
    channel, _, _ = rig(error)
    with pytest.raises(NativeConfigurationUnavailable, match='refused'):
        channel.query_native_configuration('native')


def test_capacity_exhaustion_fails_closed_without_sending():
    channel, sent, _ = rig()
    channel._owner_query_ids.update(str(n) for n in range(4096))
    with pytest.raises(NativeConfigurationUnavailable, match='capacity'):
        channel.query_native_configuration('native')
    assert len(sent) == 1


def test_bidirectional_agent_request_with_same_id_still_reaches_client():
    def query(channel, frame):
        channel.deliver(json.dumps({'jsonrpc': '2.0', 'id': frame['id'],
            'method': 'session/request_permission', 'params': {'sessionId': 'native'}}))
        answer(channel, frame)
    channel, _, received = rig(query)
    assert channel.query_native_configuration('native').native_generation == 'live-instance'
    assert len(received) == 1
    assert json.loads(received[0])['method'] == 'session/request_permission'


def test_duplicate_config_ids_and_nonfinite_values_refuse_evidence():
    for options in [[{'id': 'model', 'currentValue': 'one'}, {'id': 'model', 'currentValue': 'two'}],
                    [{'id': 'model', 'currentValue': float('nan')}]]:
        channel, _, _ = rig(lambda c, f: answer(c, f, configOptions=options))
        with pytest.raises(NativeConfigurationUnavailable):
            channel.query_native_configuration('native')


def test_registry_checks_ownership_again_after_readback():
    registry = AcpChannelRegistry(session_records=None, profile_records=None, launch=None)
    with pytest.raises(NativeConfigurationUnavailable, match='channel owner unavailable'):
        registry.query_native_configuration('missing', 'native')
    def query(channel, frame):
        registry._by_id.pop('channel')
        answer(channel, frame)
    channel, _, _ = rig(query)
    registry._by_id['channel'] = channel
    with pytest.raises(NativeConfigurationUnavailable, match='channel owner changed'):
        registry.query_native_configuration('channel', 'native')
