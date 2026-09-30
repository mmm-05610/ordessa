"""Harness-owned declaration surface for native model configuration.

Each brand registers its implementations; this explicit assembly publishes
their contribution batch through the existing C2 point. Product composition
selects this entry, while hosts remain unaware of native model semantics.

The historical plugin/adapter ids stay stable for persisted operation identity.
The old model-provider-adapters Python source distribution has been retired.

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

from ...pi.registration import configuration_adapters as pi_adapters
from ...codex.registration import configuration_adapters as codex_adapters
from ...claude.registration import configuration_adapters as claude_adapters

PLUGIN_ID = "ordessa.model-provider.adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"


class ModelProviderAdaptersPlugin:
    """Harness entry; historical class spelling retained for existing callers."""

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            PLUGIN_ID, "Harness native model configuration adapters", "1")

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(contributions=ContributionBatch(tuple(
            Contribution(CONFIGURATION_POINT, "v1", adapter,
                         required=True)
            for factory in (pi_adapters, codex_adapters, claude_adapters)
            for adapter in factory()
        ), open_points=frozenset({CONFIGURATION_POINT})))
