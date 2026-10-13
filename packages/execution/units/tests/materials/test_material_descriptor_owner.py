"""Persisted declaration syntax and the material catalog's single class owner."""
import importlib.abc
import subprocess
import sys

import pytest

from ordessa_units.definitions.materials import (
    MaterialDeclarationError, MaterialProviderIdError,
    ReconcileSupport, ResourceProviderDescriptor, validate_contract_id,
)


def test_descriptor_preserves_historical_values_and_is_immutable():
    descriptor = ResourceProviderDescriptor('vendor.material-1', ' Material ', ' 1 ',
                                            ReconcileSupport.UNSUPPORTED)
    assert (descriptor.id, descriptor.display_name, descriptor.version,
            descriptor.reconcile_support.value) == ('vendor.material-1', ' Material ', ' 1 ', 'unsupported')
    with pytest.raises(AttributeError):
        descriptor.version = '2'


@pytest.mark.parametrize('identity', ['Vendor.material', '', 'a/b', 'a@1', None])
def test_persisted_provider_id_syntax_refuses_invalid_identities(identity):
    with pytest.raises(MaterialProviderIdError):
        ResourceProviderDescriptor(identity, 'Material', '1', ReconcileSupport.SUPPORTED)


@pytest.mark.parametrize('identity', ['vendor.material@0', 'vendor.material', 'vendor.material@01', None])
def test_contract_version_is_explicit_and_canonical(identity):
    with pytest.raises(MaterialDeclarationError):
        validate_contract_id(identity)
    assert validate_contract_id('vendor.material@12') == 'vendor.material@12'


def test_undeclared_reconciliation_never_becomes_supported():
    with pytest.raises(MaterialDeclarationError):
        ResourceProviderDescriptor('vendor.material', 'Material', '1', 'supported')


def test_actual_owner_import_does_not_load_retired_c1_descriptor_family():
    script = '''
import importlib.abc, sys
class RefuseOldDescriptors(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ordessa_execution_api.c1" or fullname.startswith("ordessa_execution_api.c1."):
            raise AssertionError("retired material declaration import")
sys.meta_path.insert(0, RefuseOldDescriptors())
from ordessa_units.definitions.materials import ResourceProviderDescriptor, ReconcileSupport
from ordessa_units.admission.material_contracts import ResourceProviderDescriptor as metadata_type
from ordessa_units.admission.material_registration import ResourceProviderDescriptor as catalog_type
assert ResourceProviderDescriptor is metadata_type is catalog_type
assert ResourceProviderDescriptor.__module__ == "ordessa_units.definitions.materials"
assert ReconcileSupport.__module__ == "ordessa_units.definitions.materials"
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
