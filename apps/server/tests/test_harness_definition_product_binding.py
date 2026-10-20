"""Product factories bind original Harness admission, without Unit dispatch."""
from ordessa_execution_agents.harness.providers.registry.errors import CatalogAdmissionRefused
import pytest
from ordessa_execution_agents.harness.providers.registry import (
    HarnessAdmission, HarnessDefinitionDescriptor,
    HarnessDefinitionDeclaration, HarnessInstallationObservation,
    harness_registration_snapshot,
)
from ordessa_server.composition.agent_tools.composition import AgentToolsDeployment
from ordessa_server.composition.product_unit_admission import create_owned_product_unit_admission
from ordessa_server.composition.runtime import DataRootOwner
from test_unit_governance_product import TestFingerprint
from ordessa_units.admission.generation import reserve_next_generation


@pytest.mark.parametrize('factory', ['product', 'agent-tools'])
def test_product_factory_binds_original_declaration_owner_without_runtime_aggregate(tmp_path, factory):
    root = tmp_path/'data'
    owner = DataRootOwner(root)
    owner.acquire()
    environment = None
    fingerprint = TestFingerprint()
    calls = []
    try:
        path = root/'state'/'core.sqlite'
        if factory == 'product':
            environment = create_owned_product_unit_admission(path, owner,
                fingerprint_port=fingerprint, agent_owner_inputs=None, native_channels_selected=False)
        else:
            environment = AgentToolsDeployment(fingerprint_port=fingerprint).owned_environment_factory(path, owner)
        catalog, store = environment.harness_catalog, environment.store_port
        definition = {'environmentNamespace':environment.environment_id,'definitionId':'controlled-brand','revision':'1'}
        descriptor = HarnessDefinitionDescriptor('controlled-brand', definition,
            'sha256:'+'a'*64, 'acp/v1', 'controlled-adapter')
        def inspect(ref):
            calls.append(dict(ref))
            return HarnessInstallationObservation('unknown')
        declaration = HarnessDefinitionDeclaration(descriptor, inspect)
        generation=reserve_next_generation(store,environment.environment_id,'controlled-brand',fingerprint_port=fingerprint)
        admitted_batch=catalog.stage('controlled-brand',generation,'controlled-brand','b'*64,(declaration,)).commit()
        assert environment.harness_catalog is catalog and environment.store_port is store
        assert admitted_batch[0].descriptor == descriptor
        assert calls == []
        admission = HarnessAdmission(environment)
        assert admission._catalog is catalog
        if factory == 'product':
            assert not hasattr(environment,"agent_runtime_contributions")
            admitted = admission.describe(definition)
            assert admitted.owner_activation == admitted_batch[0].owner_activation
            assert admission.list() == (admitted,) and calls == []
            observed = admission.inspect_installation(definition)
            assert observed['installationState'] == 'unknown' and observed['runtimeReady'] == 'unknown'
            assert calls == [{'environmentNamespace':environment.environment_id,
                'installationId':'controlled-brand','sourceRevision':'b'*64}]
            catalog.drain('controlled-brand',generation)
            assert admission.list() == ()
        else:
            # Validator wiring does not grant the existing ACL's metadata read.
            with pytest.raises(CatalogAdmissionRefused):
                admission.list()
        if factory != 'product':
            catalog.drain('controlled-brand',generation)
        catalog.retire('controlled-brand',generation)
    finally:
        if environment is not None:
            environment.close()
        owner.release()
