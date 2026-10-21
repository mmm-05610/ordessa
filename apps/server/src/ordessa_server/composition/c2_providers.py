"""Host publication of one explicitly selected independent public C2 provider.

Selection supplies a public provider factory. This host layer neither discovers
brands nor issues a new authority: publication uses the existing PluginHost.
"""
from __future__ import annotations

from ordessa_agents.harness.definitions import ConfigurationAdapterDescriptor
from ordessa_server_plugin_api import (
    Contribution, ContributionBatch, ServerPluginDescriptor, ServerPluginRegistration,
)

CONFIGURATION_POINT = 'harness.configuration-adapters'


class SelectedC2ProviderPlugin:
    def __init__(self, *, configuration_adapters):
        if not callable(configuration_adapters):
            raise TypeError('Explicit public configuration provider factory required')
        adapters = tuple(configuration_adapters())
        if len(adapters) != 1:
            raise ValueError('Exactly one independent C2 provider required')
        descriptor = adapters[0].descriptor
        if not isinstance(descriptor, ConfigurationAdapterDescriptor):
            raise TypeError('Public C2 configuration descriptor required')
        self._adapters = adapters
        self._descriptor = ServerPluginDescriptor(
            'ordessa.model-provider.' + descriptor.harness_id,
            'Selected ' + descriptor.harness_id + ' C2 model provider', '1')

    def descriptor(self):
        return self._descriptor

    def build(self, context):
        return ServerPluginRegistration(contributions=ContributionBatch(
            tuple(Contribution(CONFIGURATION_POINT, 'v1', adapter, required=True)
                  for adapter in self._adapters),
            open_points=frozenset({CONFIGURATION_POINT})))


def configuration_provider_plugin(*, configuration_adapters):
    """Return one selected provider plugin; no default selection or fallback."""
    return SelectedC2ProviderPlugin(configuration_adapters=configuration_adapters)
