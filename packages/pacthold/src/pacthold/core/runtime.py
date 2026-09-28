"""``CoreRuntime`` — the C1 composition root of one core instance.

One runtime owns one ``CoreStore`` and one instance-scoped
``CoreRegistry``; nothing here is process-global (FR-001).  Since T008 the
runtime also composes the real dispatch state machine
(:class:`pacthold.core.dispatch.DispatchCoordinator`): ``submit`` /
``query`` / ``request_stop`` validate the plan, persist operation intent
before every side effect, keep idempotency on the request key, and persist
every lease/execution fact into the instance store (queryable after
restart).

Ledger authority (T010): the *store* is the record of what is unresolved, and
the in-memory ledger only carries facts the store does not (contract-level
placeholders noted through ``_note_lease``/``_note_execution``).  That is what
makes a restarted runtime answer ``owner_busy``/``unregister``/``close`` from
durable evidence instead of a lost process memory, and it can never make a
report disagree with a record rewritten around the dispatcher.  Reading those
facts is pure SQL: rebuilding never contacts a provider, so restart cannot
spawn (data-model.md Recovery).  ``close`` lists unresolved work, it never
silently kills or rewrites anything (FR-007/FR-014).
"""
from __future__ import annotations

from dataclasses import dataclass

from .dispatch import (
    DispatchCoordinator,
    ExecutionView,
    StopDispatchResult,
    SubmitResult,
    store_execution_facts,
    store_lease_facts,
)
from .dtos import ReconcileResult
from .enums import ExecutionState, LeaseState
from .errors import (
    OwnerBusyError,
    RuntimeClosedError,
)
from .plan import ExecutionPlan
from .registration import CoreContributionSet, CoreRegistration, CoreRegistry, CoreRegistrySnapshot
from .store import CoreStore


@dataclass(frozen=True)
class ShutdownReport:
    """Honest close-out facts: three ordered tuples, nothing killed silently."""

    unresolved_executions: tuple[str, ...] = ()
    unresolved_leases: tuple[str, ...] = ()
    cleanup_failures: tuple[str, ...] = ()


