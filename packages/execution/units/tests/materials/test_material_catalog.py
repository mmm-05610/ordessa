"""Focused Units catalog tests: registration metadata never dispatches effects."""
import pytest
from contextlib import contextmanager

from ordessa_execution_api.environment import AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_units.definitions.materials import ResourceProviderDescriptor
from ordessa_units.definitions.materials import ReconcileSupport
from ordessa_units.admission.material_contracts import (
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialCapability,
)
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.material_admission import MaterialAdmission


_CONTRACT = "sample.alpha@1"


class Provider:
    supported_contract_ids = (_CONTRACT,)
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
        raise AssertionError("catalog registration must not dispatch resource effects")

    def release(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch resource effects")

    def reconcile(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch resource effects")

    def describe_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch material effects")

    def resolve_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch material effects")

    def query_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch material effects")

    def release_material(self, *args):
        self.effect_calls += 1
        raise AssertionError("catalog registration must not dispatch material effects")


def test_catalog_stages_and_commits_fixed_provider_pin_without_effect_calls():
    provider = Provider()
    catalog = MaterialCatalog("environment")
    registration = catalog.stage("owner", 3, (provider,), (_CONTRACT,))

    assert catalog.provider("owner.material") is None
    committed = registration.commit()

    assert len(committed) == 1
    pin = committed[0]
    assert pin.owner_activation.plugin_id == "owner"
    assert pin.owner_activation.generation == 3
    assert pin.supported_contract_ids == (_CONTRACT,)
    assert pin.capability == provider.material_capability
    assert catalog.provider("owner.material") == pin
    assert not hasattr(pin, "provider")
    assert provider.describe_calls == 2
    assert provider.effect_calls == 0


def test_catalog_rechecks_descriptor_coverage_and_capability_before_commit():
    provider = Provider()
    catalog = MaterialCatalog("environment")
    registration = catalog.stage("owner", 3, (provider,), (_CONTRACT,))
    provider.supported_contract_ids = ()

    with pytest.raises(AdmissionRefusedError, match="metadata changed"):
        registration.commit()
    assert catalog.provider("owner.material") is None
    assert provider.effect_calls == 0


def test_retirement_requires_guard_drained_state_and_no_catalog_holds():
    provider = Provider()
    lock = __import__("threading").RLock()
    guard_calls = []

    def guard(owner_id, generation):
        assert not lock._is_owned()
        guard_calls.append((owner_id, generation))
        @contextmanager
        def protected_retirement():
            yield None
        return protected_retirement()

    catalog = MaterialCatalog("environment", admission_lock=lock, retirement_guard=guard)
    catalog.stage("owner", 3, (provider,), (_CONTRACT,)).commit()
    with pytest.raises(AdmissionRefusedError, match="drained"):
        catalog.retire("owner", 3)

    catalog.hold("owner", 3)
    catalog.drain("owner", 3)
    assert catalog.provider("owner.material") is None
    with pytest.raises(AdmissionRefusedError, match="holds"):
        catalog.retire("owner", 3)
    catalog.release_hold("owner", 3)

    retired = catalog.retire("owner", 3)
    assert retired[0].descriptor.id == "owner.material"
    with pytest.raises(AdmissionRefusedError, match="unknown"):
        catalog.retire("owner", 3)
    assert guard_calls == [("owner", 3)] * 4
    with pytest.raises(AdmissionRefusedError, match="unknown"):
        catalog.retire("owner", 3)


@pytest.mark.parametrize("invalid_permit", [True, {}])
def test_retirement_rejects_boolean_or_mapping_guard_enter_value(invalid_permit):
    provider = Provider()

    def guard(owner_id, generation):
        @contextmanager
        def protected_retirement():
            yield invalid_permit
        return protected_retirement()

    catalog = MaterialCatalog("environment", retirement_guard=guard)
    catalog.stage("owner", 3, (provider,), (_CONTRACT,)).commit()
    catalog.drain("owner", 3)

    with pytest.raises(AdmissionRefusedError, match="invalid permit"):
        catalog.retire("owner", 3)
    assert catalog.provider("owner.material") is None


def test_catalog_refuses_missing_retirement_guard_and_close_with_pending_owner():
    provider = Provider()
    catalog = MaterialCatalog("environment")
    catalog.stage("owner", 3, (provider,), (_CONTRACT,))
    with pytest.raises(AdmissionRefusedError, match="cannot close"):
        catalog.close()
    with pytest.raises(GuaranteeUnavailableError, match="guard is unavailable"):
        catalog.retire("owner", 3)


class Context:
    environment_namespace = "environment"
    principal_scope = "unit-reader"

    def __init__(self, catalog, *, allowed=True):
        self.material_catalog = catalog
        self.admission_lock = catalog.admission_lock
        self.policy = self
        self.allowed = allowed
        self.policy_calls = []

    def admit_object_access(self, principal, object_ref, permission):
        self.policy_calls.append((principal, object_ref, permission))
        return self.allowed


def test_material_admission_uses_context_catalog_policy_and_same_exact_provider():
    provider = Provider()
    catalog = MaterialCatalog("environment")
    catalog.stage("owner", 3, (provider,), (_CONTRACT,)).commit()
    context = Context(catalog)
    admission = MaterialAdmission(context)

    metadata = admission.material_provider_contribution("owner.material")
    operation_metadata, same_provider = admission._material_provider_for_operation(
        "owner.material", _CONTRACT, "1", metadata.resource_provider.owner_activation)

    assert operation_metadata == metadata
    assert same_provider is provider
    assert context.policy_calls == [
        ("unit-reader", "environment:agents.resources", "read"),
        ("unit-reader", "environment:agents.resources", "read"),
    ]
    assert not hasattr(admission, "_registry")
    assert not hasattr(admission, "_activations")

    denied = MaterialAdmission(Context(catalog, allowed=False))
    with pytest.raises(AdmissionRefusedError, match="discovery refused"):
        denied.material_provider_contribution("owner.material")
