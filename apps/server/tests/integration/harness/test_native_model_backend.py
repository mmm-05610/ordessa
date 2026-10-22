"""Native model policy belongs to Harness; no Profile or resource storage."""
from ordessa_server.composition.configuration.contributions import descriptor_admission_for
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ordessa_server.composition.configuration.model.backend import NativeModelLaunchRefused
from ordessa_server.composition.configuration.model.backend import installation_routes
from ordessa_server.composition.configuration.model.backend import launch_options
from ordessa_server.composition.configuration.model.backend import preparation_params
from ordessa_server.composition.configuration.model.backend import requires_model_catalog


def test_routes_preserve_legacy_argument_and_refuse_unknown_or_conflicting_roots():
    assert installation_routes(artifact_root='/pi', artifact_roots={'codex': '/codex'}) == {
        'pi': '/pi', 'codex': '/codex'}
    with pytest.raises(ValueError, match='Unknown'):
        installation_routes(artifact_roots={'unimplemented': '/new'})
    with pytest.raises(ValueError, match='Conflicting'):
        installation_routes(artifact_root='/new', artifact_roots={'pi': '/old'})


@pytest.mark.parametrize('brand, credential, needed', [('pi', None, False),
    ('pi', 'synthetic', True), ('codex', 'synthetic', False), ('claude-code', 'synthetic', False)])
def test_harness_decides_native_catalogue_requirement(brand, credential, needed):
    assert requires_model_catalog(brand, credential) is needed


def test_no_native_route_can_be_guessed():
    with pytest.raises(ValueError):
        requires_model_catalog('unimplemented', None)
    assert preparation_params('pi', {}, 'create:fixture') is None


def test_managed_account_options_are_owned_here_and_api_selection_never_reads_login():
    account = Mock(account_directory='/private/account')
    account.read.return_value = {'authenticated': True, 'method': 'chatgpt-managed'}
    factory = Mock(return_value=account)
    api = {'authentication': None}
    assert launch_options('codex', api, managed_account_factory=factory) == {}
    factory.assert_not_called()
    desired = dict(authentication='managed-account', protocol='openai-responses',
        provider='openai', model='model', endpoint=None, credentialRef=None)
    assert launch_options('codex', desired, managed_account_factory=factory) == {
        'codex_account_directory': '/private/account'}
    factory.assert_called_once_with('codex')
    account.read.assert_called_once_with(refresh=True)
    account.read.return_value = {'authenticated': False}
    with pytest.raises(NativeModelLaunchRefused) as refused:
        launch_options('codex', desired, managed_account_factory=factory)
    assert refused.value.code == 'AUTHENTICATION_REQUIRED'
    factory.reset_mock()
    with pytest.raises(ValueError):
        launch_options('claude-code', desired, managed_account_factory=factory)
    factory.assert_not_called()
