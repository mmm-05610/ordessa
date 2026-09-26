"""Neutral execution composition package (MB-E2a).

Contract-only: the pure standard-library DTOs, enumerations and the
``TurnExecutionPort`` protocol live once in ``pacthold.execution.contracts``.
Nothing in this package may import the product Server, a Work Core
repository, or a concrete H/P plugin - the pins in
``apps/server/tests/test_e_modular_execution_boundary.py`` and
``test_dependency_direction.py`` lock that direction. (The former re-export
entries under ``ordessa_server.execution`` were retired when the execution
domain moved to its plugin; that name no longer imports.)
"""
from __future__ import annotations

from pacthold.execution.contracts import (
    CancelOutcome, DeadlinePolicy, DeliveryOutcome, EvidenceClass,
    ExecutionObservation, ExecutionReceipt, ExecutionRequest, NeutralBinding,
    ObservationState, TurnExecutionPort,
)

__all__ = [
    "CancelOutcome", "DeadlinePolicy", "DeliveryOutcome", "EvidenceClass",
    "ExecutionObservation", "ExecutionReceipt", "ExecutionRequest",
    "NeutralBinding", "ObservationState", "TurnExecutionPort",
]
