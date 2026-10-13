"""Immutable proposals and separate mutable control projections, without IO."""
from dataclasses import dataclass, field, asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.models.identity import (Scope)
from ..common.models.values import (Digest, validate_id)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ..common.outcomes.diagnostics import (ReferenceError)
from ..common.mechanisms.hashing import (record_digest)
from ..common.models.identity import (ActorRef)
from ..common.models.values import (utc_instant)
from ordessa_engineering.domain.artifacts.provenance import (SourceRef, ClaimRef)
from ordessa_engineering.domain.common.models.selection import (ContentSelector)
from ..common.mechanisms.codec import (projection)
from ..common.models.values import (validate_items, ordered_unique, validate_text, validate_version)
from ..reviews.requirements import ReviewRequirementTemplate
from .intent import ImplementationIntentSpec

MAX_PROPOSAL_BYTES=2*1024*1024


@dataclass(frozen=True)
class Mutation:
    artifact_id: str
    operation: str
    base_ref: ArtifactRevisionRef | None
    proposed_ref: ArtifactRevisionRef

    def __post_init__(self):
        validate_id(self.artifact_id)
        if (type(self.operation) is not str or self.operation not in {'create','revise'} or
                type(self.proposed_ref) is not ArtifactRevisionRef or self.proposed_ref.artifact_id!=self.artifact_id):
            raise ReferenceError('INVALID_MUTATION')
        if self.operation=='create':
            if self.base_ref is not None:
                raise ReferenceError('INVALID_MUTATION')
        elif (type(self.base_ref) is not ArtifactRevisionRef or self.base_ref.artifact_id!=self.artifact_id or
              (self.base_ref.realm_id,self.base_ref.project_id)!=(self.proposed_ref.realm_id,self.proposed_ref.project_id) or
              self.base_ref.revision_id==self.proposed_ref.revision_id):
            raise ReferenceError('INVALID_MUTATION')


@dataclass(frozen=True)
class ProposalEvidenceLink:
    claim_ref: ClaimRef
    source_ref: SourceRef
    source_selector: ContentSelector
    relation: str
    rationale: str

    def __post_init__(self):
        if (type(self.claim_ref) is not ClaimRef or type(self.source_ref) is not SourceRef or
                type(self.source_selector) is not ContentSelector or type(self.relation) is not str or
                self.relation not in {'supports','contradicts','context'}):
            raise ReferenceError('INVALID_EVIDENCE_LINK')
        validate_text(self.rationale)


@dataclass(frozen=True)
class Proposal:
    scope: Scope
    proposal_id: str
    created_at: str
    created_by: ActorRef
    change_id: str
    intent: str
    rationale: str
    mutations: tuple[Mutation,...]
    basis_sources: tuple[SourceRef,...]
    claim_refs: tuple[ClaimRef,...]
    evidence_links: tuple[ProposalEvidenceLink,...]
    method_ref: MethodRef
    review_requirement_templates: tuple[ReviewRequirementTemplate,...]
    implementation_intent: ImplementationIntentSpec | None = None
    supersedes_refs: tuple[ProposalRef,...] = ()
    schema_version: int = 1
    digest: Digest = field(init=False)

    def __post_init__(self):
        if (type(self.scope) is not Scope or type(self.created_by) is not ActorRef or type(self.method_ref) is not MethodRef
                or type(self.schema_version) is not int or self.schema_version!=1):
            raise ReferenceError('INVALID_PROPOSAL')
        validate_id(self.proposal_id)
        validate_id(self.change_id)
        utc_instant(self.created_at)
        validate_text(self.intent)
        validate_text(self.rationale)
        validate_items(self.mutations,Mutation,nonempty=True)
        if len({m.artifact_id for m in self.mutations})!=len(self.mutations):
            raise ReferenceError('DUPLICATE_MUTATION')
        # Preserve both index-addressed sequences. Sorting would retarget templates.
        validate_items(self.claim_refs,ClaimRef)
        if len(set(self.claim_refs))!=len(self.claim_refs):
            raise ReferenceError('DUPLICATE_CLAIM')
        for name,kind,key in (
            ('basis_sources',SourceRef,lambda x:x.source_id),
            ('evidence_links',ProposalEvidenceLink,lambda x:canonical_bytes(projection(x,identity=True))),
            ('review_requirement_templates',ReviewRequirementTemplate,lambda x:x.template_id),
            ('supersedes_refs',ProposalRef,lambda x:canonical_bytes(asdict(x)))):
            value=getattr(self,name)
            validate_items(value,kind)
            object.__setattr__(self,name,ordered_unique(value,key, code='DUPLICATE_CHECK'))
        scope=(self.scope.realm_id,self.scope.project_id)
        refs=tuple(m.proposed_ref for m in self.mutations)+tuple(m.base_ref for m in self.mutations if m.base_ref)+tuple(c.owner_revision_ref for c in self.claim_refs)+self.supersedes_refs
        if any((r.realm_id,r.project_id)!=scope for r in refs):
            raise ReferenceError('REALM_MISMATCH')
        if any(r.change_id!=self.change_id or r.proposal_id==self.proposal_id for r in self.supersedes_refs):
            raise ReferenceError('INVALID_SUPERSEDES_REF')
        sources={s.source_id:s for s in self.basis_sources}
        if any(e.claim_ref not in self.claim_refs or sources.get(e.source_ref.source_id)!=e.source_ref for e in self.evidence_links):
            raise ReferenceError('UNRESOLVED_EVIDENCE_LINK')
        if self.implementation_intent is not None:
            spec=self.implementation_intent
            if type(spec) is not ImplementationIntentSpec or spec.scope.project_id!=self.scope.project_id or any(r.realm_id!=self.scope.realm_id for r in spec.expected_baselines):
                raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
            if set(spec.acceptance_requirement_refs)!=set(t.ref for t in self.review_requirement_templates if t.deferred):
                raise ReferenceError('UNRESOLVED_ACCEPTANCE_TEMPLATE')
        for template in self.review_requirement_templates:
            if template.scope!=self.scope:
                raise ReferenceError('REALM_MISMATCH')
            for target in template.expected_targets:
                selector=target.selector
                if selector.kind=='result_of_intent':
                    if self.implementation_intent is None or selector.implementation_intent_id!=self.implementation_intent.implementation_intent_id:
                        raise ReferenceError('INVALID_REVIEW_SELECTOR')
                elif selector.kind!='self_proposal':
                    sequence=self.claim_refs if selector.kind=='claim_owner' else self.mutations
                    if selector.index>=len(sequence) or selector.kind=='base_mutation' and sequence[selector.index].base_ref is None:
                        raise ReferenceError('INVALID_REVIEW_SELECTOR')
        object.__setattr__(self,'digest',record_digest('proposal',self.hash_payload()))
        if len(canonical_bytes(self.projection()))>MAX_PROPOSAL_BYTES:
            raise ReferenceError('PROPOSAL_TOO_LARGE')

    def hash_payload(self):
        return {'realm_id':self.scope.realm_id,'project_id':self.scope.project_id, **{name:projection(getattr(self,name),identity=True) for name in (
            'proposal_id','created_at','created_by','schema_version','change_id','intent','rationale',
            'mutations','basis_sources','claim_refs','evidence_links','method_ref','review_requirement_templates',
            'implementation_intent','supersedes_refs')}}

    def projection(self):
        result=self.hash_payload()
        result.update({name:projection(getattr(self,name)) for name in ('basis_sources','evidence_links')})
        return {**result,'digest':asdict(self.digest)}

    @property
    def ref(self):
        return ProposalRef(self.scope.realm_id,self.scope.project_id,self.change_id,self.proposal_id,self.digest)