class CoreRuntime:
    """Composition root: one store, one registry, one instance."""

    __slots__ = (
        "_store", "_registry", "_closed", "_leases", "_executions",
        "_shutdown_report", "_dispatch",
    )

    def __init__(self, store: CoreStore) -> None:
        if not isinstance(store, CoreStore):
            raise TypeError(f"CoreRuntime requires a CoreStore instance, got {store!r}")
        self._store = store
        self._registry = CoreRegistry()
        self._closed = False
        # lease fact id -> (owner, LeaseState); execution id -> (owner, state).
        # A memory of what THIS process dispatched; the store stays the record.
        self._leases: dict[str, tuple[str, LeaseState]] = {}
        self._executions: dict[str, tuple[str, ExecutionState]] = {}
        self._shutdown_report: ShutdownReport | None = None
        # T008: instance-scoped dispatch machine over THIS store and registry.
        self._dispatch = DispatchCoordinator(
            store, self._registry, self._note_lease, self._note_execution
        )

    @property
    def store(self) -> CoreStore:
        return self._store

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeClosedError("CoreRuntime is closed")

    # -- fact ledger (store-authoritative, ledger as the local supplement) --

    def _lease_ledger(self) -> dict[str, tuple[str, LeaseState]]:
        """``fact_id -> (owner, LeaseState)``: every lease the store records, plus
        the lease facts this process was told about that the store does not
        carry.  Store rows win on any disagreement."""
        try:
            durable = store_lease_facts(self._store)
        except Exception:  # an unreadable store adds nothing; the ledger stands
            durable = {}
        merged: dict[str, tuple[str, LeaseState]] = {}
        for fact_id, (state, provider_id, execution_owner) in durable.items():
            entry = self._registry.resource_provider(provider_id)
            merged[fact_id] = (entry[0] if entry else execution_owner, LeaseState(state))
        for fact_id, value in self._leases.items():
            merged.setdefault(fact_id, value)
        return merged

    def _execution_ledger(self) -> dict[str, tuple[str, ExecutionState]]:
        """``execution_id -> (owner, ExecutionState)`` with the same rule: the
        durable record outranks this process's memory of it."""
        try:
            durable = store_execution_facts(self._store)
        except Exception:  # noqa: BLE001 - see _lease_ledger
            durable = {}
        merged: dict[str, tuple[str, ExecutionState]] = {
            execution_id: (owner, ExecutionState(state))
            for execution_id, (state, owner) in durable.items()
        }
        for execution_id, value in self._executions.items():
            merged.setdefault(execution_id, value)
        return merged

    def _unresolved_lease_ids(self, owner: str | None = None) -> tuple[str, ...]:
        return tuple(sorted(
            fact_id
            for fact_id, (lease_owner, state) in self._lease_ledger().items()
            if state.is_unresolved() and (owner is None or lease_owner == owner)
        ))

    # -- registration (real, in-process, instance-scoped) ------------------

    def stage(self, owner: str, contributions: CoreContributionSet) -> CoreRegistration:
        """Validate and reserve one contribution batch; publishes nothing.

        Typed failure (conflict / missing contract reference / invalid
        descriptor) leaves the registry snapshot exactly as before."""
        self._ensure_open()
        if not isinstance(owner, str) or not owner.strip():
            raise TypeError(f"stage owner must be a non-empty string, got {owner!r}")
        if not isinstance(contributions, CoreContributionSet):
            raise TypeError(f"contributions must be a CoreContributionSet, got {contributions!r}")
        batch = self._registry.stage(owner, contributions)
        return CoreRegistration(self._registry, batch)

    def owner_busy(self, owner: str) -> bool:
        """True while the owner has a committed batch or any unresolved lease.

        Honest at this checkpoint: staged-only does not count as busy, an
        active registration does, and active/unknown leases keep it busy
        until evidence resolves them (FR-007).  Lease facts come from the
        store first, so a restarted runtime stays honest about what the
        previous process left behind."""
        self._ensure_open()
        if owner in self._registry.active_owners():
            return True
        return bool(self._unresolved_lease_ids(owner))

    def unregister(self, owner: str) -> None:
        """Remove one owner's active batch.  Refused (typed) while the owner
        still holds active or unknown leases; existing runs are never
        destroyed as a side effect."""
        self._ensure_open()
        blocking = self._unresolved_lease_ids(owner)
        if blocking:
            raise OwnerBusyError(
                f"owner {owner!r} still holds unresolved leases: {', '.join(blocking)}; "
                "resolve them with evidence before unregistering"
            )
        self._registry.unregister(owner)

    def registry_snapshot(self) -> CoreRegistrySnapshot:
        """Read-only view of the committed registration state."""
        self._ensure_open()
        return self._registry.snapshot()

    # -- execution entry points (T008 dispatch wiring) -----------------------

    def submit(self, plan: ExecutionPlan) -> SubmitResult:
        """Validate and dispatch one ExecutionPlan through this instance's
        store/registry (see ``pacthold.core.dispatch`` for the full state
        machine).  Closed instances refuse with ``RuntimeClosedError``; every
        validation failure is a typed ``CoreError`` raised before any
        acquire/start side effect."""
        self._ensure_open()
        return self._dispatch.submit(plan)

    def query(self, execution_id: str) -> ExecutionView:
        """Queryable execution/operation state view (FR-003)."""
        self._ensure_open()
        return self._dispatch.query(execution_id)

    def request_stop(self, execution_id: str, operation_key: str) -> StopDispatchResult:
        """Delegate stop to the execution provider; the primary failure is
        preserved and cleanup failures are recorded item-by-item (FR-007)."""
        self._ensure_open()
        return self._dispatch.request_stop(execution_id, operation_key)

    def reconcile(self, execution_id: str, operation_key: str) -> ReconcileResult:
        """Resolve ONE unresolved lease by evidence, never by guessing (T010;
        specs/010 data-model.md Recovery: 凭安全句柄核实未确认运行).

        The lease's own provider is asked to verify the persisted ``lease_id`` /
        ``safe_handle``; only a success verdict advances the lease, and the
        execution state is never touched.  A provider whose descriptor declares
        ``reconcile_support=unsupported`` refuses typed, and a lease with no
        persisted handle is reported as needing an explicit disposition instead
        of being fabricated one.  No acquire, start, observe or stop leaves this
        call, so reconciliation can never become an implicit re-dispatch after a
        restart (FR-004)."""
        self._ensure_open()
        return self._dispatch.reconcile(execution_id, operation_key)

    # -- shutdown -----------------------------------------------------------

    def close(self) -> ShutdownReport:
        """Stop admitting work, persist nothing new, report the unresolved.

        close() does not kill executions or release leases: every unresolved
        fact is listed instead (contract: "close 不隐式杀运行").  The listed
        facts are the store's, so the report says exactly what a later process
        reading the same file can query — including after a restart, where this
        process never dispatched anything.  The store is closed last; a
        store-close failure is recorded, never swallowed.  Re-close returns the
        same report."""
        if self._shutdown_report is not None:
            return self._shutdown_report
        unresolved_executions = tuple(sorted(
            execution_id
            for execution_id, (_owner, state) in self._execution_ledger().items()
            if state.is_unresolved()
        ))
        unresolved_leases = self._unresolved_lease_ids()
        cleanup_failures: list[str] = []
        try:
            self._store.close()
        except Exception as exc:  # recorded, not swallowed, not fatal
            cleanup_failures.append(f"store close failed: {exc!r}")
        self._closed = True
        self._shutdown_report = ShutdownReport(
            unresolved_executions=unresolved_executions,
            unresolved_leases=unresolved_leases,
            cleanup_failures=tuple(cleanup_failures),
        )
        return self._shutdown_report

    # -- internal bookkeeping hooks (fed by the T008 dispatcher) -----------

    def _note_lease(self, owner: str, lease_id: str, state: LeaseState) -> None:
        """Private ledger hook; the T008 dispatch machine will maintain real
        lease facts.  Contract tests use it to prove unregister/close honesty
        before dispatch exists."""
        if not isinstance(state, LeaseState):
            raise TypeError(f"lease state must be a LeaseState member, got {state!r}")
        self._leases[lease_id] = (owner, state)

    def _note_execution(self, owner: str, execution_id: str, state: ExecutionState) -> None:
        if not isinstance(state, ExecutionState):
            raise TypeError(f"execution state must be an ExecutionState member, got {state!r}")
        self._executions[execution_id] = (owner, state)
