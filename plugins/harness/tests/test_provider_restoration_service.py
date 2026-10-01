"""Controlled native owner/transport; no real model or Profile receipt."""
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from ordessa_harness_api import ApplicationTarget
from ordessa_harness.configuration.model.restoration import ProviderRestorationService
from ordessa_harness.server_acp.native_action_executor import configuration_digest


@pytest.fixture
def rig():
    target = ApplicationTarget('server', 'canonical', 'channel', 1)
    owner = SimpleNamespace(connection_id='channel', native_session_id='native')
    snapshot = SimpleNamespace(target=target, owner=owner, native_generation='old', busy=False,
        config_options=[dict(id='model', currentValue='old-model')])
    record = {}
    channel = SimpleNamespace(harness_id='codex', ended=False)
    channels = Mock()
    channels.get.return_value = channel
    channels.native_session_observation.return_value = owner
    owners = Mock()
    owners.readback.return_value = snapshot
    ticket = SimpleNamespace(before=snapshot)
    owners.begin_restoration.return_value = ticket
    restored = SimpleNamespace(previous_target=target, snapshot=SimpleNamespace(
        target=replace(target, runtime_generation=2), owner=owner,
        native_generation='new', config_options=[dict(id='model', currentValue='new-model')]))
    def complete(supplied):
        assert supplied is ticket
        owners.readback.return_value = restored.snapshot
        return restored
    owners.complete_restoration.side_effect = complete
    def apply(native_id, method, params):
        assert native_id == 'native' and method == '_ordessa/session/configuration/restore'
        record.update(operationId=params['operationId'], inputDigest=service.digest(params),
                      sessionId='native', state='observed')
        return owner, dict(record)
    channel._configuration_rpc = Mock(side_effect=apply)
    channels.query_native_operation.side_effect = lambda *a: (owner, dict(record))
    verify = Mock()
    service = ProviderRestorationService(channels, owners, verify=verify)
    desired = dict(provider='resource-provider', model='new-model', protocol='openai-responses',
        endpoint='https://controlled.invalid/v1', credentialRef='ref://synthetic')
    return SimpleNamespace(service=service, channels=channels, owners=owners, channel=channel,
        target=target, snapshot=snapshot, owner=owner, desired=desired, record=record, verify=verify,
        ticket=ticket, restored=restored)


def prepare(rig, key='profile:application'):
    return rig.service.prepare(rig.target, rig.desired, operation_key=key, credential='synthetic-secret')


def test_prepare_has_no_native_effect_and_carries_no_secret(rig):
    plan = prepare(rig)
    assert plan.before is rig.snapshot
    assert plan.expected_config_digest == configuration_digest(rig.snapshot.config_options)
    rig.verify.assert_called_once_with('codex')
    rig.channel._configuration_rpc.assert_not_called()
    rig.owners.begin_restoration.assert_not_called()
    assert 'synthetic-secret' not in repr(plan) + repr(rig.service._plans)


def test_managed_destination_is_resolved_by_harness_account_owner_not_profile(rig):
    account = Mock(account_directory='/synthetic/owned-account')
    account.read.return_value = {'authenticated': True, 'method': 'chatgpt-managed'}
    rig.service.managed_account_factory = Mock(return_value=account)
    desired = dict(provider='openai', model='new-model', protocol='openai-responses',
                   endpoint=None, credentialRef=None, authentication='managed-account')
    plan = rig.service.prepare(rig.target, desired, operation_key='return-to-official')
    rig.channel._configuration_rpc.assert_not_called()
    assert '/synthetic/owned-account' not in repr(plan)
    result = rig.service.execute(plan, desired)
    assert result.state == 'observed'
    request = rig.channel._configuration_rpc.call_args.args[2]
    assert request['provider'] == dict(providerId='openai', authentication='managed-account',
                                     accountDirectory='/synthetic/owned-account')
    assert 'accountDirectory' not in desired
    rig.channel._configuration_rpc.assert_called_once()


