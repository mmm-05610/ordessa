"""Pure original owner-proposal input value; no Unit services or registry assembly.

The original canonical projection and digest domain remain unchanged. The mixed
configuration offers module re-exports this exact class for existing consumers.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import hashlib
import json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from .contracts import ConfigurationContractError, _reference, _snapshot, _name


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

