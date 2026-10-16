"""Environment-scoped, metadata-only view of admitted C1 resource providers.

These tests exercise the existing CoreRegistry contribution route. They do not
resolve or acquire resources and do not make ResourceProvider effects visible.
"""
from dataclasses import FrozenInstanceError, dataclass
from typing import ClassVar

import pytest

from ordessa_execution_api.environment import (
    AdmissionRefusedError, GuaranteeUnavailableError,
)
from ordessa_units.public import AdmittedResourceProviderMetadata
from pacthold.public import (
    CoreContributionSet, CoreDTOError, Environment, InstallationRecord,
    ReconcileSupport, ResourceProviderDescriptor,
)




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

from ordessa_units.admission.material_admission import MaterialAdmission

@dataclass(frozen=True)
class AlphaContract:
    contract_id: ClassVar[str] = "sample.alpha@1"


@dataclass(frozen=True)
class BetaContract:
    contract_id: ClassVar[str] = "sample.beta@1"


class ResourceReadPolicy:
    def __init__(self, allowed_objects=()):
        self.allowed_objects = set(allowed_objects)
        self.object_checks = []
        self.invoke_checks = []

    def admit_object_access(self, principal, object_ref, permission):
        self.object_checks.append((principal, object_ref, permission))
        return (principal == "principal" and permission == "read"
                and object_ref in self.allowed_objects)

    def admit_invoke(self, *args):
        self.invoke_checks.append(args)
        return False


