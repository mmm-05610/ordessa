"""Authorized, durable execution observations captured as opaque Engineering blobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ...domain.common.models.refs import BlobRef


ObservationState = Literal['reserved', 'possibly-written', 'completed', 'failed', 'unknown']
# Complete native receipts include the input/frame and bounded output evidence.
# The adapter still supplies the original owner's equal or smaller actual cap.
MAX_EXECUTION_RECEIPT_BYTES = 8388608  # 8MiB; matches the original UnitRecords cap.
MAX_GENERATION_TIMEOUT_SECONDS = 1800  # One bounded full-document response; never an in-flight extension.


class AuthorizedAcpTurnReader(Protocol):
    """The original UnitRecords owner; implementations verify/consume its invocation."""
    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest): ...
    def query_acp_turn(self, unit_ref, operation_ref, context, *, input_digest,
                        expected_prompt_input_digest): ...


@dataclass(frozen=True)
class ExecutionObservationRef:
    unit_ref: dict
    operation_ref: str
    expected_prompt_digest: str
    query_digest: str
    state: ObservationState
    revision: int
    blob_ref: BlobRef
    authority_id: str


@dataclass(frozen=True)
class OriginPrewriteEvidence:
    """Original owner's own read of one attempt that provably stopped before write.

    This is evidence, not authority: it must come from the same records/issuer/
    verifier/access graph that produced the dispatch, through the owner's public
    read path. A boolean claim such as ``no_write`` or ``closed`` is never enough,
    and an operator JSON or a synthetic replay is not this value.
    """

    acp_observation: ExecutionObservationRef
    stop_record: dict
    release_record: dict


class ContinuationEvidenceReader(Protocol):
    """Read-only evidence port used to qualify one continuation.

    Refusals are explicit: an owner that cannot produce verifiable termination
    proof raises instead of returning an empty or optimistic record.
    """

    def read_origin(self, context, origin) -> OriginPrewriteEvidence: ...


__all__ = ['AuthorizedAcpTurnReader', 'ObservationState', 'ExecutionObservationRef',
           'OriginPrewriteEvidence', 'ContinuationEvidenceReader',
           'MAX_EXECUTION_RECEIPT_BYTES', 'MAX_GENERATION_TIMEOUT_SECONDS']


@dataclass(frozen=True)
class AgentExecutionObservationRef:
    agent_ref_bytes: bytes
    turn_ref_bytes: bytes
    operation_ref: str
    engineering_attempt_ref: str
    expected_prompt_digest: str
    query_digest: str
    state: ObservationState
    revision: int
    blob_ref: BlobRef
    authority_id: str
    report_text: str | None = None

class AgentReceiptSource(Protocol):
    def read_agent_reference(self,agent_ref,*,read_invocation) -> bytes: ...
    def read_agent_binding(self,agent_ref,*,read_invocation):
        """Read original BindingProvenance with separate opaque read authority."""
        ...
    def capture_reference(self, execution_ref, *, read_invocation) -> AgentExecutionObservationRef: ...
    def capture_dispatch(self,binding,*,read_invocation):
        """Original F2 persisted TurnRef cold query; returns reference + capture."""
        ...

__all__ += ['AgentExecutionObservationRef', 'AgentReceiptSource']
