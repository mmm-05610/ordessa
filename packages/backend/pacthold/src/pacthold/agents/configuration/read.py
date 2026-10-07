"""Optional owner pure-read contracts; no decision dependency or effect authority."""
from dataclasses import dataclass
from collections.abc import Mapping
import hashlib
import json
from ordessa_environment_api.operations import safe_json, sealed_mapping
from pacthold.agents.configuration.change import ConfigurationDescription, ConfigurationContractError, _name, _reference, _snapshot

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
class OwnerProposalInput:
    definition_ref: Mapping
    provider_ref: Mapping
    descriptor_revision: str
    proposal_data: Mapping
    source_refs: tuple[Mapping,...]
    required_obligations: tuple[Mapping,...]
    def __post_init__(self):
        definition=_reference(self.definition_ref)
        if set(definition)!={'environmentNamespace','definitionId','revision'}: raise ConfigurationContractError('definition reference incomplete')
        _name(self.descriptor_revision)
        object.__setattr__(self,'definition_ref',definition)
        object.__setattr__(self,'provider_ref',_reference(self.provider_ref,definition['environmentNamespace']))
        object.__setattr__(self,'proposal_data',_snapshot(self.proposal_data))
        object.__setattr__(self,'source_refs',tuple(_reference(r,definition['environmentNamespace']) for r in self.source_refs))
        object.__setattr__(self,'required_obligations',tuple(_snapshot(r) for r in self.required_obligations))
        ids=[]
        for r in self.required_obligations:
            if set(r)!={'obligationId','requirement','checkerId','checkerVersion'} or r['requirement'] not in ('must','advisory'): raise ConfigurationContractError('obligation fields')
            for key in ('obligationId','checkerId','checkerVersion'): _name(r[key])
            ids.append(r['obligationId'])
        if len(set(ids))!=len(ids): raise ConfigurationContractError('duplicate obligations')
    def to_dict(self):
        return json.loads(safe_json({'definitionRef':self.definition_ref,'providerRef':self.provider_ref,
            'descriptorRevision':self.descriptor_revision,'proposalData':self.proposal_data,
            'sourceRefs':self.source_refs,'requiredObligations':self.required_obligations}))
    @property
    def input_digest(self):
        return 'sha256:'+hashlib.sha256(b'agent.configuration-proposal\nagent-read-json/1\n'+safe_json(self.to_dict()).encode()).hexdigest()

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
