"""Immutable public decision/1 DTOs. Unknown authority is never inferred."""
from dataclasses import dataclass, field
from typing import Mapping, Any
from datetime import datetime
from .codec import ContractError, freeze, canonical, digest, name, revision, plain

class DTO:
    def to_dict(self): return plain(self)
    @classmethod
    def from_dict(cls, value):
        from .schema import construct
        return construct(cls,value)

@dataclass(frozen=True)
class ExternalRef(DTO):
    source_namespace: str
    identity: Mapping
    def __post_init__(self):
        name(self.source_namespace)
        if not isinstance(self.identity, Mapping) or not self.identity: raise ContractError('source_identity')
        object.__setattr__(self,'identity',freeze(self.identity)); canonical(self)

@dataclass(frozen=True)
class FlowRef(DTO):
    flow_id: str
    version: str
    content_digest: str
    def __post_init__(self):
        for v in (self.flow_id,self.version,self.content_digest): name(v)

@dataclass(frozen=True)
class PolicyRef(DTO):
    policy_id: str
    version: str
    content_digest: str
    def __post_init__(self):
        for v in (self.policy_id,self.version,self.content_digest): name(v)

@dataclass(frozen=True)
class TaskBrief(DTO):
    task_id: str
    task_revision: str
    goal: str
    inputs: tuple = ()
    boundaries: tuple = ()
    acceptance_criteria: tuple = ()
    context_refs: tuple = ()
    continuation_ref: ExternalRef | None = None
    def __post_init__(self):
        name(self.task_id); name(self.task_revision)
        if type(self.goal) is not str: raise ContractError('goal_type')
        for key in ('inputs','boundaries','acceptance_criteria','context_refs'):
            object.__setattr__(self,key,freeze(plain(getattr(self,key))))
        if self.continuation_ref is not None and not isinstance(self.continuation_ref,ExternalRef): raise ContractError('continuation_ref')
        canonical(self)

@dataclass(frozen=True)
class RunLimits(DTO):
    max_model_attempts: int = 12
    max_node_entries: int = 40
    max_repair_rounds: int = 2
    max_inflight_model_calls: int = 1
    wall_timeout_seconds: float = 60
    cleanup_timeout_seconds: float = 1
    max_business_candidates: int = 64
    max_choice_options: int = 66
    max_candidate_pages: int = 4
    candidate_page_size: int = 32
    max_combinations: int = 64
    max_proposals_per_round: int = 8
    def __post_init__(self):
        for k,v in self.to_dict().items():
            if k in ('wall_timeout_seconds','cleanup_timeout_seconds'):
                if type(v) not in (int,float) or not 0<v<=3600: raise ContractError('time_limit')
            elif type(v) is not int or v<0: raise ContractError('integer_limit')
        if self.max_inflight_model_calls<1 or self.max_node_entries<1 or self.max_choice_options>66 or self.max_business_candidates>64: raise ContractError('host_limit')
        canonical(self)

@dataclass(frozen=True)
class DecisionRequest(DTO):
    request_id: str
    task: TaskBrief
    flow_ref: FlowRef
    limits: RunLimits = field(default_factory=RunLimits)
    prior_outcome_ref: ExternalRef | None = None
    extensions: Mapping = field(default_factory=dict)
    contract_version: str = 'decision/1'
    def __post_init__(self):
        name(self.request_id)
        if self.contract_version!='decision/1' or not isinstance(self.task,TaskBrief) or not isinstance(self.flow_ref,FlowRef) or not isinstance(self.limits,RunLimits): raise ContractError('request_types')
        if any('.' not in k for k in self.extensions): raise ContractError('extension_namespace')
        object.__setattr__(self,'extensions',freeze(self.extensions)); canonical(self)
    @property
    def request_digest(self): return digest('request',self)

@dataclass(frozen=True)
class VersionedObservation(DTO):
    observation_id: str
    subject_ref: ExternalRef
    source_version: str | None
    content_digest: str
    observed_at: str
    data: Mapping
    freshness: str = 'unknown'
    valid_until: str | None = None
    evidence_refs: tuple = ()
    def __post_init__(self):
        name(self.observation_id); revision(self.source_version)
        if not isinstance(self.subject_ref,ExternalRef) or self.freshness not in ('current','stale','unknown'): raise ContractError('observation')
        for v in (self.observed_at,self.valid_until):
            if v is not None:
                try:
                    if datetime.fromisoformat(v.replace('Z','+00:00')).tzinfo is None: raise ValueError()
                except ValueError: raise ContractError('observation_timezone') from None
        object.__setattr__(self,'data',freeze(self.data)); object.__setattr__(self,'evidence_refs',freeze(plain(self.evidence_refs))); canonical(self)

