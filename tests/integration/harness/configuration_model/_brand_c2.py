"""Explicit test routing to each brand's public C2 provider surface."""
from __future__ import annotations

import importlib


BRAND_MODULES = {
    "pi": "ordessa_harness_pi",
    "codex": "ordessa_harness_codex",
    "claude-code": "ordessa_harness_claude_code",
}


def c2_module(brand: str):
    try:
        package = BRAND_MODULES[brand]
    except KeyError as error:
        raise ValueError(f"unknown C2 brand: {brand}") from error
    return importlib.import_module(f"{package}.configuration.c2")


def adapter_for(brand: str):
    """Return a new implementation from the brand's public C2 factory."""
    return c2_module(brand).configuration_adapter()


def descriptor_for(brand: str):
    """Return a fresh C2 descriptor from the selected brand provider."""
    return c2_module(brand).descriptor()


def registration_adapters_for(brand: str):
    """Exercise the provider's public registration port for one brand."""
    package = BRAND_MODULES.get(brand)
    if package is None:
        raise ValueError(f"unknown C2 brand: {brand}")
    registration = importlib.import_module(f"{package}.registration")
    return registration.configuration_adapters()


def owner_for_brand(brand: str) -> str:
    if brand not in BRAND_MODULES:
        raise ValueError(f"unknown C2 brand: {brand}")
    return f"ordessa.model-provider.{brand}"


class SelectedBrandC2Plugin:
    """Test-only Server plugin that publishes one brand's real C2 adapter."""

    def __init__(self, brand: str):
        if brand not in BRAND_MODULES:
            raise ValueError(f"unknown C2 brand: {brand}")
        self.brand = brand

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor

        return ServerPluginDescriptor(
            owner_for_brand(self.brand),
            f"Selected {self.brand} C2 provider fixture",
            "1",
        )

    def build(self, context):
        from server_plugin_api import (
            Contribution,
            ContributionBatch,
            ServerPluginRegistration,
        )

        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(
                "harness.configuration-adapters",
                "v1",
                adapter_for(self.brand),
                required=True,
            ),
        )))
