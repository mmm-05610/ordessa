"""Provider-neutral invocation values for atomic Execution finalization."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Ref
from .projection import ExecutionProjection
from .resource_observations import ResourceObservation
from .errors import FinalizationConflict


@dataclass(frozen=True)
class ExecutionFinalizationRequest:
    execution_id: str
    idempotency_key: str
    terminal_projection: ExecutionProjection
    native_refs: tuple[Ref, ...] = ()
    output_refs: tuple[Ref, ...] = ()
    resource_observations: tuple[ResourceObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.execution_id, str) or not self.execution_id.strip():
            raise ValueError("execution_id is required")
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ValueError("finalization idempotency_key is required")
        if not isinstance(self.terminal_projection, ExecutionProjection) or not self.terminal_projection.terminal:
            raise FinalizationConflict("terminal_projection must be Phase.TERMINAL")


@dataclass(frozen=True)
class FinalizationReceipt:
    execution_id: str
    idempotency_key: str
    bundle_digest: str
    execution_version: int


__all__ = ["ExecutionFinalizationRequest", "FinalizationReceipt"]
