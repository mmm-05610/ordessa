"""T05b — lifecycle on the REAL product host (foundation `build_runtime`).

Follows the platform's own third-party example
(`plugins/harness/tests/test_external_adapter_product.py`): the default
product registers the two Harness points, and the host owns admission,
owner identity, publication visibility and busy retirement. Proven here:

* activating the sandbox plugin publishes its three facet descriptors on the
  real point with the host-assigned owner;
* a failed staging round publishes nothing (no half-admitted batch);
* an unknown point id yields the platform's typed
  ``ContributionPointUnboundError`` — a declared-but-unknown point drops
  nothing and never silently admits the contribution;
* a wrong api_version yields ``ContributionVersionRefusedError``;
* while a consumer holds a resolution, unloading the owner raises
  ``ContributionOwnerBusyError`` — the platform-provided busy refusal.
"""
from __future__ import annotations

import pytest
from ordessa_harness.contributions import CONFIGURATION_POINT, HarnessContributionError
from ordessa_harness.application import ConfigurationApplicationService, OperationJournal, RuntimeSnapshot
from ordessa_harness.materialization import MergeAuthority
from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, ApplicationTarget, Assessment, ErrorCode, Installation,
    TargetDescriptor, TargetHandle, VerificationUnknown,
)
from _sandbox_adapters_helpers import build_compat_runtime
from server_plugin_api import (
    Contribution,
    ContributionBatch,
    ContributionOwnerBusyError,
    ContributionPointUnboundError,
    ContributionVersionRefusedError,
    ServerContributionHandler,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_sandbox_adapters import (
    ADAPTER_PLUGIN_ID,
    SANDBOX_CONFIGURATION_POINT_ID,
    SANDBOX_POINT_API_VERSION,
    SandboxAdaptersServerPlugin,
    build_configuration_descriptor,
    CodexSandboxAdapter,
    HarnessSandboxConfigurationAdapter,
)

CODEX_DESCRIPTOR = build_configuration_descriptor(CodexSandboxAdapter())


class _RecordingHandler(ServerContributionHandler):
    """Minimal host-side handler for a private busy-proof point: the busy
    refusal is the HOST's lease authority, independent of the payload."""

    def __init__(self) -> None:
        self.committed: list[Contribution] = []

    def stage(self, contribution, owner):
        return (owner, contribution)

    def commit(self, contribution, prepared, owner):
        self.committed.append(contribution)

    def rollback(self, contribution, prepared, owner):
        if contribution in self.committed:
            self.committed.remove(contribution)


class _StubPlugin:
    def __init__(self, plugin_id: str, batch: ContributionBatch) -> None:
        self._id = plugin_id
        self._batch = batch

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(self._id, "stub", "1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=self._batch)


def test_real_product_admits_the_three_brand_descriptors(tmp_path):
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        assert host.contributions(CONFIGURATION_POINT) == ()
        host.activate(SandboxAdaptersServerPlugin())
        views = host.contributions(CONFIGURATION_POINT)
        assert len(views) == 3
        assert {view.owner for view in views} == {ADAPTER_PLUGIN_ID}
        assert {view.payload.descriptor.adapter_id for view in views} == {
            "sandbox.native-config.codex", "sandbox.native-config.claude-code",
            "sandbox.native-config.pi"}
        assert all(view.api_version == SANDBOX_POINT_API_VERSION and
                   view.point_id == SANDBOX_CONFIGURATION_POINT_ID for view in views)
        # retirement: no hold outstanding, so the owner may leave cleanly
        host.deactivate(ADAPTER_PLUGIN_ID)
        assert host.contributions(CONFIGURATION_POINT) == ()
    finally:
        runtime.stop()


def test_real_product_carrier_exposes_callable_c2_with_honest_unknown_and_refusal(tmp_path):
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        host.activate(SandboxAdaptersServerPlugin(adapters=(CodexSandboxAdapter(),)))
        with host.use_contribution(CONFIGURATION_POINT, consumer=None) as held:
            adapter = held.payload
            descriptor = adapter.descriptor
            context = AdapterContext(
                (TargetDescriptor(TargetHandle("controlled-config", 1), "file", "toml",
                                  "instance", (("sandbox_mode",),)),),
                Installation(descriptor.harness_id, descriptor.native_versions.minimum,
                             descriptor.adapter_versions.minimum, "controlled:native"),
                descriptor.entries[0], "instance", "controlled:capability")
            desired = {"sandbox_mode": "read-only"}
            assessment = adapter.assess(context, desired)
            assert isinstance(assessment, Assessment) and assessment.status == "unknown"
            refusal = adapter.compile(context, {}, desired)
            assert isinstance(refusal, AdapterRefusal)
            assert refusal.code is ErrorCode.AUTHORIZATION_REFUSED
            assert isinstance(adapter.verify(context, desired), VerificationUnknown)
        host.deactivate(ADAPTER_PLUGIN_ID)
    finally:
        runtime.stop()


def test_real_product_c4_inspect_keeps_codex_empty_probe_typed_unknown(tmp_path):
    product = build_compat_runtime(tmp_path / "data")
    host = product.plugin_host
    target = ApplicationTarget("controlled-server", "controlled-session", "controlled-channel", 1)
    descriptor = CODEX_DESCRIPTOR
    context = AdapterContext((), Installation(descriptor.harness_id,
        descriptor.native_versions.minimum, descriptor.adapter_versions.minimum,
        "controlled:native"), descriptor.entries[0], "instance", "controlled:capability")

    class ReadOnlyRuntime:
        def capture(self, requested):
            return RuntimeSnapshot(requested, context, MergeAuthority(()), {}, {}, tmp_path,
                {}, "base-1", "controlled:native-version", 1, "auth-1", "secret-1")

    try:
        host.activate(SandboxAdaptersServerPlugin(adapters=(CodexSandboxAdapter(),)))
        service = ConfigurationApplicationService(principal="controlled", target=target,
            carrier=host, runtime=ReadOnlyRuntime(), permits=object(),
            journal=OperationJournal(tmp_path / "operations.sqlite"))
        capabilities = service.inspect(target)
        assert len(capabilities.capabilities) == 2
        assert {item.status for item in capabilities.capabilities} == {"unknown"}
        assert {item.operation for item in capabilities.capabilities} == {"set", "reset"}
    finally:
        product.stop()


@pytest.mark.parametrize("desired", (
    {"sandbox_mode": "danger-full-access"},
    {"sandbox_mode": "read-only", "shell": "arbitrary"},
    ["read-only"],
))
def test_callable_c2_rejects_malformed_desired_without_schema_exception(desired):
    payload = HarnessSandboxConfigurationAdapter(CODEX_DESCRIPTOR, CodexSandboxAdapter())
    context = AdapterContext((), Installation("codex", CODEX_DESCRIPTOR.native_versions.minimum,
        CODEX_DESCRIPTOR.adapter_versions.minimum, "controlled:native"),
        CODEX_DESCRIPTOR.entries[0], "instance", "controlled:capability")
    assessment = payload.assess(context, desired)
    assert isinstance(assessment, Assessment) and assessment.status == "unsupported"
    refusal = payload.compile(context, {}, desired)
    assert isinstance(refusal, AdapterRefusal) and refusal.code is ErrorCode.INVALID_FRAGMENT
    assert isinstance(payload.verify(context, desired), VerificationUnknown)


def test_callable_c2_accepts_shape_but_refuses_effect_without_sandbox_facts():
    payload = HarnessSandboxConfigurationAdapter(CODEX_DESCRIPTOR, CodexSandboxAdapter())
    context = AdapterContext((), Installation("codex", CODEX_DESCRIPTOR.native_versions.minimum,
        CODEX_DESCRIPTOR.adapter_versions.minimum, "controlled:native"),
        CODEX_DESCRIPTOR.entries[0], "instance", "controlled:capability")
    desired = {"sandbox_mode": "read-only"}
    assert payload.assess(context, {}).status == "unknown"  # read-only capability probe
    assert payload.compile(context, {}, {}).code is ErrorCode.INVALID_FRAGMENT
    assert payload.assess(context, desired).status == "unknown"
    refusal = payload.compile(context, {}, desired)
    assert refusal.code is ErrorCode.AUTHORIZATION_REFUSED


def test_failed_round_publishes_nothing(tmp_path):
    """Two sandbox descriptors whose claims collide stage in one batch: the
    platform refuses the pair and the real host publishes NOTHING."""
    from ordessa_harness_api import FieldClaim, ValueSchema, VersionRange
    twin = CODEX_DESCRIPTOR.__class__(
        "sandbox.codex.twin", "v1", "sandbox.native-configuration", "1", "codex",
        CODEX_DESCRIPTOR.native_versions, CODEX_DESCRIPTOR.adapter_versions,
        ("sandbox_mode",), ValueSchema("object"),
        (FieldClaim("file", CODEX_DESCRIPTOR.claims[0].target_id, ("sandbox_mode",)),))
    batch = ContributionBatch(
        (Contribution(CONFIGURATION_POINT, "v1", HarnessSandboxConfigurationAdapter(CODEX_DESCRIPTOR, CodexSandboxAdapter())),
         Contribution(CONFIGURATION_POINT, "v1", HarnessSandboxConfigurationAdapter(twin, object()))),
        open_points=frozenset({CONFIGURATION_POINT}))
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        with pytest.raises(HarnessContributionError):
            host.activate(_StubPlugin("t05b.conflicting-stub", batch))
        # nothing half-admitted: the published view stayed empty
        assert host.contributions(CONFIGURATION_POINT) == ()
    finally:
        runtime.stop()


def test_unknown_point_id_yields_the_typed_unbound_refusal(tmp_path):
    batch = ContributionBatch((
        Contribution("sandbox.not-a-real-point", SANDBOX_POINT_API_VERSION,
                     CODEX_DESCRIPTOR),))
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        with pytest.raises(ContributionPointUnboundError):
            host.activate(_StubPlugin("t05b.unbound-stub", batch))
        assert host.contributions(CONFIGURATION_POINT) == ()
    finally:
        runtime.stop()


def test_wrong_api_version_yields_the_typed_version_refusal(tmp_path):
    batch = ContributionBatch((
        Contribution(CONFIGURATION_POINT, "v2", CODEX_DESCRIPTOR),))
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    try:
        with pytest.raises(ContributionVersionRefusedError):
            host.activate(_StubPlugin("t05b.version-stub", batch))
    finally:
        runtime.stop()


def test_still_used_adapter_reports_owner_busy(tmp_path):
    """`use_contribution` holds the owner for the window; the platform's
    `ContributionOwnerBusyError` refuses retirement until the hold is gone
    (contracts.md §C4: 仍使用该 adapter 的实例必须 busy/deferred)."""
    handler = _RecordingHandler()
    runtime = build_compat_runtime(tmp_path / "data")
    host = runtime.plugin_host
    busy_point = "sandbox.busy-proof"
    try:
        host.register_contribution_point(busy_point, "v1", handler=handler,
                                         exclusive=True)
        batch = ContributionBatch((Contribution(busy_point, "v1",
                                                CODEX_DESCRIPTOR,
                                                required=True),))
        host.activate(_StubPlugin("t05b.busy-owner", batch))
        with host.use_contribution(busy_point) as held:
            assert held.payload is CODEX_DESCRIPTOR
            assert host.owner_busy("t05b.busy-owner") is True
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate("t05b.busy-owner")
        # hold released: retirement is now allowed
        assert host.owner_busy("t05b.busy-owner") is False
        host.deactivate("t05b.busy-owner")
        assert host.contributions(busy_point) == ()
    finally:
        runtime.stop()
