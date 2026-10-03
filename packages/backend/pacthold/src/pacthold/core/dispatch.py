"""T008 generic provider / lease / operation dispatch for one ``CoreRuntime``.

This is the scheduling state machine the T004 checkpoint honestly refused
with ``ContractWiringPending``.  Everything here is instance-scoped (FR-001):
one :class:`DispatchCoordinator` owns exactly one ``CoreStore``, reads one
instance ``CoreRegistry`` and mutates one instance ledger — two runtimes in
one process share nothing, and no process-global connection is ever touched
(work_core's ``db`` module is not imported from this package at all).

Semantics locked by specs/010 data-model.md and the US1 suite:

* **validate before any side effect** — provider registration, contract
  availability and same-key/different-digest conflicts are refused with typed
  errors before a single ``acquire``/``start`` leaves the process; the core
  never implicitly selects a provider (FR-002);
* **intent before effect** (FR-003) — every Operation row (one acquire per
  slot plus one start operation keyed by ``request_key``) is durably
  committed to ``core_operation`` *before* the corresponding provider call;
* **idempotency & concurrency** — a replay of the same ``request_key`` with
  the same digest returns the existing Execution and performs zero provider
  calls; concurrent same-key submits are serialised on the instance lock and
  the ``core_execution.request_key`` UNIQUE constraint, so exactly one caller
  dispatches (no polling, no sleeps);
* **partial failure** — when a required acquire is refused/unknown nothing is
  started and only this round's leases are reclaimed; a BORROWED reclaim is
  always a reference release, never a destroy of the original object;
* **unknown is bounded knowledge** (FR-004) — a lost start receipt persists
  Operation=unknown / Execution=start_unknown; unknown is never auto-retried,
  never fabricated into a cancellation, and no path releases a lease whose
  start operation is unknown;
* **terminal is irreversible** — every execution-state write re-reads the
  row inside its transaction and refuses to mutate a terminal state;
* **cleanup keeps the primary cause** (FR-007) — a raising ``provider.stop``
  stays the primary error while every release failure is recorded
  item-by-item in ``cleanup_failures``.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .dtos import (
    AcquireRequest,
    AcquireResult,
    ReleaseRequest,
    ReleaseResult,
    ReconcileRequest,
    ReconcileResult,
    ResolvedInputDeclaration,
    StartRequest,
    StartResult,
    StopRequest,
    StopResult,
)
from .enums import (
    AcquireOutcome,
    ExecutionState,
    LeaseState,
    OperationState,
    OwnershipKind,
    ReconcileOutcome,
    ReconcileSupport,
    ReleaseOutcome,
    StartOutcome,
    StopOutcome,
)
from .errors import (
    ContractNotRegisteredError,
    CoreDTOError,
    DispatchError,
    PlanDigestConflictError,
    ProviderNotRegisteredError,
    ProviderVersionMismatchError,
    ReconcileUnsupportedError,
    TerminalExecutionError,
    UnknownExecutionError,
    UnknownOperationError,
)
from .plan import ExecutionPlan, ResourceRequirement
from .registration import CoreRegistry
from .store import CoreStore

# ---------------------------------------------------------------------------
# neutral core schema (independent namespace; never touches work_core tables)
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS core_execution (
        id TEXT PRIMARY KEY,
        request_key TEXT NOT NULL UNIQUE,
        digest TEXT NOT NULL,
        provider_id TEXT NOT NULL,
        provider_version TEXT NOT NULL,
        work_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN
            ('active','start_unknown','stop_requested',
             'succeeded','failed','cancelled')),
        failed_slot TEXT,
        error TEXT,
        owner TEXT NOT NULL,
        previous_execution_ref TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS core_operation (
        operation_key TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES core_execution(id),
        kind TEXT NOT NULL CHECK (kind IN ('acquire','start')),
        slot TEXT,
        contract_id TEXT,
        provider_id TEXT NOT NULL,
        ownership TEXT,
        state TEXT NOT NULL CHECK (state IN
            ('planned','in_flight','succeeded','refused','unknown')),
        lease_state TEXT CHECK (lease_state IS NULL OR lease_state IN
            ('acquiring','acquired','acquire_unknown','acquire_refused',
             'releasing','released','release_unknown','release_failed')),
        lease_id TEXT,
        safe_handle TEXT,
        run_safe_handle TEXT,
        error_code TEXT,
        error TEXT,
        reconcile_ref TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS core_operation_by_execution "
    "ON core_operation (execution_id, kind)",
)

# Columns added after the T008 checkpoint (specs/010 T010: the Session-resume
# association and the durable reconcile evidence ref).  The tables above are the
# neutral core namespace, so a database created before them gets the columns
# added in place instead of being rebuilt — the existing rows are never touched.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("core_execution", "previous_execution_ref", "TEXT"),
    ("core_operation", "reconcile_ref", "TEXT"),
)

_EXEC_COLUMNS = (
    "id, request_key, digest, provider_id, provider_version, work_id, "
    "state, failed_slot, error, owner, previous_execution_ref"
)
_OP_COLUMNS = (
    "operation_key, execution_id, kind, slot, contract_id, provider_id, "
    "ownership, state, lease_state, lease_id, safe_handle, run_safe_handle, "
    "error_code, error, reconcile_ref"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# public result shapes (returned by CoreRuntime.submit/query/request_stop)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmitResult:
    """Outcome of one dispatch attempt.  A replay returns the *existing*
    execution_id; a partial acquire failure names its ``failed_slot``."""

    execution_id: str
    operation_key: str
    execution_state: ExecutionState
    failed_slot: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class LeaseView:
    """One acquire operation with its lease facts."""

    slot: str
    operation_key: str
    contract_id: str
    provider_id: str
    ownership: OwnershipKind
    state: OperationState
    lease_state: LeaseState | None
    lease_id: str | None
    safe_handle: str | None
    error_code: str | None = None
    reconcile_ref: str | None = None


@dataclass(frozen=True)
class ExecutionView:
    """Query projection of one Execution and its operations (FR-003)."""

    execution_id: str
    request_key: str
    operation_key: str
    execution_state: ExecutionState
    operation_state: OperationState | None
    digest: str
    provider_id: str
    work_id: str
    failed_slot: str | None
    error: str | None
    leases: tuple[LeaseView, ...] = ()
    previous_execution_ref: str | None = None


@dataclass(frozen=True)
class StopDispatchResult:
    """request_stop outcome: the primary stop failure is preserved in
    ``error``/``cause`` while cleanup (release) failures are recorded
    item-by-item, never overwriting the primary cause (FR-007)."""

    execution_id: str
    operation_key: str
    execution_state: ExecutionState
    operation_state: OperationState | None
    error: str | None = None
    cause: BaseException | None = None
    reason: str | None = None
    primary_error_code: str | None = None
    cleanup_failures: tuple[str, ...] = ()
    unresolved_leases: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# internal row/value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExecutionRow:
    id: str
    request_key: str
    digest: str
    provider_id: str
    provider_version: str
    work_id: str
    state: str
    failed_slot: str | None
    error: str | None
    owner: str
    previous_execution_ref: str | None

    @classmethod
    def from_tuple(cls, values: tuple) -> "_ExecutionRow":
        return cls(*values)


@dataclass(frozen=True)
class _OperationRow:
    operation_key: str
    execution_id: str
    kind: str
    slot: str | None
    contract_id: str | None
    provider_id: str
    ownership: str | None
    state: str
    lease_state: str | None
    lease_id: str | None
    safe_handle: str | None
    run_safe_handle: str | None
    error_code: str | None
    error: str | None
    reconcile_ref: str | None

    @classmethod
    def from_tuple(cls, values: tuple) -> "_OperationRow":
        return cls(*values)


@dataclass(frozen=True)
class _ProviderEntry:
    owner: str
    provider: object


@dataclass(frozen=True)
class _PlanCheck:
    """Result of pre-dispatch validation: every name resolved explicitly."""

    exec_owner: str
    exec_provider: object
    by_slot: dict  # slot -> (_ProviderEntry, ResourceRequirement)


@dataclass
class _RoundLease:
    """One lease this dispatch round actually holds (acquired)."""

    execution_id: str
    operation_key: str
    entry: _ProviderEntry
    requirement: ResourceRequirement
    lease_id: str
    safe_handle: str | None


# ---------------------------------------------------------------------------
# the coordinator
# ---------------------------------------------------------------------------


class DispatchCoordinator:
    """Operation/Lease/Execution state machine of ONE CoreRuntime instance."""

    def __init__(
        self,
        store: CoreStore,
        registry: CoreRegistry,
        note_lease: Callable[[str, str, LeaseState], None],
        note_execution: Callable[[str, str, ExecutionState], None],
    ) -> None:
        self._store = store
        self._registry = registry
        self._note_lease = note_lease
        self._note_execution = note_execution
        # instance-level serialisation of store write sections; provider
        # calls never run while it is held.  Not a process global.
        self._db_lock = threading.Lock()
        self._schema_ready = False

    # -- schema / plain reads (caller holds _db_lock) ----------------------

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._store.transaction():
            for statement in _SCHEMA_STATEMENTS:
                self._store.execute(statement)
            for table, column, sql_type in _ADDED_COLUMNS:
                existing = {
                    row[1] for row in self._store.query_all(f"PRAGMA table_info({table})")
                }
                if column not in existing:
                    self._store.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                    )
        self._schema_ready = True

    def _fetch_execution_by_key(self, request_key: str) -> _ExecutionRow | None:
        rows = self._store.query_all(
            f"SELECT {_EXEC_COLUMNS} FROM core_execution WHERE request_key = ?",
            (request_key,),
        )
        return _ExecutionRow.from_tuple(rows[0]) if rows else None

    def _fetch_execution_by_id(self, execution_id: str) -> _ExecutionRow | None:
        rows = self._store.query_all(
            f"SELECT {_EXEC_COLUMNS} FROM core_execution WHERE id = ?",
            (execution_id,),
        )
        return _ExecutionRow.from_tuple(rows[0]) if rows else None

    def _fetch_operation(self, operation_key: str) -> _OperationRow | None:
        rows = self._store.query_all(
            f"SELECT {_OP_COLUMNS} FROM core_operation WHERE operation_key = ?",
            (operation_key,),
        )
        return _OperationRow.from_tuple(rows[0]) if rows else None

    def _fetch_operations(self, execution_id: str) -> tuple[_OperationRow, ...]:
        rows = self._store.query_all(
            f"SELECT {_OP_COLUMNS} FROM core_operation WHERE execution_id = ? "
            "ORDER BY created_at, operation_key",
            (execution_id,),
        )
        return tuple(_OperationRow.from_tuple(values) for values in rows)

    # -- writes -------------------------------------------------------------

    def _set_execution_state(
        self,
        execution_id: str,
        state: ExecutionState,
        *,
        failed_slot: str | None = None,
        error: str | None = None,
    ) -> None:
        """Persist one execution transition, terminal-immutable (storage
        layer: re-read inside the transaction, refuse any write that would
        rewrite a terminal state)."""
        with self._db_lock:
            row = self._fetch_execution_by_id(execution_id)
            if row is None:
                raise UnknownExecutionError(f"execution not found: {execution_id!r}")
            current = ExecutionState(row.state)
            if current.is_terminal():
                raise TerminalExecutionError(
                    f"execution {execution_id!r} is terminal ({current.value}); "
                    "its state is irreversible and cannot be rewritten"
                )
            with self._store.transaction():
                self._store.execute(
                    "UPDATE core_execution SET state = ?, "
                    "failed_slot = COALESCE(?, failed_slot), "
                    "error = COALESCE(?, error), updated_at = ? WHERE id = ?",
                    (state.value, failed_slot, error, _now(), execution_id),
                )
            self._note_execution(row.owner, execution_id, state)

    def _insert_operation(
        self,
        *,
        operation_key: str,
        execution_id: str,
        kind: str,
        provider_id: str,
        state: OperationState,
        slot: str | None = None,
        contract_id: str | None = None,
        ownership: OwnershipKind | None = None,
    ) -> None:
        now = _now()
        with self._db_lock:
            with self._store.transaction():
                self._store.execute(
                    "INSERT INTO core_operation (operation_key, execution_id, "
                    "kind, slot, contract_id, provider_id, ownership, state, "
                    "lease_state, lease_id, safe_handle, run_safe_handle, "
                    "error_code, error, reconcile_ref, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)",
                    (operation_key, execution_id, kind, slot, contract_id,
                     provider_id, ownership.value if ownership else None,
                     state.value, now, now),
                )

    def _update_operation(self, operation_key: str, **fields: object) -> None:
        """fields: state/lease_state/lease_id/safe_handle/run_safe_handle/
        error_code/error/reconcile_ref — None values are left untouched."""
        assignments, params = [], []
        for column in ("state", "lease_state", "lease_id", "safe_handle",
                       "run_safe_handle", "error_code", "error", "reconcile_ref"):
            if column in fields and fields[column] is not None:
                assignments.append(f"{column} = ?")
                value = fields[column]
                params.append(value.value if isinstance(value, (OperationState, LeaseState)) else value)
        assignments.append("updated_at = ?")
        params.append(_now())
        params.append(operation_key)
        with self._db_lock:
            with self._store.transaction():
                self._store.execute(
                    f"UPDATE core_operation SET {', '.join(assignments)} "
                    "WHERE operation_key = ?",
                    tuple(params),
                )

    # -- validation ---------------------------------------------------------

    def _validate_new_plan(self, plan: ExecutionPlan) -> _PlanCheck:
        """Every dispatch refusal in FR-002 lands here — before any row is
        written and before any provider is contacted.  The core never picks a
        provider the plan did not name."""
        exec_entry = self._registry.execution_provider(plan.provider_id)
        if exec_entry is None:
            raise ProviderNotRegisteredError(
                f"execution provider {plan.provider_id!r} is not registered; "
                "the core never implicitly selects one"
            )
        _check_provider_version(exec_entry[1], plan)
        available = set(self._registry.snapshot().contract_ids)
        by_slot: dict[str, tuple[_ProviderEntry, ResourceRequirement]] = {}
        for requirement in plan.resources:
            if requirement.provider_id is None:
                raise ProviderNotRegisteredError(
                    f"slot {requirement.slot!r} names no provider; implicit "
                    "provider selection is refused (FR-002)"
                )
            entry = self._registry.resource_provider(requirement.provider_id)
            if entry is None:
                raise ProviderNotRegisteredError(
                    f"resource provider {requirement.provider_id!r} named by slot "
                    f"{requirement.slot!r} is not registered; the core never "
                    "implicitly selects a same-contract candidate"
                )
            if requirement.contract_id not in available:
                raise ContractNotRegisteredError(
                    f"contract {requirement.contract_id!r} of slot "
                    f"{requirement.slot!r} is not registered in this instance"
                )
            supported = getattr(entry[1], "supported_contract_ids", None)
            if supported is not None and requirement.contract_id not in set(supported):
                raise ContractNotRegisteredError(
                    f"provider {requirement.provider_id!r} does not declare support "
                    f"for contract {requirement.contract_id!r} of slot {requirement.slot!r}"
                )
            by_slot[requirement.slot] = (_ProviderEntry(entry[0], entry[1]), requirement)
        return _PlanCheck(exec_owner=exec_entry[0], exec_provider=exec_entry[1], by_slot=by_slot)

    # -- submit ---------------------------------------------------------------

    def submit(self, plan: ExecutionPlan) -> SubmitResult:
        if not isinstance(plan, ExecutionPlan):
            raise CoreDTOError(f"submit requires an ExecutionPlan, got {plan!r}")
        with self._db_lock:
            self._ensure_schema()
            existing = self._fetch_execution_by_key(plan.request_key)
            if existing is not None:
                return _replay(existing, plan)
            check = self._validate_new_plan(plan)
            execution_id = "exec-" + uuid.uuid4().hex
            now = _now()
            with self._store.transaction():
                cursor = self._store.execute(
                    "INSERT OR IGNORE INTO core_execution (id, request_key, "
                    "digest, provider_id, provider_version, work_id, state, "
                    "failed_slot, error, owner, previous_execution_ref, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)",
                    (execution_id, plan.request_key, plan.digest,
                     plan.provider_id, plan.provider_version, plan.work_id,
                     ExecutionState.ACTIVE.value, check.exec_owner,
                     plan.previous_execution_ref, now, now),
                )
                if cursor.rowcount != 1:
                    # lost the same-key race: exactly one dispatcher won.
                    raced = self._fetch_execution_by_key(plan.request_key)
                    if raced is None:
                        raise DispatchError(
                            f"request_key {plan.request_key!r}: intent insert "
                            "was neither owned nor observable"
                        )
                    return _replay(raced, plan)
            self._note_execution(check.exec_owner, execution_id, ExecutionState.ACTIVE)
        return self._dispatch(plan, execution_id, check)

    def _dispatch(
        self, plan: ExecutionPlan, execution_id: str, check: _PlanCheck
    ) -> SubmitResult:
        acquired: list[_RoundLease] = []
        failed_slot: str | None = None
        failure: str | None = None
        for requirement in _dependency_order(plan):
            entry, _req = check.by_slot[requirement.slot]
            operation_key = _acquire_key(plan.request_key, requirement.slot)
            self._insert_operation(
                operation_key=operation_key,
                execution_id=execution_id,
                kind="acquire",
                provider_id=requirement.provider_id or "",
                state=OperationState.PLANNED,
                slot=requirement.slot,
                contract_id=requirement.contract_id,
                ownership=requirement.ownership,
            )
            request = AcquireRequest(
                operation_key=operation_key,
                execution_id=execution_id,
                contract_id=requirement.contract_id,
                provider_id=requirement.provider_id or "",
                ownership=requirement.ownership,
            )
            try:
                result = entry.provider.acquire(request)
            except Exception as exc:  # noqa: BLE001 - fixed as unknown, never guessed
                self._update_operation(
                    operation_key,
                    state=OperationState.UNKNOWN,
                    lease_state=LeaseState.ACQUIRE_UNKNOWN,
                    error=f"acquire raised: {exc}",
                )
                failed_slot = requirement.slot
                failure = f"acquire for slot {requirement.slot!r} raised: {exc}"
                break
            if isinstance(result, AcquireResult) and result.outcome is AcquireOutcome.SUCCESS:
                self._update_operation(
                    operation_key,
                    state=OperationState.SUCCEEDED,
                    lease_state=LeaseState.ACQUIRED,
                    lease_id=result.lease_id,
                    safe_handle=result.safe_handle,
                )
                self._note_lease(entry.owner, result.lease_id or "", LeaseState.ACQUIRED)
                acquired.append(
                    _RoundLease(
                        execution_id=execution_id,
                        operation_key=operation_key,
                        entry=entry,
                        requirement=requirement,
                        lease_id=result.lease_id or "",
                        safe_handle=result.safe_handle,
                    )
                )
                continue
            if isinstance(result, AcquireResult) and result.outcome is AcquireOutcome.REFUSED:
                self._update_operation(
                    operation_key,
                    state=OperationState.REFUSED,
                    lease_state=LeaseState.ACQUIRE_REFUSED,
                    error_code=result.error_code,
                )
                failed_slot = requirement.slot
                failure = (
                    f"acquire for slot {requirement.slot!r} refused: {result.error_code}"
                )
                break
            # UNKNOWN (or a verdict we cannot trust): fix acquire_unknown,
            # never guess a lease, never release blindly (FR-004).
            self._update_operation(
                operation_key,
                state=OperationState.UNKNOWN,
                lease_state=LeaseState.ACQUIRE_UNKNOWN,
                error="acquire outcome unknown",
            )
            failed_slot = requirement.slot
            failure = f"acquire for slot {requirement.slot!r} outcome is unknown"
            break

        if failed_slot is not None:
            self._release_round(acquired)
            self._set_execution_state(
                execution_id, ExecutionState.FAILED,
                failed_slot=failed_slot, error=failure,
            )
            return SubmitResult(
                execution_id=execution_id,
                operation_key=plan.request_key,
                execution_state=ExecutionState.FAILED,
                failed_slot=failed_slot,
                error=failure,
            )

        # all requirements hold — start the run (prepare/validate above never
        # spawned anything; this is the only spawn point).
        self._insert_operation(
            operation_key=plan.request_key,
            execution_id=execution_id,
            kind="start",
            provider_id=plan.provider_id,
            state=OperationState.IN_FLIGHT,
        )
        request = StartRequest(
            operation_key=plan.request_key,
            execution_id=execution_id,
            provider_id=plan.provider_id,
            plan_digest=plan.digest,
            declared_inputs=tuple(
                ResolvedInputDeclaration(requirement.contract_id, plan.digest)
                for requirement in plan.resources
            ),
        )
        try:
            result = check.exec_provider.start(request)
        except Exception as exc:  # noqa: BLE001 — lost receipt: unknown, no retry
            self._update_operation(
                plan.request_key,
                state=OperationState.UNKNOWN,
                error=f"start receipt lost: {exc}",
            )
            self._set_execution_state(
                execution_id, ExecutionState.START_UNKNOWN,
                error=f"start receipt lost: {exc}",
            )
            return SubmitResult(
                execution_id=execution_id,
                operation_key=plan.request_key,
                execution_state=ExecutionState.START_UNKNOWN,
                error=f"start receipt lost: {exc}",
            )
        if isinstance(result, StartResult) and result.outcome is StartOutcome.SUCCESS:
            self._update_operation(
                plan.request_key,
                state=OperationState.SUCCEEDED,
                run_safe_handle=result.run_safe_handle,
            )
            self._note_execution(check.exec_owner, execution_id, ExecutionState.ACTIVE)
            return SubmitResult(
                execution_id=execution_id,
                operation_key=plan.request_key,
                execution_state=ExecutionState.ACTIVE,
            )
        if isinstance(result, StartResult) and result.outcome is StartOutcome.REFUSED:
            self._update_operation(
                plan.request_key,
                state=OperationState.REFUSED,
                error_code=result.error_code,
            )
            # zero spawn was promised — reclaim exactly this round's leases.
            self._release_round(acquired)
            failure = f"start refused: {result.error_code}"
            self._set_execution_state(
                execution_id, ExecutionState.FAILED, error=failure
            )
            return SubmitResult(
                execution_id=execution_id,
                operation_key=plan.request_key,
                execution_state=ExecutionState.FAILED,
                error=failure,
            )
        self._update_operation(
            plan.request_key,
            state=OperationState.UNKNOWN,
            error="start outcome unknown",
        )
        self._set_execution_state(execution_id, ExecutionState.START_UNKNOWN)
        return SubmitResult(
            execution_id=execution_id,
            operation_key=plan.request_key,
            execution_state=ExecutionState.START_UNKNOWN,
        )

    # -- lease reclaim / release ----------------------------------------------

    def _release_round(self, leases: list[_RoundLease]) -> list[str]:
        """Release exactly the given round's leases (reverse order).  OWN
        releases destroy; BORROWED releases carry ownership=BORROWED and only
        drop the reference — the provider itself defines that axis.  A failed
        or unknown release stays visible (release_failed/release_unknown)."""
        failures: list[str] = []
        for lease in reversed(leases):
            self._update_operation(lease.operation_key, lease_state=LeaseState.RELEASING)
            self._note_lease(lease.entry.owner, lease.lease_id, LeaseState.RELEASING)
            request = ReleaseRequest(
                operation_key=lease.operation_key,
                execution_id=lease.execution_id,
                lease_id=lease.lease_id,
                ownership=lease.requirement.ownership,
                safe_handle=lease.safe_handle,
            )
            try:
                result = lease.entry.provider.release(request)
            except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
                self._update_operation(lease.operation_key, lease_state=LeaseState.RELEASE_FAILED)
                self._note_lease(lease.entry.owner, lease.lease_id, LeaseState.RELEASE_FAILED)
                failures.append(
                    f"release of lease {lease.lease_id} (slot {lease.requirement.slot!r}) raised: {exc}"
                )
                continue
            if isinstance(result, ReleaseResult) and result.outcome is ReleaseOutcome.SUCCESS:
                self._update_operation(lease.operation_key, lease_state=LeaseState.RELEASED)
                self._note_lease(lease.entry.owner, lease.lease_id, LeaseState.RELEASED)
                continue
            if isinstance(result, ReleaseResult) and result.outcome is ReleaseOutcome.UNKNOWN:
                self._update_operation(lease.operation_key, lease_state=LeaseState.RELEASE_UNKNOWN)
                self._note_lease(lease.entry.owner, lease.lease_id, LeaseState.RELEASE_UNKNOWN)
                failures.append(
                    f"release of lease {lease.lease_id} (slot {lease.requirement.slot!r}) "
                    "outcome is unknown; kept visible, never auto-retried"
                )
                continue
            self._update_operation(lease.operation_key, lease_state=LeaseState.RELEASE_FAILED)
            self._note_lease(lease.entry.owner, lease.lease_id, LeaseState.RELEASE_FAILED)
            failures.append(
                f"release of lease {lease.lease_id} (slot {lease.requirement.slot!r}) "
                f"refused: {getattr(result, 'error_code', None) or 'invalid release verdict'}"
            )
        return failures

    # -- query -----------------------------------------------------------------

    def query(self, execution_id: str) -> ExecutionView:
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise CoreDTOError(f"execution_id must be a non-empty string, got {execution_id!r}")
        with self._db_lock:
            self._ensure_schema()
            row = self._fetch_execution_by_id(execution_id)
            if row is None:
                raise UnknownExecutionError(
                    f"no execution {execution_id!r} in this core instance"
                )
            operations = self._fetch_operations(execution_id)
        start_ops = [op for op in operations if op.kind == "start"]
        start = start_ops[0] if start_ops else None
        leases = tuple(
            LeaseView(
                slot=op.slot or "",
                operation_key=op.operation_key,
                contract_id=op.contract_id or "",
                provider_id=op.provider_id,
                ownership=OwnershipKind(op.ownership) if op.ownership else OwnershipKind.OWN,
                state=OperationState(op.state),
                lease_state=LeaseState(op.lease_state) if op.lease_state else None,
                lease_id=op.lease_id,
                safe_handle=op.safe_handle,
                error_code=op.error_code,
                reconcile_ref=op.reconcile_ref,
            )
            for op in operations
            if op.kind == "acquire"
        )
        return ExecutionView(
            execution_id=row.id,
            request_key=row.request_key,
            operation_key=start.operation_key if start else row.request_key,
            execution_state=ExecutionState(row.state),
            operation_state=OperationState(start.state) if start else None,
            digest=row.digest,
            provider_id=row.provider_id,
            work_id=row.work_id,
            failed_slot=row.failed_slot,
            error=row.error,
            leases=leases,
            previous_execution_ref=row.previous_execution_ref,
        )

    # -- request_stop ------------------------------------------------------------

    def request_stop(self, execution_id: str, operation_key: str) -> StopDispatchResult:
        for name, value in (("execution_id", execution_id), ("operation_key", operation_key)):
            if not isinstance(value, str) or not value.strip():
                raise CoreDTOError(f"{name} must be a non-empty string, got {value!r}")
        with self._db_lock:
            self._ensure_schema()
            row = self._fetch_execution_by_id(execution_id)
            if row is None:
                raise UnknownExecutionError(
                    f"no execution {execution_id!r} in this core instance"
                )
            if ExecutionState(row.state).is_terminal():
                raise TerminalExecutionError(
                    f"execution {execution_id!r} is terminal ({row.state}); "
                    "a stop request cannot rewrite a terminal state"
                )
            start = self._fetch_operation(operation_key)
            if start is None or start.execution_id != execution_id or start.kind != "start":
                raise UnknownOperationError(
                    f"execution {execution_id!r} has no start operation {operation_key!r}"
                )
            exec_entry = self._registry.execution_provider(row.provider_id)
            if exec_entry is None:
                raise ProviderNotRegisteredError(
                    f"execution provider {row.provider_id!r} is no longer registered; "
                    "stop must be delegated to the provider that started the run"
                )
            leases = [
                _RoundLease(
                    execution_id=execution_id,
                    operation_key=op.operation_key,
                    entry=_ProviderEntry(*self._registry.resource_provider(op.provider_id)),
                    requirement=ResourceRequirement(
                        slot=op.slot or "",
                        contract_id=op.contract_id or "",
                        provider_id=op.provider_id,
                        ownership=OwnershipKind(op.ownership),
                    ),
                    lease_id=op.lease_id or "",
                    safe_handle=op.safe_handle,
                )
                for op in self._fetch_operations(execution_id)
                if op.kind == "acquire"
                and op.state == OperationState.SUCCEEDED.value
                and op.lease_state == LeaseState.ACQUIRED.value
                and self._registry.resource_provider(op.provider_id) is not None
            ]
            start_state = OperationState(start.state)
            if row.state != ExecutionState.STOP_REQUESTED.value:
                with self._store.transaction():
                    self._store.execute(
                        "UPDATE core_execution SET state = ?, updated_at = ? WHERE id = ?",
                        (ExecutionState.STOP_REQUESTED.value, _now(), execution_id),
                    )
                self._note_execution(row.owner, execution_id, ExecutionState.STOP_REQUESTED)

        # Delegate the stop only where a run handle is known to exist.  An
        # unknown start is bounded knowledge: no stop guess, no retry, and no
        # release of leases the possibly-live run may still use (FR-004).
        primary_error: str | None = None
        cause: BaseException | None = None
        stop_error_code: str | None = None
        confirmed_stopped = False
        if start_state is OperationState.SUCCEEDED:
            try:
                result = exec_entry[1].stop(
                    StopRequest(operation_key=operation_key, execution_id=execution_id)
                )
            except Exception as exc:  # noqa: BLE001 — FR-007: primary cause preserved
                primary_error = str(exc)
                cause = exc
            else:
                if isinstance(result, StopResult):
                    if result.outcome is StopOutcome.SUCCESS:
                        confirmed_stopped = True
                    elif result.outcome is StopOutcome.REFUSED:
                        stop_error_code = result.error_code

        cleanup_failures: list[str] = []
        if confirmed_stopped:
            # A raised, unknown, refused or malformed stop receipt cannot
            # prove that the run no longer uses its OWN leases. Only a
            # confirmed stop permits the release round; its failures remain
            # independent cleanup facts (FR-004/FR-007).
            cleanup_failures.extend(self._release_round(leases))

        with self._db_lock:
            final = self._fetch_execution_by_id(execution_id)
            final_start = self._fetch_operation(operation_key)
            final_ops = self._fetch_operations(execution_id)
        unresolved = tuple(
            op.lease_id
            for op in final_ops
            if op.kind == "acquire"
            and op.lease_id
            and op.lease_state
            in (LeaseState.ACQUIRED.value, LeaseState.RELEASING.value,
                LeaseState.RELEASE_FAILED.value, LeaseState.RELEASE_UNKNOWN.value)
        )
        return StopDispatchResult(
            execution_id=execution_id,
            operation_key=operation_key,
            execution_state=ExecutionState(final.state),
            operation_state=OperationState(final_start.state) if final_start else None,
            error=primary_error,
            cause=cause,
            reason=primary_error,
            primary_error_code=stop_error_code,
            cleanup_failures=tuple(cleanup_failures),
            unresolved_leases=unresolved,
        )

    # -- reconcile (specs/010 T010: the evidence-only seam of data-model Recovery)

    def reconcile(self, execution_id: str, operation_key: str) -> ReconcileResult:
        """Ask the lease's own resource provider to verify a persisted unknown by
        its safe handle, and advance ONLY on a success verdict.

        This is the reconciliation entry data-model.md Recovery assumes ("凭安全
        句柄核实未确认运行，不默认 spawn，无 reconciliation 则明确人工处置") and
        which C1's ``ResourceProvider.reconcile`` plus the descriptor's
        ``reconcile_support`` were frozen for.  Rules it never breaks:

        * it reads the store; it never acquires, starts, observes or stops
          anything — a restart-reconciliation pass cannot spawn (FR-004);
        * the request identity (``lease_id``/``safe_handle``) is the one the
          previous process persisted — nothing is invented for an unknown whose
          handle was never learned, which is refused as explicit human
          disposition instead;
        * the descriptor decides support; ``UNSUPPORTED`` is a typed refusal with
          zero provider calls and zero writes (C1: "不支持 typed unsupported");
        * only ``ReconcileOutcome.SUCCESS`` advances anything.  ``REFUSED`` (the
          provider declines to adjudicate) and ``UNKNOWN`` (still no evidence)
          write nothing at all, so the lease keeps pinning its dependents;
        * it touches the Lease/Operation axis only.  The Execution state is never
          rewritten here — evidence about a lease is not a verdict about the run
          (no synthesized terminal state, FR-004/FR-014).
        """
        for name, value in (("execution_id", execution_id), ("operation_key", operation_key)):
            if not isinstance(value, str) or not value.strip():
                raise CoreDTOError(f"{name} must be a non-empty string, got {value!r}")
        with self._db_lock:
            self._ensure_schema()
            row = self._fetch_execution_by_id(execution_id)
            if row is None:
                raise UnknownExecutionError(
                    f"no execution {execution_id!r} in this core instance"
                )
            op = self._fetch_operation(operation_key)
            if op is None or op.execution_id != execution_id:
                raise UnknownOperationError(
                    f"execution {execution_id!r} has no operation {operation_key!r}"
                )
            if op.kind != "acquire":
                raise DispatchError(
                    f"operation {operation_key!r} is a {op.kind!r} operation, not a lease: "
                    "C1 gives the execution side no reconcile verb, so this unknown needs "
                    "an explicit disposition outside this seam"
                )
            lease_state = LeaseState(op.lease_state) if op.lease_state else None
            if lease_state is None or not lease_state.is_unresolved():
                raise DispatchError(
                    f"lease operation {operation_key!r} is not unresolved "
                    f"(lease_state={op.lease_state!r}); there is no unknown to reconcile"
                )
            if lease_state is LeaseState.ACQUIRED:
                raise DispatchError(
                    f"lease {operation_key!r} is held (acquired), not an unknown: a held "
                    "lease is released by an explicit release, never reconciled away "
                    "(FR-004 forbids unsafe release of a possibly-in-use resource)"
                )
            entry = self._registry.resource_provider(op.provider_id)
            if entry is None:
                raise ProviderNotRegisteredError(
                    f"resource provider {op.provider_id!r} of lease operation "
                    f"{operation_key!r} is not registered in this instance; reconciliation "
                    "must be delegated to the provider that owns the lease"
                )
            support = reconcile_support_of(entry[1])
            if support is not ReconcileSupport.SUPPORTED:
                raise ReconcileUnsupportedError(
                    f"provider {op.provider_id!r} declares reconcile_support="
                    f"{getattr(support, 'value', support)!r}; lease "
                    f"{operation_key!r} stays unresolved and queryable"
                )
            if not op.lease_id or not op.safe_handle:
                raise DispatchError(
                    f"lease operation {operation_key!r} has no persisted lease id/safe handle "
                    f"(lease_id={op.lease_id!r}, safe_handle={op.safe_handle!r}); without a "
                    "handle there is nothing to verify against — explicit disposition required"
                )
            request = ReconcileRequest(
                operation_key=operation_key,
                execution_id=execution_id,
                lease_id=op.lease_id,
                safe_handle=op.safe_handle,
            )
        # the provider call runs outside the write lock, like every other side
        # effect: it must not hold the store open while it thinks.
        result = entry[1].reconcile(request)
        if not isinstance(result, ReconcileResult):
            raise DispatchError(
                f"provider {op.provider_id!r} returned {result!r} instead of a ReconcileResult"
            )
        if result.operation_key != operation_key or result.execution_id != execution_id:
            raise DispatchError(
                f"reconcile verdict for {result.execution_id!r}/{result.operation_key!r} "
                f"does not name the reconciled operation {execution_id!r}/{operation_key!r}"
            )
        if result.outcome is not ReconcileOutcome.SUCCESS:
            # refused / unknown evidence: zero writes — the lease keeps its pin
            # and every unresolved fact stays queryable (FR-004).
            return result
        evidence = result.resolution_ref or "reconciled"
        # _update_operation takes the write lock itself; wrapping it here would
        # deadlock the non-reentrant lock.
        self._update_operation(
            operation_key,
            state=OperationState.SUCCEEDED,
            lease_state=LeaseState.RELEASED,
            reconcile_ref=evidence,
        )
        self._note_lease(
            entry[0], lease_fact_id(op.lease_id, operation_key), LeaseState.RELEASED
        )
        return result


# ---------------------------------------------------------------------------
# module helpers
# ---------------------------------------------------------------------------


def _acquire_key(request_key: str, slot: str) -> str:
    return f"{request_key}#acquire#{slot}"


def reconcile_support_of(provider: object) -> ReconcileSupport | None:
    """The provider's own declared reconciliation capability, or ``None`` when it
    self-describes nothing usable.  Never inferred (C1): a provider that does not
    say ``supported`` cannot be asked for evidence."""
    describe = getattr(provider, "describe", None)
    if not callable(describe):
        return None
    descriptor = describe()
    support = getattr(descriptor, "reconcile_support", None)
    return support if isinstance(support, ReconcileSupport) else None


def lease_fact_id(lease_id: str | None, operation_key: str) -> str:
    """The name a lease fact is reported and resolved under.

    A lease whose acquire was acknowledged has a provider-issued ``lease_id``; an
    unknown acquire has none, and its durable, queryable identity is the
    ``(execution_id, operation_key)`` pair (data-model.md Operation row)."""
    return lease_id or operation_key


def store_lease_facts(store: CoreStore) -> dict[str, tuple[str, str, str]]:
    """``fact_id -> (lease_state, lease_provider_id, execution_owner)`` for every
    lease fact this instance's store carries, resolved or not.

    The store is the authority for shutdown/busy accounting: a restarted process
    reports exactly what the previous one left behind, and a fact rewritten
    around the dispatcher cannot make the report disagree with the record
    (specs/010 T010).  Reads only — no schema creation, no provider contact, so
    rebuilding a ledger can never spawn anything (data-model Recovery)."""
    tables = {
        row[0]
        for row in store.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "core_operation" not in tables or "core_execution" not in tables:
        return {}
    facts: dict[str, tuple[str, str, str]] = {}
    for lease_id, operation_key, lease_state, provider_id, owner in store.query_all(
        "SELECT o.lease_id, o.operation_key, o.lease_state, o.provider_id, e.owner "
        "FROM core_operation o JOIN core_execution e ON e.id = o.execution_id "
        "WHERE o.kind = 'acquire' AND o.lease_state IS NOT NULL "
        "ORDER BY o.operation_key"
    ):
        facts[lease_fact_id(lease_id, operation_key)] = (lease_state, provider_id, owner)
    return facts


def store_execution_facts(store: CoreStore) -> dict[str, tuple[str, str]]:
    """``execution_id -> (state, owner)`` for every execution row this store
    carries, open or terminal; reads only (see :func:`store_lease_facts`)."""
    tables = {
        row[0]
        for row in store.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "core_execution" not in tables:
        return {}
    return {
        execution_id: (state, owner)
        for execution_id, state, owner in store.query_all(
            "SELECT id, state, owner FROM core_execution ORDER BY id"
        )
    }


def _replay(row: _ExecutionRow, plan: ExecutionPlan) -> SubmitResult:
    """Same-key replay: identical digest returns the existing execution with
    zero provider calls; a different digest is a typed refusal that never
    dispatches a second time."""
    if row.digest != plan.digest:
        raise PlanDigestConflictError(
            f"request_key {plan.request_key!r} was already dispatched with a "
            "different content digest; replay must carry the identical plan"
        )
    return SubmitResult(
        execution_id=row.id,
        operation_key=row.request_key,
        execution_state=ExecutionState(row.state),
        failed_slot=row.failed_slot,
        error=row.error,
    )


def _check_provider_version(provider: object, plan: ExecutionPlan) -> None:
    """Best-effort version honesty: when a provider self-describes, its
    declared version must equal the one the plan committed to."""
    describe = getattr(provider, "describe", None)
    if not callable(describe):
        return
    descriptor = describe()
    version = getattr(descriptor, "version", None)
    if isinstance(version, str) and version and version != plan.provider_version:
        raise ProviderVersionMismatchError(
            f"plan committed to provider version {plan.provider_version!r} but "
            f"{plan.provider_id!r} declares {version!r}"
        )


def _dependency_order(plan: ExecutionPlan) -> tuple[ResourceRequirement, ...]:
    """Topological order over the (already cycle-free) dependency graph,
    preserving declared order between independent slots."""
    by_slot = {requirement.slot: requirement for requirement in plan.resources}
    order: list[ResourceRequirement] = []
    done: set[str] = set()

    def visit(slot: str) -> None:
        if slot in done:
            return
        for dependency in by_slot[slot].dependencies:
            visit(dependency)
        done.add(slot)
        order.append(by_slot[slot])

    for requirement in plan.resources:
        visit(requirement.slot)
    return tuple(order)
