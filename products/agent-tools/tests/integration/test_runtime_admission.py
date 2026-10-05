"""Existing Environment registration authority, controlled provider contracts.

These are admission tests, not native process or product readiness evidence.
"""
from dataclasses import dataclass

import pytest

from ordessa_environment_api import AdmissionRefusedError, IdentityMismatchError
from pacthold.public import Environment, InstallationRecord
from pacthold.core.registration import CoreRegistry
from pacthold.core.errors import CoreDTOError, RegistrationConflictError
from pacthold.agents.runtime import AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS


class Policy:
    allowed = True
    def admit_object_access(self, principal, target, mode): return self.allowed
    def admit_invoke(self, *args): return self.allowed


def descriptor(provider_id="fixture.runtime", definition_id="fixture", environment="runtime-test"):
    return RuntimeProviderDescriptor(provider_id, RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": environment, "definitionId": definition_id, "revision": "1"},
        "sha256:" + "a" * 64)


class Provider:
    def __init__(self, value=None): self.descriptor = value or descriptor()


for name in RUNTIME_METHODS:
    setattr(Provider, name, lambda *args, **kwargs: None)


def installed(owner="fixture.plugin"):
    policy = Policy()
    env = Environment("runtime-test", policy=policy)
    env.install(InstallationRecord(owner, "a" * 64))
    env.enable(owner)
    return env, policy


def test_staged_not_visible_commit_has_host_activation_not_author():
    env, _ = installed()
    provider = Provider()
    stage = env.stage_activation("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    with pytest.raises(AdmissionRefusedError):
        env.agent_runtime_contribution(provider.descriptor.definition_ref)
    receipt = stage.commit()
    admitted = env.agent_runtime_contribution(provider.descriptor.definition_ref)
    assert admitted.owner_activation == receipt.activation
    assert admitted.provider is provider
    assert admitted.provider_ref["generation"] == receipt.activation.generation
    assert env.registry_snapshot.agent_runtime_provider_ids == ("fixture.runtime",)
    assert env.registry_snapshot.execution_provider_ids == ()
    with pytest.raises(TypeError):
        admitted.provider_ref["generation"] = 9


@pytest.mark.parametrize("name", ["owner", "owner_activation", "generation"])
def test_author_cannot_claim_host_identity(name):
    provider = Provider()
    setattr(provider, name, "fake")
    with pytest.raises(CoreDTOError): AgentContributionSet(agent_runtime_providers=(provider,))


def test_descriptor_copied_and_definition_mutation_refused():
    source = {"environmentNamespace": "runtime-test", "definitionId": "fixture", "revision": "1"}
    value = RuntimeProviderDescriptor("fixture.runtime", RUNTIME_PROVIDER_VERSION, source, "sha256:" + "a" * 64)
    source["revision"] = "wrong"
    assert value.definition_ref["revision"] == "1"
    with pytest.raises(TypeError): value.definition_ref["revision"] = "wrong"


@pytest.mark.parametrize("provider_id,definition_id", [("fixture.runtime", "different"), ("different.runtime", "fixture")])
def test_same_registry_rejects_duplicate_id_or_route_including_staged(provider_id, definition_id):
    registry = CoreRegistry()
    pending = registry.stage("first", AgentContributionSet(agent_runtime_providers=(Provider(),)))
    candidate = Provider(descriptor(provider_id, definition_id))
    with pytest.raises(RegistrationConflictError):
        registry.stage("second", AgentContributionSet(agent_runtime_providers=(candidate,)))
    registry.rollback(pending)
    replacement = registry.stage("second", AgentContributionSet(agent_runtime_providers=(candidate,)))
    registry.commit(replacement)
    registry.unregister("second")
    assert registry.snapshot().agent_runtime_provider_ids == ()


def test_mutation_before_commit_does_not_partially_publish_other_categories():
    @dataclass(frozen=True)
    class Contract:
        contract_id = "fixture.contract@1"
    registry = CoreRegistry()
    provider = Provider()
    batch = registry.stage("fixture", AgentContributionSet(contracts=(Contract,), agent_runtime_providers=(provider,)))
    provider.descriptor = descriptor("different", "different")
    with pytest.raises(CoreDTOError): registry.commit(batch)
    assert registry.snapshot().contract_ids == ()
    assert registry.snapshot().agent_runtime_provider_ids == ()
    registry.rollback(batch)


@pytest.mark.parametrize("mutate", ["descriptor", "method", "owner"])
def test_payload_changes_after_publication_are_refused(mutate):
    env, _ = installed()
    provider = Provider()
    original = provider.descriptor.definition_ref
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    if mutate == "descriptor": provider.descriptor = descriptor("different", "different")
    if mutate == "method": provider.prepare = None
    if mutate == "owner": provider.owner = "fake"
    with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(original)


def test_drain_revokes_new_runtime_discovery_and_old_generation_not_reused():
    env, _ = installed()
    provider = Provider()
    receipt = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    admitted = env.agent_runtime_contribution(provider.descriptor.definition_ref)
    env.drain(receipt.activation)
    with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(provider.descriptor.definition_ref)
    env.retire(receipt.activation)
    replacement = Provider()
    updated = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(replacement,)))
    current = env.agent_runtime_contribution(replacement.descriptor.definition_ref)
    assert current.owner_activation.generation > admitted.owner_activation.generation
    assert current.owner_activation == updated.activation
    assert current.provider is replacement


