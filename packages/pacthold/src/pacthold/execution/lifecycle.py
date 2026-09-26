"""Neutral execution lifecycle coordination (C-EXEC@v1 block1, MB-E2b).

Single implementation of the neutral run bookkeeping moved equal from
the sidecar backend (``_NeutralRun`` plus the
``submit``/``cancel_execution``/``observe_execution``/``_neutral_event``
mechanics): key claim/release/replay, the tristate cancel state machine,
observation classification and evidence append, over two ledgers and one
lock. The backend keeps thin one-way delegations and attribute aliases onto
these ledger objects - never a second copy or a second machine.

Business runs (the adapter's ``_Run``) register into ``active_runs`` under the
opaque attribute contract (``cancel_lock``/``cancel_confirmed``/``port``) and
flow through the same cancel state machine. Ports, factories and event
callbacks stay opaque; this module imports only the standard library and
``pacthold.execution.contracts``.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pacthold.execution.contracts import (
    CancelOutcome, EvidenceClass, ExecutionObservation, ExecutionReceipt,
    ExecutionRequest, ObservationState,
)

#: The composition seam types, kept opaque: a factory receives a stored,
#: provider-neutral context and an event callback and returns a port whose
#: native semantics belong to its owner, not to this module.
PortFactory = Callable[[Mapping[str, Any], Callable[..., None]], Any]
EventCallback = Callable[[], None]


@dataclass
class NeutralRun:
    """One execution tracked through the neutral verbs (C-EXEC@v1 block1).

    Deliberately free of product identity: the run is keyed by the caller's
    opaque ``execution_key`` and carries only dispatch facts and captured
    evidence. It is a projection of what this process knows, never an
    authoritative ledger.
    """

    execution_key: str
    dispatch_id: str
    port: Any
    native_id: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    cancel_lock: threading.Lock = field(default_factory=threading.Lock)
    cancel_confirmed: bool = False
    #: The start intent reached the port but `open_execution` did not answer —
    #: honestly unresolved, never silently rewritten as "nothing was started".
    start_uncertain: bool = False
    #: (kind, observed_at) pairs captured from the sidecar event callback;
    #: monotonic by construction - evidence is only ever appended.
    evidence: list[tuple[str, datetime]] = field(default_factory=list)


class NeutralRunTracker:
    """The one owner of the neutral run ledger, the cancel-receipt ledger and
    their lock (C-EXEC@v1 block1, E-INC1a; equal-moved MB-E2b).

    A cancel receipt outlives its run on purpose: a replay after retirement
    must return the original honest answer, never a fresh dispatch or a new
    refusal.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        #: Composition-layer runs under the opaque attribute contract
        #: (``cancel_lock``/``cancel_confirmed``/``port``): business runs and
        #: neutral runs answer through the same cancel state machine.
        self.active_runs: dict[str, Any] = {}
        self.runs: dict[str, NeutralRun] = {}
        self.cancel_receipts: dict[str, CancelOutcome] = {}

    def submit(
        self, request: ExecutionRequest, *,
        port_factory: PortFactory, on_event: EventCallback,
    ) -> ExecutionReceipt:
        """Neutral start path - no business record is created, read, or
        inferred here (the caller issues ``execution_key`` after its own
        bookkeeping; persistence of ``correlation`` is the caller's).

        A replay of a key already tracked returns the original receipt and
        never re-dispatches the start. A typed refusal raised before the port
        exists left no dispatch behind, so it registers nothing and leaves the
        key clean for a fresh attempt.
        """
        execution_key = request.execution_key
        with self.lock:
            existing = self.runs.get(execution_key)
            if existing is not None:
                return ExecutionReceipt(execution_key, existing.dispatch_id, replayed=True)
            # Claim the key *before* the seam exists: two racing submits of one
            # key must not each build a port and each open a start. A typed
            # refusal from the factory (nothing was dispatched) releases the
            # claim again, so the key stays clean for a fresh attempt.
            run = NeutralRun(
                execution_key=execution_key, dispatch_id=f"neutral:{uuid.uuid4()}",
                port=None)
            self.runs[execution_key] = run
            self.cancel_receipts.pop(execution_key, None)
        context = {
            "execution_key": execution_key,
            "bundle_ref": request.bundle_ref,
            "resource_bindings": [
                {"contract_id": b.contract_id, "object_digest": b.object_digest,
                 "mount_token": b.mount_token}
                for b in request.resource_bindings
            ],
            "capability_demand": sorted(request.capability_demand),
            "deadline_policy": None if request.deadline_policy is None else {
                "hard_deadline": (
                    None if request.deadline_policy.hard_deadline is None
                    else request.deadline_policy.hard_deadline.isoformat()),
                "idle_timeout_seconds": request.deadline_policy.idle_timeout_seconds,
            },
            # Passed through unparsed; the sidecar seam normalizes this with
            # C-HARNESS (IFR-04). Nothing here interprets the values.
            "correlation": dict(request.correlation),
        }
        try:
            port = port_factory(
                context,
                lambda execution_id, kind, data: self.note_native_event(
                    execution_id, kind, data, on_event=on_event),
            )
        except BaseException:
            # typed refusal before the seam produced anything: release the
            # claim so the key is honestly absent again (nothing was dispatched)
            with self.lock:
                if self.runs.get(execution_key) is run:
                    del self.runs[execution_key]
            raise
        run.port = port
        try:
            run.native_id = str(port.open_execution(execution_key))
        except BaseException:
            run.start_uncertain = True
            raise
        on_event()
        return ExecutionReceipt(execution_key, run.dispatch_id)

    def cancel_execution(self, execution_key: str) -> CancelOutcome:
        """Block-1 tristate cancel. A lost answer is captured and classified
        ``unknown`` here - it is never re-dispatched blindly and never allowed
        to leak as an exception, because both would erase the distinction the
        contract promises the consumer.
        """
        with self.lock:
            prior = self.cancel_receipts.get(execution_key)
            target = self.active_runs.get(execution_key) or self.runs.get(execution_key)
        if prior is not None:
            return prior
        if target is None:
            outcome = CancelOutcome.REFUSED_NO_ACTIVE_RUN
            with self.lock:
                self.cancel_receipts[execution_key] = outcome
            return outcome
        with target.cancel_lock:
            with self.lock:
                prior = self.cancel_receipts.get(execution_key)
            if prior is not None:
                return prior
            if getattr(target, "port", None) is None:
                # Pre-port window (submit claimed the key but the factory seam
                # has not produced a port yet): nothing was dispatched, so there
                # is no dispatch for a receipt to guard. Answer UNKNOWN honestly
                # but do NOT record it - a later cancel must still be able to
                # reach the live port once the run starts (P8, approved (i)).
                return CancelOutcome.UNKNOWN
            try:
                accepted = target.port.cancel(execution_key)
            except BaseException:  # noqa: BLE001 - timeout/channel-lost: honest unknown
                accepted = None
            if accepted is None:
                outcome = CancelOutcome.UNKNOWN
            elif accepted:
                outcome = CancelOutcome.CONFIRMED_STOPPED
                target.cancel_confirmed = True
            else:
                outcome = CancelOutcome.REFUSED_NO_ACTIVE_RUN
            # recorded while still holding the run's cancel lock: a racer
            # woken from that lock must find the receipt, never a window
            # in which it would dispatch the abort a second time.
            with self.lock:
                self.cancel_receipts[execution_key] = outcome
        return outcome

    def observe_execution(self, execution_key: str) -> ExecutionObservation:
        """Pure read of what this process currently knows (E-D2 supplement A).

        Dispatches nothing, writes nothing, and never invents a transition:
        ``NOT_KNOWN_TO_E`` is bounded knowledge, not a proof that nothing ever
        started - only a typed provider-side zero-creation fact may lift an
        ambiguous dispatch, and that proof arrives through the consumer's
        channel, never from this method.
        """
        now = datetime.now(timezone.utc)
        with self.lock:
            run = self.active_runs.get(execution_key)
            neutral = self.runs.get(execution_key)
        if run is not None:
            if run.result is not None:
                state, evidence = ObservationState.TERMINAL, EvidenceClass.TERMINAL_RECEIPT
            elif run.cancel_confirmed:
                state, evidence = (
                    ObservationState.STOPPED_CONFIRMED, EvidenceClass.CANCEL_CONFIRMATION)
            elif run.native_id:
                state, evidence = ObservationState.RUNNING, EvidenceClass.NATIVE_REPORT
            else:
                state, evidence = ObservationState.RUNNING, EvidenceClass.DISPATCH_ACK
        elif neutral is not None:
            if neutral.cancel_confirmed:
                state, evidence = (
                    ObservationState.STOPPED_CONFIRMED, EvidenceClass.CANCEL_CONFIRMATION)
            elif neutral.evidence:
                state, evidence = ObservationState.RUNNING, EvidenceClass.NATIVE_REPORT
            else:
                state, evidence = ObservationState.RUNNING, EvidenceClass.DISPATCH_ACK
        else:
            state, evidence = ObservationState.NOT_KNOWN_TO_E, EvidenceClass.NONE
        return ExecutionObservation(execution_key, state, evidence, now)

    def note_native_event(
        self, execution_key: str, kind: str, data: Mapping[str, Any], *,
        on_event: EventCallback,
    ) -> None:
        with self.lock:
            run = self.runs.get(execution_key)
            if run is not None:
                run.evidence.append((str(kind), datetime.now(timezone.utc)))
        on_event()
