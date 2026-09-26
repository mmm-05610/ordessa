"""Append-only material cross-system facts, not provider telemetry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from .models import MAX_METADATA_VALUE_LENGTH, _bounded_metadata


RESPONSIBILITY_INTENT_KEY = "responsibility_intent"
MAX_RESPONSIBILITY_INTENT_LENGTH = MAX_METADATA_VALUE_LENGTH


class EventType(str, Enum):
    WORK_CREATED = "WorkCreated"
    WORK_COMPLETED = "WorkCompleted"
    WORK_REOPENED = "WorkReopened"
    EXECUTION_CREATED = "ExecutionCreated"
    EXECUTION_DISPATCH_REQUESTED = "ExecutionDispatchRequested"
    EXECUTION_DISPATCH_ACCEPTED = "ExecutionDispatchAccepted"
    EXECUTION_DISPATCH_FAILED = "ExecutionDispatchFailed"
    EXECUTION_DISPATCH_AMBIGUOUS = "ExecutionDispatchAmbiguous"
    NATIVE_REF_DISCOVERED = "NativeRefDiscovered"
    EXECUTION_STARTED = "ExecutionStarted"
    EXECUTION_PROJECTION_CHANGED = "ExecutionProjectionChanged"
    EXECUTION_TERMINAL = "ExecutionTerminal"
    REF_ATTACHED = "RefAttached"
    EXECUTION_FINALIZED = "ExecutionFinalized"


@dataclass(frozen=True)
class CoreEvent:
    id: str
    type: EventType
    subject_id: str
    occurred_at: datetime
    data: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.subject_id:
            raise ValueError("event id and subject_id are required")
        object.__setattr__(self, "data", _bounded_metadata(self.data))


def normalize_responsibility_intent(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("execution responsibility_intent must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError("execution responsibility_intent is required")
    if len(normalized) > MAX_RESPONSIBILITY_INTENT_LENGTH:
        raise ValueError(
            "execution responsibility_intent exceeds "
            f"{MAX_RESPONSIBILITY_INTENT_LENGTH} characters"
        )
    return normalized


def execution_created_event(
    event_id: str,
    execution_id: str,
    occurred_at: datetime,
    *,
    provider_id: str,
    responsibility_intent: str,
) -> CoreEvent:
    """Build the immutable declaration of why an Execution was created."""
    return CoreEvent(
        event_id,
        EventType.EXECUTION_CREATED,
        execution_id,
        occurred_at,
        {
            "provider": provider_id,
            RESPONSIBILITY_INTENT_KEY: normalize_responsibility_intent(
                responsibility_intent
            ),
        },
    )
