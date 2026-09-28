"""Closed vocabularies for the C1 contract layer (specs/010 data-model.md).

Enum value sets are deliberately *not* merged across facts (the
``pacthold.execution.contracts`` precedent): an acquire outcome is not a
release outcome, and no enum here contains a ``cancelled`` member — unknown
stop/acquire results must stay queryable and can never be fabricated into a
cancellation (FR-004).
"""
from __future__ import annotations

from enum import Enum


class OwnershipKind(str, Enum):
    """Lease ownership axis from data-model.md (Lease.ownership)."""

    OWN = "own"
    BORROWED = "borrowed"


class LeaseState(str, Enum):
    """The exact Lease state vocabulary from specs/010 data-model.md."""

    ACQUIRING = "acquiring"
    ACQUIRED = "acquired"
    ACQUIRE_UNKNOWN = "acquire_unknown"
    ACQUIRE_REFUSED = "acquire_refused"
    RELEASING = "releasing"
    RELEASED = "released"
    RELEASE_UNKNOWN = "release_unknown"
    RELEASE_FAILED = "release_failed"

    def is_unresolved(self) -> bool:
        """True for states that still pin dependencies or need evidence.

        ``released``/``acquire_refused`` are the only states that let a
        provider be unregistered; unknown states fix their dependents and
        must not be auto-retried or released unsafely (FR-004).
        """
        return self not in (LeaseState.RELEASED, LeaseState.ACQUIRE_REFUSED)


class OperationState(str, Enum):
    """Operation transition vocabulary: planned -> in_flight -> outcome."""

    PLANNED = "planned"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class ExecutionState(str, Enum):
    """Execution projection states (data-model: 启动未知 / 请求停止 / 真实终态).

    Terminal states are irreversible; ``START_UNKNOWN`` is bounded knowledge,
    never a synthesized cancellation.
    """

    ACTIVE = "active"
    START_UNKNOWN = "start_unknown"
    STOP_REQUESTED = "stop_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in _TERMINAL_EXECUTION_STATES

    def is_unresolved(self) -> bool:
        return self in (ExecutionState.ACTIVE, ExecutionState.START_UNKNOWN,
                        ExecutionState.STOP_REQUESTED)


_TERMINAL_EXECUTION_STATES = frozenset(
    {ExecutionState.SUCCEEDED, ExecutionState.FAILED, ExecutionState.CANCELLED}
)


class ReconcileSupport(str, Enum):
    """A descriptor must state one of these explicitly; absence is a bug."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class AcquireOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class ReleaseOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class ReconcileOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class StartOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class StopOutcome(str, Enum):
    SUCCESS = "success"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class ObservationKind(str, Enum):
    """What a provider honestly knows about one execution right now."""

    NOT_KNOWN = "not_known"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    TERMINAL = "terminal"
    START_UNKNOWN = "start_unknown"
