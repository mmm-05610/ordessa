"""Retired families must not bypass independent CoreRegistry admission."""
import pytest
from ordessa_environment_api import GuaranteeUnavailableError


class NoContextAccess:
    def __getattr__(self, name):
        raise AssertionError('Retired factory accessed context: ' + name)


@pytest.mark.parametrize('family', ['codex', 'pi', 'claude-code'])
def test_direct_provider_constructor_cannot_bypass_retired_factory(family):
    from ordessa_server_product.harness_adapters.generic.execution_provider import GenericExecutionProvider
    from ordessa_server_product.harness_adapters.registry import load_builtin_registry
    with pytest.raises(GuaranteeUnavailableError, match='independent provider'):
        GenericExecutionProvider(load_builtin_registry().get(family), NoContextAccess())


@pytest.mark.parametrize('family', ['codex', 'pi', 'claude-code'])
def test_direct_generic_factory_refuses_before_context_or_storage(family):
    from ordessa_server_product.harness_adapters.generic.factory import build_registration
    with pytest.raises(GuaranteeUnavailableError):
        build_registration(NoContextAccess(), family)


@pytest.mark.parametrize('factory', ['create_codex', 'create_pi', 'create_claude'])
def test_old_named_factory_cannot_publish_runtime(factory):
    from ordessa_server_product.harness_adapters import entrypoints
    with pytest.raises(GuaranteeUnavailableError):
        getattr(entrypoints, factory)().build(NoContextAccess())


@pytest.mark.parametrize('facade', ['create_plugin', 'HarnessesPlugin'])
def test_old_default_facade_cannot_publish_codex_runtime(facade):
    from ordessa_server_product.harness_adapters import plugin
    with pytest.raises(GuaranteeUnavailableError):
        getattr(plugin, facade)().build(NoContextAccess())


@pytest.mark.parametrize('family', ['opencode', 'hermes', 'dsh', 'kilo'])
def test_unmigrated_factories_preserve_original_registration(tmp_path, family):
    from pacthold.extensions import PluginContext
    from ordessa_server_product.harness_adapters.generic.factory import build_registration
    from ordessa_server_product.harness_adapters.registry import load_builtin_registry
    definition = load_builtin_registry().get(family)
    registration = build_registration(PluginContext('1', tmp_path, tmp_path / 'plugin'), family)
    assert len(registration.execution_providers) == 1
    assert definition.harness_type == family
    assert registration.execution_providers[0].descriptor().id == family + '-execution'
    assert [control.provider_id for control in registration.host_controls] == [family + '-execution']
    assert len(registration.resource_selectors) == 1
    assert len(registration.harness_managers) == 1
    assert registration.contracts == ()
    assert registration.resource_providers == ()
    assert (tmp_path / 'profiles').is_dir()


def test_profile_store_entry_preserves_metadata_without_runtime(tmp_path):
    from pacthold.extensions import PluginContext
    from ordessa_server_product.harness_adapters.entrypoints import create_profile_store
    plugin = create_profile_store()
    registration = plugin.build(PluginContext('1', tmp_path, tmp_path / 'plugin'))
    assert plugin.descriptor().id == 'harness-profile-store'
    assert registration.execution_providers == ()
    assert registration.host_controls == ()
    assert len(registration.resource_providers) == 1
    assert registration.resource_providers[0].descriptor().id == 'harness-profile'
    assert (tmp_path / 'profiles').is_dir()
