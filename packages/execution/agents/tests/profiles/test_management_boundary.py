"""Public owner boundary and replay of literal historical storage/request facts."""
import ast
import copy
from pathlib import Path

import pytest

from ordessa_execution_agents.profiles import (
    ProfileService, Profile, ProfileRevision, ProfileRevisionRef,
    canonical_content, content_digest, decode_content, encode_revision,
)
from ordessa_execution_agents.profiles.definitions.codec import (
    encode_content, encode_profile, encode_revision_ref,
)
from ordessa_execution_agents.profiles.management.sqlite_store import SqliteProfileStore
from ordessa_infrastructure.database.records import DomainWrite
from profile_owner_fixtures import Admission, Validator
from ordessa_execution_agents.profiles.definitions.validation import canonical

class Policy:
    def __init__(self):
        self.actions = []
        self.mutate = None

    def admit_invoke(self, principal, action, guarantee):
        self.actions.append(action)
        if self.mutate:
            self.mutate()
        return True

    def admit_object_access(self, *args):
        return True


@pytest.fixture
def owner(tmp_path):
    policy = Policy()
    store = SqliteProfileStore(tmp_path / 'synthetic.sqlite')
    env = Admission(policy, 'history-test')
    try:
        yield env, store, policy, ProfileService(store, env, Validator())
    finally:
        store.close()


def content():
    return {'schemaVersion': '1', 'harnessDefinitionRef': {
        'environmentNamespace': 'history-test', 'definitionId': 'opaque'},
        'declarations': [], 'metadata': {'purpose': ['original']}}


def historical_commit(owner, action, facts, result, expected, revision=None):
    """Literal original wire namespaces/envelopes; independent of new compatibility helpers."""
    env, store, _, service = owner
    request = service.request_key('historical-' + action)
    digest = env.fingerprint_port.fingerprint(request, 'pacthold.agents.profiles.' + action,
                                               content_digest(canonical(facts)))
    encoded_profile = encode_profile(result)
    writes = [DomainWrite('agents.profile-catalog', result.profile_id, expected, encoded_profile)]
    if revision:
        writes.append(DomainWrite('agents.profile-manifests',
            f'{revision.ref.profile_id}@{revision.ref.revision}', 0, encode_revision(revision)))
    store.commit_domain_change(request, digest, tuple(writes), encoded_profile)
    return request


def test_historical_create_edit_rename_archive_restore_clone_results_replay(owner):
    env, store, policy, service = owner
    body = content()
    canonical_body = canonical_content(body, env.namespace)
    ref = ProfileRevisionRef(env.namespace, 'main', 1, content_digest(canonical_body))
    first = Profile('main', 1, 'Main', None, ref)
    request_create = historical_commit(owner, 'create', {'entry': encode_profile(first), 'content': canonical_body},
                                      first, 0, ProfileRevision(ref, decode_content(body, env.namespace)))
    updated = {**body, 'metadata': {'purpose': ['second']}}
    canonical_updated = canonical_content(updated, env.namespace)
    second_ref = ProfileRevisionRef(env.namespace, 'main', 2, content_digest(canonical_updated))
    second = Profile('main', 2, 'Main', None, second_ref)
    request_edit = historical_commit(owner, 'edit', {'profileId': 'main', 'content': canonical_updated,
        'expectedCatalogRevision': 1, 'baseManifestRef': encode_revision_ref(ref)}, second, 1,
        ProfileRevision(second_ref, decode_content(updated, env.namespace)))
    renamed = Profile('main', 3, 'Renamed', None, second_ref)
    request_rename = historical_commit(owner, 'rename', {'profileId': 'main', 'expectedCatalogRevision': 2,
                                                       'displayName': 'Renamed'}, renamed, 2)
    archived = Profile('main', 4, 'Renamed', '2026-10-09T00:00:00+00:00', second_ref)
    request_archive = historical_commit(owner, 'archive', {'profileId': 'main', 'expectedCatalogRevision': 3}, archived, 3)
    restored = Profile('main', 5, 'Renamed', None, second_ref)
    request_restore = historical_commit(owner, 'restore', {'profileId': 'main', 'expectedCatalogRevision': 4}, restored, 4)
    cloned_ref = ProfileRevisionRef(env.namespace, 'clone', 1, ref.digest)
    cloned = Profile('clone', 1, 'Clone', None, cloned_ref)
    request_clone = historical_commit(owner, 'clone', {'sourceRef': encode_revision_ref(ref), 'profileId': 'clone',
        'displayName': 'Clone'}, cloned, 0, ProfileRevision(cloned_ref, decode_content(body, env.namespace)))
    assert service.create(profile_id='main', name='Main', content=body, request=request_create) == first
    assert service.revise('main', content=updated, expected_version=1, base_revision=ref, request=request_edit) == second
    assert service.rename('main', name='Renamed', expected_version=2, request=request_rename) == renamed
    assert service.archive('main', expected_version=3, request=request_archive) == archived
    assert service.restore('main', expected_version=4, request=request_restore) == restored
    assert service.clone(ref, profile_id='clone', name='Clone', request=request_clone) == cloned
    assert service.get('main') == restored
    assert encode_content(service.get_revision(ref).content) == body
    assert store.read_domain(env.namespace, 'agents.profile-catalog', 'main')['revision'] == 5
    assert policy.actions[-6:] == ['pacthold.agents.profiles.' + action
                                  for action in ['create', 'edit', 'rename', 'archive', 'restore', 'clone']]


