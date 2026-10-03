"""Neutral execution-domain contract types (C-EXEC@v1 block1 carrier, E-INC1a a-1).

MB-E2a equal-move: these definitions previously lived in
a former sidecar-local contract module; they are defined once here and the
historical entries re-export the same objects.

Pure frozen data and enumerations only: no IO, no imports beyond the standard
library, and no knowledge of any caller's product identity. The vocabulary of
this module is deliberately execution-only - an opaque key, an opaque
correlation map, declared bindings - so a scheduler that is not the product
Server can drive the same surface without fabricating anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Protocol


class CancelOutcome(str, Enum):
    """The three block-1 cancellation classes (spelling owned by E per the
    contract; the consumer is only promised pairwise distinguishability, and
    no class may ever be pressed into another)."""

    CONFIRMED_STOPPED = "confirmed_stopped"
    REFUSED_NO_ACTIVE_RUN = "refused_no_active_run"
    UNKNOWN = "unknown"


class DeliveryOutcome(str, Enum):
    """Naming-round skeleton (E-INC1b b-3, additive definition; no consumer
    is wired in this batch):

    * the correct confirmation is the native fact itself (snake_case value);
    * ``refused_<singular reason>`` asserts zero dispatch happened for this
      key, so replaying the request returns the same verdict safely;
    * ``unknown`` means the answer was lost - never blind-redispatch.

    Value sets of the outcome enums are never merged: a stop is not a
    delivery, and pressing one word onto two facts would be a dishonest type.
    """

    DELIVERED = "delivered"
    REFUSED_UNKNOWN_ROUTE = "refused_unknown_route"
    UNKNOWN = "unknown"


class ObservationState(str, Enum):
    """What the provider honestly knows about one execution key right now.

    ``NOT_KNOWN_TO_E`` is bounded knowledge, never a proof of absence: it says
    the execution domain holds no tracked run under this key, not that no
    execution ever started elsewhere.
    """

    NOT_KNOWN_TO_E = "not_known_to_e"
    RUNNING = "running"
    TERMINAL = "terminal"
    STOPPED_CONFIRMED = "stopped_confirmed"


class EvidenceClass(str, Enum):
    """The kind of proof an observation rests on. Observations never create
    transitions; they only report which evidence the domain already holds."""

    DISPATCH_ACK = "dispatch_ack"
    NATIVE_REPORT = "native_report"
    TERMINAL_RECEIPT = "terminal_receipt"
    CANCEL_CONFIRMATION = "cancel_confirmation"
    NONE = "none"


@dataclass(frozen=True)
class NeutralBinding:
    """One caller-owned input the executor must mount, as an opaque reference.

    The executor validates presence and safety of the references only; it
    never resolves a contract id into a product concept.
    """

    contract_id: str
    object_digest: str
    mount_token: str


@dataclass(frozen=True)
class DeadlinePolicy:
    """Declarative bounds carried with a request; enforcement is composed
    elsewhere. ``None`` means the caller declares no deadline."""

    hard_deadline: datetime | None = None
    idle_timeout_seconds: float | None = None


@dataclass(frozen=True)
class ExecutionRequest:
    """A neutral start-intent for one execution.

    ``execution_key`` is an idempotency key issued by the caller after *its
    own* record creation; the execution domain never mints, reads, or infers
    any business ledger entry. ``correlation`` is passed through un-parsed
    and its persistence is the caller's responsibility.
    """

    execution_key: str
    bundle_ref: str
    resource_bindings: tuple[NeutralBinding, ...] = ()
    capability_demand: frozenset[str] = frozenset()
    deadline_policy: DeadlinePolicy | None = None
    correlation: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "correlation", MappingProxyType(dict(self.correlation)))


@dataclass(frozen=True)
class ExecutionReceipt:
    """Answer to ``submit``. A replay of a known key returns the original
    receipt with ``replayed=True`` and never re-dispatches the start."""

    execution_key: str
    dispatch_id: str
    replayed: bool = False


@dataclass(frozen=True)
class ExecutionObservation:
    """Pure-read answer to ``observe_execution``: current knowledge plus the
    evidence class it rests on. Producing one dispatches nothing."""

    execution_key: str
    state: ObservationState
    evidence: EvidenceClass
    observed_at: datetime


class TurnExecutionPort(Protocol):
    """Product-facing dispatch surface; plugins own the native semantics.

    C-EXEC@v1 block-1 (O-3): the three neutral verbs below are the contract
    carrier. The bool ``cancel`` compatibility shell was deleted in E-INC1b
    b-1 after the consumer switch; ``cancel_execution`` is the only cancel
    answer surface.
    """

    def accept(self, turn_id: str) -> None: ...

    def submit(self, request: ExecutionRequest) -> ExecutionReceipt: ...
    def cancel_execution(self, execution_key: str) -> CancelOutcome: ...
    def observe_execution(self, execution_key: str) -> ExecutionObservation: ...
