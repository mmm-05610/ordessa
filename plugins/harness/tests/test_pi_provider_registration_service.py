"""Controlled Pi owner proof; no native process or inference claims."""
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ordessa_harness_api import ApplicationTarget
from ordessa_harness.configuration.model.provider_registration import PiProviderRegistrationService


@pytest.fixture
def rig():
    target = ApplicationTarget('server', 'canonical', 'channel', 3)
    owner = SimpleNamespace(connection_id='channel', native_session_id='native')
    options = [dict(id='model', currentValue='old/model', options=[])]
    snapshot = SimpleNamespace(target=target, owner=owner, native_generation='same', busy=False, config_options=options)
    channel = SimpleNamespace(harness_id='pi', ended=False)
    channels, owners = Mock(), Mock()
    channels.get.return_value = channel
    channels.native_session_observation.return_value = owner
    owners.readback.return_value = snapshot
    record = {}
    service = PiProviderRegistrationService(channels, owners, verify=lambda _: 'trusted-publication')
    def rpc(native, method, params):
        assert native == 'native'
        if method.endswith('provider-capability'):
            return owner, {'sessionId': native, 'supported': True, 'strategy': 'live-registration', 'version': 1}
        assert method.endswith('provider-register')
        route = dict(provider='next', model='new', api='openai-completions', baseUrl='https://next.invalid/v1')
        snapshot.config_options = [dict(id='model', currentValue='old/model', options=[
            dict(value='next/new', _meta=dict(ordessaModel=route))])]
        record.update(kind='provider-registration', state='observed', operationId=params['operationId'],
            sessionId=native, target=asdict(target), inputDigest=service.digest(params),
            after=dict(generation='same', configOptions=snapshot.config_options))
        return owner, record
    channel._configuration_rpc = Mock(side_effect=rpc)
    channels.query_native_operation.side_effect = lambda *args: (owner, record)
    desired = dict(provider='next', model='new', protocol='openai-chat', endpoint='https://next.invalid/v1', credentialRef='synthetic')
    return SimpleNamespace(**locals())


def prepare(f):
    return f.service.prepare(f.target, f.desired, operation_key='switch', credential='private-test-key')


def test_live_admission_never_renews_owner_and_replay_never_repeats_effect(rig):
    f = rig; plan = prepare(f)
    assert plan.mode == 'live-update'
    assert f.channel._configuration_rpc.call_count == 1  # read-only capability
    result = f.service.execute(plan, f.desired, credential='private-test-key')
    assert result.state == 'observed' and result.ticket is None
    assert result.restored.snapshot.target == f.target
    assert result.restored.snapshot.native_generation == 'same'
    f.owners.begin_restoration.assert_not_called()
    f.owners.complete_restoration.assert_not_called()
    assert f.service.credential_binding(f.snapshot, f.desired, credential='private-test-key')
    assert not f.service.credential_binding(f.snapshot, f.desired, credential='changed')
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'observed'
    assert f.channel._configuration_rpc.call_count == 2
    assert 'private-test-key' not in repr(f.service._plans) + repr(f.service._attempts)


def test_lost_reply_without_operation_proof_remains_query_only(rig):
    f = rig; plan = prepare(f)
    f.channel._configuration_rpc.side_effect = TimeoutError('private-test-key')
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'unknown'
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'unknown'
    assert f.channel._configuration_rpc.call_count == 2
    f.owners.begin_restoration.assert_not_called()


@pytest.mark.parametrize('defect', ['digest', 'target', 'generation', 'kind', 'catalogue', 'owner'])
def test_independent_proof_defects_never_confirm(rig, defect):
    f = rig; plan = prepare(f)
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'observed'
    if defect == 'digest': f.record['inputDigest'] = 'wrong'
    if defect == 'target': f.record['target']['channel_id'] = 'foreign'
    if defect == 'generation': f.snapshot.native_generation = 'new'
    if defect == 'kind': f.record['kind'] = 'not-registration'
    if defect == 'catalogue': f.record['after']['configOptions'] = []
    if defect == 'owner': f.snapshot.owner = object()
    assert f.service.query(plan).state == 'unknown'


def test_old_assets_missing_capability_refuse_before_any_provider_effect(rig):
    f = rig
    f.channel._configuration_rpc.side_effect = ValueError('method not found')
    with pytest.raises(ValueError): prepare(f)
    assert f.service._plans == {} and f.service._attempts == {}
    assert f.channel._configuration_rpc.call_count == 1
