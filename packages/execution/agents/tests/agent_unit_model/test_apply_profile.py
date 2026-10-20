"""apply_profile: core-derived Profile declarations, never body-carried (A11).

Real temporary SQLite store, real Core/Node publication/Issuer/Profile catalog
with the controlled owner ports from the management fixture. The declarations
always come from the core-held Profile snapshot; applying never writes the
catalog back and a Profile update never applies itself.
"""
from __future__ import annotations
from ordessa_execution_agents.profiles import decode_revision_ref, encode_content

from dataclasses import replace

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitIdentityMismatch
from ordessa_units.configuration.contracts import (
    ApplicationPolicy, ConfigurationChangeRequest, ConfigurationContractError,
    ConfigurationRevisionConflict,
)
from ordessa_execution_agents.profiles.definitions.models import ProfileRevisionRef
from ordessa_execution_agents.profiles.management.service import ProfileService
from ordessa_execution_agents.harness.providers.registry.contributions import RUNTIME_METHODS

from agent_tools_fixtures.management import setup  # noqa: F401 - pytest fixture (already marked)
from agent_tools_fixtures.node_publication import setup as node_fixture, Provider  # noqa: F401 - fixture dependency


@pytest.fixture(autouse=True)
def explicit_capabilities(monkeypatch):
    monkeypatch.setattr(Provider, 'descriptor',
                        replace(Provider.descriptor, supported_methods=RUNTIME_METHODS))

DECLARATION = {'declarationId': 'model', 'configurationKind': 'model', 'schemaVersion': '1',
               'action': 'value', 'requirement': 'required', 'payload': {'modelId': 'new'}}
DEFINITION = {'environmentNamespace': 'env', 'definitionId': 'fixture', 'revision': '1'}


def _profile(parts, declarations=(DECLARATION,), name='profile-applied'):
    _, env, *_ = parts
    catalog = ProfileService(env)
    return catalog, catalog.create(
        profile_id=name, name='Applied Profile',
        content={'harnessDefinitionRef': dict(DEFINITION),
                  'schemaVersion': '1', 'declarations': list(declarations)},
        request=RequestKey('env', 'principal', 'create-' + name))


def _base_ref(parts):
    """The Node's frozen preparation manifest is the update's base source."""
    import json
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    coordinator, node = parts[3], parts[4]
    return decode_revision_ref(json.loads(safe_json(coordinator._nodes.read(node)['lineage']['profileSnapshotRef'])))


def test_apply_profile_derives_declarations_from_core_profile(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    catalog, entry = _profile(setup)
    outcome = coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile'),
        node, entry.current_revision, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert outcome.status == 'published'
    assert state['calls'] == 1 and state['model'] == 'new'


def test_same_request_with_different_content_conflicts(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup)
    key = RequestKey('env', 'principal', 'apply-profile-conflict')
    coordinator.apply_profile(key, node, entry.current_revision,
                              'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    _, other = _profile(setup, declarations=({**DECLARATION, 'payload': {'modelId': 'other'}},),
                        name='profile-other')
    with pytest.raises(UnitIdentityMismatch):
        coordinator.apply_profile(key, node, other.current_revision,
                                  'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 1  # the conflicting request never dispatched again


def test_apply_never_writes_the_catalog_back(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    catalog, entry = _profile(setup)
    entries_before = catalog.list()
    manifest_before = catalog.get_revision(entry.current_revision)
    coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-back'),
        node, entry.current_revision, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert catalog.list() == entries_before
    assert encode_content(catalog.get_revision(entry.current_revision).content) == encode_content(manifest_before.content)


def test_expected_configuration_revision_mismatch_is_refused(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup)
    with pytest.raises(ConfigurationRevisionConflict):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-revision'),
            node, entry.current_revision, 'native-wrong', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0


def test_foreign_or_malformed_profile_ref_is_refused(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    with pytest.raises(Exception):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-foreign'),
            node, ProfileRevisionRef('foreign-environment', 'profile', 1, 'sha256:' + 'a' * 64),
            'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    with pytest.raises(UnitIdentityMismatch):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-shape'),
            node, {'profileId': 'not-a-profile-ref'}, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0


def test_profile_without_declarations_is_refused_before_dispatch(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup, declarations=(), name='profile-empty')
    with pytest.raises(ConfigurationContractError):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-empty'),
            node, entry.current_revision, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0


def test_preset_current_revision_change_does_not_rebind_or_apply_to_existing_unit(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    catalog = ProfileService(env)
    fixed = _base_ref(setup)
    original_node = coordinator._nodes.read(node)
    before = catalog.get(fixed.profile_id)
    changed = encode_content(catalog.get_revision(fixed).content)
    changed['declarations'][0]['payload'] = {'modelId': 'future-preset-intent'}
    edited = catalog.revise(fixed.profile_id, content=changed,
        expected_version=before.version, base_revision=fixed,
        request=RequestKey('env', 'principal', 'edit-preset-with-bound-unit'))
    archived = catalog.archive(fixed.profile_id, expected_version=edited.version,
        request=RequestKey('env', 'principal', 'archive-preset-with-bound-unit'))
    assert edited.current_revision.revision == fixed.revision + 1
    assert archived.version == before.version + 2
    assert archived.current_revision == edited.current_revision
    assert catalog.get_revision(fixed).content.declarations[0].payload['modelId'] == 'old'
    assert coordinator._nodes.read(node) == original_node
    assert _base_ref(setup) == fixed
    assert state['model'] == 'old' and state['revision'] == 'native-1' and state['calls'] == 0