@dataclass(frozen=True)
class ObservationBatch(DTO):
    query_ref: str
    observations: tuple[VersionedObservation,...]
    complete: bool
    scope_description: str
    pagination: Mapping = field(default_factory=dict)
    unobserved_items: tuple = ()
    def __post_init__(self):
        name(self.query_ref)
        if type(self.complete) is not bool or not isinstance(self.observations,tuple) or any(not isinstance(v,VersionedObservation) for v in self.observations): raise ContractError('observation_batch')
        object.__setattr__(self,'pagination',freeze(self.pagination)); object.__setattr__(self,'unobserved_items',freeze(self.unobserved_items))

@dataclass(frozen=True)
class ConfigurationOffer(DTO):
    offer_ref: ExternalRef
    provider_ref: ExternalRef
    descriptor_revision: str | None
    descriptor_digest: str
    configuration_kind: str
    schema_version: str
    input_schema: Mapping
    supported_actions: tuple
    scope_description: str
    application_modes: tuple
    support_status: str
    constraints: tuple = ()
    evidence_refs: tuple = ()
    def __post_init__(self):
        if not isinstance(self.offer_ref,ExternalRef) or not isinstance(self.provider_ref,ExternalRef): raise ContractError('offer_refs')
        name(self.configuration_kind); name(self.schema_version); revision(self.descriptor_revision)
        if self.support_status not in ('supported','unsupported','unknown'): raise ContractError('support_status')
        for k in ('input_schema','supported_actions','application_modes','constraints','evidence_refs'): object.__setattr__(self,k,freeze(plain(getattr(self,k))))
        canonical(self)

@dataclass(frozen=True)
class DecisionQuestion(DTO):
    question_id: str
    version: str
    kind: str
    bounded_state: Mapping
    question_text: str
    options: Mapping = field(default_factory=dict)
    scale: tuple = ()
    evidence_ids: tuple = ()
    allowed_answer_ids: tuple = ()
    policy_ref: PolicyRef | None = None
    def __post_init__(self):
        name(self.question_id); name(self.version)
        if self.kind not in ('choice','score','noul'): raise ContractError('question_kind')
        for k in ('bounded_state','options','scale','evidence_ids','allowed_answer_ids'): object.__setattr__(self,k,freeze(plain(getattr(self,k))))
        if self.kind=='choice' and not 2<=len(self.options)<=66: raise ContractError('choice_size')
        if self.kind=='score' and not 2<=len(self.scale)<=10: raise ContractError('score_size')
        if self.policy_ref is None: raise ContractError('question_policy')
        canonical(self)
    @property
    def question_digest(self): return digest('question',self)

@dataclass(frozen=True)
class DecisionAnswer(DTO):
    question_id: str
    kind: str
    value: Any
    provider_receipt: Mapping
    usage_evidence: Mapping = field(default_factory=lambda:{'status':'unknown'})
    def __post_init__(self):
        name(self.question_id)
        if self.kind not in ('choice','score','noul'): raise ContractError('answer_kind')
        for k in ('value','provider_receipt','usage_evidence'): object.__setattr__(self,k,freeze(getattr(self,k)))
        canonical(self)
    @property
    def answer_digest(self): return digest('answer',self)

@dataclass(frozen=True)
class Precondition(DTO):
    condition_id: str
    kind: str
    subject_ref: ExternalRef
    expected_version: str | None
    expected_digest: str | None
    requirement: str
    checker_id: str
    checker_version: str
    description: str = ''
    def __post_init__(self):
        if not isinstance(self.subject_ref,ExternalRef): raise ContractError('precondition_ref')
        for v in (self.condition_id,self.kind,self.checker_id,self.checker_version): name(v)
        revision(self.expected_version)
        if self.requirement not in ('must','advisory'): raise ContractError('requirement')

@dataclass(frozen=True)
class ValidationObligation(DTO):
    obligation_id: str
    subject_ref: ExternalRef
    requirement: str
    validator_kind: str
    version_constraint: str
    def __post_init__(self):
        if not isinstance(self.subject_ref,ExternalRef): raise ContractError('obligation_ref')
        for v in (self.obligation_id,self.validator_kind,self.version_constraint): name(v)
        if self.requirement not in ('must','advisory'): raise ContractError('requirement')

