"""Integrated Agent Tools/Jev admission on the original core, without native effects."""
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError

import pytest

from ordessa_execution_agents import public
from ordessa_execution_agents.units.admission import invocation
from ordessa_execution_agents.units.configuration import offers as read_configuration
from ordessa_execution_agents.harness.definitions.runtime_providers import PURE_READ_METHODS, RUNTIME_METHODS
from pacthold.public import Environment, InstallationRecord


ENVIRONMENT = "integrated-agent-capabilities"
DEFINITION = {
    "environmentNamespace": ENVIRONMENT,
    "definitionId": "fixture.runtime",
    "revision": "1",
}


class ReadPolicy:
    def admit_object_access(self, principal, target, mode):
        return True

    def admit_invoke(self, *args):
        return True


def forbidden_effect(*args, **kwargs):
    raise AssertionError("admission and configuration offers must not invoke native effects")


class IntegratedProvider:
    def __init__(self):
        self.descriptor = public.RuntimeProviderDescriptor(
            "fixture.runtime", public.RUNTIME_PROVIDER_VERSION, DEFINITION,
            "sha256:" + "a" * 64,
            ("assess_configuration",) + PURE_READ_METHODS,
            public.PURE_READ_VERSION,
        )
        self.configuration_routes = (public.ConfigurationRoute(
            "fixture.configuration", "schema/1", (DEFINITION,),
            ("value",), ("fixture.field",),
        ),)

    def describe_configuration_offers(self, definition_ref, context):
        assert isinstance(context, public.OwnerReadContext)
        assert definition_ref == self.descriptor.definition_ref
        return public.OwnerConfigurationOfferBatch(
            context.provider_ref, definition_ref, definition_ref["revision"],
            self.descriptor.implementation_digest, (), False,
            public.PURE_READ_VERSION, ("application",),
        )

    def assess_configuration_proposal(self, proposal, context):
        raise AssertionError("offer discovery must not assess a proposal")


for _method in RUNTIME_METHODS:
    setattr(IntegratedProvider, _method, forbidden_effect)


@pytest.fixture
def admitted_environment():
    environment = Environment(ENVIRONMENT, policy=ReadPolicy())
    try:
        environment.install(InstallationRecord("fixture.plugin", "a" * 64))
        environment.enable("fixture.plugin")
        provider = IntegratedProvider()
        environment.activate("fixture.plugin", public.AgentContributionSet(
            agent_runtime_providers=(provider,),
        ))
        yield environment, provider
    finally:
        environment.close()


def test_one_admitted_provider_retains_configuration_routes_and_pure_read(admitted_environment):
    environment, provider = admitted_environment
    services = public.agent_services(environment)
    metadata = services.providers.configuration_describe(DEFINITION)
    offers = services.configuration_offers.describe_configuration_offers(DEFINITION)
    assert services.providers.configuration_list() == (metadata,)
    assert metadata["recognizedDefinitions"] == [DEFINITION]
    assert metadata["providerRef"] == dict(offers.owner_ref)
    assert offers.complete is False
    assert offers.unknown_items == ("application",)
    admitted = environment.agent_runtime_contribution(DEFINITION)
    assert admitted.provider is provider
    assert admitted.descriptor.pure_read_contract_version == public.PURE_READ_VERSION
    assert admitted.descriptor.to_dict()["pureReadContractVersion"] == public.PURE_READ_VERSION


@pytest.mark.parametrize("bad_routes", [[], (object(),), None])
def test_illegal_configuration_mount_refused_with_valid_pure_read(bad_routes):
    provider = IntegratedProvider()
    provider.configuration_routes = bad_routes
    with pytest.raises(CoreDTOError):
        public.AgentContributionSet(agent_runtime_providers=(provider,))


@pytest.mark.parametrize("method", PURE_READ_METHODS)
def test_noncallable_pure_read_refused_with_valid_configuration_routes(method):
    provider = IntegratedProvider()
    setattr(provider, method, None)
    with pytest.raises(CoreDTOError):
        public.AgentContributionSet(agent_runtime_providers=(provider,))


@pytest.mark.parametrize("module,names", [
    (invocation, ("InvocationIssuer", "InvocationGrant", "InvocationAuthorityPort",
                  "InvocationCurrentState", "InvocationCurrentStatePort")),
    (read_configuration, ("OwnerReadContext", "OwnerProposalInput",
                          "OwnerConfigurationOfferBatch", "OwnerProposalAssessment")),
])
def test_public_exports_original_authorization_and_read_classes(module, names):
    for name in names:
        assert name in public.__all__
        assert getattr(public, name) is getattr(module, name)
    assert public.PURE_READ_VERSION == read_configuration.PURE_READ_VERSION


def test_agent_services_keeps_one_composition_and_refuses_replacement(admitted_environment):
    environment, _ = admitted_environment
    evidence_port = object()
    services = public.agent_services(environment, node_evidence_port=evidence_port)
    assert public.agent_services(environment) is services
    assert public.agent_services(environment, node_evidence_port=evidence_port) is services
    for name in ("providers", "lifecycle", "managed_inputs", "operations", "material_operations"):
        assert getattr(services, name)._environment is environment
    with pytest.raises(ValueError, match="composed once"):
        public.agent_services(environment, node_evidence_port=object())
    assert public.agent_services(environment) is services
