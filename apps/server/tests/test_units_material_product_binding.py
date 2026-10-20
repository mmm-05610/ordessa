"""Product factories select Units admission on their original Environment."""
from ordessa_units.errors import UnitAdmissionRefused
from ordessa_units.errors import UnitGuaranteeUnavailable
from dataclasses import dataclass
from typing import ClassVar

import pytest

from ordessa_units.admission.material_admission import (
    MaterialAdmission,
)
from ordessa_server.composition.agent_tools.composition import AgentToolsDeployment
from ordessa_server.composition.product_unit_admission import create_owned_product_unit_admission
from ordessa_server.composition.runtime import DataRootOwner
from .test_unit_governance_product import TestFingerprint
from ordessa_units.admission.generation import reserve_next_generation
from types import SimpleNamespace
from ordessa_units.definitions.materials import ResourceProviderDescriptor, ReconcileSupport


@dataclass(frozen=True)
class Item:
    contract_id: ClassVar[str] = "product.material-binding@1"


class Provider:
    supported_contract_ids = frozenset({Item.contract_id})

    def describe(self):
        return ResourceProviderDescriptor("product.material-binding", "Controlled", "1",
                                          ReconcileSupport.SUPPORTED)

    def acquire(self, *args):
        raise AssertionError("metadata reads cannot acquire a resource")

    release = reconcile = acquire


def activate(context, provider):
    generation=reserve_next_generation(context.store_port,context.environment_id,'test.material',
        fingerprint_port=context.fingerprint_port)
    registration=context.material_catalog.stage('test.material',generation,(provider,),(Item.contract_id,))
    return registration.commit()[0]


@pytest.mark.parametrize("factory", ["product", "agent-tools"])
def test_original_product_environment_registers_resources_with_explicit_units_owner(tmp_path, factory):
    root = tmp_path / "data"
    owner = DataRootOwner(root)
    owner.acquire()
    environment = None
    fingerprint = TestFingerprint()
    try:
        path = root / "state" / "core.sqlite"
        if factory == "product":
            environment = create_owned_product_unit_admission(path, owner,
                fingerprint_port=fingerprint, agent_owner_inputs=None,
                native_channels_selected=False)
        else:
            environment = AgentToolsDeployment(fingerprint_port=fingerprint).owned_environment_factory(path, owner)
        catalog, store = environment.material_catalog, environment.store_port
        provider = Provider()
        receipt = activate(environment, provider)
        assert environment.material_catalog is catalog and environment.store_port is store
        assert catalog.provider("product.material-binding").descriptor == provider.describe()
        admission = MaterialAdmission(environment)
        assert admission._context is environment
        assert not hasattr(environment, "resource_provider_contributions")
        assert not hasattr(environment, "material_provider_contributions")
        if factory == "product":
            metadata = admission.resource_provider_contributions()
            assert len(metadata) == 1 and metadata[0].owner_activation == receipt.owner_activation
            assert admission.material_provider_contributions() == ()
            catalog.drain(receipt.owner_activation.plugin_id,receipt.owner_activation.generation)
            assert admission.resource_provider_contributions() == ()
        else:
            # Binding a validator grants no new agents.resources read permission.
            with pytest.raises(UnitAdmissionRefused, match="discovery refused"):
                admission.resource_provider_contributions()
        if factory != 'product':
            catalog.drain(receipt.owner_activation.plugin_id,receipt.owner_activation.generation)
        catalog.retire(receipt.owner_activation.plugin_id,receipt.owner_activation.generation)
    finally:
        if environment is not None:
            environment.close()
        owner.release()


def test_unbound_context_refuses_resource_discovery():
    with pytest.raises(UnitGuaranteeUnavailable,match='binding unavailable'):
        MaterialAdmission(SimpleNamespace(environment_namespace='unbound-product'))
