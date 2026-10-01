from ordessa_harness.configuration.model.catalog import ModelConfigurationCatalog
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
import pytest


@pytest.mark.parametrize('brand', ['pi', 'codex', 'claude-code'])
def test_real_native_directory_gains_model_credential_declaration_without_mutation(brand):
    directory = HarnessRegistry()
    descriptor = HarnessDescriptor(brand)
    directory.register(descriptor)
    catalog = ModelConfigurationCatalog(directory)
    assert catalog.get(brand).credential_kind == 'api-key'
    assert directory.get(brand) is descriptor
    assert descriptor.credential_kind is None


def test_explicit_credential_kind_is_never_replaced():
    directory = HarnessRegistry()
    descriptor = HarnessDescriptor('codex', credential_kind='declared-custom-kind')
    directory.register(descriptor)
    assert ModelConfigurationCatalog(directory).get('codex') is descriptor
