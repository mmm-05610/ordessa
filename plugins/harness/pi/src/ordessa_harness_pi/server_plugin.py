"""Optional host binding for one frozen Pi Harness definition.

Registration describes a Harness and its original installation read owner.
Live Unit creation belongs to the separately bound run-scoped UnitManager.
No provider factory, Unit lifecycle dispatch or native IO occurs here.
"""
from ordessa_execution_api.environment import EnvironmentId, GuaranteeUnavailableError
from ordessa_execution_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration, HarnessCatalog, HARNESS_DEFINITION_VERSION,
    harness_registration_snapshot,
)


class PiServerPlugin:
    def __init__(self, declaration):
        if type(declaration) is not HarnessDefinitionDeclaration:
            raise TypeError("explicit frozen Pi Harness definition declaration required")
        harness_registration_snapshot(declaration)
        if (declaration.descriptor.provider_id != "pi"
                or declaration.descriptor.definition_ref["definitionId"] != "pi"):
            raise ValueError("original Pi provider and definition identity required")
        self._declaration = declaration

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("pi", "Independent Pi AgentUnit", "0.1.0a1")

    def build(self, context):
        catalog = context.ports.get("execution.harness.catalog")
        if type(catalog) is not HarnessCatalog:
            raise GuaranteeUnavailableError("explicit original Harness catalog required")
        if self._declaration.descriptor.definition_ref["environmentNamespace"] != catalog.environment_namespace:
            raise GuaranteeUnavailableError("Pi definition in the original namespace required")
        # Only metadata publication: no Unit factory, native observer or grants.
        payload = (self._declaration,)
        from server_plugin_api import Contribution, ContributionBatch, ServerPluginRegistration
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            "execution.harness.definitions", HARNESS_DEFINITION_VERSION,
            payload, required=True),)))
