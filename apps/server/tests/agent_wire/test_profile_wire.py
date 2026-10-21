"""Thin public binding contract checks, real temporary SQLite, no HTTP claim."""
from ordessa_agents.profiles import ProfileChangeUnknown

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot
import json
from pathlib import Path
import pytest
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment
from ordessa_units.public import wire_contract, wire_schema_digest
from ordessa_system_access_bindings import agent_core_methods
from ordessa_server_plugin_api import WireError

class Policy:
    allowed = True
    def admit_invoke(self, *args): return self.allowed
    def admit_object_access(self, *args): return self.allowed

@pytest.fixture
def bound(tmp_path):
    store = SqliteStorePort(tmp_path / 'core.sqlite')
    policy = Policy()
    env = Environment('wire-test', store=store, policy=policy, principal_scope='local',
        fingerprint_port=ProtectedFingerprintHmac({'fixture': b'fixture'}, active_key_id='fixture'), resource_extension_snapshot=_test_resource_snapshot)
    methods = {m.method_id: m for m in agent_core_methods(lambda: env)}
    yield methods, policy, store
    env.close()
    store.close()

def create_params():
    return {'profileId':'one','displayName':'One','requestId':'create-one',
        'manifest':{'harnessDefinitionRef':{'environmentNamespace':'wire-test','definitionId':'absent'},
                    'schemaVersion':'1','declarations':[]}}

def test_schema_mirror_and_descriptors(bound):
    methods, _, _ = bound
    mirror = json.loads((Path(__file__).resolve().parents[4] / 'packages/interfaces/transport/client/python/src/ordessa_system_access_client/schema.json').read_text())
    assert mirror == {'schema': wire_contract(), 'schemaDigest':wire_schema_digest()}
    for name, binding in mirror['schema']['methods'].items():
        method = methods[name]
        assert method.owner == 'pacthold.agents'
        assert method.required_params == frozenset(binding['required'])
        assert method.optional_params == frozenset(binding['optional'])
    caps = methods['agents.capabilities'].handler({})
    assert caps['supports'] == {'profileCatalog':True,'nodes':False,'managedInput':False}

def test_wire_roundtrip_history_and_safe_errors(bound):
    methods, policy, _ = bound
    call = lambda name, params: methods['agents.profiles.' + name].handler(params)
    first = call('create',create_params())
    assert call('create',create_params()) == first
    assert call('read',{'profileRef':first['currentManifestRef']})['content'] == create_params()['manifest']
    with pytest.raises(WireError) as conflict:
        call('rename',{'profileId':'one','displayName':'Two','expectedCatalogRevision':1,'requestId':'create-one'})
    assert conflict.value.family == 'CONFLICT_REQUEST'
    with pytest.raises(WireError) as stale:
        call('archive',{'profileId':'one','expectedCatalogRevision':2,'requestId':'archive'})
    assert stale.value.family == 'CONFLICT_VERSION'
    policy.allowed = False
    with pytest.raises(WireError) as forbidden:
        call('list',{})
    assert forbidden.value.family == 'FORBIDDEN'

@pytest.mark.parametrize('params', [{'profileRef':None},{'profileRef':{'secret':'sensitive'}}, {'includeArchived':1}])
def test_invalid_parameters_sanitized(bound, params):
    methods, _, _ = bound
    method = 'agents.profiles.list' if 'includeArchived' in params else 'agents.profiles.read'
    with pytest.raises(WireError) as error:
        methods[method].handler(params)
    assert error.value.family == 'INVALID_REQUEST'
    assert 'sensitive' not in str(error.value)

def test_unknown_is_not_reissued(bound, monkeypatch):
    methods, _, store = bound
    writes = []
    def unknown(*args): raise ProfileChangeUnknown('secret internal error')
    monkeypatch.setattr(store,'read_domain_result',unknown)
    monkeypatch.setattr(store,'commit_domain_change',lambda *args: writes.append(args))
    with pytest.raises(WireError) as error:
        methods['agents.profiles.create'].handler(create_params())
    assert error.value.family == 'OUTCOME_UNKNOWN'
    assert writes == [] and 'secret' not in str(error.value)

