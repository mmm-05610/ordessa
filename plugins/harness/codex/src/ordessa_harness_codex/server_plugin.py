"""Optional Server host binding; no registration or native IO at import.

Provider construction belongs to explicit deployment. Host stages the payload
through its sole Environment; this adapter never grants invocation authority.
"""
from ordessa_environment_api import EnvironmentId, GuaranteeUnavailableError
from pacthold.agents.public import AgentContributionSet
from .provider import CodexRuntimeProvider


class CodexServerPlugin:
    def __init__(self, provider_factory):
        if not callable(provider_factory):
            raise TypeError("explicit provider factory required")
        self._factory = provider_factory

    def descriptor(self):
        from server_plugin_api import ServerPluginDescriptor
        return ServerPluginDescriptor("codex", "Independent Codex AgentUnit", "0.1.0a1")

    def build(self, context):
        from server_plugin_api import (Contribution, ContributionBatch,
            ServerPluginRegistration, PACTHOLD_CONTRIBUTIONS_POINT_ID,
            PACTHOLD_CONTRIBUTIONS_API_VERSION)
        binding = context.ports.get("core.binding")
        if binding is None:
            raise GuaranteeUnavailableError("existing Environment binding required")
        environment_id = EnvironmentId(binding.environment.environment_id)
        # Explicitly assembled owner view when the deployment staged one; absent
        # (legacy/discovery deployments) means the factory degrades to
        # discovery-only capabilities and must never be asked to fake one.
        owner = getattr(binding.environment, "owner_ports", None)
        owner_view = getattr(owner, "provider_view", None) if owner is not None else None
        provider = self._factory(environment_id, owner_view)
        if (not isinstance(provider, CodexRuntimeProvider)
                or provider.descriptor.provider_id != "codex"
                or provider.descriptor.definition_ref["environmentNamespace"] != environment_id.value):
            raise GuaranteeUnavailableError("independent provider family or Environment differs")
        if owner_view is not None:
            # The provider must consume exactly the owner's original records and
            # verifier: a second store/verifier can never be substituted here.
            if (provider.records is not owner_view.records
                    or provider.verifier is not owner_view.verifier):
                raise GuaranteeUnavailableError(
                    "provider does not consume the assembled owner records/verifier")
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            AgentContributionSet(agent_runtime_providers=(provider,)), required=True),)))
