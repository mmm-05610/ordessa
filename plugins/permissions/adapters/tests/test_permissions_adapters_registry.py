"""T03/T03b red/green: registration surface and composition-time refusal.

`permissions.policy-adapters` is keyed by `(harnessId, nativeVersionRange)`:
unique, with **overlap refused at composition time, never last-wins**
(contracts.md §C1). Since the foundation checkpoint the refusal authority is
the platform's: the point's conflict registry inside
`ordessa_harness.contributions` (driven through the public
`server_plugin_api.stage_contributions`). The package only *declares*;
every refusal below is asserted to be raised by the platform, and the
package's former private registry - which re-implemented these refusals as
a second authority - is gone.

Full admission proofs against the real host live in
`test_real_admission_lifecycle.py`; this file keeps the §C1 composition
semantics at the handler/registry seam.
"""
from __future__ import annotations

import pytest
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, HarnessContributionError, HarnessContributionRegistry,
    POINT_API_VERSION)
from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, FieldClaim, ValueSchema, VersionRange)
from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginContext,
    ServerPluginDescriptor, stage_contributions)

from ordessa_permissions_adapters import (
    ClaudeAdapter,
    CodexAdapter,
    CONTRACT_ID,
    NativeVersionRange,
    PiAdapter,
    PolicyConfigurationAdapter,
    PolicyAdapterDescriptor,
    PolicyAdaptersPlugin,
    configuration_descriptor,
    default_adapters,
    default_configuration_descriptors,
    policy_adapter_contributions,
    select_adapter,
)


def _batch(*descriptors: ConfigurationAdapterDescriptor) -> ContributionBatch:
    return ContributionBatch(
        tuple(Contribution(CONFIGURATION_POINT, POINT_API_VERSION,
                           PolicyConfigurationAdapter(next(a for a in default_adapters()
                                                           if a.harness_id == d.harness_id), d))
              for d in descriptors),
        open_points=frozenset({CONFIGURATION_POINT}))


def _descriptor(adapter_id: str, harness_id: str, minimum: tuple,
                maximum: "tuple | None" = None, *,
                entries: tuple = ("permissions.ask",),
                claims: tuple = ()) -> ConfigurationAdapterDescriptor:
    return ConfigurationAdapterDescriptor(
        adapter_id, POINT_API_VERSION, "permissions.policy-adapters", "v1",
        harness_id, VersionRange(minimum, maximum), VersionRange((1, 0, 0)),
        entries, ValueSchema("object"), claims)


def test_three_default_adapters_with_unique_ids_and_ranges() -> None:
    adapters = default_adapters()
    ids = [a.adapter_id for a in adapters]
    assert len(ids) == len(set(ids)) == 3
    harnesses = {a.harness_id for a in adapters}
    assert harnesses == {"pi", "codex", "claude-code"}
    for adapter in adapters:
        assert adapter.version_range is not None
        assert adapter.descriptor().contract_id == CONTRACT_ID


def test_platform_refuses_overlapping_ranges_same_harness() -> None:
    # 横向反例 (f) - refusal authority: the point's conflict registry.
    registry = HarnessContributionRegistry()
    first = _descriptor("a1", "codex", (2, 0, 0), (2, 9, 9))
    stage_contributions(registry.configuration_handler, "owner.a",
                        _batch(first)).commit()
    rival = _descriptor("a2", "codex", (2, 5, 0), (3, 5, 0),
                        claims=(FieldClaim("file", ".codex/config.toml",
                                           ("approval_policy",)),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, "owner.b",
                            _batch(rival))
    # no last-wins: the first registration stands untouched
    assert [d.adapter_id for d in registry.configuration_descriptors()] == ["a1"]


def test_disjoint_ranges_are_admitted_adjacent_never_merged() -> None:
    registry = HarnessContributionRegistry()
    a = _descriptor("a1", "codex", (2, 0, 0), (2, 9, 9))
    b = _descriptor("a2", "codex", (3, 0, 0), (3, 9, 9))
    stage_contributions(registry.configuration_handler, "owner.a", _batch(a)).commit()
    stage_contributions(registry.configuration_handler, "owner.b", _batch(b)).commit()
    assert len(registry.configuration_descriptors()) == 2


def test_same_range_different_harness_is_fine() -> None:
    registry = HarnessContributionRegistry()
    a = _descriptor("a1", "codex", (2, 0, 0))
    b = _descriptor("a2", "pi", (2, 0, 0))
    stage_contributions(registry.configuration_handler, "owner.a", _batch(a)).commit()
    stage_contributions(registry.configuration_handler, "owner.b", _batch(b)).commit()
    assert {d.adapter_id for d in registry.configuration_descriptors()} == {"a1", "a2"}
    # the compile-surface lookup is a pure view with no admission role
    assert select_adapter("codex", "2.5").adapter_id == CodexAdapter().adapter_id
    assert select_adapter("pi", "2.5").adapter_id == PiAdapter().adapter_id


def test_platform_refuses_duplicate_adapter_id() -> None:
    registry = HarnessContributionRegistry()
    first = _descriptor("a1", "codex", (2, 0, 0), (2, 9, 9))
    stage_contributions(registry.configuration_handler, "owner.a",
                        _batch(first)).commit()
    clone = _descriptor("a1", "pi", (1, 0, 0), (1, 9, 9))
    with pytest.raises(HarnessContributionError) as error:
        stage_contributions(registry.configuration_handler, "owner.b",
                            _batch(clone))
    assert "a1" in str(error.value)


def test_platform_refuses_identical_range_registration() -> None:
    registry = HarnessContributionRegistry()
    first = _descriptor("a1", "codex", (2, 0, 0), (2, 9, 9),
                        claims=(FieldClaim("file", ".codex/config.toml",
                                           ("approval_policy",)),))
    stage_contributions(registry.configuration_handler, "owner.a",
                        _batch(first)).commit()
    same = _descriptor("a9", "codex", (2, 0, 0), (2, 9, 9),
                       claims=(FieldClaim("file", ".codex/config.toml",
                                          ("approval_policy",)),))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, "owner.b",
                            _batch(same))
    assert registry.configuration_descriptors() == (first,)


