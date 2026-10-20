"""Configuration contribution admission and discovery on the sole Registry.

Freeze: docs/implementation/agent-tools/configuration-provider-admission-freeze-v1.md.
Admission/discovery tests only — no native configuration effects, no payload
parsing, no assess/compile/verify call points, no wire binding, no real model
or user-service access.
"""
import pytest
from pacthold.adapters.sqlite.environment.store import SqliteStorePort

from ordessa_execution_agents.harness.providers.registry.errors import CatalogAdmissionRefused, CatalogIdentityConflict
from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
from pacthold.public import Environment, InstallationRecord
from pacthold.core.registration import RegistrationConflictError
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from pacthold.core.registration import CoreContributionSet
from ordessa_execution_agents.harness.definitions.configuration_providers import (
    CONFIGURATION_PROVIDER_VERSION, ConfigurationProviderDescriptor, ConfigurationRoute,
)
from ordessa_execution_agents.harness.providers.registry.contributions import (
    AgentContributionSet, RuntimeProviderDescriptor,
    RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS,
)
from ordessa_units.public import (
    AdmittedConfigurationProviderMetadata, unit_services,
)




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

ENV = "configuration-test"
SUPPORTED_METHODS = ("describe", "validate", "extract_references")


class Policy:
    allowed = True
    def admit_object_access(self, principal, target, mode): return self.allowed
    def admit_invoke(self, *args): return self.allowed


def runtime_descriptor(provider_id="fixture.runtime", definition_id="fixture",
                       environment=ENV, methods=("assess_configuration",)):
    return RuntimeProviderDescriptor(
        provider_id, RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": environment, "definitionId": definition_id,
         "revision": "1"},
        "sha256:" + "a" * 64, tuple(methods))


class Provider:
    """RuntimeProvider without any configuration mount (no contribution)."""
    def __init__(self, value=None):
        self.descriptor = value or runtime_descriptor()


for _name in RUNTIME_METHODS:
    setattr(Provider, _name, lambda *args, **kwargs: None)


class ConfiguredProvider(Provider):
    """RuntimeProvider carrying a configuration_routes declaration."""
    def __init__(self, value=None, routes=()):
        super().__init__(value)
        self.configuration_routes = tuple(routes)


class RawPayload(AgentContributionSet):
    """Bypasses AgentContributionSet's own checks to reach the Registry gate."""
    def __post_init__(self):
        CoreContributionSet.__post_init__(self)
        value = self.agent_runtime_providers
        if not isinstance(value, (tuple, list)):
            raise CoreDTOError("Agent runtime providers must be a sequence")
        object.__setattr__(self, "agent_runtime_providers", tuple(value))


def definition(definition_id="fixture", revision="1", environment=ENV):
    return {"environmentNamespace": environment, "definitionId": definition_id,
            "revision": revision}


def route(kind="assets.model-provider", schema="schema/1", definitions=None,
          actions=("value",), claims=("model.selection",)):
    return ConfigurationRoute(
        kind, schema,
        tuple(definitions if definitions is not None else (definition(),)),
        tuple(actions), tuple(claims),
    )


def installed(owners=("fixture.plugin",), *, store_path=None, request=None):
    policy = Policy()
    store = SqliteStorePort(store_path) if store_path is not None else None
    env = Environment(ENV, policy=policy, store=store, resource_extension_snapshot=_test_resource_snapshot)
    if store is not None and request is not None:
        request.addfinalizer(store.close)
        request.addfinalizer(env.close)
    for owner in owners:
        env.install(InstallationRecord(owner, "a" * 64))
        env.enable(owner)
    return env, policy


def activated(env, owner, **kwargs):
    return env.activate(owner, AgentContributionSet(**kwargs))


def _walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
    else:
        yield value


# -- Gate 1: absent mount keeps legacy admission, contributes nothing --------

def test_gate1_absent_configuration_routes_keep_legacy_admission_and_discover_nothing():
    env, _ = installed()
    provider = Provider()
    receipt = activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    assert env.registry_snapshot.agent_runtime_provider_ids == ("fixture.runtime",)
    assert env._registry.agent_runtime_configuration_routes("fixture.runtime") is None
    services = unit_services(env)
    assert services.providers.configuration_list() == ()
    admitted_runtime = env.agent_runtime_contribution(provider.descriptor.definition_ref)
    assert admitted_runtime.owner_activation == receipt.activation
    assert admitted_runtime.provider is provider


