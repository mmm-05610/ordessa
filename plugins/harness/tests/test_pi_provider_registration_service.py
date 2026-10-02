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
    outcome = f.service.query(plan)
    assert outcome.state == 'unknown'
    assert isinstance(outcome.reason, str) and outcome.reason.startswith('PI_')


def test_first_mismatch_condition_codes_are_nominal_and_ordered(rig):
    """The reported code names the first failed check in evaluation order and
    never carries a digest, id or value (N1 diagnosis whitelist)."""
    f = rig; plan = prepare(f)
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'observed'
    f.snapshot.native_generation = 'advanced'
    f.record['kind'] = 'not-registration'
    assert f.service.query(plan).reason == 'PI_GENERATION_ADVANCED'
    f.snapshot.native_generation = 'same'
    assert f.service.query(plan).reason == 'PI_OPERATION_KIND_MISMATCH'
    f.record['kind'] = 'provider-registration'
    f.record['inputDigest'] = 'wrong'
    assert f.service.query(plan).reason == 'PI_OPERATION_IDENTITY_MISMATCH'
    del f.record['state']
    assert f.service.query(plan).reason == 'PI_OPERATION_NOT_OBSERVED'


def test_missing_operation_record_names_the_exact_condition(rig):
    f = rig; plan = prepare(f)
    f.channel._configuration_rpc.side_effect = ValueError('identity already exists')
    f.channels.query_native_operation.side_effect = lambda *args: (f.owner, None)
    outcome = f.service.execute(plan, f.desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_OPERATION_RECORD_MISSING'
    # A refused registration never becomes retryable: the next apply only queries.
    outcome2 = f.service.execute(plan, f.desired, credential='private-test-key')
    assert outcome2.state == 'unknown' and f.channel._configuration_rpc.call_count == 2


def test_unobserved_registration_keeps_unknown_with_condition_code(rig):
    """A registration whose native outcome never settles stays unknown and
    names the exact condition, never a replayed effect (real adapter leaves a
    state-unknown record when its own readback check fails)."""
    f = rig; plan = prepare(f)
    def failed_registration(native, method, params):
        assert method.endswith('provider-register')
        f.record.update(kind='provider-registration', state='unknown',
            operationId=params['operationId'], sessionId=native,
            target=asdict(f.target), inputDigest=f.service.digest(params), after=None)
        return f.owner, f.record
    f.channel._configuration_rpc.side_effect = failed_registration
    outcome = f.service.execute(plan, f.desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_OPERATION_NOT_OBSERVED'
    # Query-only afterwards: no second registration effect.
    again = f.service.execute(plan, f.desired, credential='private-test-key')
    assert again.state == 'unknown' and f.channel._configuration_rpc.call_count == 2


def test_busy_native_readback_names_busy_before_record_checks(rig):
    f = rig; plan = prepare(f)
    assert f.service.execute(plan, f.desired, credential='private-test-key').state == 'observed'
    f.snapshot.busy = True
    assert f.service.query(plan).reason == 'PI_SESSION_BUSY'


def test_old_assets_missing_capability_refuse_before_any_provider_effect(rig):
    f = rig
    f.channel._configuration_rpc.side_effect = ValueError('method not found')
    with pytest.raises(ValueError): prepare(f)
    assert f.service._plans == {} and f.service._attempts == {}
    assert f.channel._configuration_rpc.call_count == 1


def _reverse_sequence_rig(defect):
    """Fake emulating the real adapter's provider-register semantics condensed:
    startup-admitted provider A in the live catalogue, then B registered, then
    A re-registered (Profile reverse switch). `defect` selects which real
    failure mode the fake exhibits on the A re-registration."""
    rig = _rig_with_admission()
    f = rig
    # Step 2: provider B live-registers successfully.
    b_desired = dict(provider='next', model='new', protocol='openai-chat',
                     endpoint='https://next.invalid/v1', credentialRef='synthetic')
    plan_b = f.service.prepare(f.target, b_desired, operation_key='switch-b', credential='private-test-key')
    result_b = f.service.execute(plan_b, b_desired, credential='private-test-key')
    assert result_b.state == 'observed'
    # Step 3: reverse switch re-registers startup provider A.
    a_desired = dict(provider='start', model='base', protocol='openai-chat',
                     endpoint='https://start.invalid/v1', credentialRef='synthetic')
    if defect == 'after-drift':
        plan_a = f.service.prepare(f.target, a_desired, operation_key='switch-a', credential='private-test-key')
        # The catalogue mutates after prepare, before the query readback.
        f.rpc_state['drift_after_prepare'] = True
        return f, plan_a, a_desired
    plan_a = f.service.prepare(f.target, a_desired, operation_key='switch-a', credential='private-test-key')
    return f, plan_a, a_desired


def _rig_with_admission():
    target = ApplicationTarget('server', 'canonical', 'channel', 3)
    owner = SimpleNamespace(connection_id='channel', native_session_id='native')
    snapshot = SimpleNamespace(target=target, owner=owner, native_generation='g1', busy=False,
        config_options=[dict(id='model', currentValue='start/base', options=[
            dict(value='start/base', _meta=dict(ordessaModel=dict(provider='start', model='base',
                api='openai-completions', baseUrl='https://start.invalid/v1')))])])
    channel = SimpleNamespace(harness_id='pi', ended=False)
    channels, owners = Mock(), Mock()
    channels.get.return_value = channel
    channels.native_session_observation.return_value = owner
    owners.readback.return_value = snapshot
    service = PiProviderRegistrationService(channels, owners, verify=lambda _: 'trusted-publication')
    # Adapter-side state: records plus the startup admission map, mirroring
    # pi-profile provider-registration semantics. The admission digest covers
    # the same provider object the creation flow registered.
    startup_provider = {'providerId': 'start', 'apiType': 'openai-completions',
        'baseUrl': 'https://start.invalid/v1', 'apiKey': 'private-test-key'}
    state = {'records': {}, 'admissions': {'start': service.digest(startup_provider)},
        'drift_after_prepare': False}
    def rpc(native, method, params):
        assert native == 'native'
        if method.endswith('provider-capability'):
            return owner, {'sessionId': native, 'supported': True, 'strategy': 'live-registration', 'version': 1}
        assert method.endswith('provider-register')
        prior = state['records'].get(params['operationId'])
        if prior is not None:
            if prior['inputDigest'] != service.digest(params):
                raise ValueError('Provider operation bound to different input')
            return owner, prior
        if any(record['state'] == 'unknown' for record in state['records'].values()):
            raise ValueError('Provider registration pending; query only')
        provider = params['provider']
        in_catalogue = any(option.get('_meta', {}).get('ordessaModel', {}).get('provider') == provider['providerId']
            for item in snapshot.config_options if item.get('id') == 'model'
            for option in item.get('options', []))
        if in_catalogue and state['admissions'].get(provider['providerId']) != service.digest(provider):
            raise ValueError('Provider identity already exists in the live catalogue')
        route = dict(provider=provider['providerId'], model=params['model'],
            api='openai-completions', baseUrl=provider['baseUrl'])
        new_option = dict(value=provider['providerId'] + '/' + params['model'], _meta=dict(ordessaModel=route))
        if state['drift_after_prepare']:
            # The native record retains a stale catalogue view; the live
            # readback the query sees later includes the new option.
            stale = [dict(id='model', currentValue=snapshot.config_options[0]['currentValue'],
                options=list(snapshot.config_options[0]['options']))]
            state['records'][params['operationId']] = dict(kind='provider-registration',
                state='observed', operationId=params['operationId'], sessionId=native,
                target=asdict(target), inputDigest=service.digest(params),
                after=dict(generation='g1', configOptions=stale))
            snapshot.config_options = [dict(id='model', currentValue=snapshot.config_options[0]['currentValue'],
                options=list(snapshot.config_options[0]['options']) + [new_option])]
        else:
            snapshot.config_options = [dict(id='model', currentValue=snapshot.config_options[0]['currentValue'],
                options=list(snapshot.config_options[0]['options']) + [new_option])]
            state['records'][params['operationId']] = dict(kind='provider-registration',
                state='observed', operationId=params['operationId'], sessionId=native,
                target=asdict(target), inputDigest=service.digest(params),
                after=dict(generation='g1', configOptions=snapshot.config_options))
            state['admissions'][provider['providerId']] = service.digest(provider)
        return owner, state['records'][params['operationId']]
    channel._configuration_rpc = Mock(side_effect=rpc)
    def query_operation(connection_id, native_session_id, operation_id):
        record = state['records'].get(operation_id)
        if record is None:
            raise ValueError('Unknown provider registration')
        return owner, record
    channels.query_native_operation.side_effect = query_operation
    return SimpleNamespace(service=service, target=target, owner=owner, snapshot=snapshot,
        channel=channel, channels=channels, owners=owners, rpc_state=state)


def test_reverse_switch_registration_succeeds_when_admission_is_shared():
    f, plan, desired = _reverse_sequence_rig('green')
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'observed' and outcome.reason is None


def test_admission_map_loss_refuses_as_missing_record_and_stays_query_only():
    f, plan, desired = _reverse_sequence_rig('admission-lost')
    del f.rpc_state['admissions']['start']
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_EVIDENCE_UNAVAILABLE'
    # The refused attempt is recorded Python-side; a retry only queries.
    again = f.service.execute(plan, desired, credential='private-test-key')
    assert again.state == 'unknown'
    with pytest.raises(ValueError, match='already pending'):
        f.service.prepare(f.target, desired, operation_key='switch-a2', credential='private-test-key')


def test_typed_native_refusal_is_terminal_and_never_wedges_the_target():
    """A typed invalid-params answer over the same pinned owner proves the
    registration was declined before any effect; the outcome is refused
    (terminal), the target accepts new preparations, and no effect is ever
    re-sent (production reverse-switch refusal shape)."""
    f, plan, desired = _reverse_sequence_rig('admission-lost')
    del f.rpc_state['admissions']['start']
    f.channels.query_native_operation_state = Mock(return_value='refused')
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'refused' and outcome.reason == 'PI_REGISTRATION_REFUSED'
    assert outcome.ticket is None and outcome.restored is None
    # Terminal: queries answer from the recorded refusal without new RPCs.
    assert f.service.query(plan).state == 'refused'
    assert f.service.execute(plan, desired, credential='private-test-key').state == 'refused'
    def register_calls():
        return [call for call in f.channel._configuration_rpc.call_args_list
                if len(call.args) > 1 and call.args[1].endswith('provider-register')
                and call.args[2]['operationId'] == plan.operation_id]
    assert len(register_calls()) == 1
    # The target is not wedged: a fresh preparation for a new key succeeds.
    fresh = f.service.prepare(f.target, desired, operation_key='switch-a-new',
                              credential='private-test-key')
    assert fresh.operation_id != plan.operation_id


def test_refusal_classification_requires_the_pinned_live_owner():
    f, plan, desired = _reverse_sequence_rig('admission-lost')
    del f.rpc_state['admissions']['start']
    f.channels.query_native_operation_state = Mock(return_value='refused')
    original = f.owners.readback.return_value
    replaced = SimpleNamespace(target=f.target, owner=object(), native_generation='g1',
        busy=False, config_options=original.config_options)
    f.owners.readback.side_effect = [original, replaced]
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_EVIDENCE_UNAVAILABLE'
    f.channels.query_native_operation_state.assert_not_called()


def test_unprovable_operation_answer_stays_unknown():
    f, plan, desired = _reverse_sequence_rig('admission-lost')
    del f.rpc_state['admissions']['start']
    f.channels.query_native_operation_state = Mock(side_effect=TimeoutError('lost'))
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_EVIDENCE_UNAVAILABLE'


def test_present_operation_answer_falls_through_to_evidence_query():
    f, plan, desired = _reverse_sequence_rig('admission-lost')
    del f.rpc_state['admissions']['start']
    f.channels.query_native_operation_state = Mock(return_value='present')
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown'
    # The fall-through consulted the operation evidence query itself.
    f.channels.query_native_operation.assert_called()


def test_unsettled_registration_outcome_names_the_condition_and_blocks_retry():
    f, plan, desired = _reverse_sequence_rig('outcome-unsettled')
    def unsettled(native, method, params):
        if method.endswith('provider-register'):
            f.rpc_state['records'][params['operationId']] = dict(
                kind='provider-registration', state='unknown', operationId=params['operationId'],
                sessionId=native, target=asdict(f.target), inputDigest=f.service.digest(params), after=None)
            return f.owner, f.rpc_state['records'][params['operationId']]
        return f.owner, f.rpc_state['records'].get(params['operationId'])
    f.channel._configuration_rpc.side_effect = unsettled
    f.channels.query_native_operation.side_effect = lambda *args: (
        f.owner, f.rpc_state['records'].get(args[-1]))
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_OPERATION_NOT_OBSERVED'


def test_after_drift_between_registration_and_query_names_digest_condition():
    f, plan, desired = _reverse_sequence_rig('after-drift')
    outcome = f.service.execute(plan, desired, credential='private-test-key')
    assert outcome.state == 'unknown' and outcome.reason == 'PI_AFTER_CONFIG_DIGEST_MISMATCH'