@dataclass(frozen=True)
class ProposalDraft(DTO):
    proposal_id: str
    proposal_kind: str
    payload: Mapping
    basis_observation_ids: tuple = ()
    preconditions: tuple[Precondition,...] = ()
    rationale_codes: tuple = ()
    required_validation_obligations: tuple[ValidationObligation,...] = ()
    def __post_init__(self):
        name(self.proposal_id); name(self.proposal_kind)
        for k in ('payload','basis_observation_ids','rationale_codes'): object.__setattr__(self,k,freeze(getattr(self,k)))
        object.__setattr__(self,'preconditions',tuple(self.preconditions))
        object.__setattr__(self,'required_validation_obligations',tuple(self.required_validation_obligations))
        if any(not isinstance(v,Precondition) for v in self.preconditions) or any(not isinstance(v,ValidationObligation) for v in self.required_validation_obligations): raise ContractError('proposal_types')
        if len({v.obligation_id for v in self.required_validation_obligations})!=len(self.required_validation_obligations): raise ContractError('duplicate_obligation')
        canonical(self)
    @property
    def proposal_digest(self): return digest('proposal',self)

@dataclass(frozen=True)
class ObligationResult(DTO):
    obligation_id: str
    status: str
    checker_id: str
    checker_version: str
    source_versions: Mapping = field(default_factory=dict)
    evidence_refs: tuple = ()
    exemption_policy_ref: PolicyRef | None = None
    def __post_init__(self):
        name(self.obligation_id); name(self.checker_id); name(self.checker_version)
        if self.status not in ('passed','failed','unknown','notApplicable'): raise ContractError('obligation_status')
        object.__setattr__(self,'source_versions',freeze(self.source_versions)); object.__setattr__(self,'evidence_refs',freeze(plain(self.evidence_refs)))

@dataclass(frozen=True)
class ValidationReceipt(DTO):
    validator_id: str
    validator_version: str
    proposal_digest: str
    status: str
    obligation_results: tuple[ObligationResult,...]
    checked_at: str
    validation_scope: str
    validated_observation_versions: Mapping = field(default_factory=dict)
    issues: tuple = ()
    def __post_init__(self):
        for value in (self.validator_id,self.validator_version,self.proposal_digest,self.checked_at,self.validation_scope): name(value)
        object.__setattr__(self,'obligation_results',tuple(self.obligation_results))
        if self.status not in ('valid','invalid','unverifiable') or any(not isinstance(v,ObligationResult) for v in self.obligation_results): raise ContractError('receipt')
        if len({v.obligation_id for v in self.obligation_results})!=len(self.obligation_results): raise ContractError('duplicate_receipt_obligation')
        object.__setattr__(self,'validated_observation_versions',freeze(self.validated_observation_versions)); object.__setattr__(self,'issues',freeze(self.issues))

def validate_ready(proposal, receipt, *, policy_refs=()):
    if receipt.status!='valid' or receipt.proposal_digest!=proposal.proposal_digest: raise ContractError('proposal_unvalidated')
    results={v.obligation_id:v for v in receipt.obligation_results}
    for obligation in proposal.required_validation_obligations:
        if obligation.requirement!='must': continue
        value=results.get(obligation.obligation_id)
        if value is None or value.checker_id!=obligation.validator_kind or value.checker_version!=obligation.version_constraint: raise ContractError('obligation_missing')
        if value.status=='notApplicable' and value.exemption_policy_ref in policy_refs and value.exemption_policy_ref is not None: continue
        if value.status!='passed' or not value.evidence_refs: raise ContractError('obligation_unverified')
    for condition in proposal.preconditions:
        if condition.requirement=='must' and (condition.expected_version is None or not condition.checker_id): raise ContractError('precondition_unknown')

@dataclass(frozen=True)
class CandidateOffer(DTO):
    candidate_ref: ExternalRef
    candidate_kind: str
    observation: VersionedObservation
    capability_claims: Mapping
    compatibility_evidence: tuple = ()
    uncertainties: tuple = ()
    def __post_init__(self):
        if not isinstance(self.candidate_ref,ExternalRef) or not isinstance(self.observation,VersionedObservation): raise ContractError('candidate_refs')
        name(self.candidate_kind)
        object.__setattr__(self,'capability_claims',freeze(self.capability_claims)); object.__setattr__(self,'compatibility_evidence',freeze(plain(self.compatibility_evidence))); object.__setattr__(self,'uncertainties',freeze(self.uncertainties))

@dataclass(frozen=True)
class CandidateBatch(DTO):
    candidates: tuple[CandidateOffer,...]
    complete: bool
    cursor: str | None = None
    descriptor_digest: str | None = None
    excluded: tuple = ()
    unsupported: tuple = ()
    def __post_init__(self):
        object.__setattr__(self,'candidates',tuple(self.candidates))
        if type(self.complete) is not bool or any(not isinstance(v,CandidateOffer) for v in self.candidates): raise ContractError('candidate_batch')
        object.__setattr__(self,'excluded',freeze(self.excluded)); object.__setattr__(self,'unsupported',freeze(self.unsupported))

