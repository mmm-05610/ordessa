"""apply_profile: core-derived Profile declarations, never body-carried (A11).

Real temporary SQLite store, real Core/Node publication/Issuer/Profile catalog
with the controlled owner ports from the management fixture. The declarations
always come from the core-held Profile snapshot; applying never writes the
catalog back and a Profile update never applies itself.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from ordessa_environment_api import IdentityMismatchError, RequestKey
from pacthold.agents.configuration import (
    ApplicationPolicy, ConfigurationChangeRequest, ConfigurationContractError,
    ConfigurationRevisionConflict,
)
from pacthold.agents.contracts import ProfileRef
from pacthold.agents.profiles import ProfileCatalog
from pacthold.agents.runtime import RUNTIME_METHODS

from test_management import setup  # noqa: F401 - pytest fixture (already marked)
from test_node_publication import setup as node_fixture, Provider  # noqa: F401 - fixture dependency


@pytest.fixture(autouse=True)
def explicit_capabilities(monkeypatch):
    monkeypatch.setattr(Provider, 'descriptor',
                        replace(Provider.descriptor, supported_methods=RUNTIME_METHODS))

DECLARATION = {'declarationId': 'model', 'configurationKind': 'model', 'schemaVersion': '1',
               'action': 'value', 'requirement': 'required', 'payload': {'modelId': 'new'}}
DEFINITION = {'environmentNamespace': 'env', 'definitionId': 'fixture', 'revision': '1'}


def _profile(parts, declarations=(DECLARATION,), name='profile-applied'):
    _, env, *_ = parts
    catalog = ProfileCatalog(env)
    return catalog, catalog.create(
        profile_id=name, display_name='Applied Profile',
        manifest={'harnessDefinitionRef': dict(DEFINITION),
                  'schemaVersion': '1', 'declarations': list(declarations)},
        request=RequestKey('env', 'principal', 'create-' + name))


def _base_ref(parts):
    """The Node's frozen preparation manifest is the update's base source."""
    import json
    from ordessa_environment_api.operations import safe_json
    coordinator, node = parts[3], parts[4]
    return ProfileRef.from_dict(json.loads(safe_json(
        coordinator._nodes.read(node)['lineage']['profileSnapshotRef'])))


def test_apply_profile_derives_declarations_from_core_profile(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    catalog, entry = _profile(setup)
    outcome = coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile'),
        node, entry.current_manifest_ref, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert outcome.status == 'published'
    assert state['calls'] == 1 and state['model'] == 'new'


def test_same_request_with_different_content_conflicts(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup)
    key = RequestKey('env', 'principal', 'apply-profile-conflict')
    coordinator.apply_profile(key, node, entry.current_manifest_ref,
                              'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    _, other = _profile(setup, declarations=({**DECLARATION, 'payload': {'modelId': 'other'}},),
                        name='profile-other')
    with pytest.raises(IdentityMismatchError):
        coordinator.apply_profile(key, node, other.current_manifest_ref,
                                  'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 1  # the conflicting request never dispatched again


def test_apply_never_writes_the_catalog_back(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    catalog, entry = _profile(setup)
    entries_before = catalog.list()
    manifest_before = catalog.read(entry.current_manifest_ref)
    coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-back'),
        node, entry.current_manifest_ref, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert catalog.list() == entries_before
    assert catalog.read(entry.current_manifest_ref).content == manifest_before.content


def test_expected_configuration_revision_mismatch_is_refused(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup)
    with pytest.raises(ConfigurationRevisionConflict):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-revision'),
            node, entry.current_manifest_ref, 'native-wrong', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0


def test_foreign_or_malformed_profile_ref_is_refused(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    with pytest.raises(Exception):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-foreign'),
            node, ProfileRef('foreign-environment', 'profile', 1, 'sha256:' + 'a' * 64),
            'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    with pytest.raises(IdentityMismatchError):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-shape'),
            node, {'profileId': 'not-a-profile-ref'}, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0


def test_profile_without_declarations_is_refused_before_dispatch(setup):
    store, env, policy, coordinator, node, request, change, state, authority, current, issuer = setup
    _, entry = _profile(setup, declarations=(), name='profile-empty')
    with pytest.raises(ConfigurationContractError):
        coordinator.apply_profile(RequestKey('env', 'principal', 'apply-profile-empty'),
            node, entry.current_manifest_ref, 'native-1', ApplicationPolicy(), base_profile_ref=_base_ref(setup))
    assert state['calls'] == 0
