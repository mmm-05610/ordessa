"""Registry publication rules: two arbitrary capabilities, no host edits."""
from __future__ import annotations

import pytest

from ordessa_interfaces_contracts import Capability, CapabilityDescriptor, ContractError
from ordessa_interfaces.system_access.registry import (
    CapabilityRegistry, RegistryError, build_registry,
)

from host_fakes import make_capability


def test_two_fake_capabilities_register_without_host_changes():
    registry = build_registry([
        make_capability('alpha', operation_ids=('alpha.run',)),
        make_capability('beta', operation_ids=('beta.run', 'beta.other')),
    ])
    assert set(registry.capabilities) == {'alpha', 'beta'}
    assert set(registry.operations) == {'alpha.run', 'beta.run', 'beta.other'}
    assert registry.resolve('beta.other').capability_id == 'beta'
    assert registry.registration_order() == ('alpha', 'beta')


def test_duplicate_capability_or_operation_ids_refuse():
    registry = CapabilityRegistry()
    registry.register(make_capability('alpha', operation_ids=('alpha.run',)))
    with pytest.raises(RegistryError, match='capability id'):
        registry.register(make_capability('alpha', operation_ids=('alpha.other',)))



def test_foreign_operation_prefix_refuses():
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError, match='not owned'):
        registry.register(make_capability('alpha', operation_ids=('beta.run',)))


def test_unknown_operation_and_frozen_registry():
    registry = build_registry([make_capability('alpha', operation_ids=('alpha.run',))])
    with pytest.raises(RegistryError, match='not registered'):
        registry.resolve('alpha.missing')
    with pytest.raises(RegistryError, match='frozen'):
        registry.register(make_capability('beta', operation_ids=('beta.run',)))
