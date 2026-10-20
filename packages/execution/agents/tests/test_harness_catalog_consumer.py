"""AgentProviders projects declared Harness metadata, never runtime aggregates."""
import pytest

from agent_tools_fixtures.runtime_admission import Provider
from ordessa_execution_agents.harness.providers.registry.errors import (
    CatalogAdmissionRefused,
    CatalogUnavailable,
    CatalogIdentityConflict,
)
from ordessa_execution_agents.harness.providers.registry.contributions import AgentContributionSet
from ordessa_execution_agents.harness.providers.registry.definition_admission import (
    HarnessContributionSet,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    HarnessInstallationObservation,
    harness_registration_snapshot,
)
from ordessa_units.public import unit_services
from ordessa_units.admission.material_admission import material_registration_snapshot
from pacthold.public import Environment, InstallationRecord


class Policy:
    allowed = True

    def admit_object_access(self, principal, obj, permission):
        assert (principal, obj, permission) == (
            "controlled", "runtime-test:agents.runtime", "read"
        )
        return self.allowed

    def admit_invoke(self, *args):
        raise AssertionError("catalog metadata must not invoke providers")


def make_declaration():
    def observe(_installation_ref):
        return HarnessInstallationObservation("present")

    descriptor = HarnessDefinitionDescriptor(
        "brand",
        {"environmentNamespace": "runtime-test", "definitionId": "brand", "revision": "1"},
        "sha256:" + "a" * 64,
        "acp/v1",
        "reviewed-adapter",
        capabilities=("existingChannel",),
    )
    return HarnessDefinitionDeclaration(descriptor, observe)


def make_environment(*, bound=True):
    policy = Policy()
    env = Environment(
        "runtime-test",
        policy=policy,
        principal_scope="controlled",
        resource_extension_snapshot=material_registration_snapshot,
        harness_definition_snapshot=harness_registration_snapshot if bound else None,
    )
    for owner in ("brand", "fixture.plugin"):
        env.install(InstallationRecord(owner, "b" * 64))
        env.enable(owner)
    return env, policy


def test_unit_services_catalog_lists_only_admitted_harness_declarations(monkeypatch):
    env, _ = make_environment()
    declaration = make_declaration()
    legacy = Provider()
    env.stage_activation(
        "fixture.plugin", AgentContributionSet(agent_runtime_providers=(legacy,))
    ).commit()
    stage = env.stage_activation(
        "brand", HarnessContributionSet(harness_definitions=(declaration,))
    )
    catalog = unit_services(env).providers
    # Both retired lookup routes remain available for other consumers, but
    # this catalog projection must never reach them.
    def old_lookup(*_args, **_kwargs):
        raise AssertionError("Harness catalog called the old runtime lookup")

    monkeypatch.setattr(env, "agent_runtime_contributions", old_lookup)
    monkeypatch.setattr(env, "agent_runtime_contribution", old_lookup)
    assert catalog.list() == ()
    stage.commit()
    listed = catalog.list()
    assert len(listed) == 1
    assert listed[0]["descriptor"] == declaration.descriptor.to_dict()
    assert listed[0]["descriptor"]["contractVersion"] == "harness-definition/1"
    assert listed[0]["providerRef"]["providerId"] == "brand"
    assert listed[0]["providerRef"]["contractVersion"] == "agent-runtime/2"
    assert listed[0] == catalog.describe(declaration.descriptor.definition_ref)
    assert catalog.list() == (listed[0],)

    # Returned DTOs are detached data and cannot mutate the admitted declaration.
    listed[0]["descriptor"]["definitionRef"]["revision"] = "forged"
    listed[0]["providerRef"]["generation"] = 999
    current = catalog.describe(declaration.descriptor.definition_ref)
    assert current["descriptor"] == declaration.descriptor.to_dict()
    assert current["providerRef"]["generation"] != 999


def test_catalog_keeps_admission_permission_mutation_and_scope_fences():
    env, policy = make_environment()
    declaration = make_declaration()
    env.activate("brand", HarnessContributionSet(harness_definitions=(declaration,)))
    catalog = unit_services(env).providers
    ref = declaration.descriptor.definition_ref

    policy.allowed = False
    with pytest.raises(CatalogAdmissionRefused):
        catalog.list()
    policy.allowed = True

    foreign = dict(ref)
    foreign["environmentNamespace"] = "other"
    with pytest.raises(CatalogIdentityConflict):
        catalog.describe(foreign)

    object.__setattr__(declaration, "installation_observer", lambda _ref: None)
    with pytest.raises(CatalogAdmissionRefused):
        catalog.describe(ref)


def test_catalog_construction_is_lazy_without_harness_binding():
    env, _ = make_environment(bound=False)
    # Configuration and service composition can exist without opting into
    # Harness admission; providers.list/describe will require the real binding.
    services = unit_services(env)
    assert services.providers is not None
    with pytest.raises(CatalogUnavailable, match="original Harness admission binding required"):
        services.providers.list()
    with pytest.raises(CatalogUnavailable, match="original Harness admission binding required"):
        services.providers.describe(
            {"environmentNamespace": "runtime-test", "definitionId": "brand", "revision": "1"}
        )


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"environmentNamespace": "runtime-test", "definitionId": "brand"},
        {"environmentNamespace": "runtime-test", "definitionId": "brand", "revision": "1", "owner": "fake"},
        {"environmentNamespace": "", "definitionId": "brand", "revision": "1"},
        {"environmentNamespace": "runtime-test", "definitionId": 3, "revision": "1"},
    ],
)
def test_describe_rejects_invalid_definition_reference_shapes(reference):
    env, _ = make_environment()
    catalog = unit_services(env).providers
    with pytest.raises(CatalogIdentityConflict):
        catalog.describe(reference)