def test_empty_configuration_routes_mount_contributes_nothing():
    env, _ = installed()
    provider = ConfiguredProvider(routes=())
    activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    assert env._registry.agent_runtime_configuration_routes("fixture.runtime") is None
    assert unit_services(env).providers.configuration_list() == ()


# -- Gate 2: illegal routes are typed refusals, no residual staged batch -----

@pytest.mark.parametrize("bad_routes", [
    "routes", [route()], (route(), "junk"), (None,), (object(),),
])
def test_gate2_illegal_configuration_route_mounts_are_core_dto_errors(bad_routes):
    provider = ConfiguredProvider()
    provider.configuration_routes = bad_routes
    with pytest.raises(CoreDTOError):
        AgentContributionSet(agent_runtime_providers=(provider,))
    env, _ = installed()
    with pytest.raises(CoreDTOError):
        env.stage_activation("fixture.plugin",
                             RawPayload(agent_runtime_providers=(provider,)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


def test_gate2_cross_environment_route_is_refused_at_stage():
    env, _ = installed()
    provider = ConfiguredProvider(
        routes=(route(definitions=(definition(environment="other-env"),)),))
    with pytest.raises(CoreDTOError):
        env.stage_activation("fixture.plugin",
                             AgentContributionSet(agent_runtime_providers=(provider,)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


def test_gate2_unacknowledged_definition_is_registration_conflict():
    env, _ = installed()
    provider = ConfiguredProvider(
        routes=(route(definitions=(definition("nobody"),)),))
    with pytest.raises(RegistrationConflictError):
        env.stage_activation("fixture.plugin",
                             AgentContributionSet(agent_runtime_providers=(provider,)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


# -- Gate 3: conflict keys, tamper refusal, generation semantics -------------

def test_gate3_same_batch_kind_schema_conflict_refused():
    env, _ = installed(owners=("plugin.one", "plugin.two"))
    one = ConfiguredProvider(runtime_descriptor("one.runtime", "one"),
                             routes=(route(definitions=(definition("one"),)),))
    two = ConfiguredProvider(runtime_descriptor("two.runtime", "two"),
                             routes=(route(definitions=(definition("two"),)),))
    with pytest.raises(RegistrationConflictError):
        env.activate("plugin.one",
                     AgentContributionSet(agent_runtime_providers=(one, two)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


def test_gate3_cross_batch_kind_schema_conflict_refused():
    env, _ = installed(owners=("plugin.one", "plugin.two"))
    first = ConfiguredProvider(runtime_descriptor("first.runtime", "first"),
                               routes=(route(definitions=(definition("first"),)),))
    activated(env, "plugin.one", agent_runtime_providers=(first,))
    second = ConfiguredProvider(runtime_descriptor("second.runtime", "second"),
                                routes=(route(definitions=(definition("second"),)),))
    with pytest.raises(RegistrationConflictError):
        env.activate("plugin.two",
                     AgentContributionSet(agent_runtime_providers=(second,)))
    assert env._registry._pending == []


def test_gate3_one_provider_duplicate_route_refused():
    env, _ = installed()
    provider = ConfiguredProvider(routes=(
        route(),
        route(definitions=(definition("extra"),)),
    ))
    with pytest.raises(RegistrationConflictError):
        env.activate("fixture.plugin",
                     AgentContributionSet(agent_runtime_providers=(provider,)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


def test_gate3_definition_ambiguity_within_one_batch_refused():
    env, _ = installed()
    runtime_base = Provider(runtime_descriptor("runtime.base", "def.base"))
    config_one = ConfiguredProvider(runtime_descriptor("config.one", "def.config-one"),
                                    routes=(route(definitions=(definition("def.base"),)),))
    config_two = ConfiguredProvider(runtime_descriptor("config.two", "def.config-two"),
                                    routes=(route(definitions=(definition("def.base"),)),))
    with pytest.raises(RegistrationConflictError):
        env.activate("fixture.plugin", AgentContributionSet(
            agent_runtime_providers=(runtime_base, config_one, config_two)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


def test_gate3_definition_ambiguity_across_batches_refused():
    env, _ = installed(owners=("plugin.one", "plugin.two"))
    runtime_one = Provider(runtime_descriptor("runtime.one", "def.one"))
    config_one = ConfiguredProvider(runtime_descriptor("config.one", "def.config-one"),
                                    routes=(route(definitions=(definition("def.one"),)),))
    activated(env, "plugin.one", agent_runtime_providers=(runtime_one, config_one))
    runtime_two = Provider(runtime_descriptor("runtime.two", "def.two"))
    config_two = ConfiguredProvider(runtime_descriptor("config.two", "def.config-two"),
                                    routes=(route(definitions=(definition("def.one"),)),))
    with pytest.raises(RegistrationConflictError):
        env.activate("plugin.two", AgentContributionSet(
            agent_runtime_providers=(runtime_two, config_two)))
    assert env._registry._pending == []
    # the refused batch leaves no residual staged or published state
    assert env.registry_snapshot.agent_runtime_provider_ids == (
        "config.one", "runtime.one")


@pytest.mark.parametrize("mutate", ["descriptor", "method", "owner"])
def test_gate3_post_admission_mutation_refuses_configuration_discovery(mutate):
    env, _ = installed()
    provider = ConfiguredProvider(routes=(route(),))
    activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    original_ref = dict(provider.descriptor.definition_ref)
    services = unit_services(env)
    assert len(services.providers.configuration_list()) == 1
    if mutate == "descriptor":
        provider.descriptor = runtime_descriptor("tampered.runtime", "tampered")
    if mutate == "method":
        provider.prepare = None
    if mutate == "owner":
        provider.owner = "fake"
    with pytest.raises(CatalogAdmissionRefused):
        env.agent_configuration_contributions()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_list()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(original_ref)


def test_gate3_drained_and_replaced_generation_refuses_old_route_queries(tmp_path, request):
    env, _ = installed(store_path=tmp_path / "configuration-provider.sqlite", request=request)
    provider = ConfiguredProvider(routes=(route(),))
    receipt = activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    old_ref = dict(provider.descriptor.definition_ref)
    services = unit_services(env)
    view = services.providers.configuration_describe(old_ref)
    assert view["providerRef"]["generation"] == receipt.activation.generation
    env.drain(receipt.activation)
    # draining activations are excluded from list discovery, direct query refused
    assert env.agent_configuration_contributions() == ()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(old_ref)
    env.retire(receipt.activation)
    assert env._store.unresolved_provider_usages(
        env.environment_id, receipt.activation.plugin_id, receipt.activation.generation) == ()
    replacement = ConfiguredProvider(
        runtime_descriptor("replacement.runtime", "replacement"),
        routes=(route(definitions=(definition("replacement"),)),))
    new = activated(env, "fixture.plugin", agent_runtime_providers=(replacement,))
    new_ref = dict(replacement.descriptor.definition_ref)
    view = services.providers.configuration_describe(new_ref)
    assert view["providerRef"]["generation"] == new.activation.generation
    assert view["recognizedDefinitions"] == [definition("replacement")]
    # retired pin / old definition is never carried across generations
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(old_ref)
    with pytest.raises(CatalogAdmissionRefused):
        env.agent_configuration_contribution(old_ref)


# -- Gate 4: declaration is not capability -----------------------------------

def test_gate4_missing_runtime_assess_configuration_keeps_admission_but_empty_recognized():
    env, _ = installed()
    provider = ConfiguredProvider(runtime_descriptor(methods=("start",)),
                                  routes=(route(),))
    receipt = activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    services = unit_services(env)
    listed = services.providers.configuration_list()
    assert len(listed) == 1
    view = listed[0]
    assert set(view) == {"descriptor", "providerRef", "recognizedDefinitions"}
    assert view["recognizedDefinitions"] == []
    assert view["descriptor"]["supportedMethods"] == list(SUPPORTED_METHODS)
    assert view["descriptor"]["providerId"] == "fixture.runtime"
    assert view["providerRef"]["providerId"] == "fixture.runtime"
    assert view["providerRef"]["generation"] == receipt.activation.generation
    single = services.providers.configuration_describe(
        dict(provider.descriptor.definition_ref))
    assert single["recognizedDefinitions"] == []


def test_recognized_definitions_cover_acknowledged_definitions_in_fixed_order():
    env, _ = installed()
    runtime_a = Provider(runtime_descriptor("runtime.a", "def.b"))
    runtime_b = Provider(runtime_descriptor("runtime.b", "def.a"))
    config = ConfiguredProvider(
        runtime_descriptor("config.one", "def.config"),
        routes=(route(definitions=(definition("def.b"), definition("def.a"))),))
    activated(env, "fixture.plugin", agent_runtime_providers=(
        runtime_a, runtime_b, config))
    services = unit_services(env)
    # describe is keyed by a route-acknowledged definition, not the provider id
    view = services.providers.configuration_describe(definition("def.b"))
    assert view["recognizedDefinitions"] == [
        definition("def.a"), definition("def.b"),
    ]
    admitted = env.agent_configuration_contributions()[0]
    assert admitted.recognized_definitions == (
        sealed_mapping(definition("def.a")), sealed_mapping(definition("def.b")))
    assert admitted.descriptor.supported_methods == SUPPORTED_METHODS


# -- Gate 5: host identity forgery stays refused ------------------------------

@pytest.mark.parametrize("name", ["owner", "owner_activation", "generation"])
def test_gate5_host_identity_forgery_with_configuration_mount_refused(name):
    provider = ConfiguredProvider(routes=(route(),))
    setattr(provider, name, "fake")
    with pytest.raises(CoreDTOError):
        AgentContributionSet(agent_runtime_providers=(provider,))
    env, _ = installed()
    raw = ConfiguredProvider(routes=(route(),))
    setattr(raw, name, "fake")
    with pytest.raises(CoreDTOError):
        env.stage_activation("fixture.plugin",
                             RawPayload(agent_runtime_providers=(raw,)))
    assert env._registry._pending == []
    assert env.registry_snapshot.agent_runtime_provider_ids == ()


# -- Gate 6: metadata safety (no callable, no aliasing) ----------------------

def test_gate6_metadata_has_no_callable_and_copies_never_alias_author_state():
    env, _ = installed()
    mutable_definition = definition()
    provider = ConfiguredProvider(routes=(route(definitions=(mutable_definition,)),))
    receipt = activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    mutable_definition["revision"] = "input-pollution"
    services = unit_services(env)
    admitted = env.agent_configuration_contributions()[0]
    assert type(admitted) is AdmittedConfigurationProviderMetadata
    # the DTO graph itself carries no callable anywhere
    for node in (admitted.owner_activation, admitted.descriptor,
                 admitted.recognized_definitions, admitted.runtime_provider_ref):
        for slot in list(getattr(node, "__dict__", {}).values()):
            assert not callable(slot)
            if isinstance(slot, (list, tuple)):
                for item in slot:
                    assert not callable(item)
                    for sub in list(getattr(item, "__dict__", {}).values()):
                        assert not callable(sub)
    # sealed projections are read-only
    with pytest.raises(TypeError):
        admitted.recognized_definitions[0]["revision"] = "x"
    with pytest.raises(TypeError):
        admitted.runtime_provider_ref["generation"] = 99
    view = services.providers.configuration_list()[0]
    assert not any(callable(leaf) for leaf in _walk(view))
    # input alias: the admitted snapshot keeps the sealed original
    assert view["recognizedDefinitions"] == [definition()]
    assert view["descriptor"]["routes"][0]["definitionRefs"][0]["revision"] == "1"
    # output copies cannot mutate internals
    view["descriptor"]["routes"][0]["configurationKind"] = "mutated.kind"
    view["providerRef"]["generation"] = 999
    view["recognizedDefinitions"][0]["revision"] = "mutated"
    again = services.providers.configuration_list()[0]
    assert again["descriptor"]["routes"][0]["configurationKind"] == "assets.model-provider"
    assert again["providerRef"]["generation"] == receipt.activation.generation
    assert again["recognizedDefinitions"][0]["revision"] == "1"
    # post-admission mount replacement does not touch the admitted snapshot
    provider.configuration_routes = (route(kind="assets.replaced"),)
    still = services.providers.configuration_list()[0]
    assert still["descriptor"]["routes"][0]["configurationKind"] == "assets.model-provider"
    assert admitted.descriptor.routes[0].configuration_kind == "assets.model-provider"


def test_admitted_metadata_dto_rejects_unsorted_or_incoherent_runtime_refs():
    activation = HarnessActivationRef(ENV, "fixture.plugin", 1)
    descriptor = ConfigurationProviderDescriptor(
        "fixture.runtime", CONFIGURATION_PROVIDER_VERSION, "sha256:" + "a" * 64,
        (route(),), SUPPORTED_METHODS)
    defn_a = sealed_mapping(definition("def.a"))
    defn_b = sealed_mapping(definition("def.b"))
    ref = sealed_mapping({
        "environmentNamespace": ENV, "providerId": "fixture.runtime",
        "ownerActivationRef": {"environmentNamespace": ENV,
                                "pluginId": "fixture.plugin", "generation": 1},
        "generation": 1, "contractVersion": "agent-runtime/2",
        "implementationDigest": "sha256:" + "a" * 64})
    admitted = AdmittedConfigurationProviderMetadata(
        activation, descriptor, (defn_a, defn_b), ref)
    assert admitted.recognized_definitions == (defn_a, defn_b)
    assert admitted.runtime_provider_ref["providerId"] == "fixture.runtime"
    assert admitted.owner_activation == activation
    with pytest.raises(ValueError):
        AdmittedConfigurationProviderMetadata(activation, descriptor, (defn_b, defn_a), ref)
    with pytest.raises(ValueError):
        AdmittedConfigurationProviderMetadata(activation, descriptor, (defn_a,), "not-a-ref")
    wrong_generation = sealed_mapping({
        "environmentNamespace": ENV, "providerId": "fixture.runtime",
        "ownerActivationRef": {"environmentNamespace": ENV,
                                "pluginId": "fixture.plugin", "generation": 1},
        "generation": 2, "contractVersion": "agent-runtime/2",
        "implementationDigest": "sha256:" + "a" * 64})
    with pytest.raises(ValueError):
        AdmittedConfigurationProviderMetadata(activation, descriptor, (defn_a,),
                                              wrong_generation)
    wrong_provider = sealed_mapping({
        "environmentNamespace": ENV, "providerId": "other.runtime",
        "ownerActivationRef": {"environmentNamespace": ENV,
                                "pluginId": "fixture.plugin", "generation": 1},
        "generation": 1, "contractVersion": "agent-runtime/2",
        "implementationDigest": "sha256:" + "a" * 64})
    with pytest.raises(ValueError):
        AdmittedConfigurationProviderMetadata(activation, descriptor, (defn_a,),
                                              wrong_provider)


# -- Gate 7: missing provider is empty or refused, never a fallback ----------

def test_gate7_missing_provider_is_empty_or_refused_without_fallback():
    env, _ = installed()
    services = unit_services(env)
    assert services.providers.configuration_list() == ()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(definition())
    with pytest.raises(CatalogAdmissionRefused):
        env.agent_configuration_contribution(definition())
    with pytest.raises(CatalogIdentityConflict):
        services.providers.configuration_describe(definition(environment="other-env"))
    with pytest.raises(CatalogIdentityConflict):
        services.providers.configuration_describe({"environmentNamespace": ENV})
    # runtime-only registry: no configuration contribution invented
    runtime_only = Provider()
    activated(env, "fixture.plugin", agent_runtime_providers=(runtime_only,))
    assert services.providers.configuration_list() == ()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(
            dict(runtime_only.descriptor.definition_ref))


def test_read_acl_refuses_configuration_discovery_without_runtime_permission():
    env, policy = installed()
    provider = ConfiguredProvider(routes=(route(),))
    activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    services = unit_services(env)
    policy.allowed = False
    with pytest.raises(CatalogAdmissionRefused):
        env.agent_configuration_contributions()
    with pytest.raises(CatalogAdmissionRefused):
        services.providers.configuration_describe(
            dict(provider.descriptor.definition_ref))


def test_staged_configuration_contribution_is_not_discoverable_until_commit():
    env, _ = installed()
    provider = ConfiguredProvider(routes=(route(),))
    stage = env.stage_activation(
        "fixture.plugin", AgentContributionSet(agent_runtime_providers=(provider,)))
    services = unit_services(env)
    assert services.providers.configuration_list() == ()
    receipt = stage.commit()
    listed = services.providers.configuration_list()
    assert len(listed) == 1
    assert listed[0]["providerRef"]["generation"] == receipt.activation.generation


def test_positive_admitted_metadata_shape_is_frozen_projection():
    env, _ = installed()
    provider = ConfiguredProvider(routes=(route(),))
    receipt = activated(env, "fixture.plugin", agent_runtime_providers=(provider,))
    admitted = env.agent_configuration_contributions()[0]
    assert type(admitted) is AdmittedConfigurationProviderMetadata
    assert admitted.owner_activation == receipt.activation
    assert admitted.descriptor.provider_id == "fixture.runtime"
    assert admitted.descriptor.contract_version == CONFIGURATION_PROVIDER_VERSION
    assert admitted.descriptor.implementation_digest == "sha256:" + "a" * 64
    assert admitted.descriptor.supported_methods == SUPPORTED_METHODS
    assert admitted.runtime_provider_ref["generation"] == receipt.activation.generation
    assert admitted.runtime_provider_ref["contractVersion"] == RUNTIME_PROVIDER_VERSION
    assert dict(admitted.recognized_definitions[0]) == definition()
    assert env.agent_configuration_contribution(
        dict(provider.descriptor.definition_ref)) == admitted