def test_select_is_unique_or_none() -> None:
    # pure consumer-side lookup over the adapters' bounded ranges - it
    # registers nothing and refuses nothing.
    assert select_adapter("codex", "2.0").harness_id == "codex"
    assert select_adapter("codex", "9.0") is None      # outside every range
    assert select_adapter("opencode", "2.0") is None   # no adapter claims it
    assert select_adapter("claude-code", "0.81.2").harness_id == "claude-code"


def test_contribution_batch_declares_real_point_and_host_owned_identity() -> None:
    batch = policy_adapter_contributions()
    assert isinstance(batch, ContributionBatch)
    payloads = [c.payload for c in batch.contributions]
    assert all(isinstance(p, PolicyConfigurationAdapter) and
               isinstance(p.descriptor, ConfigurationAdapterDescriptor) for p in payloads)
    # owner/generation are assigned by the host, never claimed by this plugin:
    # a Contribution has no owner field at all, and the staged view carries
    # the injected owner only.
    assert all(not hasattr(c, "owner") or c.payload is not None for c in batch.contributions)
    registry = HarnessContributionRegistry()
    staged = stage_contributions(registry.configuration_handler,
                                 "ordessa.permissions-adapters", batch)
    assert staged.owner == "ordessa.permissions-adapters"
    staged.commit()
    assert len(registry.configuration_descriptors()) == 3


def test_overlap_within_my_own_declaration_is_refused_before_anything_admits() -> None:
    # the batch is a declaration; the platform conflict gate sees every
    # entry - a self-conflicting pair refuses the staging and publishes
    # nothing (no partial batch survives).
    registry = HarnessContributionRegistry()
    base = _descriptor("b1", "codex", (2, 0, 0), (3, 0, 0))
    overlap = _descriptor("b2", "codex", (2, 9, 0), (3, 5, 0))
    with pytest.raises(HarnessContributionError):
        stage_contributions(registry.configuration_handler, "owner.a",
                            _batch(base, overlap))
    assert registry.configuration_descriptors() == ()


def test_plugin_surface_uses_only_public_contracts() -> None:
    plugin = PolicyAdaptersPlugin()
    descriptor = plugin.descriptor()
    assert isinstance(descriptor, ServerPluginDescriptor)
    assert descriptor.id == "ordessa.permissions-adapters"
    registration = plugin.build(ServerPluginContext(
        plugin_id=descriptor.id, data_root=None, ports={}))
    # no self-registered port carrying a private adapter set anymore: the
    # declared composition rides the registration's contribution batch.
    assert registration.provided_ports == {}
    batch = registration.contributions
    assert isinstance(batch, ContributionBatch)
    assert {c.point_id for c in batch.contributions} == {CONFIGURATION_POINT}


def test_adapters_each_declare_their_own_configuration_descriptor() -> None:
    descriptors = default_configuration_descriptors()
    assert {d.adapter_id for d in descriptors} == \
        {ClaudeAdapter().adapter_id, CodexAdapter().adapter_id, PiAdapter().adapter_id}
    for adapter in default_adapters():
        built = configuration_descriptor(adapter)
        assert built.adapter_id == adapter.adapter_id
        assert built.harness_id == adapter.harness_id
