"""Vibe-owned pure Profile validation/preparation through the public SDK.

The former direct ProcessChannel/AcpClient consumer is retired. This provider
never starts a process, reads login state, owns a Unit/session ledger or answers
permissions. Unsupported bootstrap/configuration is refused explicitly.
"""
from ordessa_execution_agents.sdk import (HarnessDescriptor,HarnessError,PrepareContext,
    ProfileContent,LaunchPlan)
from .native_channel import compile_config,ConfigRefusal


class VibeHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('vibe',definition_ref,implementation_digest,'acp',
            ('work','home','config','data','state','cache','tmp'),('vibe.configuration/1',))

    def _options(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options={}
        for declaration in content.declarations:
            if (declaration.configuration_kind!='vibe.configuration' or declaration.schema_version!='1'
                    or declaration.action!='value' or declaration.resource_refs):
                raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:values=dict(declaration.payload)
            except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options)&set(values):raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        try:return compile_config(options)
        except ConfigRefusal:raise HarnessError('CONFIGURATION_UNSUPPORTED') from None

    def validate_profile(self,content):self._options(content)

    def prepare(self,content,context):
        compiled=self._options(content)
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):
            raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if compiled['session_params']:raise HarnessError('SESSION_CONFIGURATION_UNAVAILABLE')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','VIBE_HOME')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','API_KEY','APIKEY')) for key in environment):
            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb'})
        # Externally approved complete native command; no guessed ACP flag.
        return LaunchPlan(context.command_prefix,context.private_dirs['work'],
            environment,(),(),context.prepared_configuration_refs,context.materials,context.session_bootstrap,('launcher','communicate'))

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        open_session=getattr(process,'open_acp_session',None)
        if not callable(open_session):raise HarnessError('ACP_BOOTSTRAP_UNAVAILABLE')
        return await open_session(context.session_bootstrap)


class VibeProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return VibeHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=VibeProviderFactory()