def test_unavailable_managed_login_refuses_before_restoration_effect(rig):
    account = Mock(account_directory='/synthetic/owned-account')
    account.read.return_value = {'authenticated': False, 'method': None}
    rig.service.managed_account_factory = Mock(return_value=account)
    desired = dict(provider='openai', model='new-model', protocol='openai-responses',
                   endpoint=None, credentialRef=None, authentication='managed-account')
    with pytest.raises(ValueError, match='login required'):
        rig.service.prepare(rig.target, desired, operation_key='return-to-official')
    rig.channel._configuration_rpc.assert_not_called()
    rig.owners.begin_restoration.assert_not_called()


def test_managed_destination_refuses_without_an_owned_account_owner(rig):
    """B02: no factory, foreign brand and wrong-scope login each refuse first.

    The managed destination exists only when the Harness account owner resolves
    it. A Profile can neither name a native path nor substitute an API key for
    the subscription, and none of these refusals may reach a native effect.
    """
    desired = dict(provider='openai', model='new-model', protocol='openai-responses',
                   endpoint=None, credentialRef=None, authentication='managed-account')

    # No account factory at all: the brand cannot resolve an owned destination.
    rig.service.managed_account_factory = None
    with pytest.raises(ValueError, match='authentication destination unavailable'):
        rig.service.prepare(rig.target, desired, operation_key='no-factory')

    # A factory that raises (no managed account owned by this Harness).
    rig.service.managed_account_factory = Mock(side_effect=RuntimeError('absent'))
    with pytest.raises(RuntimeError):
        rig.service.prepare(rig.target, desired, operation_key='factory-absent')

    # Right owner, wrong scope: an API-key account is not a managed subscription.
    account = Mock(account_directory='/synthetic/owned-account')
    account.read.return_value = {'authenticated': True, 'method': 'api-key'}
    rig.service.managed_account_factory = Mock(return_value=account)
    with pytest.raises(ValueError, match='login required'):
        rig.service.prepare(rig.target, desired, operation_key='wrong-scope')

    rig.channel._configuration_rpc.assert_not_called()
    rig.owners.begin_restoration.assert_not_called()


def test_managed_destination_is_never_written_back_into_the_profile_intent(rig):
    """B01: the resolved account path stays Harness-private, never a Profile field."""
    account = Mock(account_directory='/synthetic/owned-account')
    account.read.return_value = {'authenticated': True, 'method': 'chatgpt-managed'}
    rig.service.managed_account_factory = Mock(return_value=account)
    desired = dict(provider='openai', model='new-model', protocol='openai-responses',
                   endpoint=None, credentialRef=None, authentication='managed-account')
    plan = rig.service.prepare(rig.target, desired, operation_key='private-destination')
    assert 'accountDirectory' not in desired
    assert '/synthetic/owned-account' not in repr(plan)
    assert '/synthetic/owned-account' not in repr(rig.service._plans)
    assert 'accountDirectory' not in json.dumps(rig.service.digest(desired))


def test_effect_once_retains_conversation_and_requires_independent_completion(rig):
    plan = prepare(rig)
    result = rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    assert result.state == 'observed' and result.restored is rig.restored and result.ticket is rig.ticket
    assert result.restored.snapshot.target.session_id == rig.target.session_id
    assert result.restored.snapshot.target.runtime_generation != rig.target.runtime_generation
    rig.owners.begin_restoration.assert_called_once_with(rig.target, operation_id=plan.operation_id)
    rig.owners.complete_restoration.assert_called_once_with(rig.ticket)
    for _ in range(2):
        assert rig.service.execute(plan, rig.desired, credential='synthetic-secret').state == 'observed'
    rig.channel._configuration_rpc.assert_called_once()
    assert 'synthetic-secret' not in repr(rig.service._attempts)


def test_timeout_is_unknown_and_replay_or_query_never_repeats_restore(rig):
    plan = prepare(rig)
    rig.channel._configuration_rpc.side_effect = TimeoutError('synthetic-secret')
    assert rig.service.execute(plan, rig.desired, credential='synthetic-secret').state == 'unknown'
    for _ in range(2):
        assert rig.service.query(plan).state == 'unknown'
        assert rig.service.execute(plan, rig.desired, credential='synthetic-secret').state == 'unknown'
    rig.channel._configuration_rpc.assert_called_once()
    rig.owners.complete_restoration.assert_not_called()
    assert 'synthetic-secret' not in repr(rig.service._attempts)


