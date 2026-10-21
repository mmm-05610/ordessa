"""Sole import surface for Harness plugins. Importing performs no IO or assembly."""
from .harness import (SDK_VERSION,HarnessError,HarnessDescriptor,HarnessProvider,
    ProviderFactory,PrepareContext,AgentSession,ManagedProcess,ProfileContent,ConfigurationDeclaration)
from .prepare import (LaunchPlan,SessionBootstrap,BoundPath,CredentialRef,SecretBinding,
    MaterialRef,PreparedConfigurationRef,ConfigurationArtifact)

__all__=['SDK_VERSION','HarnessError','HarnessDescriptor','HarnessProvider','ProviderFactory',
    'PrepareContext','AgentSession','ManagedProcess','ProfileContent','ConfigurationDeclaration','LaunchPlan',
    'SessionBootstrap','BoundPath','CredentialRef','SecretBinding','MaterialRef',
    'PreparedConfigurationRef','ConfigurationArtifact']


# Existing pure model-policy contracts and installed-artifact observation are
# explicit plugin ports. Load them only when a policy consumer selects them;
# ordinary provider imports must not assemble the older configuration runtime.
_POLICY_EXPORTS = {
    'NativeModelLaunchRefused': ('ordessa_agents.harness.contracts.errors.native', 'NativeModelLaunchRefused'),
    'build_initial_model_params': ('ordessa_agents.harness.configuration.validation.initial_params', 'build_initial_model_params'),
    'Installation': ('ordessa_agents.harness.definitions.contracts', 'Installation'),
    'ConfigurationAdapterDescriptor': ('ordessa_agents.harness.definitions.contracts', 'ConfigurationAdapterDescriptor'),
    'FieldClaim': ('ordessa_agents.harness.definitions.contracts', 'FieldClaim'),
    'VersionRange': ('ordessa_agents.harness.definitions.contracts', 'VersionRange'),
    'installed_verifier': ('ordessa_agents.harness.providers.resolution.verifier_deployment', 'installed_verifier'),
    'canonical_text': ('ordessa_infrastructure.encoding.canonical_json', 'canonical_text'),
}
for _policy_name in ('FACET_ID', 'FACET_SCHEMA_VERSION', 'ENTRY', 'ENV_HANDLE_SUFFIX',
                     'choice_payload_schema', 'native_version_range'):
    _POLICY_EXPORTS[_policy_name] = (
        'ordessa_agents.harness.configuration.compilation.model_choice', _policy_name)
__all__ += list(_POLICY_EXPORTS)


def __getattr__(name):
    target = _POLICY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module(target[0]), target[1])
