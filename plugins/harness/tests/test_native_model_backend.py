"""Native model policy belongs to Harness; no Profile or resource storage."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ordessa_harness.configuration.model.backend import (
    NativeModelLaunchRefused, NativeModelServices, installation_routes,
    launch_options, preparation_params, requires_model_catalog,
)


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


def test_service_dispatch_uses_only_the_observed_channel_and_verified_installation(monkeypatch):
    from ordessa_harness.configuration.model import live_service
    verify, create = Mock(return_value=object()), Mock(return_value=('service', 'runtime'))
    monkeypatch.setattr(live_service, 'verified_installation', verify)
    monkeypatch.setattr(live_service, 'create_model_service', create)
    owner = SimpleNamespace(connection_id='owned')
    channel = SimpleNamespace(harness_id='codex')
    channels = Mock()
    channels.get.return_value = channel
    owners = SimpleNamespace(readback=lambda target: SimpleNamespace(owner=owner))
    services = NativeModelServices(roots={'codex': '/trusted'}, channels=channels,
        owners=owners, carrier=object(), journal_path='/private/journal')
    binding = object()
    assert services.create_service('target', credential_binding=binding) == ('service', 'runtime')
    assert services.create_service('target', credential_binding=binding) == ('service', 'runtime')
    verify.assert_called_once_with('codex', '/trusted')
    assert create.call_args.kwargs['installation'] is verify.return_value
    assert create.call_args.kwargs['credential_binding'] is binding
    assert create.call_args.kwargs['target'] == 'target'
    channel.harness_id = 'claude-code'
    with pytest.raises(ValueError, match='installation route'):
        services.create_service('target', credential_binding=binding)
    assert create.call_count == 2
    with pytest.raises(NativeModelLaunchRefused):
        services.managed_account('claude-code')