def test_timeout_can_be_proved_later_only_by_queries(rig):
    plan = prepare(rig)
    real = rig.channel._configuration_rpc.side_effect
    def late(*args):
        real(*args)
        raise TimeoutError()
    rig.channel._configuration_rpc.side_effect = late
    result = rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    assert result.state == 'observed'
    rig.channel._configuration_rpc.assert_called_once()
    rig.channels.query_native_operation.assert_called()


@pytest.mark.parametrize('defect', ['changed-credential', 'changed-choice', 'foreign-plan',
    'busy', 'generation', 'config', 'ended', 'owner', 'channel', 'harness'])
def test_changed_fences_refuse_before_native_effect(rig, defect):
    plan = prepare(rig)
    credential, desired = 'synthetic-secret', rig.desired
    if defect == 'changed-credential': credential = 'different-secret'
    elif defect == 'changed-choice': desired = dict(desired, model='different')
    elif defect == 'foreign-plan': plan = replace(plan)
    elif defect == 'busy': rig.snapshot.busy = True
    elif defect == 'generation': rig.snapshot.native_generation = 'other'
    elif defect == 'config': rig.snapshot.config_options = []
    elif defect == 'ended': rig.channel.ended = True
    elif defect == 'owner': rig.channels.native_session_observation.return_value = SimpleNamespace(**vars(rig.owner))
    elif defect == 'channel': rig.channels.get.return_value = SimpleNamespace(harness_id='codex', ended=False)
    elif defect == 'harness': rig.channel.harness_id = 'claude-code'
    with pytest.raises(ValueError):
        rig.service.execute(plan, desired, credential=credential)
    rig.channel._configuration_rpc.assert_not_called()


@pytest.mark.parametrize('defect', ['ack', 'wrong-digest', 'foreign-owner', 'unproven-restoration'])
def test_ack_or_unbound_evidence_cannot_confirm(rig, defect):
    plan = prepare(rig)
    real = rig.channel._configuration_rpc.side_effect
    def broken(*args):
        answer = real(*args)
        if defect == 'ack': rig.record.clear(); rig.record.update(sessionId='native')
        elif defect == 'wrong-digest': rig.record['inputDigest'] = '0' * 64
        elif defect == 'foreign-owner':
            rig.channels.query_native_operation.side_effect = lambda *a: (object(), dict(rig.record))
        else: rig.owners.complete_restoration.side_effect = ValueError('unproven')
        return answer
    rig.channel._configuration_rpc.side_effect = broken
    assert rig.service.execute(plan, rig.desired, credential='synthetic-secret').state == 'unknown'
    rig.channel._configuration_rpc.assert_called_once()


def test_unknown_attempt_blocks_a_different_operation_for_this_conversation(rig):
    plan = prepare(rig)
    rig.channel._configuration_rpc.side_effect = TimeoutError()
    rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    with pytest.raises(ValueError, match='pending'):
        prepare(rig, 'different-operation')
    rig.channel._configuration_rpc.assert_called_once()


def test_unsupported_route_and_managed_destination_refuse_without_effect(rig):
    rig.channel.harness_id = 'pi'
    with pytest.raises(ValueError): prepare(rig)
    rig.channel.harness_id = 'codex'
    rig.desired.update(provider='openai', authentication='managed-account', endpoint=None, credentialRef=None)
    with pytest.raises(ValueError):
        rig.service.prepare(rig.target, rig.desired, operation_key='unsupported')
    rig.channel._configuration_rpc.assert_not_called()


def test_publication_change_and_lease_absence_refuse_before_restore(rig):
    from contextlib import contextmanager
    plan = prepare(rig)
    rig.verify.return_value = 'new-publication'
    with pytest.raises(ValueError, match='publication changed'):
        rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    rig.channel._configuration_rpc.assert_not_called()
    @contextmanager
    def unavailable(*args):
        raise ValueError('publication lease absent')
        yield
    rig.service.lease = unavailable
    with pytest.raises(ValueError, match='lease absent'):
        rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    rig.channel._configuration_rpc.assert_not_called()


