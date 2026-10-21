"""Kilo pure SDK provider over an externally approved native ACP artifact.

No ambient executable lookup, projection, direct launch or historical Unit API.
Native config/material bytes are prepared and verified by the external owner.
"""
import json
import re
from ordessa_agents.sdk import HarnessDescriptor,HarnessError,PrepareContext,ProfileContent,LaunchPlan,BoundPath


class KiloHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('kilo',definition_ref,implementation_digest,'acp',
            ('work','home','config','data','state','cache','tmp'),())

    def validate_profile(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        if content.declarations:raise HarnessError('CONFIGURATION_UNSUPPORTED')

    def prepare(self,content,context):
        self.validate_profile(content)
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):
            raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        forbidden={'--allow-all','--allow-all-tools','--allow-all-paths','--yolo','--auto-approve','--yes'}
        if any(token.split('=',1)[0] in forbidden for token in context.command_prefix):raise HarnessError('AUTO_APPROVAL_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','KILO_CONFIG_CONTENT')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','APIKEY','API_KEY','CREDENTIAL')) for key in environment):
            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate configuration key')
                result[key]=value
            return result
        def reject_constant(value):raise ValueError('nonfinite configuration value')
        try:configuration=json.loads(environment['KILO_CONFIG_CONTENT'],object_pairs_hook=pairs,parse_constant=reject_constant)
        except (KeyError,TypeError,ValueError,RecursionError):raise HarnessError('PREPARED_CONFIGURATION_REQUIRED') from None
        if type(configuration) is not dict or configuration.get('autoupdate') is not False:
            raise HarnessError('CONFIGURATION_INVALID')
        def check(value,depth=0):
            if depth>16:raise HarnessError('CONFIGURATION_INVALID')
            if isinstance(value,dict):
                for key,item in value.items():
                    if any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','APIKEY','API_KEY','CREDENTIAL')):
                        if type(item) is not str or re.fullmatch(r'\{env:[A-Za-z_][A-Za-z0-9_]*\}',item) is None:
                            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
                    check(item,depth+1)
            elif isinstance(value,list):
                for item in value:check(item,depth+1)
        check(configuration)
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb'})
        return LaunchPlan(context.command_prefix+('acp',),context.private_dirs['work'],environment,
            (),(),context.prepared_configuration_refs,context.materials,context.session_bootstrap,('launcher','communicate'))

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        open_session=getattr(process,'open_acp_session',None)
        if not callable(open_session):raise HarnessError('ACP_BOOTSTRAP_UNAVAILABLE')
        return await open_session(context.session_bootstrap)


class KiloProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return KiloHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=KiloProviderFactory()
