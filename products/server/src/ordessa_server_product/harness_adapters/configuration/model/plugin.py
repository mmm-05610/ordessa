"""Retired three-family C2 assembly metadata.

The historical descriptor id is retained for persisted operation identity.
Pure model contracts and compilers remain migration sources; this batch can no
longer activate Pi/Codex/Claude under a single owner. Independent providers own
new configuration effects through the public AgentUnit management contract.
"""
from __future__ import annotations

from server_plugin_api import ServerPluginDescriptor, ServerPluginRegistration

PLUGIN_ID = "ordessa.model-provider.adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"


class ModelProviderAdaptersPlugin:
    """Historical descriptor retained; old effect registration is refused."""

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            PLUGIN_ID, "Harness native model configuration adapters", "1")

    def build(self, context) -> ServerPluginRegistration:
        from ordessa_environment_api import GuaranteeUnavailableError
        raise GuaranteeUnavailableError(
            "Migrated Harness model configuration requires explicit independent provider admission")