def test_input_is_frozen_before_admission_callback_and_snapshot_is_staged_only(owner):
    env, store, policy, service = owner
    body = content()
    expected = copy.deepcopy(body)
    policy.mutate = lambda: body['metadata']['purpose'].append('callback mutation')
    created = service.create(profile_id='main', name='Main', content=body, request=service.request_key('create'))
    assert encode_content(service.get_revision(created.current_revision).content) == expected
    policy.mutate = None
    ref, write = service.stage_snapshot(expected)
    assert write.namespace == 'agents.profile-snapshots'
    assert store.read_domain(env.namespace, write.namespace, write.record_id) is None
    assert service.get('main') == created
    assert ref.digest == created.current_revision.digest


def boundary_violations(source):
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module.startswith('ordessa_execution_agents.profiles.'):
                violations.append(module)
        elif isinstance(node, ast.Import):
            violations.extend(alias.name for alias in node.names
                if alias.name.startswith('ordessa_execution_agents.profiles.'))
    return violations


def test_cross_distribution_consumers_use_explicit_public_entry():
    root = Path(__file__).resolve().parents[5]
    for directory in ['apps', 'products', 'plugins', 'tests']:
        for path in (root / directory).rglob('*.py'):
            if any(part in {'build', 'node_modules', '.venv', '__pycache__'} for part in path.parts):
                continue
            source = path.read_text()
            if 'ordessa_execution_agents.profiles' not in source:
                continue
            assert not boundary_violations(source), str(path)
    for planted in ['from ordessa_execution_agents.profiles.definitions.models import Profile',
                    'from ordessa_execution_agents.profiles.management.service import ProfileService',
                    'import ordessa_execution_agents.profiles.management.environment_store']:
        assert boundary_violations(planted)


def test_public_entry_has_same_owner_and_no_retired_management_api(owner):
    import ordessa_execution_agents.profiles as public
    env, _, _, service = owner
    assert public.ProfileService is type(service)
    assert service._admission is env
    assert service._profile_store is owner[1]
    for retired in ['ProfileCatalog', 'read', 'read_entry', 'edit']:
        assert not hasattr(public, retired)
        assert not hasattr(service, retired)
    directory = Path(public.__file__).parent
    assert not tuple((directory / 'catalog').glob('*.py'))
    import importlib.util
    # A source-free cache directory may be a namespace parent. Otherwise the
    # exact missing parent raises; neither case supplies the retired service.
    try:
        retired_service = importlib.util.find_spec('ordessa_execution_agents.profiles.catalog.service')
    except ModuleNotFoundError as missing:
        assert missing.name == 'ordessa_execution_agents.profiles.catalog'
        retired_service = None
    assert retired_service is None
    assert not (directory / 'catalog.py').exists()
    assert not (directory / 'wire_schema.py').exists()
    assert not (directory / 'management' / 'wire_schema.py').exists()
    assert not importlib.util.find_spec('ordessa_execution_agents.harness.contracts.schemas.wire_schema')
    for path in directory.rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('sqlite3', 'ordessa_persistence_sqlite',
                    'ordessa_server', 'ordessa_harness', 'ordessa_units',
                    'ordessa_execution_agents.harness'))