def test_cross_environment_and_current_permission_refused():
    env, policy = installed()
    with pytest.raises(IdentityMismatchError):
        env.stage_activation("fixture.plugin", AgentContributionSet(agent_runtime_providers=(Provider(descriptor(environment="other-env")),)))
    provider = Provider()
    env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    policy.allowed = False
    with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(provider.descriptor.definition_ref)


def test_missing_method_is_not_empty_implementation():
    provider = Provider()
    provider.stop = None
    with pytest.raises(CoreDTOError): AgentContributionSet(agent_runtime_providers=(provider,))


def test_disable_between_stage_and_commit_leaves_no_published_provider():
    env, _ = installed()
    provider = Provider()
    stage = env.stage_activation("fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    env.disable("fixture.plugin")
    with pytest.raises(AdmissionRefusedError): stage.commit()
    assert env.registry_snapshot.agent_runtime_provider_ids == ()
    with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(provider.descriptor.definition_ref)
    stage.rollback()


def test_mutable_contract_class_cannot_leave_partially_published_provider():
    @dataclass(frozen=True)
    class Contract:
        contract_id = "fixture.contract@1"
    env, _ = installed()
    stage = env.stage_activation("fixture.plugin", AgentContributionSet(contracts=(Contract,), agent_runtime_providers=(Provider(),)))
    Contract.contract_id = ""
    with pytest.raises(CoreDTOError): stage.commit()
    assert env.registry_snapshot.contract_ids == ()
    assert env.registry_snapshot.agent_runtime_provider_ids == ()
    assert env._activations == {}
    stage.rollback()


def test_invalid_surface_is_validated_before_registry_commit():
    @dataclass(frozen=True)
    class Contract:
        contract_id = "fixture." + "x" * 70 + "@1"
    env, _ = installed()
    stage = env.stage_activation("fixture.plugin", AgentContributionSet(contracts=(Contract,), agent_runtime_providers=(Provider(),)))
    with pytest.raises(ValueError): stage.commit()
    assert env.registry_snapshot.contract_ids == ()
    assert env.registry_snapshot.agent_runtime_provider_ids == ()
    assert env._activations == {}
    stage.rollback()


def test_canonical_core_owner_contract_with_version_is_reserved():
    @dataclass(frozen=True)
    class Contract:
        contract_id = "pacthold.agents@1"
    env, _ = installed()
    with pytest.raises(RegistrationConflictError):
        env.stage_activation("fixture.plugin", AgentContributionSet(contracts=(Contract,)))
    assert env.registry_snapshot.contract_ids == ()


def test_old_generation_retirement_preserves_new_generation_routes():
    env, _ = installed()
    first = Provider()
    old = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(first,)))
    env.drain(old.activation)
    second = Provider(descriptor("second.runtime", "second"))
    new = env.activate("fixture.plugin", AgentContributionSet(agent_runtime_providers=(second,)))
    env.retire(old.activation)
    assert env.agent_runtime_contribution(second.descriptor.definition_ref).owner_activation == new.activation
    assert env.registry_snapshot.agent_runtime_provider_ids == ("second.runtime",)


def test_descriptor_getter_cannot_reenter_staging_reservations():
    registry = CoreRegistry()
    inner = Provider()
    class Reentrant(Provider):
        @property
        def descriptor(self):
            if registry._mutating:
                registry.stage("inner", AgentContributionSet(agent_runtime_providers=(inner,)))
            return descriptor()
        def __init__(self): pass
    provider = Reentrant()
    contributions = AgentContributionSet(agent_runtime_providers=(provider,))
    with pytest.raises(CoreDTOError): registry.stage("outer", contributions)
    assert registry._pending == []
    assert registry.snapshot().agent_runtime_provider_ids == ()


def test_concurrent_same_definition_has_one_staged_claim():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    registry, barrier = CoreRegistry(), Barrier(2)
    def reserve(owner):
        contributions = AgentContributionSet(agent_runtime_providers=(Provider(),))
        barrier.wait(timeout=3)
        try: return registry.stage(owner, contributions)
        except RegistrationConflictError: return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, ("first", "second")))
    assert sum(item is not None for item in results) == 1
    registry.rollback(next(item for item in results if item is not None))
