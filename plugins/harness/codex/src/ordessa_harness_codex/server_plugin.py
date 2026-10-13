"""Optional metadata-only registration of Codex's frozen Harness definition."""
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_execution_agents.harness.providers.registry import (
    HARNESS_DEFINITION_VERSION,
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    harness_registration_snapshot,
)


class CodexServerPlugin:
    def __init__(self, declaration):
        if type(declaration) is not HarnessDefinitionDeclaration:
            raise TypeError("explicit frozen Codex Harness definition declaration required")
        harness_registration_snapshot(declaration)
        if (declaration.descriptor.provider_id != "codex"
                or declaration.descriptor.definition_ref["definitionId"] != "codex"):
            raise ValueError("original Codex provider and definition identity required")
        self._declaration = declaration

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("codex", "Independent Codex AgentUnit", "0.1.0a1")

    def build(self, context):
        catalog = context.ports.get("execution.harness.catalog")
        if type(catalog) is not HarnessCatalog:
            raise GuaranteeUnavailableError("explicit original Harness catalog required")
        if self._declaration.descriptor.definition_ref["environmentNamespace"] != catalog.environment_namespace:
            raise GuaranteeUnavailableError("Codex definition in the original namespace required")
        from server_plugin_api import Contribution, ContributionBatch, ServerPluginRegistration
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            "execution.harness.definitions", HARNESS_DEFINITION_VERSION,
            (self._declaration,), required=True),)))
