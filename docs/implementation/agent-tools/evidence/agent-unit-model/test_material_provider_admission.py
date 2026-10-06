"""Same-CoreRegistry admission of optional Agent material metadata.

These tests cover only staging, publication and metadata discovery. They never
resolve, query, release, consume or otherwise acquire material.
"""
from dataclasses import dataclass
from typing import ClassVar

import pytest

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError
from pacthold.agents.public import (
    AdmittedMaterialProviderMetadata,
    AdmittedResourceProviderMetadata,
    AGENT_MATERIAL_CONTRACT_VERSION,
    MaterialCapability,
    MaterialContractError,
)
from pacthold.public import (
    CoreContributionSet,
    CoreDTOError,
    Environment,
    InstallationRecord,
    ReconcileSupport,
    ResourceProviderDescriptor,
)


@dataclass(frozen=True)
class AlphaContract:
    contract_id: ClassVar[str] = "sample.alpha@1"


class ReadPolicy:
    def __init__(self, allowed=()):
        self.allowed = set(allowed)
        self.calls = []

    def admit_object_access(self, principal, object_ref, permission):
        self.calls.append((principal, object_ref, permission))
        return (principal == "principal" and permission == "read"
                and object_ref in self.allowed)


def _capability(*, query=True, lifetimes=("copyComplete", "dynamic"), recovery="both"):
    return MaterialCapability(
        AGENT_MATERIAL_CONTRACT_VERSION, lifetimes, query, recovery)


