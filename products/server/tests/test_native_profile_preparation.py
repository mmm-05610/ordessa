"""Controlled backend catalogue/channel effects, never an Agent/model process."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ordessa_profile.errors import ProfileError
from ordessa_server_product.profile_preparation import NativeProfilePreparation, _digest


def setup(brand='codex', secret=None):
    channel = SimpleNamespace(_lock=Lock(), _ended=False, session_scope_id='attempt',
        _native_sessions={}, _pending_new=set(), harness_id=brand)
    profile = dict(realm='local', harness_id=brand, archived_at=None, version=2, current_revision=2)
    choice = dict(harnessId=brand, providerConfigId='catalog', modelId='m')
    payload = dict(provider='business-label', model='m', protocol='openai-responses' if brand == 'codex' else 'anthropic-messages',
                   endpoint='https://controlled.invalid', credentialRef='ref://key' if secret else None)
    resolved = SimpleNamespace(payload=payload, revisions={'version': 1})
    core = SimpleNamespace(profiles=Mock())
    core.profiles.get.return_value = profile
    core.profiles.facet_values.return_value = [dict(facet_id='assets.model-provider', item_id='choice', value=choice, quarantined=False)]
    channels = Mock()
    channels.get.return_value = channel
    record = {}
    def prepare(cid, params):
        record.update(operationId=params['operationId'], inputDigest=_digest(params), state='prepared', after=None)
        return {**record, 'unsafe': secret}
    channels.prepare_native_creation.side_effect = prepare
    channels.query_native_creation.side_effect = lambda *args: dict(record)
    catalog = Mock()
    catalog.application_credential.return_value = secret
    resolver = Mock()
    resolver.resolve.return_value = resolved
    verify = Mock()
    service = NativeProfilePreparation(core, channels, roots={brand: '/trusted'}, verify=verify,
        resolver_factory=lambda: resolver, catalog_factory=lambda: catalog)
    args = dict(connection_id='c', profile_id='p', operation_id='create:attempt')
    return SimpleNamespace(service=service, args=args, channel=channel, channels=channels, core=core,
        profile=profile, payload=payload, resolved=resolved, catalog=catalog, record=record, verify=verify)


def test_launch_selection_is_read_only_and_creation_rechecks_its_snapshot():
    f = setup(secret='synthetic-secret')
    selection = f.service.resolve_launch_selection(profile_id='p', harness_id='codex')
    assert selection['transportOptions'] == {}
    assert 'synthetic-secret' not in repr(selection)
    f.catalog.application_credential.assert_not_called()
    f.channels.prepare_native_creation.assert_not_called()
    f.channel.configuration_profile_id = 'p'
    f.channel.configuration_profile_snapshot = selection['snapshot']
    f.profile['version'] += 1
    with pytest.raises(ProfileError):
        f.service.prepare(**f.args)
    f.channels.prepare_native_creation.assert_not_called()


def test_managed_launch_requires_account_owner_and_never_imports_api_credentials():
    f = setup()
    f.payload.update(provider='openai', endpoint=None, authentication='managed-account')
    account = Mock()
    account.account_directory = '/private/ordessa-account'
    account.read.return_value = {'authenticated': True, 'method': 'chatgpt-managed'}
    f.service.managed_account_factory = Mock(return_value=account)
    selected = f.service.resolve_launch_selection(profile_id='p', harness_id='codex')
    assert selected['transportOptions'] == {'codex_account_directory': '/private/ordessa-account'}
    account.read.assert_called_once_with(refresh=True)
    f.catalog.application_credential.assert_not_called()
    f.channels.prepare_native_creation.assert_not_called()
    f.channel.configuration_profile_id = 'p'
    f.channel.configuration_profile_snapshot = selected['snapshot']
    f.service.prepare(**f.args)
    assert f.channels.prepare_native_creation.call_args.args[1]['provider'] == {
        'providerId': 'openai', 'authentication': 'managed-account'}
    account.read.return_value = {'authenticated': False, 'method': 'chatgpt-managed'}
    with pytest.raises(ProfileError, match='login required'):
        f.service.resolve_launch_selection(profile_id='p', harness_id='codex')


@pytest.mark.parametrize('brand', ['codex', 'claude-code'])
def test_prepare_reserved_once_and_query_only_with_sanitized_projection(brand):
    fixture = setup(brand, 'synthetic-private-key')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: fixture.service.prepare(**fixture.args), range(2)))
    assert results[0] == results[1]
    assert results[0]['state'] == 'prepared'
    assert set(results[0]) == {'state', 'operation_id', 'connection_id', 'profile_id', 'harness_id', 'profile_revision'}
    assert 'synthetic-private-key' not in repr(results) + repr(fixture.service._operations)
    fixture.channels.prepare_native_creation.assert_called_once()
    fixture.channels.query_native_creation.assert_called_once_with('c', 'create:attempt')
    params = fixture.channels.prepare_native_creation.call_args.args[1]
    assert params['provider']['headers'] == {
        'authorization': 'Bearer synthetic-private-key',
        **({'x-api-key': 'synthetic-private-key'} if brand == 'claude-code' else {})}
    assert params['provider']['providerId'] == ('custom-gateway' if brand == 'codex' else 'main')


def test_unknown_never_replays_effect_and_retained_query_can_resolve():
    f = setup()
    f.channels.prepare_native_creation.side_effect = TimeoutError('unsafe upstream secret')
    assert f.service.prepare(**f.args)['state'] == 'unknown'
    f.channels.query_native_creation.side_effect = TimeoutError('unsafe upstream secret')
    assert f.service.prepare(**f.args)['state'] == 'unknown'
    f.channels.query_native_creation.side_effect = lambda *args: dict(operationId=f.args['operation_id'], state='prepared',
        inputDigest=f.service._operations[f.args['operation_id']]['input_digest'])
    assert f.service.prepare(**f.args)['state'] == 'prepared'
    f.channels.prepare_native_creation.assert_called_once()


@pytest.mark.parametrize('change', ['realm', 'harness', 'archived', 'shared', 'scope', 'owned', 'creating', 'ended', 'roots', 'quarantined', 'missing-choice', 'missing-secret'])
def test_initial_admission_refuses_before_effect(change):
    f = setup(secret='synthetic')
    if change == 'realm': f.profile['realm'] = 'remote'
    if change == 'harness': f.profile['harness_id'] = 'claude-code'
    if change == 'archived': f.profile['archived_at'] = 'yes'
    if change == 'shared': f.channel.session_scope_id = None
    if change == 'scope': f.channel.session_scope_id = 'different-attempt'
    if change == 'owned': f.channel._native_sessions['s'] = object()
    if change == 'creating': f.channel._pending_new.add('request')
    if change == 'ended': f.channel._ended = True
    if change == 'roots': f.service.roots = {}
    if change == 'quarantined': f.core.profiles.facet_values.return_value[0]['quarantined'] = True
    if change == 'missing-choice': f.core.profiles.facet_values.return_value = []
    if change == 'missing-secret': f.catalog.application_credential.side_effect = ValueError('secret not available')
    with pytest.raises(ProfileError): f.service.prepare(**f.args)
    f.channels.prepare_native_creation.assert_not_called()
    assert f.service._operations == {}


def test_unavailable_secret_store_preserves_exact_public_code():
    from ordessa_server.errors import ServerError
    f = setup(secret='synthetic')
    f.catalog.application_credential.side_effect = ServerError('CREDENTIAL_UNRESOLVED', 'Application credential unavailable', status=422)
    with pytest.raises(ProfileError) as error: f.service.prepare(**f.args)
    assert error.value.code == 'CREDENTIAL_UNRESOLVED'
    f.channels.prepare_native_creation.assert_not_called()


@pytest.mark.parametrize('change', ['profile', 'catalog', 'secret', 'payload', 'owner', 'operation'])
def test_retries_refuse_changed_reservation_without_effect_or_query(change):
    f = setup(secret='synthetic')
    f.service.prepare(**f.args)
    if change == 'profile': f.profile['version'] += 1
    if change == 'catalog': f.resolved.revisions['version'] += 1
    if change == 'secret': f.catalog.application_credential.return_value = 'rotated'
    if change == 'payload': f.payload['endpoint'] = 'https://changed.invalid'
    if change == 'owner':
        f.channels.get.return_value = SimpleNamespace(**{**vars(f.channel), '_lock': Lock()})
    if change == 'operation': f.args['operation_id'] = 'create:other'
    with pytest.raises(ProfileError): f.service.prepare(**f.args)
    f.channels.prepare_native_creation.assert_called_once()
    f.channels.query_native_creation.assert_not_called()


def test_pi_reports_not_required_without_preparation_rpc():
    f = setup('pi')
    assert f.service.prepare(**f.args)['state'] == 'not-required'
    assert f.service.prepare(**f.args)['state'] == 'not-required'
    f.channels.prepare_native_creation.assert_not_called()
    f.channels.query_native_creation.assert_not_called()
    assert f.core.profiles.mock_calls  # Profile/model validation still happens


def test_pi_new_api_key_provider_uses_reserved_private_runtime_dialect():
    f = setup('pi', '!opaque-key-not-a-command')
    f.payload['protocol'] = 'openai-chat'
    f.resolved.revisions.update(providerConfigId='catalog', configVersion=1, modelsObjectDigest='models-digest')
    row = dict(id='catalog', version=1, models_object_digest='models-digest')
    f.catalog.records.get.return_value = row
    f.catalog.project.return_value = dict(models=[dict(modelId='m', availability='available'),
        dict(modelId='next', availability='available', protocols=['openai-chat']),
        dict(modelId='unsupported', availability='available', protocols=['anthropic-messages']),
        dict(modelId='unknown', availability='unknown')])
    result = f.service.prepare(**f.args)
    assert result['state'] == 'prepared'
    params = f.channels.prepare_native_creation.call_args.args[1]
    assert params['models'] == ['m', 'next']
    assert params['provider'] == dict(providerId='business-label', apiType='openai-completions',
        baseUrl='https://controlled.invalid', apiKey='!opaque-key-not-a-command')
    assert '!opaque-key-not-a-command' not in repr(f.service._operations) + repr(result)
    assert f.service.prepare(**f.args)['state'] == 'prepared'
    f.channels.prepare_native_creation.assert_called_once()


def test_pi_changed_catalogue_is_refused_before_native_effect():
    f = setup('pi', 'synthetic')
    f.payload['protocol'] = 'openai-chat'
    f.resolved.revisions.update(providerConfigId='catalog', configVersion=1, modelsObjectDigest='expected')
    f.catalog.records.get.return_value = dict(id='catalog', version=2, models_object_digest='changed')
    f.catalog.project.return_value = dict(models=[dict(modelId='m', availability='available')])
    with pytest.raises(ProfileError): f.service.prepare(**f.args)
    f.channels.prepare_native_creation.assert_not_called()


def test_credential_binding_requires_observed_native_owner_generation_and_current_secret():
    f = setup(secret='synthetic')
    f.service.prepare(**f.args)
    owner = SimpleNamespace(connection_id='c', native_session_id='s')
    snapshot = SimpleNamespace(owner=owner, native_generation='g')
    f.channels.native_session_observation.return_value = owner
    assert not f.service.credential_binding(snapshot, f.payload), 'startup ACK cannot authorize C4'
    f.record.update(state='observed', after=dict(sessionId='s', generation='g'))
    assert f.service.credential_binding(snapshot, f.payload)
    assert not f.service.credential_binding(snapshot, {**f.payload, 'credentialRef': None})
    f.profile['version'] += 1
    f.profile['current_revision'] += 1
    f.resolved.revisions['version'] += 1
    assert f.service.credential_binding(snapshot, {**f.payload, 'model': 'second-model'})
    assert not f.service.credential_binding(snapshot, {**f.payload, 'endpoint': 'https://changed.invalid'})
    f.channels.native_session_observation.return_value = SimpleNamespace(**vars(owner))
    assert not f.service.credential_binding(snapshot, f.payload)
    f.channels.native_session_observation.return_value = owner
    f.record['after']['generation'] = 'wrong'
    assert not f.service.credential_binding(snapshot, f.payload)
    f.record['after']['generation'] = 'g'
    f.catalog.application_credential.return_value = 'rotated'
    assert not f.service.credential_binding(snapshot, f.payload)


def test_controlled_product_wire_preparation_registration_and_authenticated_c4(tmp_path):
    """Real wire/Profile/catalogue/owner/C4; controlled native transport only.

    This does not verify installation or process launch: the pinned Installation
    and empty registry channel are explicitly provided by the test fixture.
    Credentials use real reference records and a private in-memory test store.
    """
    import copy
    import hashlib
    import json
    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.credentials import CredentialRecords
    from ordessa_server.idempotency import IdempotentRecords
    from ordessa_profile.core import StaticHarnessCatalog
    from ordessa_profile.server_plugin import ProfileServerPlugin
    from ordessa_model_provider.catalog import ModelCatalogService
    from ordessa_model_provider.records import ProviderModelRecords
    from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver
    from ordessa_model_provider.testing import FakeHarnesses, harness_descriptor, wire_body
    from ordessa_model_provider_profile.profile_glue import ModelProviderFacetProvider
    from ordessa_harness_api import Installation
    from ordessa_harness.configuration.model.bridge import choice_payload_schema
    from ordessa_harness.configuration.model.live_service import create_model_service
    from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin
    from ordessa_harness.server_acp.registry import AcpChannelRegistry, _Channel, _ObservedTransport
    from ordessa_harness.server_acp.profile_owner import ProfileSessionOwner
    from ordessa_harness.server_acp.native_action_executor import configuration_digest
    from ordessa_server_product.profile_sessions import ProfileNativeSessions
    from ordessa_server_product.native_configuration import NativeConfigurationAuthority
    from ordessa_server_product.profile_configuration import NativeProfileConfigPort

    product = build_runtime(tmp_path / 'product')
    product.start()  # T006-02 round gate: wire answers only a started round
    credentials = CredentialRecords(product.database)
    credentials.register('controlled-key', 'api_key', 'memory://controlled-key')
    class PrivateStore:
        value = b'synthetic-never-project'
        def read(self, locator):
            assert locator == 'memory://controlled-key'
            return self.value
    harnesses = FakeHarnesses(descriptors={'codex': harness_descriptor(credential_kind='api_key')},
        protocols={'codex': {'openai-responses': ''}})
    catalog = ModelCatalogService(ProviderModelRecords(product.database, IdempotentRecords(product.database)),
        product.objects, harnesses=harnesses, credentials=credentials, secret_store=PrivateStore())
    provider = catalog.create('controlled-provider', wire_body(harness='codex', credentialId='controlled-key',
        configuration=[], protocols=['openai-responses'], endpoints={'openai-responses': 'http://127.0.0.1:9/v1'},
        models=[dict(modelId=m, availability='available') for m in ('m1', 'm2')]))
    registry = AcpChannelRegistry(session_records=None, profile_records=None,
        launch=lambda **kwargs: pytest.fail('No process launch in controlled integration'))
    owner_service = ProfileSessionOwner(registry, server_id='controlled-server')
    transports = {}
    def add_channel(cid, scope, unknown=False):
        channel = _Channel(connection_id=cid, harness_id='codex', workspace_id='project',
            profile_id='controlled-profile', cwd=str(tmp_path), session_scope_id=scope)
        channel.session_id, channel.execution_id = 'controlled-ledger-' + cid, 'controlled-execution-' + cid
        class NativeTransport:
            def __init__(self):
                self.sent, self.record = [], None
                self.options = [dict(id='model', type='select', currentValue='m1', options=[
                    dict(value=m, _meta={'ordessaModel': dict(provider='custom-gateway', model=m,
                        api='responses', baseUrl='http://127.0.0.1:9/v1')}) for m in ('m1', 'm2')])]
            def snapshot(self):
                return dict(sessionId='native-' + cid, generation='generation-' + cid, busy=False,
                    configOptions=copy.deepcopy(self.options))
            def send_line(self, line):
                frame = json.loads(line)
                self.sent.append(frame)
                method, params = frame['method'], frame['params']
                if method == '_ordessa/channel/configuration/prepare':
                    assert params['provider']['headers'] == {'authorization': 'Bearer synthetic-never-project'}
                    self.record = dict(operationId=params['operationId'], inputDigest=_digest(params),
                        state='unknown' if unknown else 'prepared', after=None)
                    result = self.record
                elif method == '_ordessa/channel/configuration/operation':
                    assert params['operationId'] == self.record['operationId']
                    result = self.record
                elif method == 'session/new':
                    assert self.record['state'] == 'prepared'
                    self.record.update(state='observed', after=self.snapshot())
                    result = dict(sessionId='native-' + cid)
                elif method == '_ordessa/session/configuration':
                    result = self.snapshot()
                elif method == '_ordessa/session/configuration/apply':
                    before = configuration_digest(self.options)
                    assert params['expectedConfigDigest'] == before
                    self.options[0]['currentValue'] = params['value']
                    manifest = json.dumps(params['actionManifest'], sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                    result = dict(sessionId='native-' + cid, operationId=params['operationId'], state='observed', generation='generation-' + cid,
                        target=params['actionManifest']['target'], manifestDigest=hashlib.sha256(manifest.encode()).hexdigest(),
                        beforeConfigDigest=before, configId='model', requestedValue=params['value'], observedValue=params['value'],
                        afterConfigDigest=configuration_digest(self.options), after=self.snapshot(), evidenceRef='codex-native-operation:controlled')
                else:
                    pytest.fail('Unexpected effect: ' + method)
                channel.deliver(json.dumps(dict(jsonrpc='2.0', id=frame['id'], result=result)))
        transport = NativeTransport()
        channel.transport = _ObservedTransport(channel, transport)
        registry._by_id[cid], registry._by_pair[channel.pair] = channel, channel
        transports[cid] = transport
        return channel
    channel = add_channel('c', 'attempt')
    add_channel('u', 'unknown', unknown=True)
    installation = Installation('codex', (1, 1, 14), (1, 0, 0), 'controlled:pinned-installation')
    resolver = lambda: ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema())
    sessions_holder = {}
    def native_factory(core):
        configuration = NativeConfigurationAuthority(channels=registry, owners=owner_service, services=Mock())
        sessions = ProfileNativeSessions(core=core, configuration=configuration, realm='local')
        sessions.preparation = NativeProfilePreparation(core, registry, roots={'codex': '/controlled-installation'},
            verify=lambda brand: installation if brand == installation.harness_id else pytest.fail('Wrong installation brand'),
            resolver_factory=resolver, catalog_factory=lambda: catalog)
        def service_factory(target):
            return create_model_service(registry=registry, owners=owner_service, target=target,
                carrier=product.plugin_host, installation=installation, journal_path=tmp_path / 'c4.sqlite',
                credential_binding=sessions.preparation.credential_binding)
        core.config_port = NativeProfileConfigPort(sessions, service_factory=service_factory,
            resolver_factory=resolver, supported_harnesses=('codex',))
        sessions_holder['sessions'] = sessions
        return sessions
    try:
        product.plugin_host.deactivate('ordessa.profile')
        product.plugin_host.activate(ModelProviderAdaptersPlugin())
        plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({'codex': frozenset()}),
            providers=(('ordessa.model-provider-profile', ModelProviderFacetProvider()),), native_registration_factory=native_factory)
        product.plugin_host.activate(plugin)
        def call(name, **params):
            return product.wire.dispatch('profiles.v2.' + name, params)['data']
        profile = call('createProfile', operationKey='create-profile', realm='local', harnessId='codex', displayName='Controlled')
        pid = profile['profileId']
        def choice(model):
            return dict(harnessId='codex', providerConfigId=provider['id'], modelId=model)
        def save(model, version):
            return call('saveProfile', operationKey='save-' + model, profileId=pid, expectedVersion=version,
                patches=[dict(facetId='assets.model-provider', itemId='choice', op='set', value=choice(model))])
        save('m1', 1)
        prepared = call('prepareNativeCreation', connectionId='c', profileId=pid, operationId='create:attempt')
        assert prepared['state'] == 'prepared' and registry.native_session_observation('c', 'native-c') is None
        assert not any(frame['method'] in ('session/new', 'session/prompt') for frame in transports['c'].sent)
        unknown_result = call('prepareNativeCreation', connectionId='u', profileId=pid, operationId='create:unknown')
        assert unknown_result['state'] == 'unknown'
        assert call('prepareNativeCreation', connectionId='u', profileId=pid, operationId='create:unknown')['state'] == 'unknown'
        assert [frame['method'] for frame in transports['u'].sent] == [
            '_ordessa/channel/configuration/prepare', '_ordessa/channel/configuration/operation']
        channel.transport.send_line(json.dumps(dict(jsonrpc='2.0', id='new', method='session/new', params={})))
        observed_owner = registry.native_session_observation('c', 'native-c')
        assert observed_owner is not None
        registered = call('registerNativeSession', connectionId='c', nativeSessionId='native-c', profileId=pid)
        ref = registered['sessionRef']
        from ordessa_profile.contracts import SessionRef
        binding = sessions_holder['sessions'].require_registered(SessionRef(ref['realm'], ref['harnessId'], ref['nativeSessionKey'], ref['sessionUid']))
        assert binding.snapshot.owner is observed_owner
        initial = call('beginTurnApplication', operationKey='first-c4', sessionRef=ref)
        assert 'receipt' in initial
        save('m2', 2)
        second = call('beginTurnApplication', operationKey='second-c4', sessionRef=ref)
        assert 'receipt' in second and transports['c'].options[0]['currentValue'] == 'm2'
        assert registry.native_session_observation('c', 'native-c') is observed_owner
        assert len([frame for frame in transports['c'].sent if frame['method'] == 'session/new']) == 1
        assert len([frame for frame in transports['c'].sent if frame['method'] == '_ordessa/session/configuration/apply']) == 2
        from server_plugin_api import WireError
        catalog.secret_store.value = b'synthetic-rotated'
        with pytest.raises(WireError) as refusal:
            call('beginTurnApplication', operationKey='rotated-c4', sessionRef=ref)
        assert refusal.value.details['internalCode'] == 'SWITCH_BLOCKED'
        assert len([frame for frame in transports['c'].sent if frame['method'] == '_ordessa/session/configuration/apply']) == 2
        assert not any(frame['method'] == 'session/prompt' for t in transports.values() for frame in t.sent)
        assert 'synthetic-never-project' not in repr(prepared) + repr(registered) + repr(initial) + repr(second)
    finally:
        product.stop()
