"""Backward-compatible entry for the neutral execution-domain contracts.

MB-E2a equal-move: every definition below now lives exactly once in
``pacthold.execution.contracts``; this module re-exports the same objects so
historical import paths (``from
ordessa_server.execution.execution_contract import CancelOutcome`` ...)
keep the identical object identity, signatures and value surfaces. No second
definition is written here - ``tests/server/test_e_modular_execution_boundary.py``
pins that by AST.
"""
from __future__ import annotations

from pacthold.execution.contracts import (
    CancelOutcome, DeadlinePolicy, DeliveryOutcome, EvidenceClass,
    ExecutionObservation, ExecutionReceipt, ExecutionRequest, NeutralBinding,
    ObservationState,
)

__all__ = [
    "CancelOutcome", "DeadlinePolicy", "DeliveryOutcome", "EvidenceClass",
    "ExecutionObservation", "ExecutionReceipt", "ExecutionRequest",
    "NeutralBinding", "ObservationState",
]
