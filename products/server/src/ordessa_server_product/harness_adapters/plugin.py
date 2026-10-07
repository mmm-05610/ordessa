"""Historical metadata facade; migrated runtime construction is refused."""
from .entrypoints import create_profile_store, create_codex, create_claude, create_opencode, create_hermes, create_pi
def create_plugin(): return create_codex()
# Direct-instantiation facade retained for the SDK's bundle-level catalog
# checks. It is not an entry point and owns no alternate registry.
class HarnessesPlugin:
    def descriptor(self):
        from pacthold.extensions import PluginDescriptor
        return PluginDescriptor("harnesses", "Agent-Box Harnesses", "2.0.0a1", description="Official declarative Harness bundle", config_namespace="harnesses")
    def build(self, context):
        from ordessa_environment_api import GuaranteeUnavailableError
        raise GuaranteeUnavailableError('Unified Codex runtime facade is retired; admit the independent provider explicitly')
