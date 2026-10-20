"""Retained staging and detached-metadata guarantees on the actual Unit owner."""
from dataclasses import FrozenInstanceError

import pytest

from ordessa_units.errors import UnitAdmissionRefused
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.material_admission import MaterialAdmission
from test_material_catalog import Provider, Context, _CONTRACT


def test_pending_provider_identity_has_one_claim_and_rollback_releases_it():
    catalog = MaterialCatalog("environment")
    first, second = Provider(), Provider()
    registration = catalog.stage("first", 1, (first,), (_CONTRACT,))
    with pytest.raises(UnitAdmissionRefused, match="already registered"):
        catalog.stage("second", 1, (second,), (_CONTRACT,))
    assert catalog.providers() == ()
    registration.rollback()
    result = catalog.stage("second", 1, (second,), (_CONTRACT,)).commit()
    assert len(result) == 1
    assert result[0].owner_activation.plugin_id == "second"
    assert first.effect_calls == second.effect_calls == 0
    with pytest.raises(UnitAdmissionRefused, match="finished"):
        registration.commit()


@pytest.mark.parametrize("during_commit", [False, True])
def test_provider_metadata_callback_cannot_reenter_registration(during_commit):
    catalog = MaterialCatalog("environment")
    attempted = []

    class Reentrant(Provider):
        def describe(self):
            if bool(self.describe_calls) is during_commit:
                attempted.append(True)
                with pytest.raises(UnitAdmissionRefused, match="cannot reenter"):
                    catalog.stage("injected", 2, (Provider(),), (_CONTRACT,))
            return super().describe()

    provider = Reentrant()
    result = catalog.stage("original", 1, (provider,), (_CONTRACT,)).commit()
    assert attempted == [True]
    assert len(result) == len(catalog.providers()) == 1
    assert result[0].owner_activation.plugin_id == "original"
    assert provider.effect_calls == 0


def test_public_admission_metadata_is_detached_from_original_provider_and_owner():
    catalog = MaterialCatalog("environment")
    provider = Provider()
    original = catalog.stage("original", 7, (provider,), (_CONTRACT,)).commit()[0]
    admission = MaterialAdmission(Context(catalog))
    metadata = admission.material_provider_contribution(original.descriptor.id)
    resource = metadata.resource_provider
    assert not hasattr(resource, "provider")
    assert set(resource.__dataclass_fields__) == {
        "owner_activation", "descriptor", "supported_contract_ids"}
    assert resource.owner_activation == original.owner_activation
    assert resource.owner_activation is not original.owner_activation
    assert resource.descriptor is not original.descriptor
    with pytest.raises(FrozenInstanceError):
        resource.descriptor.id = "changed"
    object.__setattr__(resource.owner_activation, "generation", 0)
    object.__setattr__(resource.descriptor, "version", "changed")
    refreshed = admission.material_provider_contribution(original.descriptor.id)
    assert refreshed.resource_provider.owner_activation.generation == 7
    assert refreshed.resource_provider.descriptor.version == "1"
    assert provider.effect_calls == 0