@dataclass(frozen=True)
class Change:
    scope: Scope
    change_id: str
    created_at: str
    proposal_ids: tuple[str,...] = ()
    selected_proposal_id: str | None = None
    version: int = 0

    def __post_init__(self):
        if type(self.scope) is not Scope:
            raise ReferenceError('INVALID_SCHEMA')
        validate_id(self.change_id)
        utc_instant(self.created_at)
        validate_items(self.proposal_ids,str)
        for identifier in self.proposal_ids:
            validate_id(identifier)
        object.__setattr__(self,'proposal_ids',ordered_unique(self.proposal_ids,lambda x:x, code='DUPLICATE_CHECK'))
        validate_version(self.version)
        if self.selected_proposal_id is not None and self.selected_proposal_id not in self.proposal_ids:
            raise ReferenceError('INVALID_SELECTION')


@dataclass(frozen=True)
class ProposalControl:
    proposal_ref: ProposalRef
    disposition: str = 'available'
    replacement_ref: ProposalRef | None = None
    control_evidence: tuple[Digest,...] = ()
    version: int = 0

    def __post_init__(self):
        if type(self.proposal_ref) is not ProposalRef or type(self.disposition) is not str or self.disposition not in {'available','withdrawn','superseded'}:
            raise ReferenceError('INVALID_PROPOSAL_CONTROL')
        validate_version(self.version)
        validate_items(self.control_evidence,Digest)
        object.__setattr__(self,'control_evidence',ordered_unique(self.control_evidence,lambda x:x.hex, code='DUPLICATE_CHECK'))
        if self.disposition=='superseded':
            if (type(self.replacement_ref) is not ProposalRef or
                    (self.replacement_ref.realm_id,self.replacement_ref.project_id,self.replacement_ref.change_id)!=
                    (self.proposal_ref.realm_id,self.proposal_ref.project_id,self.proposal_ref.change_id) or
                    self.replacement_ref.proposal_id==self.proposal_ref.proposal_id):
                raise ReferenceError('INVALID_PROPOSAL_CONTROL')
        elif self.replacement_ref is not None:
            raise ReferenceError('INVALID_PROPOSAL_CONTROL')
        if (self.version==0 and (self.disposition!='available' or self.control_evidence) or
                self.version>0 and (self.disposition=='available' or not self.control_evidence)):
            raise ReferenceError('INVALID_PROPOSAL_CONTROL')


@dataclass(frozen=True)
class ChangeSet:
    proposal_refs: tuple[ProposalRef,...]
    digest: Digest = field(init=False)

    def __post_init__(self):
        validate_items(self.proposal_refs,ProposalRef,nonempty=True)
        if len({(r.realm_id,r.project_id) for r in self.proposal_refs})!=1:
            raise ReferenceError('REALM_MISMATCH')
        if len({r.proposal_id for r in self.proposal_refs})!=len(self.proposal_refs):
            raise ReferenceError('DUPLICATE_PROPOSAL')
        object.__setattr__(self,'proposal_refs',ordered_unique(self.proposal_refs,lambda x:canonical_bytes(asdict(x)), code='DUPLICATE_CHECK'))
        object.__setattr__(self,'digest',record_digest('change-set',{'proposal_refs':[asdict(r) for r in self.proposal_refs]}))
