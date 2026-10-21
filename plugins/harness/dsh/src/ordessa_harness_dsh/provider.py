"""Dsh-owned pure Profile validation/preparation through the public SDK.

The former direct ProcessChannel/AcpClient consumer is retired. This provider
never starts a process, reads login state, owns a Unit/session ledger or answers
permissions. Unsupported bootstrap/configuration is refused explicitly.
"""
from ordessa_agents.sdk import (HarnessDescriptor,HarnessError,PrepareContext,
    ProfileContent,LaunchPlan)
from .acp_model_configuration import compile_config


def _credential_binding(declaration):
    if (declaration.schema_version!='1' or declaration.action!='value'
            or declaration.resource_refs):raise HarnessError('CONFIGURATION_UNSUPPORTED')
    try:payload=dict(declaration.payload)
    except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
    if set(payload)!={'sourcePath','rootKey','relativePath'}:raise HarnessError('CONFIGURATION_INVALID')
    for key in ('sourcePath','rootKey','relativePath'):
        value=payload[key]
        if type(value) is not str or not value or len(value)>4096 or '\x00' in value:
            raise HarnessError('CONFIGURATION_INVALID')
    import pathlib as _pathlib
    if not _pathlib.PurePosixPath(payload['sourcePath']).is_absolute():
        raise HarnessError('CONFIGURATION_INVALID')
    return payload


class DshHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('dsh',definition_ref,implementation_digest,'acp',
            ('work','home','config','data','state','cache','tmp','dsh-home'),
            ('dsh.configuration/1','credentials.file/1'))

    def _options(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        options={}
        for declaration in content.declarations:
            if declaration.configuration_kind=='credentials.file':
                _credential_binding(declaration)
                continue
            if (declaration.configuration_kind!='dsh.configuration' or declaration.schema_version!='1'
                    or declaration.action!='value' or declaration.resource_refs):
                raise HarnessError('CONFIGURATION_UNSUPPORTED')
            try:values=dict(declaration.payload)
            except (TypeError,ValueError):raise HarnessError('CONFIGURATION_INVALID') from None
            if set(options)&set(values):raise HarnessError('CONFIGURATION_CONFLICT')
            options.update(values)
        return compile_config(options)

    def validate_profile(self,content):self._options(content)

    def prepare(self,content,context):
        self._options(content)
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        if not set(self.descriptor.required_roots)<=set(context.private_dirs):raise HarnessError('APPROVED_ROOTS_UNAVAILABLE')
        if not {'launcher','communicate'}<=set(context.endpoint_facts.get('members',())):
            raise HarnessError('ENDPOINT_CAPABILITY_UNAVAILABLE')
        if context.credential_refs:raise HarnessError('CREDENTIAL_BINDING_UNAVAILABLE')
        if context.session_bootstrap.mode!='fresh':raise HarnessError('SESSION_MODE_UNSUPPORTED')
        environment=dict(context.launch_environment)
        required=('HOME','PATH','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME','TMPDIR','DSH_HOME')
        if any(not environment.get(key) for key in required):raise HarnessError('EXPLICIT_LAUNCH_ENVIRONMENT_REQUIRED')
        if any(any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','API_KEY','APIKEY')) for key in environment):
            raise HarnessError('CREDENTIAL_REFERENCE_REQUIRED')
        # Native home must be explicit and separate; physical/source checks belong
        # to the external directory-binding owner, never filesystem probes here.
        if environment['HOME']==environment['DSH_HOME']:
            raise HarnessError('PRIVATE_HOME_BINDING_CONFLICT')
        if context.private_dirs['home']==context.private_dirs['dsh-home']:
            raise HarnessError('PRIVATE_HOME_BINDING_CONFLICT')
        environment.update({'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TERM':'dumb'})
        return LaunchPlan(context.command_prefix+('--profile','acp'),context.private_dirs['work'],
            environment,(),(),context.prepared_configuration_refs,context.materials,context.session_bootstrap,('launcher','communicate'))

    async def open_session(self,process,context):
        if type(context) is not PrepareContext:raise HarnessError('PREPARE_CONTEXT_REQUIRED')
        open_session=getattr(process,'open_acp_session',None)
        if not callable(open_session):raise HarnessError('ACP_BOOTSTRAP_UNAVAILABLE')
        return await open_session(context.session_bootstrap)


class DshProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return DshHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=DshProviderFactory()
