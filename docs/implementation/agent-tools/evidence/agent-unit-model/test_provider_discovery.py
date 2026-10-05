"""Public discovery against the sole registry; no native readiness evidence."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "products/agent-tools/tests/integration"))
from test_runtime_admission import Provider, installed

from ordessa_environment_api import AdmissionRefusedError, IdentityMismatchError
from pacthold.agents.public import agent_services, AGENT_MANAGEMENT_CONTRACT_VERSION
from pacthold.agents.runtime import AgentContributionSet
from ordessa_server.agent_core_wire import agent_core_methods
from server_plugin_api import WireError


@pytest.fixture
def discovery():
    env, policy = installed()
    provider = Provider()
    stage = env.stage_activation("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    return env, policy, provider, stage, agent_services(env).providers


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
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    assert catalog.list()[0]["providerRef"]["generation"] > old["generation"]


def test_permission_checked_even_when_registry_empty(discovery):
    _, policy, _, _, catalog = discovery
    policy.allowed = False
    with pytest.raises(AdmissionRefusedError): catalog.list()


@pytest.mark.parametrize("mutation", ["descriptor", "method", "owner"])
def test_active_mutation_refused_without_native_invocation(discovery, mutation):
    _, _, provider, stage, catalog = discovery
    stage.commit()
    if mutation == "descriptor": provider.descriptor = replace(provider.descriptor, implementation_digest="sha256:" + "b" * 64)
    elif mutation == "method": provider.prepare = None
    else: provider.owner = "forged"
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