class ControlledResourceProvider:
    """Brand-neutral C1 provider; discovery must never call its effect methods."""

    def __init__(self, provider_id, supported_contract_ids=(), *, declare_support=True,
                 stable_descriptor=False):
        self.provider_id = provider_id
        self.display_name = f"Provider {provider_id}"
        self.version = "1.0"
        self.stable_descriptor = stable_descriptor
        self._descriptor_object = None
        self.describe_calls = 0
        if declare_support:
            self.supported_contract_ids = frozenset(supported_contract_ids)
        self.effect_calls = {name: 0 for name in ("acquire", "release", "reconcile")}

    def describe(self):
        self.describe_calls += 1
        if self.stable_descriptor:
            if self._descriptor_object is None:
                self._descriptor_object = ResourceProviderDescriptor(
                    self.provider_id, self.display_name, self.version, ReconcileSupport.SUPPORTED)
            return self._descriptor_object
        return ResourceProviderDescriptor(
            self.provider_id, self.display_name, self.version, ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        self.effect_calls["acquire"] += 1
        raise AssertionError("resource metadata discovery must not acquire")

    def release(self, request):
        self.effect_calls["release"] += 1
        raise AssertionError("resource metadata discovery must not release")

    def reconcile(self, request):
        self.effect_calls["reconcile"] += 1
        raise AssertionError("resource metadata discovery must not reconcile")


def _new_environment(environment_id="env", *, allowed_objects=None):
    if allowed_objects is None:
        allowed_objects = {f"{environment_id}:agents.resources"}
    policy = ResourceReadPolicy(allowed_objects)
    env = Environment(environment_id, policy=policy, principal_scope="principal", resource_extension_snapshot=_test_resource_snapshot)
    env.install(InstallationRecord("contracts.owner", "a" * 64))
    env.enable("contracts.owner")
    env.activate("contracts.owner", CoreContributionSet(contracts=(AlphaContract, BetaContract)))
    return env, policy


def _activate_resource(env, owner, provider):
    env.install(InstallationRecord(owner, "b" * 64))
    env.enable(owner)
    receipt = env.activate(owner, CoreContributionSet(resource_providers=(provider,)))
    return receipt.activation


def test_two_active_providers_return_only_frozen_metadata_from_the_same_registry():
    env, policy = _new_environment()
    alpha = ControlledResourceProvider("res.alpha", {"sample.alpha@1"})
    beta = ControlledResourceProvider("res.beta", {"sample.beta@1", "sample.alpha@1"})
    alpha_owner = _activate_resource(env, "owner.alpha", alpha)
    beta_owner = _activate_resource(env, "owner.beta", beta)

    rows = MaterialAdmission(env).resource_provider_contributions()
    assert len(rows) == 2
    by_id = {row.descriptor.id: row for row in rows}
    assert set(by_id) == {"res.alpha", "res.beta"}
    assert type(by_id["res.alpha"]) is AdmittedResourceProviderMetadata
    assert by_id["res.alpha"].owner_activation == alpha_owner
    assert by_id["res.beta"].owner_activation == beta_owner
    assert by_id["res.alpha"].owner_activation.environment == env.environment_id
    assert by_id["res.alpha"].supported_contract_ids == ("sample.alpha@1",)
    assert by_id["res.beta"].supported_contract_ids == (
        "sample.alpha@1", "sample.beta@1")
    assert MaterialAdmission(env).resource_provider_contribution("res.alpha") == by_id["res.alpha"]

    assert set(by_id["res.alpha"].__dataclass_fields__) == {
        "owner_activation", "descriptor", "supported_contract_ids"}
    assert not hasattr(by_id["res.alpha"], "provider")
    assert not any(callable(getattr(by_id["res.alpha"], field))
                   for field in by_id["res.alpha"].__dataclass_fields__)
    _, _, registry_descriptor, _ = env._registry.resource_provider_admission(
        "res.alpha")
    assert by_id["res.alpha"].descriptor is not registry_descriptor
    with pytest.raises(FrozenInstanceError):
        by_id["res.alpha"].supported_contract_ids = ()
    with pytest.raises(FrozenInstanceError):
        by_id["res.alpha"].descriptor.id = "res.changed"

    # C1 keeps the original same-registry (owner, provider) lookup unchanged.
    assert env._registry.resource_provider("res.alpha") == ("owner.alpha", alpha)
    assert alpha.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    assert beta.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    assert policy.object_checks[-1] == (
        "principal", "env:agents.resources", "read")
    assert policy.invoke_checks == []


def test_owner_activation_metadata_is_a_copy_of_the_host_fact():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.owner-copy", {"sample.alpha@1"})
    owner = _activate_resource(env, "owner.owner-copy", provider)
    host_entry = env._activation_entry(owner)
    original_generation = host_entry.ref.generation

    metadata = MaterialAdmission(env).resource_provider_contribution("res.owner-copy")
    assert metadata.owner_activation == owner
    assert metadata.owner_activation is not owner
    assert metadata.owner_activation is not host_entry.ref

    object.__setattr__(metadata.owner_activation, "generation", 0)
    assert host_entry.ref.generation == original_generation
    refreshed = MaterialAdmission(env).resource_provider_contribution("res.owner-copy")
    assert refreshed.owner_activation == owner
    assert refreshed.owner_activation.generation == original_generation
    assert refreshed.owner_activation is not host_entry.ref
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_activate_commit_drift_cleans_unpublished_provider_id_for_retry():
    class DriftOnceProvider(ControlledResourceProvider):
        def __init__(self):
            super().__init__("res.activate-retry", {"sample.alpha@1"})
            self.fixed = False

        def describe(self):
            self.describe_calls += 1
            version = "1.0" if self.fixed or self.describe_calls == 1 else "2.0"
            return ResourceProviderDescriptor(
                self.provider_id, self.display_name, version, ReconcileSupport.SUPPORTED)

    env, _ = _new_environment()
    owner = "owner.activate-retry"
    env.install(InstallationRecord(owner, "f" * 64))
    env.enable(owner)
    provider = DriftOnceProvider()
    contributions = CoreContributionSet(resource_providers=(provider,))

    with pytest.raises(CoreDTOError):
        env.activate(owner, contributions)
    assert "res.activate-retry" not in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider("res.activate-retry") is None
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}

    provider.fixed = True
    receipt = env.activate(owner, contributions)
    assert receipt.activation.plugin_id == owner
    assert "res.activate-retry" in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider("res.activate-retry") == (owner, provider)
    assert MaterialAdmission(env).resource_provider_contribution("res.activate-retry").descriptor.version == "1.0"
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_staged_resource_is_not_discoverable_until_environment_commit():
    env, _ = _new_environment()
    active = ControlledResourceProvider("res.active", {"sample.alpha@1"})
    staged_provider = ControlledResourceProvider("res.staged", {"sample.beta@1"})
    _activate_resource(env, "owner.active", active)
    env.install(InstallationRecord("owner.staged", "c" * 64))
    env.enable("owner.staged")
    staged = env.stage_activation(
        "owner.staged", CoreContributionSet(resource_providers=(staged_provider,)))

    before = MaterialAdmission(env).resource_provider_contributions()
    assert tuple(row.descriptor.id for row in before) == ("res.active",)
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.staged")
    staged.commit()
    assert {row.descriptor.id for row in MaterialAdmission(env).resource_provider_contributions()} == {
        "res.active", "res.staged"}
    assert staged_provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_missing_provider_and_cross_environment_provider_are_not_resolved():
    env_a, _ = _new_environment("env-a")
    env_b, _ = _new_environment("env-b")
    local = ControlledResourceProvider("res.shared", {"sample.alpha@1"})
    foreign = ControlledResourceProvider("res.shared", {"sample.alpha@1"})
    foreign_only = ControlledResourceProvider("res.foreign-only", {"sample.beta@1"})
    local_owner = _activate_resource(env_a, "owner.local", local)
    foreign_owner = _activate_resource(env_b, "owner.foreign", foreign)
    _activate_resource(env_b, "owner.foreign-only", foreign_only)

    local_view = MaterialAdmission(env_a).resource_provider_contribution("res.shared")
    foreign_view = MaterialAdmission(env_b).resource_provider_contribution("res.shared")
    assert local_view.owner_activation == local_owner
    assert foreign_view.owner_activation == foreign_owner
    assert local_view.owner_activation.environment == "env-a"
    assert foreign_view.owner_activation.environment == "env-b"
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env_a).resource_provider_contribution("res.foreign-only")
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env_a).resource_provider_contribution("res.absent")
    assert local.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    assert foreign.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
    assert foreign_only.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_draining_resource_owner_is_hidden_and_single_lookup_refuses():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.draining", {"sample.alpha@1"})
    owner = _activate_resource(env, "owner.draining", provider)
    env.drain(owner)

    assert MaterialAdmission(env).resource_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.draining")
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_retired_resource_owner_is_removed_from_registry_and_discovery():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.retired", {"sample.alpha@1"})
    owner = _activate_resource(env, "owner.retired", provider)

    assert env.retire_activation(owner) == ("retired", ())
    assert env._registry.resource_provider("res.retired") is None
    assert MaterialAdmission(env).resource_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.retired")
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_registry_entry_without_matching_environment_owner_is_not_discoverable():
    env, _ = _new_environment()
    orphan = ControlledResourceProvider("res.orphan", {"sample.alpha@1"})
    batch = env._registry.stage(
        "registry-only-owner", CoreContributionSet(resource_providers=(orphan,)))
    env._registry.commit(batch)

    assert MaterialAdmission(env).resource_provider_contributions() == ()
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.orphan")
    assert env._registry.resource_provider("res.orphan") == ("registry-only-owner", orphan)
    assert orphan.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


