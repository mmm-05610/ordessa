"""Real wire/SQLite/credential records; key-store effects are controlled."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import sqlite3

import pytest
from server_plugin_api import WireError
from ordessa_server.credentials import CredentialRecords
from ordessa_server.plugin_host.host import ServerPluginHost
from ordessa_server.wire.handlers import WireService
from ordessa_model_provider.plugin import ModelProviderPlugin
from ordessa_model_provider.credential_import import ApiKeyImportService
from ordessa_model_provider.testing import FakeHarnesses, harness_descriptor, wire_body


class ByteStore:
    def __init__(self):
        self.imports, self.deleted, self.reads = [], [], 0
        self.values = {}
    def import_bytes(self, value, kind):
        self.imports.append((value, kind))
        cid = 'credential_' + uuid4().hex
        locator = 'controlled://' + cid
        self.values[locator] = value
        return cid, locator
    def delete(self, locator):
        self.deleted.append(locator)
        self.values.pop(locator, None)
    def read(self, locator):
        self.reads += 1
        return self.values[locator]


@pytest.fixture
def rig(stack):
    credentials = CredentialRecords(stack['database'])
    harnesses = FakeHarnesses(descriptors={'codex': harness_descriptor(credential_kind='api-key'),
        'claude-code': harness_descriptor(credential_kind='api-key'), 'unsupported': harness_descriptor()},
        protocols={'codex': {'openai-responses': ''}})
    store = ByteStore()
    plugin = ModelProviderPlugin(harnesses=harnesses, secret_store=store)
    host = ServerPluginHost(data_root=stack['root'], host_ports={**stack, 'credentials': credentials})
    host.activate_all([plugin])
    wire = WireService(server_id_provider=lambda: 'controlled-server', cursor_secret=b'x' * 32, method_registry=host.methods)
    return SimpleNamespace(store=store, plugin=plugin, host=host, wire=wire, credentials=credentials,
        harnesses=harnesses, stack=stack, args=dict(requestId='request-import-01', harnessId='codex', apiKey='synthetic-utf8-key-秘密'))


def import_key(rig, **changes):
    return rig.wire.dispatch('modelProvider.importApiKey', {**rig.args, **changes})


def query(rig, **changes):
    params = {k: v for k, v in rig.args.items() if k != 'apiKey'}
    return rig.wire.dispatch('modelProvider.queryApiKeyImport', {**params, **changes})


def test_wire_import_query_restart_and_sqlite_never_persist_key(rig):
    r = rig
    result = import_key(r)
    assert result['state'] == 'imported' and result['kind'] == 'api-key'
    assert set(result) == {'operationId', 'state', 'credentialId', 'kind'}
    assert r.credentials.get(result['credentialId'], kind='api-key')['secret_locator'] in r.store.values
    assert r.store.imports == [(r.args['apiKey'].encode(), 'api-key')]
    assert query(r) == result and r.store.reads == 0
    with pytest.raises(WireError) as error: import_key(r, apiKey='changed-input')
    assert error.value.family == 'CONFLICT_REQUEST'
    assert error.value.details['internalCode'] == 'API_KEY_IMPORT_ALREADY_STARTED'
    assert len(r.store.imports) == 1
    reopened = ApiKeyImportService(data_root=r.stack['root'], harnesses=r.harnesses, credentials=r.credentials, secret_store=r.store)
    assert reopened.query(request_id=r.args['requestId'], harness_id='codex') == result
    with pytest.raises(WireError): reopened.import_key(request_id=r.args['requestId'], harness_id='codex', api_key='other')
    assert len(r.store.imports) == 1 and r.store.reads == 0
    assert query(r, requestId='request-missing')['state'] == 'not-found'
    raw = reopened.path.read_bytes()
    assert r.args['apiKey'].encode() not in raw and b'controlled://' not in raw
    with sqlite3.connect(reopened.path) as conn:
        columns = [row[1] for row in conn.execute('PRAGMA table_info(imports)')]
        assert columns == ['request_id', 'harness_id', 'state', 'credential_id', 'kind', 'cleanup_state']


def test_same_request_concurrency_has_one_effect(rig):
    r = rig
    def invoke(_):
        try: return import_key(r)
        except WireError as error: return error
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(invoke, range(2)))
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len(r.store.imports) == 1 and query(r)['state'] == 'imported'


def test_reservation_is_committed_before_entering_store_effect(rig):
    original = rig.store.import_bytes
    def observe_before_effect(value, kind):
        with sqlite3.connect(rig.plugin.credential_imports.path) as conn:
            row = conn.execute('SELECT request_id,harness_id,state,credential_id,kind FROM imports').fetchone()
        assert row == (rig.args['requestId'], 'codex', 'unknown', None, None)
        return original(value, kind)
    rig.store.import_bytes = observe_before_effect
    assert import_key(rig)['state'] == 'imported'


def test_completion_storage_failure_does_not_claim_imported_or_replay(rig, monkeypatch):
    monkeypatch.setattr(rig.plugin.credential_imports, '_complete', lambda *args, **kwargs: False)
    result = import_key(rig)
    assert result == dict(operationId='key-import:request-import-01', state='unknown')
    assert query(rig) == result and len(rig.credentials.list()) == 1
    with pytest.raises(WireError): import_key(rig)
    assert len(rig.store.imports) == 1


@pytest.mark.parametrize('key', ['', ' ', 'key\n', 'key\x00', 'key\x7f', 'key\u0085', 'key\u200b', '秘密' * 2667, '\ud800', None, 123])
def test_key_bounds_and_controls_refuse_before_reservation_or_effect(rig, key):
    with pytest.raises(WireError) as error: import_key(rig, apiKey=key)
    assert error.value.family == 'INVALID_REQUEST'
    assert not rig.store.imports and query(rig)['state'] == 'not-found'


@pytest.mark.parametrize('params', [{'extra': 'field'}, {'apiKey': None}, {'harnessId': ''}, {'requestId': 'short'}])
def test_wire_strict_shape_or_values_are_safe(rig, params):
    with pytest.raises(WireError): import_key(rig, **params)
    assert not rig.store.imports
    with pytest.raises(WireError): query(rig, apiKey='must-not-be-accepted')


@pytest.mark.parametrize('brand', ['unknown', 'unsupported'])
def test_harness_must_declare_exact_api_key_kind(rig, brand):
    with pytest.raises(WireError) as error: import_key(rig, harnessId=brand)
    assert error.value.family == 'CAPABILITY_UNSUPPORTED'
    assert not rig.store.imports


def test_original_harness_is_fenced_for_import_and_query(rig):
    import_key(rig)
    for call in (lambda: import_key(rig, harnessId='claude-code'), lambda: query(rig, harnessId='claude-code')):
        with pytest.raises(WireError) as error: call()
        assert error.value.details['internalCode'] == 'API_KEY_IMPORT_HARNESS_CONFLICT'
    assert len(rig.store.imports) == 1


def test_missing_capability_is_retained_refusal_and_never_reimported(rig):
    rig.plugin.credential_imports.secret_store = None
    assert import_key(rig) == dict(operationId='key-import:request-import-01', state='refused')
    assert query(rig)['state'] == 'refused'
    with pytest.raises(WireError): import_key(rig)
    assert not rig.store.imports


def test_decidable_availability_refusal_is_before_effect(rig):
    def unavailable(): raise RuntimeError('synthetic-provider-secret-error')
    rig.store.check_available = unavailable
    result = import_key(rig)
    assert result['state'] == 'refused' and 'synthetic' not in repr(result)
    assert query(rig) == result and not rig.store.imports


def test_timeout_retains_unknown_and_query_never_reads_or_retries(rig):
    def timeout(value, kind):
        rig.store.imports.append((value, kind))
        raise TimeoutError('synthetic-provider-secret-error')
    rig.store.import_bytes = timeout
    result = import_key(rig)
    assert result == dict(operationId='key-import:request-import-01', state='unknown')
    assert query(rig) == result and rig.store.reads == 0
    with pytest.raises(WireError): import_key(rig)
    assert len(rig.store.imports) == 1
    reopened = ApiKeyImportService(data_root=rig.stack['root'], harnesses=rig.harnesses, credentials=rig.credentials, secret_store=rig.store)
    assert reopened.query(request_id=rig.args['requestId'], harness_id='codex') == result


@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_registration_failure_cleans_only_exact_returned_locator_and_retains_unknown(rig, monkeypatch, cleanup_fails):
    def fail_register(*args): raise RuntimeError('synthetic-registration-secret-error')
    monkeypatch.setattr(rig.credentials, 'register', fail_register)
    if cleanup_fails:
        def fail_delete(locator):
            rig.store.deleted.append(locator)
            raise RuntimeError('synthetic-cleanup-secret-error')
        rig.store.delete = fail_delete
    result = import_key(rig)
    assert result['state'] == 'unknown' and 'credentialId' not in result and 'synthetic' not in repr(result)
    assert len(rig.store.imports) == len(rig.store.deleted) == 1
    assert rig.store.deleted[0].startswith('controlled://credential_')
    with sqlite3.connect(rig.plugin.credential_imports.path) as conn:
        row = conn.execute('SELECT state,cleanup_state FROM imports').fetchone()
    assert row == ('unknown', 'unknown' if cleanup_fails else 'removed')
    assert query(rig) == result and rig.store.reads == 0
    with pytest.raises(WireError): import_key(rig)
    assert len(rig.store.imports) == 1


@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_malformed_credential_id_cleans_exact_created_locator_without_registering(rig, cleanup_fails):
    original = rig.store.import_bytes
    returned = []
    def malformed(value, kind):
        _, locator = original(value, kind)
        returned.append(locator)
        return 'not-a-credential-id', locator
    rig.store.import_bytes = malformed
    if cleanup_fails:
        def failed_delete(locator):
            rig.store.deleted.append(locator)
            raise RuntimeError('synthetic-provider-error')
        rig.store.delete = failed_delete
    result = import_key(rig)
    assert result == dict(operationId='key-import:request-import-01', state='unknown')
    assert rig.store.deleted == returned and rig.credentials.list() == []
    with sqlite3.connect(rig.plugin.credential_imports.path) as conn:
        row = conn.execute('SELECT state,cleanup_state FROM imports').fetchone()
    assert row == ('unknown', 'unknown' if cleanup_fails else 'removed')
    assert query(rig) == result and rig.store.reads == 0
    with pytest.raises(WireError): import_key(rig)
    assert len(rig.store.imports) == 1


def test_malformed_store_shape_has_no_inferred_locator_cleanup(rig):
    original = rig.store.import_bytes
    def malformed(value, kind):
        original(value, kind)
        return {'locator': 'unproven-locator'}
    rig.store.import_bytes = malformed
    assert import_key(rig)['state'] == 'unknown'
    assert rig.store.deleted == [] and rig.credentials.list() == []


def test_wire_saved_protocol_endpoint_credential_choice_resolves_and_omission_preserves(rig):
    from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver
    from ordessa_harness.configuration.model.bridge import choice_payload_schema
    imported = import_key(rig)
    body = dict(requestId='request-save-01', **wire_body(harness='codex', credentialId=imported['credentialId'], configuration=[],
        protocols=['openai-responses'], endpoints={'openai-responses': 'http://127.0.0.1:9/v1'}))
    saved = rig.wire.dispatch('providerModels.create', body)['providerModel']
    resolver = ProfileModelChoiceResolver(rig.plugin.catalog, payload_schema=choice_payload_schema())
    choice = dict(harnessId='codex', providerConfigId=saved['id'], modelId='m1')
    resolved = resolver.resolve(choice, harness_id='codex')
    assert resolved.payload == dict(provider='acme', model='m1', protocol='openai-responses', endpoint='http://127.0.0.1:9/v1',
        credentialRef='ref://' + imported['credentialId'])
    assert resolved.revisions['configVersion'] == 1
    update = {k: v for k, v in body.items() if k not in ('harness', 'provider', 'protocols', 'endpoints')}
    update.update(requestId='request-update-01', providerModelId=saved['id'], expectedVersion=1, displayName='Updated')
    updated = rig.wire.dispatch('providerModels.update', update)['providerModel']
    assert updated['protocols'] == saved['protocols'] and updated['endpoints'] == saved['endpoints']
    assert resolver.resolve(choice, harness_id='codex').revisions['configVersion'] == 2
    assert rig.store.reads == 0


def test_actual_native_product_model_catalog_declares_api_key_for_import(tmp_path):
    from ordessa_server_product.composition import create_composition
    from ordessa_harness.configuration.model.catalog import ModelConfigurationCatalog
    root = Path(__file__).resolve().parents[4]
    runtime = create_composition().native_runtime(tmp_path / 'native', plugin_root=root / 'plugins/harness',
        harness_id='codex', adapter_command='/usr/bin/node')
    try:
        directory = runtime.plugin_host.provided_port('harness.directory')
        harnesses = ModelConfigurationCatalog(directory)
        assert directory.get('codex').credential_kind is None
        assert harnesses.get('codex').credential_kind == 'api-key'
        store = ByteStore()
        importer = ApiKeyImportService(data_root=tmp_path / 'import', harnesses=harnesses,
            credentials=CredentialRecords(runtime.database), secret_store=store)
        result = importer.import_key(request_id='production-catalog-key', harness_id='codex', api_key='synthetic-production-key')
        assert result['state'] == 'imported' and len(store.imports) == 1
    finally:
        runtime.stop()
