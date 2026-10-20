"""SDK-only kimi provider; native protocol transport is explicitly unavailable.

Pure preparation retains pinned native flags/configuration. No direct process,
Unit, permission issuer, protocol fallback or ACP substitution is exported.
"""
from ordessa_execution_agents.sdk import (HarnessDescriptor,HarnessError,PrepareContext,
    ProfileContent,LaunchPlan)
from .native_channel import compile_config,ConfigRefusal


class KimiHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('kimi',definition_ref,implementation_digest,'kimi-wire/1.10',
            ('work','home','config','data','state','cache','tmp'),('kimi.configuration/1',))

    def _options(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options={}
        for declaration in content.declarations:
            if (declaration.configuration_kind!='kimi.configuration' or declaration.schema_version!='1'
                    or declaration.action!='value' or declaration.resource_refs):
                raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:values=dict(declaration.payload)
            except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options)&set(values):raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        if 'model' in options and (type(options['model']) is not str or not options['model'] or len(options['model'])>512):
            raise HarnessError('CONFIGURATION_INVALID')
        if 'thinking' in options and type(options['thinking']) is not bool:
            raise HarnessError('CONFIGURATION_INVALID')
        if any(key in options for key in ('provider','session','replay')):
            raise HarnessError('SESSION_CONFIGURATION_UNAVAILABLE')
        try:return compile_config(options)
        except (ConfigRefusal,TypeError,ValueError,OverflowError):raise HarnessError('CONFIGURATION_UNSUPPORTED') from None

    def validate_profile(self,content):self._options(content)

    def prepare(self,content,context):
        compiled=self._options(content)
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):
            raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        forbidden={'--allow-all','--allow-all-tools','--allow-all-paths','--yolo','--auto-approve','--yes'}
        if any(token.split('=',1)[0] in forbidden for token in context.command_prefix):raise HarnessError('AUTO_APPROVAL_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','KIMI_SHARE_DIR')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','APIKEY','API_KEY','CREDENTIAL')) for key in environment):
            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb','NO_COLOR':'1'})
        environment['KIMI_CLI_NO_AUTO_UPDATE']='1'
        return LaunchPlan(context.command_prefix+('--wire',)+tuple(compiled['args']),context.private_dirs['work'],
            environment,(),(),context.prepared_configuration_refs,context.materials,context.session_bootstrap,('launcher','communicate'))

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        # kimi-wire/1.10 is not ACP. Do not call open_acp_session with alien frames.
        raise HarnessError('NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE')


class KimiProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return KimiHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=KimiProviderFactory()
