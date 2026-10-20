"""SDK metadata and validation; Qoder has no established executable channel.

The native key registry remains first-hand configuration knowledge. It does not
establish a command/protocol/login binding and cannot authorize a fake launch.
"""
from ordessa_execution_agents.sdk import HarnessDescriptor,HarnessError,ProfileContent


class QoderHarnessProvider:
    def __init__(self,definition_ref,implementation_digest):
        self.descriptor=HarnessDescriptor('qoder',definition_ref,implementation_digest,None,(),())

    def validate_profile(self,content):
        if type(content) is not ProfileContent or dict(content.harness_definition_ref)!=dict(self.descriptor.definition_ref):
            raise HarnessError('PROFILE_HARNESS_PIN_MISMATCH')
        if content.declarations:raise HarnessError('CONFIGURATION_COMPILATION_UNAVAILABLE')

    def prepare(self,content,context):
        self.validate_profile(content)
        raise HarnessError('NATIVE_LAUNCH_UNAVAILABLE')

    async def open_session(self,process,context):
        raise HarnessError('NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE')


class QoderProviderFactory:
    def build(self,bindings):
        if set(bindings)!={'definition_ref','implementation_digest'}:raise HarnessError('HARNESS_BINDINGS_INVALID')
        return QoderHarnessProvider(bindings['definition_ref'],bindings['implementation_digest'])


factory=QoderProviderFactory()
