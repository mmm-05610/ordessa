"""Production Minimal Work Core contracts.

This package is additive and intentionally independent from the legacy
fixed-workflow implementation.
"""

from .events import CoreEvent, EventType
from .finalization import ExecutionFinalizationRequest, FinalizationReceipt
from .models import Execution, Ref, RefType, Work, WorkLifecycle
from .projection import ExecutionProjection, Freshness, Outcome, Phase
from .registry import (
    DispatchReceipt,
    ExecutionPreflightRequest,
    ExecutionStartReceipt,
    ExecutionStartRequest,
    ExtensionRegistry,
    ProviderDescriptor,
    RecoverySupport,
    ResolvedExecutionInput,
    ResolutionEffect,
    ResourceProvider,
    ResourceResolutionContext,
)
from .resource_observations import (
    ResourceObservation,
    ResourceObservationCoverage,
    ResourceObservationKind,
    ResourceObservationResult,
    ResourceObserverRole,
)

__all__ = [
    "CoreEvent",
    "EventType",
    "ExecutionFinalizationRequest",
    "FinalizationReceipt",
    "Execution",
    "ExecutionPreflightRequest",
    "ExecutionStartReceipt",
    "ExecutionProjection",
    "ExecutionStartRequest",
    "ExtensionRegistry",
    "Freshness",
    "Outcome",
    "Phase",
    "ProviderDescriptor",
    "RecoverySupport",
    "ResolvedExecutionInput",
    "ResolutionEffect",
    "DispatchReceipt",
    "ResourceObservation",
    "ResourceObservationCoverage",
    "ResourceObservationKind",
    "ResourceObservationResult",
    "ResourceObserverRole",
    "ResourceProvider",
    "ResourceResolutionContext",
    "Ref",
    "RefType",
    "Work",
    "WorkLifecycle",
]
