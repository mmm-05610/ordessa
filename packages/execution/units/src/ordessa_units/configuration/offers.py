"""Owner pure-read offer/proposal contracts and their instance-configuration aggregation.

Owned by the unit-configuration mechanism. This module:
  * defines the closed owner pure-read contracts (`OwnerReadContext`,
    `OwnerConfigurationOfferBatch`, `OwnerProposalAssessment`) and re-exports
    the original pure `OwnerProposalInput` value
    and their assessment check; and
  * aggregates instance-configuration offers/proposals over the Environment's
    admitted providers, reading the existing Environment admission and admitted
    provider only. It creates no second registry, issuer or store.

It holds no decision dependency and issues no effect authority.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import json

from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_agents.harness.providers.registry.definition_admission import HarnessAdmission

from .contracts import (
    ConfigurationDescription, ConfigurationContractError, ConfigurationRevisionConflict,
    ConfigurationUnsupported, _name, _reference, _snapshot,
)

from .proposal_input import OwnerProposalInput

PURE_READ_VERSION = 'agent-configuration-read/1'


@dataclass(frozen=True, repr=False)
class OwnerReadContext:
    environment_namespace: str
    provider_ref: Mapping
    principal_scope: str
    contract_version: str = PURE_READ_VERSION
    def __post_init__(self):
        _name(self.environment_namespace); _name(self.principal_scope)
        if self.contract_version != PURE_READ_VERSION: raise ConfigurationContractError('read contract unsupported')
        object.__setattr__(self,'provider_ref',_reference(self.provider_ref,self.environment_namespace))
    def __repr__(self): return '<OwnerReadContext>'


@dataclass(frozen=True)
class OwnerConfigurationOfferBatch:
    owner_ref: Mapping
    definition_ref: Mapping
    descriptor_revision: str
    descriptor_digest: str
    offers: tuple[ConfigurationDescription,...]
    complete: bool
    pure_read_guarantee: str
    unknown_items: tuple[str,...] = ()
    evidence_refs: tuple[Mapping,...] = ()
    def __post_init__(self):
        definition=_reference(self.definition_ref)
        object.__setattr__(self,'definition_ref',definition)
        object.__setattr__(self,'owner_ref',_reference(self.owner_ref,definition['environmentNamespace']))
        _name(self.descriptor_revision); _name(self.descriptor_digest)
        if self.pure_read_guarantee!=PURE_READ_VERSION or type(self.complete) is not bool or not isinstance(self.offers,tuple) or any(not isinstance(o,ConfigurationDescription) for o in self.offers): raise ConfigurationContractError('pure-read offer contract')
        if len({(v.configuration_kind,v.schema_version) for v in self.offers})!=len(self.offers): raise ConfigurationContractError('duplicate offers')
        object.__setattr__(self,'unknown_items',tuple(self.unknown_items))
        object.__setattr__(self,'evidence_refs',tuple(_reference(r,definition['environmentNamespace']) for r in self.evidence_refs))
    def to_dict(self):
        return json.loads(safe_json({'ownerRef':self.owner_ref,'definitionRef':self.definition_ref,
            'descriptorRevision':self.descriptor_revision,'descriptorDigest':self.descriptor_digest,
            'offers':[v.to_dict() for v in self.offers],'complete':self.complete,
            'pureReadGuarantee':self.pure_read_guarantee,'unknownItems':self.unknown_items,'evidenceRefs':self.evidence_refs}))


@dataclass(frozen=True)
class OwnerProposalAssessment:
    input_digest: str
    source_versions: Mapping
    status: str
    issues: tuple
    obligation_results: tuple[Mapping,...]
    validation_scope: str
    evidence_refs: tuple[Mapping,...]
    pure_read_guarantee: str
    def __post_init__(self):
        _name(self.input_digest); _name(self.validation_scope)
        if self.status not in ('valid','invalid','unverifiable') or self.pure_read_guarantee!=PURE_READ_VERSION: raise ConfigurationContractError('pure-read assessment contract')
        object.__setattr__(self,'source_versions',_snapshot(self.source_versions))
        object.__setattr__(self,'issues',tuple(_snapshot(v) for v in self.issues))
        object.__setattr__(self,'obligation_results',tuple(_snapshot(v) for v in self.obligation_results))
        object.__setattr__(self,'evidence_refs',tuple(_reference(v) for v in self.evidence_refs))
        ids=[]
        for r in self.obligation_results:
            if set(r)!={'obligationId','status','checkerId','checkerVersion','sourceVersions','evidenceRefs'} or r['status'] not in ('passed','failed','unknown'): raise ConfigurationContractError('assessment obligation contract')
            for key in ('obligationId','checkerId','checkerVersion'): _name(r[key])
            if not isinstance(r['sourceVersions'],Mapping) or not isinstance(r['evidenceRefs'],tuple): raise ConfigurationContractError('assessment evidence containers')
            for ref in r['evidenceRefs']: _reference(ref)
            ids.append(r['obligationId'])
        if len(set(ids))!=len(ids): raise ConfigurationContractError('duplicate assessment obligation')
    def to_dict(self):
        return json.loads(safe_json({'inputDigest':self.input_digest,'sourceVersions':self.source_versions,
            'status':self.status,'issues':self.issues,'obligationResults':self.obligation_results,
            'validationScope':self.validation_scope,'evidenceRefs':self.evidence_refs,'pureReadGuarantee':self.pure_read_guarantee}))


def require_assessment(input, result):
    if not isinstance(result,OwnerProposalAssessment) or result.input_digest!=input.input_digest: raise ConfigurationContractError('assessment input mismatch')
    by_id={r['obligationId']:r for r in result.obligation_results}
    for ref in result.evidence_refs: _reference(ref,input.definition_ref['environmentNamespace'])
    for row in result.obligation_results:
        for ref in row['evidenceRefs']: _reference(ref,input.definition_ref['environmentNamespace'])
    if result.status=='valid':
        if result.source_versions.get('descriptor') != input.descriptor_revision: raise ConfigurationContractError('assessment descriptor version missing')
        known_versions={'descriptor':input.descriptor_revision}
        for ref in input.source_refs:
            expected=ref.get('sourceRevision',ref.get('manifestRevision',ref.get('revision')))
            actual=result.source_versions.get(safe_json(ref))
            if expected is None or type(actual) is not type(expected) or actual != expected: raise ConfigurationContractError('assessment source version unknown')
            known_versions[safe_json(ref)]=expected
        for o in input.required_obligations:
            r=by_id.get(o['obligationId'])
            if o['requirement']=='must' and r is not None:
                versions=r['sourceVersions']
                if not versions or any(k not in known_versions or type(known_versions[k]) is not type(v) or known_versions[k]!=v for k,v in versions.items()):
                    raise ConfigurationContractError('assessment obligation source version unverified')
            if o['requirement']=='must' and (r is None or r['status']!='passed' or not r['evidenceRefs'] or r['checkerId']!=o['checkerId'] or r['checkerVersion']!=o['checkerVersion']): raise ConfigurationContractError('assessment must obligation unverified')


class AgentConfigurationOffers:
    """Instance-configuration offer/proposal aggregation over admitted providers.

    This is the upper-layer Agent configuration read aggregation. It was moved out
    of the provider registry so the registry stays a neutral admission projection.
    It reads the existing Environment admission and the admitted provider; it does
    not create a second registry, issuer or store, and exports no proposal/effect
    authority (callers pass an explicitly built ``OwnerProposalInput``).
    """

    def __init__(self, environment):
        self._environment = environment

    def _require_definition_ref(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise UnitIdentityMismatch("complete RuntimeProvider definition reference required")

    def _pure_read_owner(self, definition_ref, method):
        self._require_definition_ref(definition_ref)
        env = self._environment
        HarnessAdmission(env).describe(definition_ref)
        # Public lookup rechecks same Environment, current read policy and admission.
        if not env._policy.admit_object_access(env._principal_scope,
                f'{env.environment_id}:agents.definition:{definition_ref["definitionId"]}', 'read'):
            raise UnitAdmissionRefused('configuration offer read refused')
        raise UnitGuaranteeUnavailable('specific configuration offer compiler owner is not bound')

    def _recheck_read_owner(self, admitted, definition_ref, method):
        current, _ = self._pure_read_owner(definition_ref, method)
        if current.provider_ref != admitted.provider_ref or current.descriptor != admitted.descriptor:
            raise UnitAdmissionRefused('pure-read owner changed during observation')

    def describe_configuration_offers(self, definition_ref):
        env = self._environment
        with env._admission_lock:
            admitted, context = self._pure_read_owner(definition_ref, 'describe_configuration_offers')
        try:
            result = admitted.provider.describe_configuration_offers(definition_ref, context)
        except Exception as exc:
            if isinstance(exc, ConfigurationUnsupported): raise ConfigurationUnsupported('owner pure-read unsupported') from None
            if isinstance(exc, UnitAdmissionRefused): raise UnitAdmissionRefused('owner pure-read refused') from None
            raise UnitGuaranteeUnavailable('pure-read offer unavailable') from None
        with env._admission_lock:
            self._recheck_read_owner(admitted, definition_ref, 'describe_configuration_offers')
            if (not isinstance(result, OwnerConfigurationOfferBatch)
                    or result.owner_ref != admitted.provider_ref or result.definition_ref != admitted.descriptor.definition_ref
                    or result.descriptor_revision != admitted.descriptor.definition_ref['revision']
                    or result.descriptor_digest != admitted.descriptor.implementation_digest):
                raise UnitGuaranteeUnavailable('pure-read offer version or owner differs')
            return result

    def _proposal_source_snapshot(self, source):
        """Recheck the existing public read authority; no secondary registry."""
        if set(source) == {'environmentNamespace','profileId','manifestRevision','contentDigest'}:
            from ordessa_agents.profiles.definitions.codec import decode_revision_ref, encode_content, encode_revision_ref
            from ordessa_agents.profiles.definitions.models import ProfileRevisionRef
            from ordessa_agents.profiles.management.service import ProfileService
            value = ProfileService(UnitProfileAdmission(self._environment)).get_revision(
                decode_revision_ref(json.loads(safe_json(source))))
            return safe_json({'ref': encode_revision_ref(value.ref), 'content': encode_content(value.content)})
        if set(source) == {'environmentNamespace','instanceId','generation'}:
            from ordessa_units.bindings.publication import decode_node_ref, NodePublication
            value = NodePublication(self._environment).read(decode_node_ref(source))
            if value is None: raise UnitGuaranteeUnavailable('proposal source Node absent')
            return safe_json(value)
        if set(source) == {'environmentNamespace','definitionId','revision'}:
            self._require_definition_ref(source)
            return safe_json(self._environment_definition_view(source))
        raise ConfigurationUnsupported('proposal source read scheme unsupported')

    def _environment_definition_view(self, definition_ref):
        admitted = HarnessAdmission(self._environment).describe(definition_ref)
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.provider_ref))}

    def assess_configuration_proposal(self, proposal):
        if not isinstance(proposal, OwnerProposalInput):
            raise UnitIdentityMismatch('typed owner proposal required')
        env = self._environment
        with env._admission_lock:
            admitted, context = self._pure_read_owner(proposal.definition_ref, 'assess_configuration_proposal')
            if proposal.provider_ref != admitted.provider_ref:
                raise UnitIdentityMismatch('proposal owner generation differs')
            sources = tuple(self._proposal_source_snapshot(source) for source in proposal.source_refs)
            if proposal.descriptor_revision != admitted.descriptor.definition_ref['revision']:
                raise ConfigurationRevisionConflict('proposal descriptor revision differs')
        try:
            result = admitted.provider.assess_configuration_proposal(proposal, context)
            require_assessment(proposal, result)
        except Exception as exc:
            if isinstance(exc, ConfigurationUnsupported): raise ConfigurationUnsupported('owner pure-read unsupported') from None
            if isinstance(exc, UnitAdmissionRefused): raise UnitAdmissionRefused('owner pure-read refused') from None
            raise UnitGuaranteeUnavailable('pure-read proposal assessment unavailable or unverified') from None
        with env._admission_lock:
            self._recheck_read_owner(admitted, proposal.definition_ref, 'assess_configuration_proposal')
            current_sources = tuple(self._proposal_source_snapshot(source) for source in proposal.source_refs)
            if current_sources != sources:
                raise UnitGuaranteeUnavailable('proposal source changed during assessment')
            return result


__all__ = [
    "PURE_READ_VERSION", "OwnerReadContext", "OwnerProposalInput",
    "OwnerConfigurationOfferBatch", "OwnerProposalAssessment", "require_assessment",
    "AgentConfigurationOffers",
]