@dataclass(frozen=True)
class ProposalCandidateBatch(DTO):
    proposals: tuple[ProposalDraft,...]
    complete: bool
    cursor: str | None = None
    issues: tuple = ()
    def __post_init__(self):
        object.__setattr__(self,'proposals',tuple(self.proposals))
        if type(self.complete) is not bool or any(not isinstance(v,ProposalDraft) for v in self.proposals): raise ContractError('proposal_batch')
        object.__setattr__(self,'issues',freeze(self.issues))

@dataclass(frozen=True)
class CheckBatch(DTO):
    condition_results: tuple[ObligationResult,...]
    complete: bool
    unverified_ids: tuple = ()
    def __post_init__(self):
        object.__setattr__(self,'condition_results',tuple(self.condition_results))
        if type(self.complete) is not bool: raise ContractError('check_complete')
        object.__setattr__(self,'unverified_ids',freeze(self.unverified_ids))
    def require(self, conditions):
        results={v.obligation_id:v for v in self.condition_results}
        if not self.complete or self.unverified_ids or len(results)!=len(self.condition_results): raise ContractError('checks_incomplete')
        for c in conditions:
            if c.requirement=='must':
                r=results.get(c.condition_id)
                if r is None or r.status!='passed' or r.checker_id!=c.checker_id or r.checker_version!=c.checker_version or c.expected_version is None or r.source_versions.get(c.condition_id)!=c.expected_version: raise ContractError('precondition_failed')

@dataclass(frozen=True)
class BusinessOutcome(DTO):
    disposition: str
    proposals: tuple[ProposalDraft,...] = ()
    receipts: tuple[ValidationReceipt,...] = ()
    issues: tuple = ()
    def __post_init__(self):
        object.__setattr__(self,'proposals',tuple(self.proposals)); object.__setattr__(self,'receipts',tuple(self.receipts))
        if self.disposition not in ('ready','revise','clarify','blocked'): raise ContractError('disposition')
        if self.disposition!='ready' and (self.proposals or self.receipts): raise ContractError('business_drafts')
        if self.disposition=='ready' and (not self.proposals or len(self.proposals)!=len(self.receipts)): raise ContractError('ready_empty')
        object.__setattr__(self,'issues',freeze(self.issues))

@dataclass(frozen=True)
class RunManifest(DTO):
    request_digest: str
    flow_ref: FlowRef
    effective_policy_refs: tuple[PolicyRef,...]
    effective_limits: RunLimits
    provider_binding_ref: str
    codec_version: str = 'decision-json/1'
    def __post_init__(self):
        object.__setattr__(self,'effective_policy_refs',tuple(self.effective_policy_refs))
        if not isinstance(self.flow_ref,FlowRef) or not isinstance(self.effective_limits,RunLimits) or any(not isinstance(p,PolicyRef) for p in self.effective_policy_refs) or self.codec_version!='decision-json/1': raise ContractError('manifest_types')
    @property
    def manifest_digest(self): return digest('runmanifest',self)

@dataclass(frozen=True)
class DecisionResult(DTO):
    run_id: str
    request_id: str
    task_revision: str
    flow_ref: FlowRef
    run_manifest_digest: str
    effective_policy_refs: tuple[PolicyRef,...]
    status: str
    outcome: BusinessOutcome | None = None
    error_code: str | None = None
    failure_stage: str | None = None
    call_evidence: str = 'unknown'
    exhausted_dimension: str | None = None
    consumed: Mapping = field(default_factory=dict)
    evidence_summary_ref: str | None = None
    def __post_init__(self):
        object.__setattr__(self,'effective_policy_refs',tuple(self.effective_policy_refs))
        if self.status not in ('completed','failed','budget_exhausted','cancelled'): raise ContractError('terminal_status')
        if self.status=='completed':
            if not isinstance(self.outcome,BusinessOutcome) or self.error_code is not None or self.exhausted_dimension is not None: raise ContractError('terminal_union')
            for p,r in zip(self.outcome.proposals,self.outcome.receipts): validate_ready(p,r,policy_refs=self.effective_policy_refs)
        elif self.outcome is not None: raise ContractError('terminal_union')
        if self.status=='failed' and not self.error_code: raise ContractError('failure_code')
        if self.status=='budget_exhausted' and not self.exhausted_dimension: raise ContractError('budget_dimension')
        object.__setattr__(self,'consumed',freeze(self.consumed)); canonical(self)
    @property
    def result_digest(self): return digest('result',self)
