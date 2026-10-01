"""Controlled native record tests; no production permit or real-model claim."""
from dataclasses import asdict
from types import SimpleNamespace
import copy
import json

import pytest
from ordessa_harness_api import ApplicationTarget, InvokeAction, IntentSource
from ordessa_harness.application.action_execution import ActionBatch, ActionInvocation
from ordessa_harness.server_acp.pi_action_executor import ACTION_ID, PiSessionActionExecutor, configuration_digest
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


@pytest.mark.parametrize('brand', ['codex', 'claude-code'])
def test_native_model_action_reuses_owner_fences_but_requires_its_own_brand_evidence(brand):
    from ordessa_harness.server_acp.native_action_executor import NativeSessionActionExecutor
    old, _, calls, snapshot = rig()
    snapshot.config_options[0]['id'] = 'model'
    channel = old.registry.get('channel')
    channel.harness_id = brand
    batch = ActionBatch(old.target, (ActionInvocation('provider', 'publication', InvokeAction(
        IntentSource('assets.model-provider', 'choice', '1'), ACTION_ID, '1',
        {'configId': 'model', 'value': 'low'}, 'native-model-low')),))
    def respond(native_id, method, request):
        calls.append((method, copy.deepcopy(request)))
        after = copy.deepcopy(snapshot.config_options)
        after[0]['currentValue'] = request['value']
        return snapshot.owner, {'sessionId': native_id, 'operationId': request['operationId'],
            'state': 'observed', 'generation': snapshot.native_generation,
            'target': asdict(old.target), 'manifestDigest': batch.manifest_digest,
            'beforeConfigDigest': configuration_digest(snapshot.config_options),
            'configId': 'model', 'requestedValue': 'low', 'observedValue': 'low',
            'afterConfigDigest': configuration_digest(after),
            'after': {'sessionId': native_id, 'generation': snapshot.native_generation,
                      'busy': False, 'configOptions': after},
            'evidenceRef': brand + '-native-operation:controlled'}
    channel._configuration_rpc = respond
    executor = NativeSessionActionExecutor(old.registry, old.owners, target=old.target,
        expected_configuration_digest=configuration_digest(snapshot.config_options), harness_id=brand)
    executor.preflight(batch)
    assert calls == []
    assert executor.execute('operation', batch).evidence_ref.startswith(brand + '-native-operation:')
    executor.last_receipt = None
    def foreign(*args):
        owner, record = respond(*args)
        return owner, {**record, 'evidenceRef': 'pi-native-operation:foreign'}
    channel._configuration_rpc = foreign
    with pytest.raises(NativeConfigurationUnavailable):
        executor.execute('foreign', batch)
    assert executor.last_receipt is None
    channel.harness_id = 'pi'
    count = len(calls)
    with pytest.raises(ValueError, match='owner'):
        executor.preflight(batch)
    assert len(calls) == count
