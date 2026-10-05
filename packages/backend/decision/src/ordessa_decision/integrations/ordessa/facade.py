"""Read-only snapshots of public Agent services, preserving incomplete scope."""
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from pacthold.agents.public import (AgentServices, OwnerProposalInput, ProfileRef, decode_node_ref)
from ordessa_decision.contracts import *

@dataclass(frozen=True)
class ObservationQuery:
    kind: str
    parameters: Mapping
    def __post_init__(self):
        if self.kind not in ('providers','profiles','profile','nodes','configuration','configuration_offers'):
            raise ContractError('query_unregistered')
        object.__setattr__(self,'parameters',freeze(self.parameters))

class OrdessaReadFacade:
    """Composed capability; business graph sees observe, never AgentServices."""
    def __init__(self, services: AgentServices, *, namespace, read_context, max_items=64):
        if not isinstance(services,AgentServices) or not isinstance(read_context,ReadContext) or type(max_items) is not int or not 1<=max_items<=64: raise ContractError('adapter_binding')
        self.__services=services; self.namespace=namespace; self.__context=read_context; self.max_items=max_items
    def _authorise(self,context):
        if not isinstance(context,ReadContext) or context.authority is not self.__context.authority or context.scope_ref!=self.__context.scope_ref: raise ContractError('read_refused')
    def _observation(self, identity, version, data, label):
        ref=ExternalRef(self.namespace,identity)
        return VersionedObservation(digest('descriptor',{'kind':label,'identity':identity,'data':data}),ref,version,
            digest('descriptor',data),datetime.now(timezone.utc).isoformat(),data,'current' if version is not None else 'unknown',
            evidence_refs=({'source_namespace':self.namespace,'identity':identity},))
    async def observe(self,query,read_context):
        self._authorise(read_context)
        if not isinstance(query,ObservationQuery): raise ContractError('query_unregistered')
        s=self.__services; p=query.parameters; values=[]; complete=False; unknown=[]
        if query.kind=='providers':
            if p: raise ContractError('query_parameters')
            for v in s.providers.list():
                d=v['descriptor']; values.append(self._observation(v['providerRef'],d['definitionRef']['revision'],v,'provider'))
            unknown=['installation','availability','directory_scope']
        elif query.kind=='profiles':
            if p: raise ContractError('query_parameters')
            for v in s.profiles.list(): values.append(self._observation(v.current_manifest_ref.to_dict(),str(v.catalog_revision),v.to_dict(),'profile'))
            # Core may silently filter per-item authorisation: empty is not absence.
            unknown=['permission_filtered_items']
        elif query.kind=='profile':
            if set(p)!={'profile_ref'}: raise ContractError('query_parameters')
            ref=ProfileRef.from_dict(plain(p['profile_ref'])); v=s.profiles.read(ref)
            values=[self._observation(ref.to_dict(),str(ref.manifest_revision),{'profileRef':ref.to_dict(),'content':v.content},'profile')]; complete=True
        elif query.kind=='nodes':
            if p: raise ContractError('query_parameters')
            for v in s.nodes.list(): values.append(self._observation(plain(v['nodeRef']),None,plain(v),'node'))
            unknown=['availability','continuity','directory_scope']
        elif query.kind=='configuration':
            if set(p)!={'node_ref'}: raise ContractError('query_parameters')
            v=s.configuration.inspect(decode_node_ref(plain(p['node_ref'])))
            values=[self._observation(plain(v.unit_ref),v.source_revision,v.to_dict(),'configuration')]; complete=True
            unknown=list(v.unknown_items)
        elif query.kind=='configuration_offers':
            if set(p)!={'definition_ref'}: raise ContractError('query_parameters')
            v=s.providers.describe_configuration_offers(plain(p['definition_ref']))
            values=[self._observation(plain(v.definition_ref),v.descriptor_revision,v.to_dict(),'configuration_offers')]
            complete=v.complete; unknown=list(v.unknown_items)
        truncated=len(values)>self.max_items
        return ObservationBatch(query.kind,tuple(values[:self.max_items]),complete and not truncated,
            'public authorised observation; sources checked independently; no global snapshot',
            pagination={'truncated':truncated,'count':min(len(values),self.max_items)},unobserved_items=tuple(unknown))

class OwnerProposalValidator:
    """Explicitly pins a public owner input mapping; no private provider access."""
    def __init__(self, providers, *, input_builder, read_context, input_verifier=None):
        if not callable(input_builder) or not isinstance(read_context,ReadContext) or (input_verifier is not None and not callable(input_verifier)): raise ContractError('validator_binding')
        self.__providers=providers; self.__builder=input_builder; self.__context=read_context
        self.__verifier=input_verifier
    async def validate(self,draft,basis,read_context):
        if read_context.authority is not self.__context.authority or read_context.scope_ref!=self.__context.scope_ref: raise ContractError('read_refused')
        input=self.__builder(draft,basis)
        if not isinstance(input,OwnerProposalInput): raise ContractError('owner_input')
        # Different digest domains cannot prove a semantic field mapping. The
        # host must supply an independently reviewed pure mapping check; absence
        # or ambiguity fails closed before invoking the owner. This is trusted
        # assembly, never a check selected or generated by the decision model.
        if self.__verifier is None: raise ContractError('owner_mapping_unverified')
        if self.__verifier(draft,basis,input) is not True: raise ContractError('owner_mapping_mismatch')
        expected=tuple({'obligationId':o.obligation_id,'requirement':o.requirement,
            'checkerId':o.validator_kind,'checkerVersion':o.version_constraint}
            for o in draft.required_validation_obligations)
        if plain(input.required_obligations)!=plain(expected): raise ContractError('owner_obligation_mapping')
        # Local map freezes the exact two separate digest domains before public call.
        mapping=freeze({'decision_proposal_digest':draft.proposal_digest,'source_input_digest':input.input_digest})
        result=self.__providers.assess_configuration_proposal(input)
        if result.input_digest!=mapping['source_input_digest'] or draft.proposal_digest!=mapping['decision_proposal_digest']: raise ContractError('owner_digest_mismatch')
        rows=tuple(ObligationResult(v['obligationId'],v['status'],v['checkerId'],v['checkerVersion'],v['sourceVersions'],tuple(v['evidenceRefs'])) for v in result.obligation_results)
        receipt=ValidationReceipt('ordessa.owner','1',draft.proposal_digest,result.status,rows,
            datetime.now(timezone.utc).isoformat(),result.validation_scope,result.source_versions,tuple(plain(v) for v in result.issues))
        if receipt.status=='valid': validate_ready(draft,receipt)
        return receipt
