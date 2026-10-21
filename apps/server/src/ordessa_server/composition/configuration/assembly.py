"""One host contribution registry shared by declarations and pre-binding."""
from ordessa_server_plugin_api import ContributionPointSpec, unique_contribution_point_specs
from .contributions import (CONFIGURATION_POINT, POINT_API_VERSION, RUNTIME_POINT,
                            HarnessContributionRegistry)


class HarnessContributionAssembly:
    def __init__(self):
        self._registry = HarnessContributionRegistry()
        self._specs = unique_contribution_point_specs((
            ContributionPointSpec(RUNTIME_POINT, POINT_API_VERSION,
                                  self._registry.runtime_handler, exclusive=False),
            ContributionPointSpec(CONFIGURATION_POINT, POINT_API_VERSION,
                                  self._registry.configuration_handler, exclusive=False),
        ))

    def server_contribution_points(self):
        return self._specs

    def bind_contribution_points(self, host):
        host.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                        handler=self._registry.configuration_handler)

    def admitted_descriptor(self, payload, owner, point):
        return self._registry.admitted_descriptor(payload, owner, point)

    def bind_carrier(self, carrier):
        self._registry.bind_carrier(carrier)
