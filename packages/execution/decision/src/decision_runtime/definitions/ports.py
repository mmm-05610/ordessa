"""Ports are async and contain no mutation service. Contexts are host-injected."""
from dataclasses import dataclass
from typing import Protocol, Any
import time
from .errors import ContractError
from .values import freeze, name, plain
from .models import *

__all__ = ['ReadContext', 'CallPermit', 'ModelCallContext', 'DurabilityAck',
           'ObservationPort', 'CandidateSource', 'ProposalSource', 'ProposalValidationPort',
           'PreconditionChecker', 'DecisionProvider', 'DecisionGateway', 'EvidenceSink',
           'EvidenceReader', 'DecisionServices']


@dataclass(frozen=True, repr=False)
class ReadContext:
    """Opaque capability; identity comparison is performed by the composed port."""
    authority: object
    scope_ref: str
    def __post_init__(self):
        if self.authority is None: raise ContractError('read_authority')
        name(self.scope_ref)
    def __repr__(self): return '<ReadContext>'

class CallPermit:
    __slots__ = ('_run_id','_question_digest','_settings_digest','_deadline','_claimed')
    def __init__(self, run_id, question_digest, settings_digest, deadline):
        self._run_id,self._question_digest,self._settings_digest,self._deadline=run_id,question_digest,settings_digest,deadline
        self._claimed=False
    def claim(self, *, run_id, question_digest, settings_digest):
        if self._claimed or run_id!=self._run_id or question_digest!=self._question_digest or settings_digest!=self._settings_digest or time.monotonic()>=self._deadline: raise ContractError('permit_refused')
        self._claimed=True
    def __repr__(self): return '<CallPermit>'

@dataclass(frozen=True, repr=False)
class ModelCallContext:
    run_id: str
    call_id: str
    attempt_no: int
    question_digest: str
    provider_settings_digest: str
    monotonic_deadline: float
    permit: CallPermit
    def claim(self, question, settings_digest):
        self.permit.claim(run_id=self.run_id,question_digest=question.question_digest,settings_digest=settings_digest)
    def __repr__(self): return '<ModelCallContext>'

@dataclass(frozen=True)
class DurabilityAck:
    seq: int
    digest: str
    durability: str

class ObservationPort(Protocol):
    async def observe(self, query: Any, read_context: ReadContext) -> ObservationBatch: ...
class CandidateSource(Protocol):
    async def list_candidates(self, task, observation_refs, policy_ref, read_context, *, cursor=None) -> CandidateBatch: ...
class ProposalSource(Protocol):
    async def compose(self, task, candidate_refs, configuration_offer_refs, constraints, cursor, read_context) -> ProposalCandidateBatch: ...
class ProposalValidationPort(Protocol):
    async def validate(self, draft, basis, read_context) -> ValidationReceipt: ...
class PreconditionChecker(Protocol):
    async def check(self, preconditions, read_context) -> CheckBatch: ...
class DecisionProvider(Protocol):
    settings_digest: str
    binding_ref: str
    async def decide(self, question: DecisionQuestion, model_context: ModelCallContext) -> DecisionAnswer: ...
class DecisionGateway(Protocol):
    async def decide(self, question: DecisionQuestion) -> DecisionAnswer: ...
class EvidenceSink(Protocol):
    durable: bool
    async def start(self, run_meta) -> DurabilityAck: ...
    async def append_durable(self, event) -> DurabilityAck: ...
    async def finish(self, terminal) -> DurabilityAck: ...
    async def read(self, run_id, read_context) -> Any: ...
    async def close(self) -> None: ...
class EvidenceReader(Protocol):
    async def read(self, run_id, read_context) -> Any: ...

@dataclass(frozen=True)
class DecisionServices:
    read: ObservationPort | None
    candidate_source: CandidateSource | None
    proposal_source: ProposalSource | None
    validator: ProposalValidationPort | None
    decision_provider: DecisionProvider
    evidence: EvidenceSink
    policy: Any
    read_context: ReadContext
    policy_refs: tuple[PolicyRef,...]
    mode: str = 'offline'
    def __post_init__(self):
        if self.mode not in ('offline','real') or not isinstance(self.read_context,ReadContext) or not self.policy_refs: raise ContractError('services')
        object.__setattr__(self, 'policy', freeze(plain(self.policy)))
        object.__setattr__(self, 'policy_refs', tuple(self.policy_refs))
        if any(not isinstance(ref, PolicyRef) for ref in self.policy_refs): raise ContractError('services_policy_refs')
