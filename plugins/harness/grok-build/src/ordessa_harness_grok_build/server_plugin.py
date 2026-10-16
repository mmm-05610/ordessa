"""Optional metadata-only registration of Grok Build's frozen definition."""
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_execution_agents.harness.providers.registry import (
    HARNESS_DEFINITION_VERSION,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    harness_registration_snapshot,
)


class GrokBuildServerPlugin:
    def __init__(self, declaration):
        if type(declaration) is not HarnessDefinitionDeclaration:
            raise TypeError("explicit frozen Grok Build Harness definition declaration required")
        harness_registration_snapshot(declaration)
        if (declaration.descriptor.provider_id != "grok-build"
                or declaration.descriptor.definition_ref["definitionId"] != "grok-build"):
            raise ValueError("original Grok Build provider and definition identity required")
        self._declaration = declaration

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("grok-build", "xAI Grok Build AgentUnit", "0.1.0a1")

    def build(self, context):
        catalog = context.ports.get("execution.harness.catalog")
        if type(catalog) is not HarnessCatalog:
            raise GuaranteeUnavailableError("explicit original Harness catalog required")
        if self._declaration.descriptor.definition_ref["environmentNamespace"] != catalog.environment_namespace:
            raise GuaranteeUnavailableError("Grok Build definition in the original namespace required")
        from server_plugin_api import Contribution, ContributionBatch, ServerPluginRegistration
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            "execution.harness.definitions", HARNESS_DEFINITION_VERSION,
            (self._declaration,), required=True),)))