@pytest.mark.parametrize("mutation", ["provider-id", "descriptor", "contracts"])
def test_active_provider_identity_or_contract_mutation_fails_closed(mutation):
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.mutating", {"sample.alpha@1"})
    _activate_resource(env, "owner.mutating", provider)
    if mutation == "provider-id":
        provider.provider_id = "res.changed"
    elif mutation == "descriptor":
        provider.version = "2.0"
    else:
        provider.supported_contract_ids = frozenset({"sample.beta@1"})

    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.mutating")
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contributions()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_c1_provider_without_support_declaration_remains_registered_but_not_discoverable():
    env, _ = _new_environment()
    provider = ControlledResourceProvider(
        "res.legacy-no-coverage", declare_support=False)
    _activate_resource(env, "owner.legacy", provider)

    # The old C1 registry contract is preserved; the richer discovery view
    # refuses to claim complete resource coverage from a missing declaration.
    assert env._registry.resource_provider("res.legacy-no-coverage") == (
        "owner.legacy", provider)
    with pytest.raises(GuaranteeUnavailableError):
        MaterialAdmission(env).resource_provider_contribution("res.legacy-no-coverage")
    with pytest.raises(GuaranteeUnavailableError):
        MaterialAdmission(env).resource_provider_contributions()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_explicit_none_support_declaration_keeps_c1_registration_but_is_unavailable():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.none-coverage", {"sample.alpha@1"})
    provider.supported_contract_ids = None
    _activate_resource(env, "owner.none-coverage", provider)

    assert env._registry.resource_provider("res.none-coverage") == (
        "owner.none-coverage", provider)
    with pytest.raises(GuaranteeUnavailableError):
        MaterialAdmission(env).resource_provider_contribution("res.none-coverage")
    with pytest.raises(GuaranteeUnavailableError):
        MaterialAdmission(env).resource_provider_contributions()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_empty_support_declaration_is_a_known_empty_snapshot():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.empty-coverage", ())
    _activate_resource(env, "owner.empty-coverage", provider)

    view = MaterialAdmission(env).resource_provider_contribution("res.empty-coverage")
    assert view.supported_contract_ids == ()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


