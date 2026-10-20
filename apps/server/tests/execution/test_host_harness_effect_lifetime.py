"""Captured Host contribution assembly lifetime; no service/model effects."""
from ordessa_server_product.composition import ProductCompositionUnavailable
from types import SimpleNamespace
import pytest
from ordessa_server.composition import runtime
from ordessa_server_product.composition import create_composition
from ordessa_server.composition.configuration.assembly import HarnessContributionAssembly
from ordessa_server.composition.native_channels.plugin import AcpChannelServerPlugin


def test_repeated_selected_product_resolution_reuses_same_explicit_instances(monkeypatch):
    composition = create_composition()
    point = SimpleNamespace(load=lambda: lambda: composition)
    entries = SimpleNamespace(select=lambda **kwargs: (point,))
    monkeypatch.setattr("importlib.metadata.entry_points", lambda: entries)
    first = runtime._resolve_product_composition()
    assert first.host_harness_effects is None
    assert first.server_contribution_points() == ()
    assembly = HarnessContributionAssembly()
    first.bind_host_harness_effects(channel_plugin_factory=AcpChannelServerPlugin,
                                   contribution_assembly=assembly)
    registry = first.bound_harness_registry
    assert runtime._resolve_product_composition() is first
    assert first.host_harness_effects is assembly
    assert first.bound_harness_registry is registry
    first.bind_host_harness_effects(channel_plugin_factory=AcpChannelServerPlugin,
                                   contribution_assembly=assembly)
    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        first.bind_host_harness_effects(channel_plugin_factory=AcpChannelServerPlugin,
                                       contribution_assembly=HarnessContributionAssembly())
    assert first.host_harness_effects is assembly
