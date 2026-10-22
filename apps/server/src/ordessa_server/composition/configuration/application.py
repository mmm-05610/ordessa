"""Read fixed desired configuration via original Agent/Profile authorities.

No C4 plan/permit/journal or live configuration executor is composed here.
Profile intent is not proof that a running native process applied those values.
"""
from ordessa_agents.public import ProfileService,HarnessCatalog
from ordessa_agents.profiles import encode_revision
from .native_evidence import AgentNativeEvidenceReader,NativeEvidenceUnavailable


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


__all__=['AgentConfigurationReadService']
