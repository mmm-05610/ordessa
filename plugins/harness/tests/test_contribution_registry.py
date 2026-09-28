"""Harness T04 contribution admission without product composition."""
from __future__ import annotations

import pytest

from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, FieldClaim, RuntimeAdapterDescriptor,
    ValueSchema, VersionRange,
)
from server_plugin_api import Contribution, ContributionBatch, stage_contributions
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, RUNTIME_POINT, HarnessContributionRegistry,
    HarnessContributionError, admitted_descriptor,
)


def runtime(adapter: str, harness: str, aliases: tuple[str, ...] = ()):
    return RuntimeAdapterDescriptor(adapter, "v1", harness, aliases, VersionRange((1, 0, 0)))


def config(adapter: str, *, facet="model", harness="codex", entry="acp", claim=("provider",),
           low=(1, 0, 0), high=None):
    return ConfigurationAdapterDescriptor(
        adapter, "v1", facet, "v1", harness, VersionRange(low, high),
        VersionRange((1, 0, 0)), (entry,), ValueSchema("object"),
        (FieldClaim("file", "config", claim),),
    )


def contribution(point, payload):
    if isinstance(payload, (RuntimeAdapterDescriptor, ConfigurationAdapterDescriptor)):
        payload = _DescriptorFixture(payload)
    return Contribution(point, "v1", payload, required=True)


class _DescriptorFixture:
    """Metadata-only registry fixture; lifecycle calls are forbidden in these tests."""

    def __init__(self, descriptor):
        self.descriptor = descriptor

    def __getattr__(self, name):
        runtime_methods = {"describe_installation", "describe_targets", "describe_actions",
                           "prepare_launch", "start", "connect", "close", "reconcile",
                           "prepare_reconfiguration", "resume"}
        config_methods = {"assess", "compile", "verify"}
        expected = runtime_methods if isinstance(self.descriptor, RuntimeAdapterDescriptor) else config_methods
        if name in expected:
            def forbidden(*args, **kwargs):
                raise AssertionError("registry admission must not execute adapter methods")
            return forbidden
        raise AttributeError(name)


def stage(handler, owner, *payloads, point):
    return stage_contributions(handler, owner, ContributionBatch(
        tuple(contribution(point, payload) for payload in payloads),
        open_points=frozenset({point}),
    ))


def test_runtime_alias_and_canonical_collisions_refused_before_publication():
    registry = HarnessContributionRegistry()
    first = stage(registry.runtime_handler, "owner.a", runtime("a", "claude-code", ("claude",)), point=RUNTIME_POINT)
    assert registry.runtime_descriptors() == ()
    with pytest.raises(HarnessContributionError):
        stage(registry.runtime_handler, "owner.b", runtime("b", "claude"), point=RUNTIME_POINT)
    first.commit()
    assert registry.runtime_descriptors() == (runtime("a", "claude-code", ("claude",)),)
    with pytest.raises(HarnessContributionError):
        stage(registry.runtime_handler, "owner.b", runtime("b", "claude-code"), point=RUNTIME_POINT)
    registry.runtime_handler.rollback(contribution(RUNTIME_POINT, runtime("a", "claude-code", ("claude",))), first.entries[0][1], "owner.a")
    assert registry.runtime_descriptors() == ()


def test_config_range_and_claim_conflicts_rejected_but_disjoint_ranges_allowed():
    registry = HarnessContributionRegistry()
    a = stage(registry.configuration_handler, "owner.a", config("a", high=(1, 9, 9)), point=CONFIGURATION_POINT)
    with pytest.raises(HarnessContributionError):
        stage(registry.configuration_handler, "owner.b", config("b", low=(1, 9, 9), claim=("other",)), point=CONFIGURATION_POINT)
    with pytest.raises(HarnessContributionError):
        stage(registry.configuration_handler, "owner.b", config("b", facet="skills", claim=("provider", "name")), point=CONFIGURATION_POINT)
    a.commit()
    b = stage(registry.configuration_handler, "owner.b", config("b", low=(2, 0, 0), claim=("other",)), point=CONFIGURATION_POINT)
    b.commit()
    assert len(registry.configuration_descriptors()) == 2


def test_spoofed_owner_and_failed_stage_roll_back_private_reservations():
    registry = HarnessContributionRegistry()
    class Spoof:
        owner = "victim"
        descriptor = runtime("bad", "bad")
    with pytest.raises(HarnessContributionError):
        stage(registry.runtime_handler, "actual", Spoof(), point=RUNTIME_POINT)
    batch = stage(registry.runtime_handler, "actual", runtime("a", "a"), point=RUNTIME_POINT)
    assert registry.runtime_descriptors() == ()
    batch.rollback()
    batch.rollback()
    assert registry.runtime_descriptors() == ()
    stage(registry.runtime_handler, "other", runtime("b", "a"), point=RUNTIME_POINT).commit()


def test_conflicting_second_entry_undoes_first_staged_entry():
    registry = HarnessContributionRegistry()
    with pytest.raises(HarnessContributionError):
        stage(registry.runtime_handler, "owner", runtime("a", "a"), runtime("b", "a"), point=RUNTIME_POINT)
    assert registry.runtime_descriptors() == ()
    stage(registry.runtime_handler, "next", runtime("c", "a"), point=RUNTIME_POINT).commit()