class ResourceProvider:
    def __init__(self, provider_id, *, capability=None, supported=(), descriptor_version="1.0"):
        self.provider_id = provider_id
        self.display_name = f"Provider {provider_id}"
        self.version = descriptor_version
        self.supported_contract_ids = frozenset(supported)
        self._capability = capability
        self.capability_reads = 0
        self.describe_calls = 0
        self.effects = {name: 0 for name in (
            "acquire", "release", "reconcile", "describe_material",
            "resolve_material", "query_material", "release_material")}

    @property
    def material_capability(self):
        self.capability_reads += 1
        return self._capability

    def describe(self):
        self.describe_calls += 1
        return ResourceProviderDescriptor(
            self.provider_id, self.display_name, self.version, ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        self.effects["acquire"] += 1
        raise AssertionError("admission must not use C1 acquire")

    def release(self, request):
        self.effects["release"] += 1
        raise AssertionError("admission must not use C1 release")

    def reconcile(self, request):
        self.effects["reconcile"] += 1
        raise AssertionError("admission must not use C1 reconcile")

    def describe_material(self, resource_ref, principal):
        self.effects["describe_material"] += 1
        raise AssertionError("metadata admission must not describe a material")

    def resolve_material(self, request, invocation):
        self.effects["resolve_material"] += 1
        raise AssertionError("metadata admission must not resolve a material")

    def query_material(self, request, invocation):
        self.effects["query_material"] += 1
        raise AssertionError("metadata admission must not query a material")

    def release_material(self, request, invocation):
        self.effects["release_material"] += 1
        raise AssertionError("metadata admission must not release a material")


class LegacyResourceProvider:
    """Valid C1 provider with no statically declared material capability."""

    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.display_name = f"Legacy {provider_id}"
        self.supported_contract_ids = frozenset({"sample.alpha@1"})
        self.describe_calls = 0
        self.effects = {name: 0 for name in (
            "acquire", "release", "reconcile")}

    def describe(self):
        self.describe_calls += 1
        return ResourceProviderDescriptor(
            self.provider_id, self.display_name, "1.0", ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        self.effects["acquire"] += 1
        raise AssertionError("metadata admission must not use old C1 acquire")

    def release(self, request):
        self.effects["release"] += 1
        raise AssertionError("metadata admission must not use old C1 release")

    def reconcile(self, request):
        self.effects["reconcile"] += 1
        raise AssertionError("metadata admission must not use old C1 reconcile")


def _environment(environment_id="env", *, allowed=None):
    if allowed is None:
        allowed = {f"{environment_id}:agents.resources"}
    policy = ReadPolicy(allowed)
    env = Environment(environment_id, policy=policy, principal_scope="principal")
    env.install(InstallationRecord("contracts.owner", "a" * 64))
    env.enable("contracts.owner")
    env.activate("contracts.owner", CoreContributionSet(contracts=(AlphaContract,)))
    return env, policy


def _activate(env, provider, owner=None):
    owner = owner or f"owner.{provider.provider_id.split('.')[-1]}"
    env.install(InstallationRecord(owner, "b" * 64))
    env.enable(owner)
    receipt = env.activate(owner, CoreContributionSet(resource_providers=(provider,)))
    return owner, receipt.activation


def _assert_effects_zero(provider):
    assert provider.effects == {name: 0 for name in provider.effects}


def test_capability_is_pinned_in_the_original_registry_entry_and_public_view_is_detached():
    env, _ = _environment()
    capability = _capability()
    provider = ResourceProvider("provider.alpha", capability=capability,
                                supported={"sample.alpha@1"})
    owner, activation = _activate(env, provider)

    old_pair = env._registry.resource_provider(provider.provider_id)
    old_admission = env._registry.resource_provider_admission(provider.provider_id)
    material_admission = env._registry.resource_provider_material_admission(provider.provider_id)
    assert old_pair == (owner, provider)
    assert len(old_admission) == 4
    assert len(material_admission) == 5
    assert material_admission[:4] == old_admission
    assert material_admission[1] is provider
    assert material_admission[4] == capability
    assert material_admission[4] is not capability

    view = env.material_provider_contribution(provider.provider_id)
    assert type(view) is AdmittedMaterialProviderMetadata
    assert type(view.resource_provider) is AdmittedResourceProviderMetadata
    assert view.resource_provider.owner_activation == activation
    assert view.resource_provider.owner_activation is not activation
    assert view.capability == capability
    assert view.capability is not material_admission[4]
    assert not hasattr(view, "provider")
    assert not hasattr(view.resource_provider, "provider")
    assert env.material_provider_contributions() == (view,)

    object.__setattr__(view.capability, "query_acquire", False)
    assert material_admission[4].query_acquire is True
    assert env.material_provider_contribution(provider.provider_id).capability.query_acquire is True
    assert provider._capability.query_acquire is True
    assert provider.capability_reads >= 3
    assert provider.describe_calls >= 3
    _assert_effects_zero(provider)


def test_legacy_c1_without_static_capability_keeps_pair_and_quad_but_is_not_advertised():
    env, _ = _environment()
    provider = LegacyResourceProvider("provider.legacy")
    # C1 still permits a provider that does not declare contract coverage.
    provider.supported_contract_ids = None
    owner, _ = _activate(env, provider)
    assert not hasattr(type(provider), "material_capability")

    assert env._registry.resource_provider(provider.provider_id) == (owner, provider)
    four = env._registry.resource_provider_admission(provider.provider_id)
    five = env._registry.resource_provider_material_admission(provider.provider_id)
    assert len(four) == 4 and len(five) == 5
    assert five[:4] == four and five[4] is None
    with pytest.raises(GuaranteeUnavailableError):
        env.material_provider_contribution(provider.provider_id)
    assert env.material_provider_contributions() == ()
    assert env._registry.resource_provider(provider.provider_id) == (owner, provider)
    assert provider.describe_calls > 0  # C1 registration only; helper did not describe again.
    assert provider.effects == {"acquire": 0, "release": 0, "reconcile": 0}


def test_staged_capability_is_invisible_until_commit_and_list_skips_it():
    env, _ = _environment()
    provider = ResourceProvider("provider.staged", capability=_capability(),
                                supported={"sample.alpha@1"})
    owner = "owner.staged"
    env.install(InstallationRecord(owner, "c" * 64))
    env.enable(owner)
    staged = env.stage_activation(
        owner, CoreContributionSet(resource_providers=(provider,)))

    before_reads, before_describes = provider.capability_reads, provider.describe_calls
    assert env.material_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    assert provider.capability_reads == before_reads
    assert provider.describe_calls == before_describes

    receipt = staged.commit()
    assert receipt.activation.plugin_id == owner
    assert env.material_provider_contribution(provider.provider_id).capability == _capability()
    assert env._registry.resource_provider_material_admission(provider.provider_id)[1] is provider
    _assert_effects_zero(provider)


def test_bad_declared_capability_fails_stage_typed_without_reserving_or_publishing():
    class RaisingProvider(ResourceProvider):
        @property
        def material_capability(self):
            self.capability_reads += 1
            raise RuntimeError("MATERIAL_SECRET_CANARY")

    env, _ = _environment()
    provider = RaisingProvider("provider.bad-property", capability=_capability(),
                               supported={"sample.alpha@1"})
    owner = "owner.bad-property"
    env.install(InstallationRecord(owner, "d" * 64))
    env.enable(owner)
    with pytest.raises(CoreDTOError) as error:
        env.stage_activation(
            owner, CoreContributionSet(resource_providers=(provider,)))
    assert "MATERIAL_SECRET_CANARY" not in str(error.value)
    assert provider.provider_id not in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider(provider.provider_id) is None
    _assert_effects_zero(provider)


@pytest.mark.parametrize("mutation", ["change", "remove", "in-place"])
def test_capability_mutation_between_stage_and_commit_rejects_whole_batch(mutation):
    env, _ = _environment()
    first = ResourceProvider("provider.first", capability=_capability(),
                             supported={"sample.alpha@1"})
    second = ResourceProvider("provider.second", capability=_capability(),
                              supported={"sample.alpha@1"})
    owner = "owner.batch"
    env.install(InstallationRecord(owner, "e" * 64))
    env.enable(owner)
    staged = env.stage_activation(
        owner, CoreContributionSet(resource_providers=(first, second)))

    if mutation == "change":
        second._capability = _capability(query=False)
    elif mutation == "remove":
        second._capability = None
    else:
        object.__setattr__(second._capability, "query_acquire", False)

    with pytest.raises(CoreDTOError):
        staged.commit()
    assert not ({"provider.first", "provider.second"}
                & set(env.registry_snapshot.resource_provider_ids))
    assert env._registry.resource_provider("provider.first") is None
    assert env._registry.resource_provider("provider.second") is None
    second._capability = _capability()
    retry = env.activate(owner, CoreContributionSet(resource_providers=(second,)))
    assert retry.activation.plugin_id == owner
    assert env.material_provider_contribution("provider.second").capability == _capability()

    for provider in (first, second):
        _assert_effects_zero(provider)


def test_legacy_stage_then_capability_addition_is_rejected_and_same_id_can_retry():
    env, _ = _environment()
    provider = LegacyResourceProvider("provider.added")
    owner = "owner.added"
    env.install(InstallationRecord(owner, "f" * 64))
    env.enable(owner)
    contributions = CoreContributionSet(resource_providers=(provider,))
    staged = env.stage_activation(owner, contributions)
    provider.material_capability = _capability()

    with pytest.raises(CoreDTOError):
        staged.commit()
    assert provider.provider_id not in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider(provider.provider_id) is None

    del provider.material_capability
    receipt = env.activate(owner, contributions)
    assert receipt.activation.plugin_id == owner
    assert env._registry.resource_provider(provider.provider_id) == (owner, provider)
    with pytest.raises(GuaranteeUnavailableError):
        env.material_provider_contribution(provider.provider_id)
    assert env.material_provider_contributions() == ()
    assert provider.effects == {"acquire": 0, "release": 0, "reconcile": 0}


@pytest.mark.parametrize("late_value", [_capability(), object(), None])
def test_active_legacy_pinned_absence_does_not_hide_later_capability_change(late_value):
    env, _ = _environment()
    provider = LegacyResourceProvider("provider.late")
    _activate(env, provider)
    provider.material_capability = late_value

    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contributions()
    assert provider.effects == {"acquire": 0, "release": 0, "reconcile": 0}


def test_active_provider_capability_drift_is_refused_without_mutating_pinned_registry_fact():
    env, _ = _environment()
    original = _capability()
    provider = ResourceProvider("provider.active-drift", capability=original,
                                supported={"sample.alpha@1"})
    _activate(env, provider)
    pinned = env._registry.resource_provider_material_admission(provider.provider_id)[4]
    provider._capability = _capability(query=False)

    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contributions()
    assert env._registry.resource_provider_material_admission(provider.provider_id)[4] == pinned
    assert pinned.query_acquire is True

    provider._capability = original
    assert env.material_provider_contribution(provider.provider_id).capability == original
    _assert_effects_zero(provider)


def test_material_read_acl_precedes_registry_and_provider_metadata_access(monkeypatch):
    env, policy = _environment(allowed=set())
    provider = ResourceProvider("provider.protected", capability=_capability(),
                                supported={"sample.alpha@1"})
    _activate(env, provider)
    before_reads, before_describes = provider.capability_reads, provider.describe_calls
    registry = env._registry

    def forbidden(*args, **kwargs):
        raise AssertionError("registry must not be read before agents.resources ACL")

    monkeypatch.setattr(registry, "resource_provider_material_admission", forbidden)
    monkeypatch.setattr(registry, "snapshot", forbidden)
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contributions()
    assert policy.calls[-2:] == [
        ("principal", "env:agents.resources", "read"),
        ("principal", "env:agents.resources", "read")]
    assert provider.capability_reads == before_reads
    assert provider.describe_calls == before_describes
    _assert_effects_zero(provider)


@pytest.mark.parametrize("provider_id", [{"provider": "x"}, ["provider.x"], "  "])
def test_invalid_exact_material_provider_ids_are_typed_refused_after_acl(provider_id):
    env, policy = _environment()
    provider = ResourceProvider("provider.valid", capability=_capability(),
                                supported={"sample.alpha@1"})
    _activate(env, provider)
    before_checks = len(policy.calls)
    before_reads, before_describes = provider.capability_reads, provider.describe_calls
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider_id)
    assert policy.calls[before_checks:] == [
        ("principal", "env:agents.resources", "read")]
    assert provider.capability_reads == before_reads
    assert provider.describe_calls == before_describes
    _assert_effects_zero(provider)


def test_material_capability_snapshot_never_calls_provider_to_dict():
    env, _ = _environment()
    capability = _capability()
    calls = []

    def forbidden_to_dict():
        calls.append("called")
        raise AssertionError("provider capability methods are untrusted")

    object.__setattr__(capability, "to_dict", forbidden_to_dict)
    provider = ResourceProvider("provider.cap-method", capability=capability,
                                supported={"sample.alpha@1"})
    _activate(env, provider)

    view = env.material_provider_contribution(provider.provider_id)
    assert view.capability == _capability()
    assert calls == []
    _assert_effects_zero(provider)


def test_material_capability_requires_exact_tuple_without_iterating_subclass():
    calls = []

    class HostileTuple(tuple):
        def __iter__(self):
            calls.append("iterated")
            raise AssertionError("capability must reject tuple subclasses before iteration")

    with pytest.raises(MaterialContractError):
        MaterialCapability(
            AGENT_MATERIAL_CONTRACT_VERSION,
            HostileTuple(("copyComplete", "dynamic")),
            True,
            "both",
        )
    assert calls == []


def test_inactive_owner_is_omitted_from_list_and_exact_lookup_refuses():
    env, _ = _environment()
    provider = ResourceProvider("provider.draining", capability=_capability(),
                                supported={"sample.alpha@1"})
    _, activation = _activate(env, provider)
    env.drain(activation)

    assert env.material_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    _assert_effects_zero(provider)


def test_registry_entry_without_active_original_environment_owner_is_not_visible():
    env, _ = _environment()
    provider = ResourceProvider("provider.orphan", capability=_capability(),
                                supported={"sample.alpha@1"})
    batch = env._registry.stage(
        "registry-only-owner", CoreContributionSet(resource_providers=(provider,)))
    env._registry.commit(batch)
    reads, describes = provider.capability_reads, provider.describe_calls

    assert env.material_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        env.material_provider_contribution(provider.provider_id)
    assert env._registry.resource_provider(provider.provider_id) == (
        "registry-only-owner", provider)
    assert provider.capability_reads == reads
    assert provider.describe_calls == describes
    _assert_effects_zero(provider)
