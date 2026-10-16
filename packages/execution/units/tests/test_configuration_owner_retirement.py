"""Metadata is not a configuration executor; no legacy lookup or native IO."""
from types import SimpleNamespace

import pytest

from ordessa_execution_api.environment import AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment.identity import ParticipantInstanceRef
from ordessa_execution_agents.harness.providers.registry import (
    HarnessCatalog, HarnessDefinitionDescriptor, HarnessDefinitionDeclaration,
    HarnessInstallationObservation,
)
from ordessa_execution_agents.harness.providers.registry.catalog import AgentProviders
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.admission.invocation import InvocationIssuer
from ordessa_units.channels.reservations import ManagedInputReservations
from ordessa_units.configuration.service import AgentConfiguration
from ordessa_units.configuration.offers import AgentConfigurationOffers
from ordessa_units.persistence.sqlite.store import SqliteUnitStore


class Policy:
    allowed = True
    def admit_object_access(self, *args): return self.allowed
    def admit_invoke(self, *args): return self.allowed


class Authority:
    issuer_ref = {'environmentNamespace': 'env', 'issuerId': 'controlled-no-grants'}
    def authorize(self, *args): raise AssertionError('metadata must not authorize')
    def revalidate(self, *args): raise AssertionError('metadata must not revalidate a grant')


class CurrentState:
    def inspect(self, *args): raise AssertionError('metadata must not inspect an execution target')


@pytest.fixture
def binding(tmp_path):
    store = SqliteUnitStore(tmp_path / 'original.sqlite')
    policy = Policy()
    catalog = HarnessCatalog('env', policy=policy, principal_scope='principal')
    descriptor = HarnessDefinitionDescriptor('controlled', {
        'environmentNamespace': 'env', 'definitionId': 'controlled', 'revision': '1'},
        'sha256:' + 'a' * 64, 'acp/v1', 'controlled-test')
    declaration = HarnessDefinitionDeclaration(descriptor,
        lambda ref: HarnessInstallationObservation('unknown'))
    admitted, = catalog.stage('controlled', 1, 'controlled', 'b' * 64, (declaration,)).commit()
    context = UnitAdmissionContext('env', store=store, policy=policy, fingerprint_port=None,
        harness_catalog=catalog, material_catalog=MaterialCatalog('env'), principal_scope='principal')
    node = {'binding': {'harnessDefinitionRef': descriptor.definition_ref,
        'harnessProviderRef': admitted.provider_ref,
        'harnessUnitRef': {'environmentNamespace': 'env', 'unitId': 'original',
            'ownerProviderRef': admitted.provider_ref, 'sourceRevision': 'sha256:' + 'c' * 64}}}
    nodes = SimpleNamespace(read=lambda ref: node)
    yield context, policy, descriptor, admitted, nodes, node
    store.close()


def test_metadata_does_not_advertise_full_manifest_configuration_with_real_issuer(binding):
    context, _, descriptor, _, nodes, _ = binding
    issuer = InvocationIssuer(context.store_port, Authority(), CurrentState())
    try:
        configuration = AgentConfiguration(context, nodes, invocation_issuer=issuer)
        assert configuration.capabilities() == {'configurationManagement': False}
        with pytest.raises(GuaranteeUnavailableError, match='manifest configuration owner'):
            configuration.describe(ParticipantInstanceRef('env', 'original-node', 1))
        with context.store_port.transaction() as connection:
            assert connection.execute('SELECT COUNT(*) FROM env_requests').fetchone()[0] == 0
    finally:
        issuer.close()


def test_missing_offer_compiler_and_configuration_catalog_are_explicit(binding):
    context, _, descriptor, _, _, _ = binding
    providers = AgentProviders(context)
    assert providers.describe(descriptor.definition_ref)['descriptor']['contractVersion'] == 'harness-definition/1'
    with pytest.raises(GuaranteeUnavailableError, match='compiler owner'):
        AgentConfigurationOffers(context).describe_configuration_offers(descriptor.definition_ref)
    with pytest.raises(GuaranteeUnavailableError, match='definition owner'):
        providers.configuration_list()
    with pytest.raises(GuaranteeUnavailableError, match='definition owner'):
        providers.configuration_describe(descriptor.definition_ref)


def test_configuration_read_still_checks_original_node_permission(binding):
    context, policy, _, _, nodes, _ = binding
    policy.allowed = False
    with pytest.raises(AdmissionRefusedError, match='Node configuration access'):
        AgentConfiguration(context, nodes).inspect(ParticipantInstanceRef('env', 'original-node', 1))


def test_managed_input_pin_check_uses_catalog_and_rejects_changed_original_pin(binding):
    context, _, _, admitted, nodes, node = binding
    inputs = ManagedInputReservations(context, nodes)
    request = RequestKey('env', 'principal', 'original-query')
    identity = {'nodeRef': {'environmentNamespace': 'env', 'instanceId': 'original-node', 'generation': 1},
        'unitRef': node['binding']['harnessUnitRef'], 'providerRef': admitted.provider_ref}
    assert inputs._first_publication_permission(request, identity) is None
    identity['providerRef'] = {**dict(admitted.provider_ref), 'generation': 2}
    with pytest.raises(AdmissionRefusedError, match='Unit/provider unavailable'):
        inputs._first_publication_permission(request, identity)
