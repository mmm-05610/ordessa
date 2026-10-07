"""Trusted host assembly; these checks are admission, not a Python sandbox."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
from pydantic_graph import Graph
from pacthold.decision.contracts import BusinessOutcome, ContractError, digest

def reviewed_code_digest(*paths):
    """Bind review to actual source bytes, ordered by caller-supplied stable path."""
    hasher = hashlib.sha256(b'decision.reviewed-code/1\n')
    for path in sorted(map(Path, paths), key=lambda p: p.as_posix()):
        data = path.read_bytes()
        hasher.update(str(len(data)).encode() + b'\n' + data + b'\n')
    if not paths:
        raise ContractError('review_sources_missing')
    return 'sha256:' + hasher.hexdigest()

def flow_digest(code_digest, policy_refs):
    return digest('flow', {'reviewed_code_digest': code_digest, 'policy_refs': policy_refs})

@dataclass(frozen=True)
class TrustedFlow:
    ref: object
    graph: Graph
    new_state: object
    policy_refs: tuple
    reviewed_code_digest: str
    review_ref: str
    output_schema: type = BusinessOutcome
    parallel_state_writes: bool = False

    def validate(self):
        if not isinstance(self.graph, Graph) or not self.graph.name:
            raise ContractError('explicit_real_graph_required')
        if not callable(self.new_state) or not self.review_ref or not self.reviewed_code_digest.startswith('sha256:'):
            raise ContractError('flow_unreviewed')
        if self.parallel_state_writes:
            raise ContractError('parallel_state_writes')
        if self.ref.content_digest != flow_digest(self.reviewed_code_digest, self.policy_refs):
            raise ContractError('flow_digest_mismatch')
        if self.output_schema is not BusinessOutcome:
            raise ContractError('flow_output_schema')
