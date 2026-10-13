import asyncio
import time
from dataclasses import dataclass
from decision_runtime.definitions import freeze, plain
from decision_runtime.definitions.errors import BudgetExhausted, ExplicitCancellation, EvidenceUnknown, RuntimeFailure

@dataclass(frozen=True)
class NodeServices:
    read: object
    candidate_source: object
    proposal_source: object
    validator: object
    policy: object
    read_context: object
    policy_refs: tuple

class RunContext:
    """Per-run dependency object. Model access goes only through gateway."""
    def __init__(self, request, services, run_id, deadline):
        self.request = request
        self.services = NodeServices(services.read, services.candidate_source,
            services.proposal_source, services.validator, services.policy,
            services.read_context, services.policy_refs)
        self.limits = request.limits
        self.run_id = run_id
        self.deadline = deadline
        self.gateway = None
        self.node_entries = self.model_attempts = self.repair_rounds = 0
        self.cancelled = False
        self.exhausted_dimension = None
        self.evidence_unknown = False
        self.failure_code = None
        self.evidence_seq = 0
        self.evidence_digest = None
        self.lock = asyncio.Lock()

    def check(self):
        if self.cancelled:
            raise ExplicitCancellation()
        if self.evidence_unknown:
            raise EvidenceUnknown(self.run_id)
        if self.failure_code:
            raise RuntimeFailure(self.failure_code)
        if self.exhausted_dimension:
            raise BudgetExhausted(self.exhausted_dimension)
        if time.monotonic() >= self.deadline:
            self.exhaust('wall_timeout_seconds')

    def exhaust(self, dimension):
        self.exhausted_dimension = self.exhausted_dimension or dimension
        raise BudgetExhausted(self.exhausted_dimension)

    def mark_evidence_unknown(self):
        """Uncertain evidence cannot be caught and converted into completion."""
        self.evidence_unknown = True
        raise EvidenceUnknown(self.run_id) from None

    async def enter_node(self, node_id):
        if not isinstance(node_id, str) or not node_id:
            raise ValueError('node_id')
        async with self.lock:
            self.check()
            if self.node_entries >= self.limits.max_node_entries:
                self.exhaust('max_node_entries')
            self.node_entries += 1

    async def enter_repair(self):
        async with self.lock:
            self.check()
            if self.repair_rounds >= self.limits.max_repair_rounds:
                self.exhaust('max_repair_rounds')
            self.repair_rounds += 1

    def cancel(self):
        """Explicit host cancellation; asyncio cancellation still propagates."""
        self.cancelled = True

    def consumed(self):
        return {'node_entries': self.node_entries, 'model_attempts': self.model_attempts,
                'repair_rounds': self.repair_rounds}

async def immutable_queries(*queries):
    """Read branches receive no state; fixed ordered join yields frozen values."""
    async def one(query):
        return freeze(plain(await query()))
    return tuple(await asyncio.gather(*(one(query) for query in queries)))
