"""Root scope identity and Harness-only registration after Core retirement."""
from ordessa_units.errors import UnitGuaranteeUnavailable
from pathlib import Path
from types import SimpleNamespace
import pytest
from ordessa_server.composition.unit_runtime import UnitRuntimeOwner
from ordessa_server.composition.harness_registration import HarnessDefinitionHandler
from server_plugin_api import ServerPluginDescriptor
from test_unit_governance_product import scope,declaration


def test_root_forwards_exact_product_context_without_a_second_store(tmp_path):
    context=scope(tmp_path/'original/state/core.sqlite')
    path=tmp_path/'unused.sqlite'
    factory_paths=[]
    def factory(selected_path):
        factory_paths.append(Path(selected_path))
        return context
    owner=UnitRuntimeOwner(path,environment_factory=factory)
    try:
        assert owner.open() is context
        assert owner.context is context
        assert factory_paths==[path]
        assert not path.exists(), 'Root constructed a second Unit store'
        assert not hasattr(owner,'submit')
        assert not hasattr(owner,'invoke')
        assert not hasattr(owner,'stage'), 'Root lifetime must not become a mixed role registry'
    finally:
        owner.close()


def test_missing_product_scope_refuses_before_any_effect(tmp_path):
    path=tmp_path/'unused.sqlite'
    owner=UnitRuntimeOwner(path)
    effects=[]
    with pytest.raises(UnitGuaranteeUnavailable,match='no Unit admission factory'):
        context=owner.open()
        effects.append(context)
    assert effects==[]
    assert not path.exists()
    owner.close()


def test_host_role_stages_and_commits_in_the_original_product_catalog(tmp_path):
    owner=UnitRuntimeOwner(tmp_path/'state/core.sqlite',environment_factory=scope)
    context=owner.open()
    handler=HarnessDefinitionHandler(owner)
    descriptor=ServerPluginDescriptor('sample.plugin','Sample','1')
    token=handler.begin_owner_activation(descriptor)
    contribution=SimpleNamespace(payload=(declaration(context.environment_id),))
    try:
        prepared=handler.stage(contribution,descriptor.id)
        assert prepared is token and token.prepared.state=='staged'
        assert context.harness_catalog.list()==()
        handler.commit(contribution,prepared,descriptor.id)
        assert token.prepared.state=='committed'
        assert context.harness_catalog.list()[0].descriptor.provider_id=='controlled.provider'
        handler.retire_owner_activation(descriptor,token)
        assert context.harness_catalog.list()==()
    finally:
        owner.close()
