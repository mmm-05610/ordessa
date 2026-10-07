"""Read-only public projections of the Environment's admitted providers.

No discovery cache, native probing or invocation capability is created here.
Supported methods are declarations, not installation or readiness evidence.
"""
import json
from collections.abc import Mapping

from ordessa_environment_api import IdentityMismatchError
from ordessa_environment_api.operations import safe_json


class AgentProviders:
    def __init__(self, environment):
        self._environment = environment

    @staticmethod
    def _view(admitted):
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.provider_ref))}

    @staticmethod
    def _configuration_view(admitted):
        """Thin projection of admitted configuration metadata (freeze §3).

        Data only: descriptor dict, sealed runtime provider ref and the
        §2-verified recognized definition subset. No callable, no instance.
        """
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.runtime_provider_ref)),
                "recognizedDefinitions": [json.loads(safe_json(item))
                                          for item in admitted.recognized_definitions]}

    def list(self):
        return tuple(self._view(item) for item in
                     self._environment.agent_runtime_contributions())

    def describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise IdentityMismatchError("complete RuntimeProvider definition reference required")
        return self._view(self._environment.agent_runtime_contribution(definition_ref))

    def configuration_list(self):
        return tuple(self._configuration_view(item) for item in
                     self._environment.agent_configuration_contributions())

    def configuration_describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise IdentityMismatchError("complete configuration definition reference required")
        return self._configuration_view(
            self._environment.agent_configuration_contribution(definition_ref))

    def _pure_read_owner(self, definition_ref, method):
        from .read_configuration import PURE_READ_VERSION, OwnerReadContext
        from .configuration import ConfigurationUnsupported
        from ordessa_environment_api import AdmissionRefusedError
        # Public lookup rechecks same Environment, current read policy and admission.
        self.describe(definition_ref)
        env = self._environment
        admitted = env.agent_runtime_contribution(definition_ref)
        if not env._policy.admit_object_access(env._principal_scope,
                f'{env.environment_id}:agents.definition:{definition_ref["definitionId"]}', 'read'):
            raise AdmissionRefusedError('configuration offer read refused')
        if admitted.descriptor.pure_read_contract_version != PURE_READ_VERSION or method not in admitted.descriptor.supported_methods:
            raise ConfigurationUnsupported('owner pure-read contract unsupported')
        if not callable(getattr(admitted.provider, method, None)):
            raise ConfigurationUnsupported('owner pure-read method unavailable')
        return admitted, OwnerReadContext(env.environment_id, admitted.provider_ref, env._principal_scope)

    def _recheck_read_owner(self, admitted, definition_ref, method):
        from ordessa_environment_api import AdmissionRefusedError
        current, _ = self._pure_read_owner(definition_ref, method)
        if current.provider_ref != admitted.provider_ref or current.descriptor != admitted.descriptor:
            raise AdmissionRefusedError('pure-read owner changed during observation')

    def describe_configuration_offers(self, definition_ref):
        from .read_configuration import OwnerConfigurationOfferBatch
        from ordessa_environment_api import GuaranteeUnavailableError
        env = self._environment
        with env._admission_lock:
            admitted, context = self._pure_read_owner(definition_ref, 'describe_configuration_offers')
        try:
            result = admitted.provider.describe_configuration_offers(definition_ref, context)
        except Exception as exc:
            from .configuration import ConfigurationUnsupported
            from ordessa_environment_api import AdmissionRefusedError
            if isinstance(exc,ConfigurationUnsupported): raise ConfigurationUnsupported('owner pure-read unsupported') from None
            if isinstance(exc,AdmissionRefusedError): raise AdmissionRefusedError('owner pure-read refused') from None
            raise GuaranteeUnavailableError('pure-read offer unavailable') from None
        with env._admission_lock:
            self._recheck_read_owner(admitted, definition_ref, 'describe_configuration_offers')
            if (not isinstance(result, OwnerConfigurationOfferBatch)
                    or result.owner_ref != admitted.provider_ref or result.definition_ref != admitted.descriptor.definition_ref
                    or result.descriptor_revision != admitted.descriptor.definition_ref['revision']
                    or result.descriptor_digest != admitted.descriptor.implementation_digest):
                raise GuaranteeUnavailableError('pure-read offer version or owner differs')
            return result

    def _proposal_source_snapshot(self, source):
        """Recheck the existing public read authority; no secondary registry."""
        from .configuration import ConfigurationUnsupported
        from ordessa_environment_api import GuaranteeUnavailableError
        if set(source) == {'environmentNamespace','profileId','manifestRevision','contentDigest'}:
            from .contracts import ProfileRef
            from .profiles import ProfileCatalog
            value = ProfileCatalog(self._environment).read(ProfileRef.from_dict(json.loads(safe_json(source))))
            return safe_json({'ref': value.ref.to_dict(), 'content': value.content})
        if set(source) == {'environmentNamespace','instanceId','generation'}:
            from .nodes import decode_node_ref, NodePublication
            value = NodePublication(self._environment).read(decode_node_ref(source))
            if value is None: raise GuaranteeUnavailableError('proposal source Node absent')
            return safe_json(value)
        if set(source) == {'environmentNamespace','definitionId','revision'}:
            return safe_json(self.describe(source))
        raise ConfigurationUnsupported('proposal source read scheme unsupported')

    def assess_configuration_proposal(self, proposal):
        from .read_configuration import OwnerProposalInput, require_assessment
        from ordessa_environment_api import GuaranteeUnavailableError, IdentityMismatchError
        from .configuration import ConfigurationRevisionConflict
        if not isinstance(proposal, OwnerProposalInput):
            raise IdentityMismatchError('typed owner proposal required')
        env = self._environment
        with env._admission_lock:
            admitted, context = self._pure_read_owner(proposal.definition_ref, 'assess_configuration_proposal')
            if proposal.provider_ref != admitted.provider_ref:
                raise IdentityMismatchError('proposal owner generation differs')
            sources = tuple(self._proposal_source_snapshot(source) for source in proposal.source_refs)
            if proposal.descriptor_revision != admitted.descriptor.definition_ref['revision']:
                raise ConfigurationRevisionConflict('proposal descriptor revision differs')
        try:
            result = admitted.provider.assess_configuration_proposal(proposal, context)
            require_assessment(proposal, result)
        except Exception as exc:
            from .configuration import ConfigurationUnsupported
            from ordessa_environment_api import AdmissionRefusedError
            if isinstance(exc,ConfigurationUnsupported): raise ConfigurationUnsupported('owner pure-read unsupported') from None
            if isinstance(exc,AdmissionRefusedError): raise AdmissionRefusedError('owner pure-read refused') from None
            raise GuaranteeUnavailableError('pure-read proposal assessment unavailable or unverified') from None
        with env._admission_lock:
            self._recheck_read_owner(admitted, proposal.definition_ref, 'assess_configuration_proposal')
            current_sources = tuple(self._proposal_source_snapshot(source) for source in proposal.source_refs)
            if current_sources != sources:
                raise GuaranteeUnavailableError('proposal source changed during assessment')
            return result
