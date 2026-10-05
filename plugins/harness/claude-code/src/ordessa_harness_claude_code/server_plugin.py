"""Optional Server host binding; no registration or native IO at import.

Provider construction belongs to explicit deployment. Host stages the payload
through its sole Environment; this adapter never grants invocation authority.
"""
from ordessa_environment_api import EnvironmentId, GuaranteeUnavailableError
from pacthold.agents.public import AgentContributionSet
from .provider import ClaudeCodeRuntimeProvider


class ClaudeCodeServerPlugin:
    def __init__(self, provider_factory):
        if not callable(provider_factory):
            raise TypeError("explicit provider factory required")
        self._factory = provider_factory

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("claude-code", "Independent ClaudeCode AgentUnit", "0.1.0a1")

    def build(self, context):
        from server_plugin_api import (Contribution, ContributionBatch,
            ServerPluginRegistration, PACTHOLD_CONTRIBUTIONS_POINT_ID,
            PACTHOLD_CONTRIBUTIONS_API_VERSION)
        binding = context.ports.get("core.binding")
        if binding is None:
            raise GuaranteeUnavailableError("existing Environment binding required")
        environment_id = EnvironmentId(binding.environment.environment_id)
        provider = self._factory(environment_id)
        if (not isinstance(provider, ClaudeCodeRuntimeProvider)
                or provider.descriptor.provider_id != "claude"
                or provider.descriptor.definition_ref["environmentNamespace"] != environment_id.value):
            raise GuaranteeUnavailableError("independent provider family or Environment differs")
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            AgentContributionSet(agent_runtime_providers=(provider,)), required=True),)))
