"""Pure plugin contract: pinned Profile input to an immutable launch plan.

No manager, store, invocation, process ownership or environment/Use authority is
exported here. Composition supplies approved nonsecret launch values explicitly;
providers cannot resolve directory refs, inherit a process environment or spawn.
"""
from dataclasses import dataclass
from typing import Mapping,Protocol
from .prepare import (BoundPath,CredentialRef,MaterialRef,PreparedConfigurationRef,
    SessionBootstrap,LaunchPlan,_sealed_map,_tuple_of,_text,_digest,canonical_json,_depth,ROOT_KEY)
from ..profiles import ProfileContent,ConfigurationDeclaration

SDK_VERSION='agent-harness-sdk/1'

class HarnessError(RuntimeError):
    def __init__(self,code):self.code=code;super().__init__(code)


@dataclass(frozen=True)
class HarnessDescriptor:
    provider_id:str
    definition_ref:Mapping
    implementation_digest:str
    protocol_id:str|None
    required_roots:tuple[str,...]
    configuration_kinds:tuple[str,...]

    def __post_init__(self):
        _text(self.provider_id,'provider id');_digest(self.implementation_digest)
        value=dict(self.definition_ref)
        if set(value)!={'environmentNamespace','definitionId','revision'}:raise HarnessError('DEFINITION_PIN_REQUIRED')
        for name,item in value.items():_text(item,name)
        object.__setattr__(self,'definition_ref',_sealed_map(value,'definition ref'))
        if self.protocol_id is not None:_text(self.protocol_id,'protocol id')
        for values in (self.required_roots,self.configuration_kinds):
            if type(values) is not tuple or len(values)>128 or len(set(values))!=len(values):raise HarnessError('DESCRIPTOR_INVALID')
            for value in values:_text(value,'descriptor item')
        if any(ROOT_KEY.fullmatch(key) is None for key in self.required_roots):raise HarnessError('DESCRIPTOR_INVALID')

    def projection(self):
        return {'schemaVersion':'harness-descriptor/1','providerId':self.provider_id,
            'definitionRef':dict(self.definition_ref),'implementationDigest':self.implementation_digest,
            'protocolId':self.protocol_id,'requiredRoots':list(self.required_roots),
            'configurationKinds':list(self.configuration_kinds)}


@dataclass(frozen=True)
class PrepareContext:
    endpoint_facts:Mapping
    private_dirs:Mapping[str,BoundPath]
    command_prefix:tuple[str,...]
    launch_environment:Mapping[str,str]
    credential_refs:tuple[CredentialRef,...]
    materials:tuple[MaterialRef,...]
    prepared_configuration_refs:tuple[PreparedConfigurationRef,...]
    session_bootstrap:SessionBootstrap

    def __post_init__(self):
        facts=_sealed_map(self.endpoint_facts,'endpoint facts')
        def validate_facts(value):
            if isinstance(value,Mapping):
                if set(value)&{'environmentRef','environment_ref','useRef','use_ref','resourceRef','grant','authority','permit'}:
                    raise HarnessError('RESOURCE_AUTHORITY_NOT_SDK_DATA')
                for item in value.values():validate_facts(item)
            elif isinstance(value,tuple):
                for item in value:validate_facts(item)
        validate_facts(facts)
        if _depth(facts)>8 or len(canonical_json(facts).encode('utf-8'))>65536:raise HarnessError('ENDPOINT_FACTS_INVALID')
        object.__setattr__(self,'endpoint_facts',facts)
        dirs=dict(self.private_dirs)
        if any(type(key) is not str or ROOT_KEY.fullmatch(key) is None or type(value) is not BoundPath for key,value in dirs.items()):raise HarnessError('DIRECTORY_BINDING_INVALID')
        from types import MappingProxyType
        object.__setattr__(self,'private_dirs',MappingProxyType(dirs))
        if type(self.command_prefix) is not tuple or not self.command_prefix or len(self.command_prefix)>64:raise HarnessError('COMMAND_PIN_REQUIRED')
        for item in self.command_prefix:_text(item,'command prefix',8192)
        values=dict(self.launch_environment)
        if any(type(key) is not str or type(value) is not str for key,value in values.items()):raise HarnessError('LAUNCH_ENVIRONMENT_INVALID')
        object.__setattr__(self,'launch_environment',_sealed_map(values,'approved nonsecret launch environment'))
        _tuple_of(self.credential_refs,CredentialRef,'credential refs')
        _tuple_of(self.materials,MaterialRef,'materials')
        _tuple_of(self.prepared_configuration_refs,PreparedConfigurationRef,'prepared configurations')
        if type(self.session_bootstrap) is not SessionBootstrap:raise HarnessError('SESSION_BOOTSTRAP_INVALID')


class AgentSession(Protocol):
    @property
    def session_id(self)->str:...
    @property
    def protocol_id(self)->str:...


class ManagedProcess(Protocol):
    async def open_acp_session(self,bootstrap:SessionBootstrap)->AgentSession:
        """Original owner performs guarded bootstrap; no raw writer or invocation."""
        ...


class HarnessProvider(Protocol):
    descriptor:HarnessDescriptor
    def validate_profile(self,content:ProfileContent)->None:...
    def prepare(self,content:ProfileContent,context:PrepareContext)->LaunchPlan:...
    def open_session(self,process,context:PrepareContext)->AgentSession|None:...


class ProviderFactory(Protocol):
    def build(self,bindings:Mapping)->HarnessProvider:...