@pytest.mark.parametrize("allowed", [set(), {"env:agents.runtime"}])
def test_resource_discovery_requires_its_own_read_acl(allowed):
    env, policy = _new_environment(allowed_objects=allowed)
    provider = ControlledResourceProvider("res.protected", {"sample.alpha@1"})
    _activate_resource(env, "owner.protected", provider)

    describe_calls_before = provider.describe_calls

    def registry_read_forbidden(*args, **kwargs):
        raise AssertionError("resource registry must not be read before its ACL")

    # The denial must happen before owner/descriptor lookup, not merely before
    # calling one of the provider's effectful C1 methods.
    env._registry.snapshot = registry_read_forbidden
    env._registry.resource_provider = registry_read_forbidden
    env._registry.resource_descriptors = registry_read_forbidden
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contributions()
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.protected")
    assert provider.describe_calls == describe_calls_before
    assert policy.object_checks == [
        ("principal", "env:agents.resources", "read"),
        ("principal", "env:agents.resources", "read")]
    assert policy.invoke_checks == []
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


@pytest.mark.parametrize("mutation", ["provider-id", "contracts"])
def test_stage_commit_rejects_resource_metadata_mutated_before_publication(mutation):
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.staged-mutation", {"sample.alpha@1"})
    env.install(InstallationRecord("owner.staged-mutation", "d" * 64))
    env.enable("owner.staged-mutation")
    staged = env.stage_activation(
        "owner.staged-mutation", CoreContributionSet(resource_providers=(provider,)))
    if mutation == "provider-id":
        provider.provider_id = "res.precommit-changed"
    else:
        provider.supported_contract_ids = frozenset({"sample.beta@1"})

    with pytest.raises(CoreDTOError):
        staged.commit()
    assert "res.staged-mutation" not in env.registry_snapshot.resource_provider_ids
    assert "res.precommit-changed" not in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider("res.staged-mutation") is None
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_stage_commit_copies_descriptor_before_original_object_can_mutate():
    env, _ = _new_environment()
    provider = ControlledResourceProvider(
        "res.descriptor-alias", {"sample.alpha@1"}, stable_descriptor=True)
    env.install(InstallationRecord("owner.descriptor-alias", "e" * 64))
    env.enable("owner.descriptor-alias")
    staged = env.stage_activation(
        "owner.descriptor-alias", CoreContributionSet(resource_providers=(provider,)))
    staged_descriptor = provider.describe()
    object.__setattr__(staged_descriptor, "version", "2.0")

    with pytest.raises(CoreDTOError):
        staged.commit()
    assert "res.descriptor-alias" not in env.registry_snapshot.resource_provider_ids
    assert env._registry.resource_provider("res.descriptor-alias") is None
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_postcommit_descriptor_object_mutation_is_not_advertised():
    env, _ = _new_environment()
    provider = ControlledResourceProvider(
        "res.descriptor-alias", {"sample.alpha@1"}, stable_descriptor=True)
    _activate_resource(env, "owner.descriptor-alias", provider)
    view = MaterialAdmission(env).resource_provider_contribution("res.descriptor-alias")
    original_descriptor = provider.describe()
    assert view.descriptor is not original_descriptor
    _, _, registry_descriptor, _ = env._registry.resource_provider_admission(
        "res.descriptor-alias")
    assert view.descriptor is not registry_descriptor

    object.__setattr__(original_descriptor, "version", "2.0")
    assert view.descriptor.version == "1.0"
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.descriptor-alias")
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contributions()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}


def test_postcommit_in_place_supported_contract_set_mutation_is_not_advertised():
    env, _ = _new_environment()
    provider = ControlledResourceProvider("res.mutable-support", {"sample.alpha@1"})
    provider.supported_contract_ids = {"sample.alpha@1"}
    _activate_resource(env, "owner.mutable-support", provider)
    view = MaterialAdmission(env).resource_provider_contribution("res.mutable-support")

    provider.supported_contract_ids.add("sample.beta@1")
    assert view.supported_contract_ids == ("sample.alpha@1",)
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contribution("res.mutable-support")
    with pytest.raises(AdmissionRefusedError):
        MaterialAdmission(env).resource_provider_contributions()
    assert provider.effect_calls == {"acquire": 0, "release": 0, "reconcile": 0}
