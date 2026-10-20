"""Retained registration guarantees on the actual HarnessCatalog owner."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, RLock

import pytest

from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from ordessa_execution_agents.harness.providers.registry import (
    CatalogAdmissionRefused,
    HarnessAdmission,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
    harness_registration_snapshot,
)
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.persistence.sqlite.store import SqliteUnitStore


class _Policy:
    def admit_object_access(self, *_args):
        return True

    def admit_invoke(self, *_args):
        raise AssertionError("Harness metadata admission must not invoke providers")


def _declaration(*, provider="fixture", definition="fixture", revision="1"):
    descriptor = HarnessDefinitionDescriptor(
        provider,
        {
            "environmentNamespace": "catalog-regression",
            "definitionId": definition,
            "revision": revision,
        },
        "sha256:" + "a" * 64,
        "fixture/protocol",
        "fixture-adapter/1",
    )
    return HarnessDefinitionDeclaration(
        descriptor,
        lambda _installation: HarnessInstallationObservation("unknown"),
    )


def _owner(tmp_path):
    policy = _Policy()
    lock = RLock()
    store = SqliteUnitStore(tmp_path / "catalog-owner.sqlite")
    catalog = HarnessCatalog(
        "catalog-regression",
        policy=policy,
        principal_scope="catalog-test",
        admission_lock=lock,
        retirement_guard=lambda owner_id, generation: context.harness_provider_retirement_guard(
            owner_id, generation
        ),
    )
    materials = MaterialCatalog("catalog-regression", admission_lock=lock)
    context = UnitAdmissionContext(
        "catalog-regression",
        store=store,
        policy=policy,
        fingerprint_port=object(),
        harness_catalog=catalog,
        material_catalog=materials,
        principal_scope="catalog-test",
        admission_lock=lock,
    )
    return context, catalog, materials, store


def _stage(catalog, declaration, *, owner="host-brand", generation=4):
    return catalog.stage(
        owner,
        generation,
        "installation-4",
        "b" * 64,
        (declaration,),
    )


def _close(context, catalog, materials, store):
    context.close()
    catalog.close()
    materials.close()
    store.close()


@pytest.mark.parametrize("field", ["descriptor", "installation_observer"])
def test_admitted_declaration_drift_is_refused_and_host_metadata_is_detached(tmp_path, field):
    context, catalog, materials, store = _owner(tmp_path)
    declaration = _declaration()
    definition_ref = declaration.descriptor.definition_ref
    registration = _stage(catalog, declaration)
    admitted, = registration.commit()

    # Owner identity comes from the host registration call, not from fields on
    # the Harness declaration. Returned identity is immutable owner metadata.
    assert admitted.owner_activation == HarnessActivationRef(
        "catalog-regression", "host-brand", 4
    )
    provider_ref = admitted.provider_ref
    assert provider_ref["ownerActivationRef"]["pluginId"] == "host-brand"
    assert provider_ref["generation"] == 4
    with pytest.raises(TypeError):
        provider_ref["generation"] = 99
    with pytest.raises(TypeError):
        provider_ref["ownerActivationRef"]["generation"] = 99

    other = _declaration(provider="changed", definition="changed")
    object.__setattr__(declaration, field, getattr(other, field))
    with pytest.raises(CatalogAdmissionRefused, match="changed after admission"):
        HarnessAdmission(context).describe(definition_ref)

    catalog.drain("host-brand", 4)
    catalog.retire("host-brand", 4)
    _close(context, catalog, materials, store)


def test_declaration_cannot_supply_host_owner_or_generation(tmp_path):
    context, catalog, materials, store = _owner(tmp_path)
    declaration = _declaration()
    object.__setattr__(declaration, "owner_activation", HarnessActivationRef(
        "catalog-regression", "forged-owner", 900
    ))
    with pytest.raises(CoreDTOError):
        _stage(catalog, declaration)
    assert HarnessAdmission(context).list() == ()

    clean = _declaration()
    admitted, = _stage(catalog, clean).commit()
    assert admitted.owner_activation == HarnessActivationRef(
        "catalog-regression", "host-brand", 4
    )
    catalog.drain("host-brand", 4)
    catalog.retire("host-brand", 4)
    _close(context, catalog, materials, store)


def test_concurrent_staging_has_one_claim_for_same_definition_route(tmp_path):
    context, catalog, materials, store = _owner(tmp_path)
    barrier = Barrier(2)

    def stage_as(owner):
        barrier.wait(timeout=3)
        try:
            return _stage(catalog, _declaration(), owner=owner)
        except CatalogAdmissionRefused:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(stage_as, ("host-a", "host-b")))

    claims = tuple(result for result in results if result is not None)
    assert len(claims) == 1
    claims[0].rollback()
    assert HarnessAdmission(context).list() == ()
    committed, = _stage(catalog, _declaration(), owner="host-c").commit()
    assert committed.descriptor.provider_id == "fixture"
    catalog.drain("host-c", 4)
    catalog.retire("host-c", 4)
    _close(context, catalog, materials, store)


def test_retiring_old_generation_does_not_remove_new_generation_route(tmp_path):
    context, catalog, materials, store = _owner(tmp_path)
    admission = HarnessAdmission(context)
    old_declaration = _declaration()
    old, = _stage(catalog, old_declaration, generation=4).commit()
    catalog.drain("host-brand", 4)
    with pytest.raises(CatalogAdmissionRefused):
        _stage(catalog, _declaration(), generation=5)
    catalog.retire("host-brand", 4)

    new_declaration = _declaration()
    new, = _stage(catalog, new_declaration, generation=5).commit()
    assert new.owner_activation.generation == 5
    assert admission.describe(new_declaration.descriptor.definition_ref) == new
    with pytest.raises(CatalogAdmissionRefused):
        catalog.retire("host-brand", 4)
    assert admission.describe(new_declaration.descriptor.definition_ref) == new
    assert old.owner_activation.generation == 4

    catalog.drain("host-brand", 5)
    catalog.retire("host-brand", 5)
    _close(context, catalog, materials, store)


def test_untrusted_descriptor_getter_cannot_reenter_catalog_staging(tmp_path):
    context, catalog, materials, store = _owner(tmp_path)
    calls = []

    class ReentrantDeclaration:
        @property
        def descriptor(self):
            calls.append("descriptor")
            _stage(catalog, _declaration(), owner="nested")
            return _declaration().descriptor

        @property
        def installation_observer(self):
            calls.append("observer")
            return lambda _installation: HarnessInstallationObservation("unknown")

    with pytest.raises(CoreDTOError):
        catalog.stage(
            "outer", 4, "installation-4", "b" * 64, (ReentrantDeclaration(),)
        )
    assert calls == []
    assert HarnessAdmission(context).list() == ()

    admitted, = _stage(catalog, _declaration(), owner="valid", generation=5).commit()
    assert admitted.owner_activation.plugin_id == "valid"
    catalog.drain("valid", 5)
    catalog.retire("valid", 5)
    _close(context, catalog, materials, store)
