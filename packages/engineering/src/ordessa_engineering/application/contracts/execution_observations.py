"""Authorized, durable execution observations captured as opaque Engineering blobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ...domain.common.models.refs import BlobRef


ObservationState = Literal['reserved', 'possibly-written', 'completed', 'failed', 'unknown']
# Complete native receipts include the input/frame and bounded output evidence.
# The adapter still supplies the original owner's equal or smaller actual cap.
MAX_EXECUTION_RECEIPT_BYTES = 2 * 1024 * 1024


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


__all__ = ['AuthorizedAcpTurnReader', 'ObservationState', 'ExecutionObservationRef',
           'MAX_EXECUTION_RECEIPT_BYTES']
