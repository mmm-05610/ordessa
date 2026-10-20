"""Units-owned material registration negatives and capability ownership."""
import importlib
import threading

import pytest

from ordessa_units.errors import UnitAdmissionRefused
from ordessa_units.definitions.materials import ResourceProviderDescriptor
from ordessa_units.definitions.materials import ReconcileSupport
from ordessa_units.admission.material_contracts import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialCapability,
)
from ordessa_units.admission.material_registration import MaterialCatalog


class Provider:
    supported_contract_ids = ()
    material_capability = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION, ("copyComplete",), True, "both")

    def __init__(self):
        self.describe_calls = 0
        self.effect_calls = 0

    def describe(self):
        self.describe_calls += 1
        return ResourceProviderDescriptor(
            "owner.material", "Material", "1", ReconcileSupport.SUPPORTED)

    def acquire(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch acquisition")

    def release(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch release")

    def reconcile(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch reconciliation")

    def describe_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch material methods")

    def resolve_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch material methods")

    def query_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch material methods")

    def release_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("registration must never dispatch material methods")


def test_invalid_resource_role_does_not_publish_any_catalog_entry():
    class IncompleteProvider:
        pass

    catalog = MaterialCatalog("environment")
    with pytest.raises(UnitAdmissionRefused):
        catalog.stage("owner", 1, (IncompleteProvider(),), ())
    assert catalog.providers() == ()


def test_registration_snapshots_same_provider_under_catalog_lock_twice():
    lock = threading.RLock()

    class LockCheckingProvider(Provider):
        def describe(self):
            assert lock._is_owned()
            return super().describe()

    catalog = MaterialCatalog("environment", admission_lock=lock)
    provider = LockCheckingProvider()
    staged = catalog.stage("owner", 1, (provider,), ())
    assert catalog.provider("owner.material") is None
    committed = staged.commit()

    assert provider.describe_calls == 2
    assert provider.effect_calls == 0
    assert committed[0].descriptor.id == "owner.material"
    assert committed[0].capability == provider.material_capability
    assert catalog.provider("owner.material") == committed[0]
    assert not hasattr(committed[0], "provider")


def test_commit_refuses_material_capability_drift_without_publication():
    provider = Provider()
    catalog = MaterialCatalog("environment")
    staged = catalog.stage("owner", 1, (provider,), ())
    provider.material_capability = MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION, ("dynamic",), True, "both")

    with pytest.raises(UnitAdmissionRefused, match="metadata changed"):
        staged.commit()
    assert catalog.provider("owner.material") is None
    assert provider.effect_calls == 0


def test_old_kernel_material_definition_is_retired():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pacthold.core.resource_admission")
    assert MaterialCapability.__module__ == "ordessa_units.admission.material_contracts"
