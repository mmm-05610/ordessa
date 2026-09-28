"""T03b: admission proofs against the REAL platform, not a private registry.

Every refusal here is raised by `ordessa_harness.contributions` (the
Harness plugin's public contributions seam - the conflict authority the
product composition binds to `harness.configuration-adapters`) or by the
Server plugin host driving `server_plugin_api.stage_contributions`.

Gate map (docs/design/safety-controls/verification.md):
- gate 2: nothing here imports `ordessa_sandbox_*`; the field-claim conflict
  is proven with a LOCAL stub facet, so installing Permissions never needs
  the Sandbox domain.
- gate 3: two facets claiming one native field refuse at composition.

Shape follows plugins/harness/tests/test_contribution_registry.py and
test_external_adapter_product.py (the platform's own exemplars).
"""
from __future__ import annotations

import pytest
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, HarnessContributionError, HarnessContributionRegistry,
    POINT_API_VERSION, RUNTIME_POINT)
from ordessa_harness_api import (ConfigurationAdapterDescriptor, FieldClaim,
                                 ValueSchema, VersionRange)
from ordessa_server.plugin_host import (MethodRegistry, ServerPluginHost,
                                        StreamRouteRegistry)
from server_plugin_api import (
    AbsentContribution, Contribution, ContributionBatch,
    ContributionOwnerBusyError, ContributionPointUnboundError,
    ContributionVersionRefusedError, DuplicateContributionError,
    ServerPluginDescriptor, ServerPluginRegistration, stage_contributions)

import ordessa_permissions_adapters as adapters

OWNER = "ordessa.permissions-adapters"


def host_with_points() -> "tuple[ServerPluginHost, HarnessContributionRegistry]":
    registry = HarnessContributionRegistry()
    host = ServerPluginHost(methods=MethodRegistry(), stream_routes=StreamRouteRegistry())
    host.register_contribution_point(RUNTIME_POINT, POINT_API_VERSION,
                                     handler=registry.runtime_handler, exclusive=False)
    host.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                     handler=registry.configuration_handler, exclusive=False)
    return host, registry


def batch_of(*descriptors: ConfigurationAdapterDescriptor,
             point: str = CONFIGURATION_POINT) -> ContributionBatch:
    return ContributionBatch(
        tuple(Contribution(point, POINT_API_VERSION, _payload(d), required=True)
              for d in descriptors),
        open_points=frozenset({point}))


def _payload(descriptor: ConfigurationAdapterDescriptor):
    brand = next(a for a in adapters.default_adapters()
                 if a.harness_id == descriptor.harness_id)
    return adapters.PolicyConfigurationAdapter(brand, descriptor)


class Declarant:
    """A plugin that only declares; the host injects owner and admits."""

    def __init__(self, batch: ContributionBatch, plugin_id: str = OWNER) -> None:
        self._batch = batch
        self._plugin_id = plugin_id

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(self._plugin_id, "Policy Adapters", "1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=self._batch)


@pytest.fixture()
def host_and_registry() -> "tuple[ServerPluginHost, HarnessContributionRegistry]":
    return host_with_points()


def claude_descriptor() -> ConfigurationAdapterDescriptor:
    return next(d for d in adapters.default_configuration_descriptors()
                if d.harness_id == "claude-code")


def variant(base: ConfigurationAdapterDescriptor, **overrides):
    fields = {name: getattr(base, name) for name in base.__dataclass_fields__}
    fields.update(overrides)
    return ConfigurationAdapterDescriptor(**fields)


# ------------------------------------------------------------------- views

def test_activation_publishes_all_three_descriptors(host_and_registry) -> None:
    host, registry = host_and_registry
    host.activate(Declarant(adapters.policy_adapter_contributions()))
    views = host.contributions(CONFIGURATION_POINT)
    assert len(views) == 3
    for view in views:
        assert view.owner == OWNER  # host-injected, never author-declared
        assert view.api_version == POINT_API_VERSION
        assert isinstance(view.payload.descriptor, ConfigurationAdapterDescriptor)
    assert {d.adapter_id for d in registry.configuration_descriptors()} == {
        a.adapter_id for a in adapters.default_adapters()}


def test_deactivate_retires_every_record_atomically(host_and_registry) -> None:
    host, registry = host_and_registry
    host.activate(Declarant(adapters.policy_adapter_contributions()))
    assert len(registry.configuration_descriptors()) == 3
    host.deactivate(OWNER)
    assert host.contributions(CONFIGURATION_POINT) == ()
    assert registry.configuration_descriptors() == ()


# ---------------------------------------------------- stage-then-commit gate

def test_staged_but_uncommitted_is_invisible() -> None:
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler, OWNER,
                                 batch_of(claude_descriptor()))
    # staged: reserved against conflicts, but nothing is published anywhere
    assert registry.configuration_descriptors() == ()
    view = staged.resolve(CONFIGURATION_POINT)
    assert isinstance(view, AbsentContribution)
    # a competing admission touching the same claim is refused meanwhile
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, "other",
                            batch_of(variant(claude_descriptor(),
                                             adapter_id="stub.rival")))
    staged.commit()
    assert len(registry.configuration_descriptors()) == 1
    assert staged.resolve(CONFIGURATION_POINT).payload is not None


# ------------------------------------------------------- refusal authorities

def test_overlapping_ranges_between_two_of_my_adapters_refuse_not_last_wins() -> None:
    # §C1: unique by (harnessId, nativeVersionRange); overlap refused.
    registry = HarnessContributionRegistry()
    first = claude_descriptor()
    stage_contributions(registry.configuration_handler, OWNER,
                        batch_of(first)).commit()
    rival = variant(first, adapter_id="permissions.policy-adapter.claude-later",
                    native_versions=VersionRange((0, 81, 2), (0, 82, 0)))
    with pytest.raises(HarnessContributionError) as error:
        stage_contributions(registry.configuration_handler, "someone-else",
                            batch_of(rival))
    assert "overlap" in str(error.value).lower()
    # no last-wins: the first descriptor still stands, the rival never got in
    assert registry.configuration_descriptors() == (first,)


