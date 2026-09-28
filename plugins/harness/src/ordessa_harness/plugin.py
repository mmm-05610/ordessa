"""Compatibility-free official Harness plugin entry point facade."""
from .entrypoints import create_profile_store, create_codex, create_claude, create_opencode, create_hermes, create_pi
def create_plugin(): return create_codex()
# Direct-instantiation facade retained for the SDK's bundle-level catalog
# checks. It is not an entry point and owns no alternate registry.
class HarnessesPlugin:
    def descriptor(self):
        from pacthold.extensions import PluginDescriptor
        return PluginDescriptor("harnesses", "Agent-Box Harnesses", "2.0.0a1", description="Official declarative Harness bundle", config_namespace="harnesses")
    def build(self, context):
        from pacthold_runtime_compat.api import PluginRegistration
        # Brand-specific implementation stays inside the Harness package.
        from ordessa_harness.codex.credentials import CodexCredentialSource
        registration=create_codex().build(context)
        return PluginRegistration(execution_providers=registration.execution_providers, resource_selectors=registration.resource_selectors, host_controls=registration.host_controls, harness_managers=registration.harness_managers, credential_materializers=(CodexCredentialSource(home=context.agent_box_home),))
