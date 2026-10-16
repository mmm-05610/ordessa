"""Public discovery against the sole registry; no native readiness evidence."""
from dataclasses import replace

import pytest

from ordessa_execution_api.environment import AdmissionRefusedError, IdentityMismatchError
from ordessa_units.admission.material_admission import material_registration_snapshot
from ordessa_units.public import unit_services, AGENT_MANAGEMENT_CONTRACT_VERSION
from ordessa_execution_agents.harness.providers.registry.definition_admission import (
    HarnessContributionSet,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
    harness_registration_snapshot,
)
from ordessa_system_access_bindings import agent_core_methods
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment, InstallationRecord
from server_plugin_api import WireError


@pytest.fixture
def discovery(tmp_path, request):
    policy = type("Policy", (), {"allowed": True,
        "admit_object_access": lambda self, principal, target, mode: self.allowed,
        "admit_invoke": lambda self, *args: self.allowed})()
    store = SqliteStorePort(tmp_path / "provider-discovery.sqlite")
    env = Environment("runtime-test", store=store, policy=policy,
        principal_scope="controlled",
        resource_extension_snapshot=material_registration_snapshot,
        harness_definition_snapshot=harness_registration_snapshot)
    request.addfinalizer(store.close)
    request.addfinalizer(env.close)
    env.install(InstallationRecord("fixture.plugin", "a" * 64))
    env.enable("fixture.plugin")

    def observe(_installation_ref):
        raise AssertionError("catalog metadata must not probe native installation")

    provider = HarnessDefinitionDeclaration(HarnessDefinitionDescriptor(
        "fixture.runtime",
        {"environmentNamespace": "runtime-test", "definitionId": "fixture", "revision": "1"},
        "sha256:" + "a" * 64, "acp/v1", "reviewed-adapter"), observe)
    stage = env.stage_activation("fixture.plugin",
        HarnessContributionSet(harness_definitions=(provider,)))
    return env, policy, provider, stage, unit_services(env).providers


def test_staged_excluded_active_reference_is_host_owned(discovery):
    env, _, provider, stage, catalog = discovery
    assert catalog.list() == ()
    receipt = stage.commit()
    result = catalog.list()
    assert len(result) == 1
    assert result[0] == catalog.describe(provider.descriptor.definition_ref)
    assert result[0]["descriptor"] == provider.descriptor.to_dict()
    assert result[0]["providerRef"]["ownerActivationRef"]["generation"] == receipt.activation.generation
    assert "ready" not in result[0] and "installation" not in result[0]
    assert env.registry_snapshot.agent_runtime_provider_ids == ("fixture.runtime",)


def test_drain_excluded_and_retire_then_reactivate_uses_new_generation(discovery):
    env, _, provider, stage, catalog = discovery
    receipt = stage.commit()
    old = catalog.list()[0]["providerRef"]
    env.drain(receipt.activation)
    assert catalog.list() == ()
    with pytest.raises(AdmissionRefusedError): catalog.describe(provider.descriptor.definition_ref)
    env.retire(receipt.activation)
    assert env._store.unresolved_provider_usages(
        env.environment_id, receipt.activation.plugin_id, receipt.activation.generation) == ()
    env.activate("fixture.plugin", HarnessContributionSet(harness_definitions=(make_declaration(),)))
    assert catalog.list()[0]["providerRef"]["generation"] > old["generation"]


def make_declaration():
    def observe(_installation_ref):
        raise AssertionError("catalog metadata must not probe native installation")
    return HarnessDefinitionDeclaration(HarnessDefinitionDescriptor(
        "fixture.runtime",
        {"environmentNamespace": "runtime-test", "definitionId": "fixture", "revision": "1"},
        "sha256:" + "a" * 64, "acp/v1", "reviewed-adapter"), observe)


def test_permission_checked_even_when_registry_empty(discovery):
    _, policy, _, _, catalog = discovery
    policy.allowed = False
    with pytest.raises(AdmissionRefusedError): catalog.list()


@pytest.mark.parametrize("mutation", ["descriptor", "method", "owner"])
def test_active_mutation_refused_without_native_invocation(discovery, mutation):
    _, _, provider, stage, catalog = discovery
    stage.commit()
    if mutation == "descriptor":
        object.__setattr__(provider, "descriptor", replace(provider.descriptor,
            implementation_digest="sha256:" + "b" * 64))
    elif mutation == "method":
        object.__setattr__(provider, "prepare", None)
    else:
        object.__setattr__(provider, "owner", "forged")
    with pytest.raises(AdmissionRefusedError): catalog.list()


def test_detached_views_cannot_change_registry(discovery):
    _, _, provider, stage, catalog = discovery
    stage.commit()
    result = catalog.list()[0]
    result["descriptor"]["definitionRef"]["revision"] = "forged"
    result["providerRef"]["ownerActivationRef"]["generation"] = 999
    current = catalog.describe(provider.descriptor.definition_ref)
    assert current["descriptor"]["definitionRef"]["revision"] == "1"
    assert current["providerRef"]["ownerActivationRef"]["generation"] != 999


@pytest.mark.parametrize("reference", [None, {}, {"environmentNamespace": "runtime-test", "definitionId": "fixture", "revision": "1", "owner": "fake"}])
def test_incomplete_or_author_identity_reference_refused(discovery, reference):
    with pytest.raises(IdentityMismatchError): discovery[4].describe(reference)


def test_cross_environment_refused(discovery):
    ref = dict(discovery[2].descriptor.definition_ref)
    ref["environmentNamespace"] = "other"
    with pytest.raises(IdentityMismatchError): discovery[4].describe(ref)


def methods(env, version=AGENT_MANAGEMENT_CONTRACT_VERSION):
    return {item.method_id: item.handler for item in agent_core_methods(lambda: env, contract_version=version)}


def test_explicit_v2_wire_discovery_and_honest_capabilities(discovery):
    env, _, provider, stage, _ = discovery
    handlers = methods(env)
    assert handlers["agents.providers.list"]({}) == {"providers": []}
    stage.commit()
    listed = handlers["agents.providers.list"]({})["providers"]
    assert handlers["agents.providers.describe"]({"definitionRef": dict(provider.descriptor.definition_ref)}) == listed[0]
    capabilities = handlers["agents.capabilities"]({})
    assert {"agents.providers.list", "agents.providers.describe"} <= set(capabilities["supportedMethods"])
    assert "agents.nodes.prepare" not in capabilities["supportedMethods"]
    assert "agents.providers.list" not in methods(env, "agent-assembly/1")


def test_wire_invalid_shape_and_permission_refusal(discovery):
    env, policy, _, stage, _ = discovery
    stage.commit()
    handlers = methods(env)
    with pytest.raises(WireError) as error:
        handlers["agents.providers.describe"]({"definitionRef": {}})
    assert error.value.family == "INVALID_REQUEST"
    policy.allowed = False
    with pytest.raises(WireError) as error:
        handlers["agents.providers.list"]({})
    assert error.value.family == "FORBIDDEN"