def test_actual_host_injects_owner_and_guards_busy_unload():
    # Test-only import of the actual host. Production registry imports only
    # server_plugin_api and ordessa_harness_api.
    from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost, StreamRouteRegistry
    from server_plugin_api import (
        ContributionOwnerBusyError, ServerPluginDescriptor,
        ServerPluginRegistration,
    )

    class Contributor:
        def descriptor(self):
            return ServerPluginDescriptor("test.harness-owner", "Harness owner", "1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                contribution(RUNTIME_POINT, runtime("a", "pi")),
            )))

    registry = HarnessContributionRegistry()
    host = ServerPluginHost(methods=MethodRegistry(), stream_routes=StreamRouteRegistry())
    host.register_contribution_point(RUNTIME_POINT, "v1", handler=registry.runtime_handler, exclusive=False)
    host.register_contribution_point(CONFIGURATION_POINT, "v1", handler=registry.configuration_handler, exclusive=False)
    host.activate(Contributor())
    assert host.contributions(RUNTIME_POINT)[0].owner == "test.harness-owner"
    payload = host.contributions(RUNTIME_POINT)[0].payload
    admitted = admitted_descriptor(payload, "test.harness-owner", RUNTIME_POINT)
    payload.descriptor = runtime("drifted", "foreign")
    assert admitted_descriptor(payload, "test.harness-owner", RUNTIME_POINT) == admitted
    assert registry.runtime_descriptors() == (admitted,)
    with host.use_contribution(RUNTIME_POINT, consumer=None):
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate("test.harness-owner")
        assert registry.runtime_descriptors()
    host.deactivate("test.harness-owner")
    assert registry.runtime_descriptors() == ()
    with pytest.raises(HarnessContributionError, match="unavailable"):
        admitted_descriptor(payload, "test.harness-owner", RUNTIME_POINT)


def test_admission_snapshots_author_descriptor_before_in_place_mutation():
    registry = HarnessContributionRegistry()
    author = config("author", claim=("provider",))
    payload = _DescriptorFixture(author)
    batch = stage(registry.configuration_handler, "owner.a", payload, point=CONFIGURATION_POINT)
    # A frozen dataclass is not a security boundary against its author.
    object.__setattr__(author, "facet_id", "rogue")
    object.__setattr__(author, "claims", (FieldClaim("file", "config", ("rogue",)),))
    batch.commit()
    admitted = admitted_descriptor(payload, "owner.a", CONFIGURATION_POINT)
    assert admitted.facet_id == "model"
    assert admitted.claims == (FieldClaim("file", "config", ("provider",)),)
    object.__setattr__(admitted, "facet_id", "reader-drift")
    exposed = registry.configuration_descriptors()[0]
    object.__setattr__(exposed, "claims", ())
    assert admitted_descriptor(payload, "owner.a", CONFIGURATION_POINT).facet_id == "model"
    assert registry.configuration_descriptors()[0].claims == (
        FieldClaim("file", "config", ("provider",)),)
    with pytest.raises(HarnessContributionError, match="claims overlap"):
        stage(registry.configuration_handler, "owner.b", config("other", facet="other",
            claim=("provider",)), point=CONFIGURATION_POINT)


@pytest.mark.parametrize("point,payload", (
    (RUNTIME_POINT, runtime("bare", "test-bare")),
    (CONFIGURATION_POINT, config("bare.config", harness="test-bare")),
))
def test_default_product_refuses_descriptor_only_payload_before_publication(tmp_path, point, payload):
    from ordessa_server.bootstrap import build_runtime
    from server_plugin_api import ServerPluginDescriptor, ServerPluginRegistration

    class DescriptorOnly:
        def descriptor(self):
            return ServerPluginDescriptor("test.descriptor-only", "Descriptor only", "1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                Contribution(point, "v1", payload, required=True),
            )))

    product = build_runtime(tmp_path / "data")
    try:
        before = product.plugin_host.contributions(point)
        with pytest.raises(HarnessContributionError, match="Adapter"):
            product.plugin_host.activate(DescriptorOnly())
        assert product.plugin_host.contributions(point) == before
    finally:
        product.stop()


def test_default_product_rolls_back_valid_runtime_if_configuration_shape_fails(tmp_path):
    from ordessa_server.bootstrap import build_runtime
    from server_plugin_api import ServerPluginDescriptor, ServerPluginRegistration

    class MixedBatch:
        def descriptor(self):
            return ServerPluginDescriptor("test.mixed-harness", "Mixed Harness", "1")

        def build(self, context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                contribution(RUNTIME_POINT, runtime("good", "test-good")),
                Contribution(CONFIGURATION_POINT, "v1", config("bad", harness="test-good"), required=True),
            )))

    product = build_runtime(tmp_path / "data")
    try:
        before_config = product.plugin_host.contributions(CONFIGURATION_POINT)
        with pytest.raises(HarnessContributionError, match="ConfigurationAdapter"):
            product.plugin_host.activate(MixedBatch())
        assert product.plugin_host.contributions(RUNTIME_POINT) == ()
        assert product.plugin_host.contributions(CONFIGURATION_POINT) == before_config
        # The failed first reservation must not block a subsequent owner.
        class ValidRuntime:
            def descriptor(self):
                return ServerPluginDescriptor("test.valid-after-rollback", "Valid", "1")

            def build(self, context):
                return ServerPluginRegistration(contributions=ContributionBatch((
                    contribution(RUNTIME_POINT, runtime("good", "test-good")),
                )))

        product.plugin_host.activate(ValidRuntime())
        with product.plugin_host.use_contribution(RUNTIME_POINT) as view:
            assert view.owner == "test.valid-after-rollback"
            assert callable(view.payload.start)
        product.plugin_host.deactivate("test.valid-after-rollback")
    finally:
        product.stop()
