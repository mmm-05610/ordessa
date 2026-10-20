"""The adapters' own declaration surface (RA-1): the eight brand
configuration adapters enter the real C2 point
``harness.configuration-adapters`` through THIS plugin's contribution batch —
never through a products/ or host-side composition edit.

The host injects the owner (the descriptor id below) at stage time; the batch
carries no owner. Activating a second plugin claiming any
``assets.runtime-preferences.*`` adapter id is refused by the real registry
(pinned in ``tests/test_adapters_conformance.py``).
"""
from __future__ import annotations

from server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .bridge import BRANDS, BridgeConfigurationAdapter

PLUGIN_ID = "ordessa.runtime-preferences.adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"


class RuntimePreferencesAdaptersPlugin:
    """Registers the eight brand configuration adapters with the host."""

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            PLUGIN_ID, "Runtime preferences brand configuration adapters", "1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=ContributionBatch(tuple(
            Contribution(CONFIGURATION_POINT, "v1", BridgeConfigurationAdapter(brand),
                         required=True)
            for brand in BRANDS
        ), open_points=frozenset({CONFIGURATION_POINT})))
