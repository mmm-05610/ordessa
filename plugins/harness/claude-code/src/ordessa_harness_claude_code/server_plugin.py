"""Optional metadata-only registration of Claude's frozen definition."""
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_execution_agents.harness.providers.registry import (
    HARNESS_DEFINITION_VERSION,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    harness_registration_snapshot,
)


class ClaudeCodeServerPlugin:
    def __init__(self, declaration):
        if type(declaration) is not HarnessDefinitionDeclaration:
            raise TypeError("explicit frozen Claude Harness definition declaration required")
        harness_registration_snapshot(declaration)
        if (declaration.descriptor.provider_id != "claude"
                or declaration.descriptor.definition_ref["definitionId"] != "claude"):
            raise ValueError("original Claude provider and definition identity required")
        self._declaration = declaration

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("claude-code", "Independent ClaudeCode AgentUnit", "0.1.0a1")

    def build(self, context):
        catalog = context.ports.get("execution.harness.catalog")
        if type(catalog) is not HarnessCatalog:
            raise GuaranteeUnavailableError("explicit original Harness catalog required")
        if self._declaration.descriptor.definition_ref["environmentNamespace"] != catalog.environment_namespace:
            raise GuaranteeUnavailableError("Claude definition in the original namespace required")
        from server_plugin_api import Contribution, ContributionBatch, ServerPluginRegistration
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            "execution.harness.definitions", HARNESS_DEFINITION_VERSION,
            (self._declaration,), required=True),)))
