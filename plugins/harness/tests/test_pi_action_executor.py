"""Controlled native record tests; no production permit or real-model claim."""
from dataclasses import asdict
from types import SimpleNamespace
import copy
import json

import pytest
from ordessa_harness_api import ApplicationTarget, InvokeAction, IntentSource
from ordessa_harness.application.action_execution import ActionBatch, ActionInvocation
from ordessa_harness.server_acp.pi_action_executor import PiSessionActionExecutor, configuration_digest
from ordessa_harness.server_acp.registry import NativeSessionObservation, NativeConfigurationUnavailable


def rig():
    target = ApplicationTarget('server-incarnation', 'canonical', 'channel', 1)
    owner = NativeSessionObservation('channel', 'execution', 'ledger', 'native')
    options = [{'id': 'thinkingLevel', 'type': 'select', 'currentValue': 'off',
                'options': [{'value': 'off'}, {'value': 'low'}]}]
    snapshot = SimpleNamespace(owner=owner, native_generation='native-generation', config_options=options)
    calls = []
    class Channel:
        harness_id = 'pi'
        ended = False
        def _configuration_rpc(self, native_id, method, request):
            calls.append((method, copy.deepcopy(request)))
            assert native_id == 'native'
            after_options = copy.deepcopy(options)
            after_options[0]['currentValue'] = 'low'
            result = {'sessionId': 'native', 'operationId': request['operationId'],
                'state': 'observed', 'generation': 'native-generation',
                'target': asdict(target), 'manifestDigest': batch.manifest_digest,
                'beforeConfigDigest': configuration_digest(options), 'configId': 'thinkingLevel',
                'requestedValue': 'low', 'observedValue': 'low',
                'afterConfigDigest': configuration_digest(after_options),
                'after': {'sessionId': 'native', 'generation': 'native-generation',
                          'busy': False, 'configOptions': after_options},
                'evidenceRef': 'pi-native-operation:controlled'}
            return owner, result
    channel = Channel()
    registry = SimpleNamespace(get=lambda key: channel,
                               native_session_observation=lambda *args: owner)
    owners = SimpleNamespace(readback=lambda value: snapshot)
    batch = ActionBatch(target, (ActionInvocation('provider', 'publication', InvokeAction(
        IntentSource('assets.model-provider', 'choice', '1'), 'acp.session.set-config-option', '1',
        {'configId': 'thinkingLevel', 'value': 'low'}, 'native-thinking-low')),))
    executor = PiSessionActionExecutor(registry, owners, target=target,
        expected_configuration_digest=configuration_digest(options))
    return executor, batch, calls, snapshot


def test_preflight_has_no_effect_and_execute_sends_exact_bound_manifest():
    executor, batch, calls, _ = rig()
    executor.preflight(batch)
    assert calls == []
    receipt = executor.execute('operation', batch)
    assert receipt.target == batch.target
    assert receipt.manifest_digest == batch.manifest_digest
    assert receipt.native_session_identity == 'native'
    assert calls[0][1]['actionManifest'] == json.loads(batch.manifest_json)
    assert receipt is executor.last_receipt


def test_changed_before_configuration_refuses_without_native_action():
    executor, batch, calls, snapshot = rig()
    snapshot.config_options[0]['currentValue'] = 'low'
    with pytest.raises(ValueError, match='before configuration changed'):
        executor.execute('operation', batch)
    assert calls == []


@pytest.mark.parametrize('changed', [
    {'state': 'unknown'}, {'target': {}}, {'manifestDigest': '0' * 64},
    {'operationId': 'other'}, {'observedValue': 'off'}, {'generation': 'replaced'},
    {'afterConfigDigest': '0' * 64}, {'evidenceRef': 'ordinary-ack'},
])
def test_plain_ack_or_unbound_native_record_cannot_make_receipt(changed):
    executor, batch, _, _ = rig()
    channel = executor.registry.get('channel')
    original = channel._configuration_rpc
    def corrupt(*args):
        owner, result = original(*args)
        return owner, {**result, **changed}
    channel._configuration_rpc = corrupt
    with pytest.raises(NativeConfigurationUnavailable):
        executor.execute('operation', batch)
    assert executor.last_receipt is None