@pytest.mark.parametrize('change', ['environment', 'revision', 'digest', 'extra'])
def test_corrupted_replay_cannot_publish_another_identity(bound, change):
    methods, _, store = bound
    call = methods['agents.profiles.create'].handler
    first = call(create_params())
    wrong = json.loads(json.dumps(first))
    if change == 'environment': wrong['currentManifestRef']['environmentNamespace'] = 'other'
    if change == 'revision': wrong['catalogRevision'] = 9
    if change == 'digest': wrong['currentManifestRef']['contentDigest'] = 'sha256:' + '0' * 64
    if change == 'extra': wrong['secret'] = 'private'
    store._conn.execute('UPDATE env_requests SET receipt=? WHERE request_id=?',
                        (json.dumps({'domain_result':wrong}), 'create-one'))
    store._conn.commit()
    with pytest.raises(WireError) as error:
        call(create_params())
    assert error.value.family == 'OUTCOME_UNKNOWN'
    assert methods['agents.profiles.readEntry'].handler({'profileId':'one'}) == first


def test_bad_stored_json_is_service_unavailable_not_bad_input(bound):
    methods, _, store = bound
    methods['agents.profiles.create'].handler(create_params())
    store._conn.execute("UPDATE env_domain_records SET payload='broken' WHERE namespace='agents.profile-catalog'")
    store._conn.commit()
    with pytest.raises(WireError) as error:
        methods['agents.profiles.readEntry'].handler({'profileId':'one'})
    assert error.value.family == 'CAPABILITY_UNSUPPORTED'


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, KeyError, TypeError])
def test_unclassified_commit_failure_cannot_claim_no_effect(bound, monkeypatch, failure):
    methods, _, store = bound
    original = store.commit_domain_change
    def committed_then_lost(*args):
        original(*args)
        raise failure('sensitive internal failure after commit')
    monkeypatch.setattr(store, 'commit_domain_change', committed_then_lost)
    with pytest.raises(WireError) as error:
        methods['agents.profiles.create'].handler(create_params())
    assert error.value.family == 'OUTCOME_UNKNOWN'
    assert 'sensitive' not in str(error.value)
    assert methods['agents.profiles.readEntry'].handler({'profileId':'one'})['catalogRevision'] == 1


def test_invalid_utf8_catalog_input_has_no_persistent_effect(bound):
    methods, _, store = bound
    params = create_params()
    params['displayName'] = '\ud800'
    with pytest.raises(WireError) as error:
        methods['agents.profiles.create'].handler(params)
    assert error.value.family == 'INVALID_REQUEST'
    assert methods['agents.profiles.list'].handler({}) == {'entries':[]}
    assert store._conn.execute('SELECT count(*) FROM env_requests').fetchone()[0] == 0


def test_wire_full_management_lifecycle_keeps_exact_history_cas_and_replay(bound):
    methods, policy, _store = bound
    call = lambda name, params: methods["agents.profiles." + name].handler(params)
    created = call("create", create_params())
    first_ref = created["currentManifestRef"]
    cloned_params = {"profileRef": first_ref, "profileId": "copy",
                     "displayName": "Copy", "requestId": "clone-one"}
    cloned = call("clone", cloned_params)
    assert cloned["profileId"] == "copy"
    assert call("clone", cloned_params) == cloned
    changed = dict(create_params()["manifest"])
    changed["metadata"] = {"audit": "revised"}
    revised = call("edit", {"profileId": "one", "manifest": changed,
        "expectedCatalogRevision": 1, "baseManifestRef": first_ref,
        "requestId": "revise-one"})
    assert revised["catalogRevision"] == 2
    assert call("read", {"profileRef": first_ref})["content"] == create_params()["manifest"]
    renamed = call("rename", {"profileId": "one", "displayName": "Renamed",
        "expectedCatalogRevision": 2, "requestId": "rename-one"})
    assert renamed["displayName"] == "Renamed"
    with pytest.raises(WireError) as stale:
        call("archive", {"profileId": "one", "expectedCatalogRevision": 2,
                         "requestId": "stale-archive"})
    assert stale.value.family == "CONFLICT_VERSION"
    archived = call("archive", {"profileId": "one",
        "expectedCatalogRevision": 3, "requestId": "archive-one"})
    assert archived["archivedAt"] is not None
    assert all(item["profileId"] != "one" for item in call("list", {})["entries"])
    assert call("read", {"profileRef": first_ref})["content"] == create_params()["manifest"]
    assert call("archive", {"profileId": "one",
        "expectedCatalogRevision": 3, "requestId": "archive-one"}) == archived
    policy.allowed = False
    with pytest.raises(WireError) as forbidden:
        call("read", {"profileRef": first_ref})
    assert forbidden.value.family == "FORBIDDEN"
    policy.allowed = True
    restored = call("restore", {"profileId": "one",
        "expectedCatalogRevision": 4, "requestId": "restore-one"})
    assert restored["archivedAt"] is None
    assert restored["catalogRevision"] == 5
    assert call("readEntry", {"profileId": "one"}) == restored
