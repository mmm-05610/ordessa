"""Read fixed desired configuration via original Agent/Profile authorities.

No C4 plan/permit/journal or live configuration executor is composed here.
Profile intent is not proof that a running native process applied those values.
"""
from ordessa_execution_agents.public import ProfileService,HarnessCatalog
from ordessa_execution_agents.profiles import encode_revision
from .native_evidence import AgentNativeEvidenceReader,NativeEvidenceUnavailable
from ordessa_execution_agents.sdk.native_contracts import METHODS


class AgentConfigurationReadService:
    def __init__(self,source,profiles,catalog):
        if type(profiles) is not ProfileService or type(catalog) is not HarnessCatalog:
            raise NativeEvidenceUnavailable('original Profile service and pinned Harness catalog required')
        self.evidence=AgentNativeEvidenceReader(source)
        self.profiles,self.catalog=profiles,catalog

    def read_desired_configuration(self,agent_ref,*,invocation):
        binding=self.evidence.read_binding(agent_ref,invocation=invocation)
        revision=self.profiles.get_revision(binding.profile_ref)
        provider=self.catalog.resolve(revision.content.harness_definition_ref)
        # Pure validation on the pinned real provider, no apply or runtime ACK.
        provider.validate_profile(revision.content)
        return {'binding':binding.projection(),'profile':encode_revision(revision),
            'harness':provider.descriptor.projection(),'nativeApplied':'unobserved'}


class AgentNativeConfigurationService:
    """Thin application binding to the original recorded native-operation API.

    The original service owns identities, authorization, physical writes and
    replay. Every invocation and physical guard comes from trusted composition;
    a Profile intent or an ACP routing label cannot supply either one.
    """

    def __init__(self, *, source):
        self.evidence = AgentNativeEvidenceReader(source)
        self.source = source

    def freeze(self, agent_ref, *, purpose, params_bytes):
        # The SDK's closed codec checks fixed session, allowed config IDs,
        # generation, digest and operation identity; never translate protocols.
        method = METHODS.get(purpose)
        return self.source.freeze_native_request(
            agent_ref, purpose=purpose, method=method, params_bytes=params_bytes)

    async def execute(self, request, *, request_id, invocation, write_guard, deadline):
        return await self.source.native_recorded(
            request, request_id=request_id, invocation=invocation,
            write_guard=write_guard, deadline=deadline)

    def read_operation(self, operation_ref, expected_input_digest, *, invocation):
        return self.source.native_query(
            operation_ref, expected_input_digest, invocation=invocation)


__all__=['AgentConfigurationReadService', 'AgentNativeConfigurationService']