def test_restored_credential_proof_needs_retained_operation_and_current_owner(rig):
    plan = prepare(rig)
    result = rig.service.execute(plan, rig.desired, credential='synthetic-secret')
    snapshot = result.restored.snapshot
    assert rig.service.credential_binding(snapshot, rig.desired, credential='synthetic-secret')
    assert rig.service.credential_binding(snapshot, dict(rig.desired, model='another-model'), credential='synthetic-secret')
    for desired, credential in [(rig.desired, 'different-key'), (dict(rig.desired, endpoint='https://other.invalid'),
                                                              'synthetic-secret')]:
        assert not rig.service.credential_binding(snapshot, desired, credential=credential)
    rig.record['sessionId'] = 'foreign-session'
    assert not rig.service.credential_binding(snapshot, rig.desired, credential='synthetic-secret')
    rig.record.clear()
    assert not rig.service.credential_binding(snapshot, rig.desired, credential='synthetic-secret')


def test_actual_registry_and_owner_restore_keep_native_conversation_and_execution():
    from ordessa_harness.server_acp.registry import AcpChannelRegistry, _Channel, _ObservedTransport
    from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner, ProfileOwnerUnavailable

    channel = _Channel(connection_id='channel', harness_id='codex', workspace_id='project',
        profile_id='fixture', cwd='/controlled-project')
    channel.session_id, channel.execution_id = 'ledger', 'execution'
    generation, options, records, sent = 'before', [dict(id='model', currentValue='old-model')], {}, []

    class Transport:
        def send_line(self, line):
            nonlocal generation, options
            frame = json.loads(line)
            sent.append(frame)
            method, params = frame['method'], frame['params']
            def observation():
                return dict(sessionId='native', generation=generation, busy=False,
                            configOptions=json.loads(json.dumps(options)))
            if method == 'session/new': result = dict(sessionId='native')
            elif method == '_ordessa/session/configuration': result = observation()
            elif method == '_ordessa/session/configuration/restore':
                before = observation()
                generation, options = 'after', [dict(id='model', currentValue=params['model'])]
                result = dict(operationId=params['operationId'], sessionId='native', kind='provider-resume',
                    state='observed', inputDigest=ProviderRestorationService.digest(params), target=params['target'],
                    before=before, after=observation(), evidenceRef='native-restoration:controlled')
                records[params['operationId']] = result
            else:
                assert method == '_ordessa/session/configuration/operation'
                result = records[params['operationId']]
            channel.deliver(json.dumps(dict(jsonrpc='2.0', id=frame['id'], result=result)))

    channel.transport = _ObservedTransport(channel, Transport())
    channels = AcpChannelRegistry(session_records=None, profile_records=None,
        launch=lambda **kw: pytest.fail('no replacement launch in controlled transport'))
    channels._by_id['channel'] = channel
    channels._by_pair[channel.pair] = channel
    channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id='first-create', method='session/new', params={})))
    owners = ProfileSessionOwner(channels, server_id='server-incarnation')
    before = owners.bind(canonical_session_id='canonical', harness_id='codex', workspace_id='project',
                        connection_id='channel', native_session_id='native')
    service = ProviderRestorationService(channels, owners, verify=lambda brand: None)
    desired = dict(provider='resource-label', model='new-model', protocol='openai-responses',
        endpoint='http://127.0.0.1:9/v1', credentialRef=None)
    plan = service.prepare(before.target, desired, operation_key='profile:restore')
    result = service.execute(plan, desired)
    assert result.state == 'observed'
    assert result.restored.snapshot.owner is before.owner
    assert result.restored.snapshot.target.session_id == 'canonical'
    assert result.restored.snapshot.target.runtime_generation > before.target.runtime_generation
    assert result.restored.snapshot.owner.native_session_id == 'native'
    assert result.restored.snapshot.owner.execution_id == 'execution'
    assert result.restored.snapshot.config_options == [dict(id='model', currentValue='new-model')]
    with pytest.raises(ProfileOwnerUnavailable): owners.readback(before.target)
    assert service.query(plan).state == 'observed'
    assert service.execute(plan, desired).state == 'observed'
    assert sum(frame['method'] == '_ordessa/session/configuration/restore' for frame in sent) == 1
    assert sum(frame['method'] == 'session/new' for frame in sent) == 1
