"""The adapters' own declaration surface (PB-2): the three brand
configuration adapters enter the real C2 point
``harness.configuration-adapters`` through THIS plugin's contribution batch —
never through a products/ or host-side composition edit (assembly stays with
core S-03, after the S-08① retirement).

The host injects the owner (the descriptor id below) at stage time; the batch
carries no owner. Activating a second plugin claiming any
``assets.model-provider.*`` adapter id is refused by the real registry
(MP-11), pinned in ``tests/test_c2_registration.py``.
"""
from __future__ import annotations

from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .bridge import BRANDS, BridgeConfigurationAdapter

PLUGIN_ID = "ordessa.model-provider.adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"


class ModelProviderAdaptersPlugin:
    """Registers the Pi/Codex/Claude Code configuration adapters with the host."""

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            PLUGIN_ID, "Model Provider brand configuration adapters", "1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=ContributionBatch(tuple(
            Contribution(CONFIGURATION_POINT, "v1", BridgeConfigurationAdapter(brand),
                         required=True)
            for brand in BRANDS
        ), open_points=frozenset({CONFIGURATION_POINT})))