def test_duplicate_adapter_id_is_refused_by_the_platform() -> None:
    registry = HarnessContributionRegistry()
    first = claude_descriptor()
    stage_contributions(registry.configuration_handler, OWNER,
                        batch_of(first)).commit()
    with pytest.raises(HarnessContributionError) as error:
        stage_contributions(registry.configuration_handler, "other",
                            batch_of(first))
    assert first.adapter_id in str(error.value)
    assert registry.configuration_descriptors() == (first,)


def test_field_claim_conflict_across_facets_refuses_at_composition(
        host_and_registry) -> None:
    # gate 3, WITHOUT the Sandbox domain: a locally defined stub facet - not
    # imported from any sandbox package - claiming one field the permissions
    # projection already owns must be refused at composition, and NEITHER of
    # the two conflicting admissions may end up partly published.
    host, registry = host_and_registry
    host.activate(Declarant(adapters.policy_adapter_contributions()))
    published = registry.configuration_descriptors()
    stub = ConfigurationAdapterDescriptor(
        "stub.other-facet.claude-ask", "v1", "stub.sandbox-facet", "v1",
        "claude-code", VersionRange((0, 81, 2), (0, 81, 2)),
        # mirror the LIVE declared adapter pin so the claim conflict stays a
        # conflict whatever exact pin the facet declares (contribution.py
        # _ADAPTER_VERSION, backed by pyproject.toml:7)
        next(d.adapter_versions for d in published if d.harness_id == "claude-code"),
        ("stub-entry",), ValueSchema("object"),
        (FieldClaim("file", ".claude/settings.json", ("permissions", "ask")),))
    with pytest.raises(HarnessContributionError) as error:
        host.activate(Declarant(batch_of(stub), plugin_id="test.stub-facet"))
    assert "claim" in str(error.value).lower()
    # nothing half-admitted: same published set as before, stub absent, and
    # the failed activation left no staged reservations behind
    assert registry.configuration_descriptors() == published
    assert all(d.adapter_id != stub.adapter_id for d in registry.configuration_descriptors())
    assert not host.is_active("test.stub-facet")
    # the refused stub can be re-staged after the permissions claim retires:
    # the refusal is the conflict, not a poisoned registry
    host.deactivate(OWNER)
    host.activate(Declarant(batch_of(stub), plugin_id="test.stub-facet"))
    assert registry.configuration_descriptors() == (stub,)
    host.deactivate("test.stub-facet")


def test_parent_claim_path_overlap_refuses_too() -> None:
    # a sibling claim under the already-claimed `permissions` subtree collides
    # (claim overlap compares path prefixes) - stub-local, no sandbox import.
    registry = HarnessContributionRegistry()
    stage_contributions(registry.configuration_handler, OWNER,
                        batch_of(claude_descriptor())).commit()
    stub = variant(claude_descriptor(), adapter_id="stub.sibling",
                   facet_id="stub.facet", entries=("stub-entry",),
                   claims=(FieldClaim("file", ".claude/settings.json",
                                      ("permissions", "ask", "extra")),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, "other", batch_of(stub))


def test_unknown_point_id_is_refused_as_unbound(host_and_registry) -> None:
    host, registry = host_and_registry
    ghost = "harness.configuration-adapters-ghost"  # valid grammar, never bound
    with pytest.raises(ContributionPointUnboundError):
        host.activate(Declarant(batch_of(claude_descriptor(), point=ghost),
                                plugin_id="test.unbound"))
    assert host.contributions(ghost) == ()
    assert registry.configuration_descriptors() == ()


def test_wrong_api_version_is_refused_by_the_host(host_and_registry) -> None:
    host, _registry = host_and_registry
    batch = ContributionBatch((Contribution(CONFIGURATION_POINT, "v2",
                                            _payload(claude_descriptor())),))
    with pytest.raises(ContributionVersionRefusedError):
        host.activate(Declarant(batch, plugin_id="test.version"))
    assert host.contributions(CONFIGURATION_POINT) == ()


def test_spoofed_payload_never_reaches_the_registry(host_and_registry) -> None:
    class Spoof:  # author-declared owner must not supersede the host identity
        owner = "victim"

        def __init__(self, descriptor):
            self.descriptor = descriptor

    host, registry = host_and_registry
    with pytest.raises(HarnessContributionError):
        host.activate(Declarant(ContributionBatch(
            (Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                          Spoof(claude_descriptor())),))))
    assert registry.configuration_descriptors() == ()


# ----------------------------------------------------------- unload / busy

def test_unload_while_held_refuses_owner_busy(host_and_registry) -> None:
    # busy semantics are per single-record resolution: use the platform's own
    # `use_contribution` hold path with a one-descriptor contributor.
    host, registry = host_and_registry
    one = batch_of(claude_descriptor())
    host.activate(Declarant(one))
    assert host.contributions(CONFIGURATION_POINT)[0].owner == OWNER
    published = registry.configuration_descriptors()
    with host.use_contribution(CONFIGURATION_POINT):
        assert host.owner_busy(OWNER)
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate(OWNER)
        # the refusal changed nothing: still published, still held
        assert registry.configuration_descriptors() == published
    assert not host.owner_busy(OWNER)
    host.deactivate(OWNER)
    assert host.contributions(CONFIGURATION_POINT) == ()
    assert registry.configuration_descriptors() == ()
