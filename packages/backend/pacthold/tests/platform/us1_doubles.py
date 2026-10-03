"""Controlled C1 protocol test doubles for the US1 natural-integration suite.

These doubles satisfy the *frozen* C1 provider protocols (see
``pacthold.core.protocols`` / ``specs/010-platform-core/contracts/platform-api.md``
section C1) so they pass ``CoreRuntime.stage`` registration, and they record
every protocol call so the US1 tests can make black-box side-effect claims
(acquire/release/start call counts, ownership axes, lease/handle identity) that
do **not** depend on the not-yet-delivered T008 dispatch return shapes.

Nothing here imports ``work_core`` or the process-global db: the whole suite is
built on ``pacthold.public`` and per-test ``tmp_path`` ``CoreStore`` instances.
"""
from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from pacthold.public import (
    AcquireOutcome,
    AcquireRequest,
    AcquireResult,
    CoreContributionSet,
    ExecutionPlan,
    LeaseState,
    Observation,
    ObservationKind,
    OwnershipKind,
    ReleaseOutcome,
    ReleaseRequest,
    ReleaseResult,
    ReconcileOutcome,
    ReconcileRequest,
    ReconcileResult,
    ReconcileSupport,
    ResourceProviderDescriptor,
    ResourceRequirement,
    RunHandle,
    StartOutcome,
    StartRequest,
    StartResult,
    StopOutcome,
    StopRequest,
    StopResult,
)

# A digest must be 64-char lowercase hex (see plan._DIGEST); these are the two
# distinct content digests the idempotency scenarios replay against one key.
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


# --------------------------------------------------------------------------
# contracts (frozen dataclasses carrying a versioned contract_id ClassVar)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AlphaContractV1:
    contract_id: dataclasses.ClassVar[str] = "sample.alpha@1"
    value: str = ""


@dataclass(frozen=True)
class BetaContractV1:
    contract_id: dataclasses.ClassVar[str] = "sample.beta@1"
    value: str = ""


# --------------------------------------------------------------------------
# controlled resource provider
# --------------------------------------------------------------------------

class ControlledResourceProvider:
    """A ``ResourceProvider`` whose every call is recorded and scripted."""

    def __init__(
        self,
        provider_id: str,
        *,
        supported: frozenset[str] | None = None,
        reconcile_support: ReconcileSupport = ReconcileSupport.SUPPORTED,
        acquire_mode: str = "success",       # success | refused | unknown
        release_mode: str = "success",        # success | refused | raise
    ) -> None:
        self.provider_id = provider_id
        if supported is not None:
            self.supported_contract_ids = supported
        self._reconcile_support = reconcile_support
        self.acquire_mode = acquire_mode
        self.release_mode = release_mode
        self._lock = threading.Lock()
        self.acquire_calls: list[AcquireRequest] = []
        self.release_calls: list[ReleaseRequest] = []
        self.reconcile_calls: list[ReconcileRequest] = []
        #: lease_ids actually destroyed via a non-borrowing release (test-side
        #: bookkeeping used by the borrowed/own negative scenarios).
        self._own_released_lease_ids: set[str] = set()

    # -- registration identity -------------------------------------------
    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id,
            display_name=f"controlled {self.provider_id}",
            version="1.0",
            reconcile_support=self._reconcile_support,
        )

    # -- acquire ----------------------------------------------------------
    def acquire(self, request: AcquireRequest) -> AcquireResult:
        with self._lock:
            self.acquire_calls.append(request)
        if self.acquire_mode == "success":
            lease_id = f"lease-{self.provider_id}-{len(self.acquire_calls)}"
            return AcquireResult(
                outcome=AcquireOutcome.SUCCESS,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
                lease_id=lease_id,
                safe_handle=f"handle-{lease_id}",
                lease_state=LeaseState.ACQUIRED,
            )
        if self.acquire_mode == "refused":
            return AcquireResult(
                outcome=AcquireOutcome.REFUSED,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
                error_code="controlled_refused",
            )
        # unknown: fixes the acquire as ACQUIRE_UNKNOWN, never guesses a lease
        return AcquireResult(
            outcome=AcquireOutcome.UNKNOWN,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            lease_state=LeaseState.ACQUIRE_UNKNOWN,
        )

    # -- release ----------------------------------------------------------
    def release(self, request: ReleaseRequest) -> ReleaseResult:
        with self._lock:
            self.release_calls.append(request)
        if self.release_mode == "raise":
            raise RuntimeError(f"{self.provider_id} release blew up")
        if self.release_mode == "refused":
            return ReleaseResult(
                outcome=ReleaseOutcome.REFUSED,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
                error_code="controlled_release_refused",
            )
        # success.  An OWN release destroys the object; a BORROWED release only
        # drops the reference (the original object/lease stays acquired).  The
        # double records which lease it actually destroyed so the tests can
        # prove a borrowed release never destroyed the original.
        if request.ownership is OwnershipKind.OWN:
            self._own_released_lease_ids.add(request.lease_id)
        return ReleaseResult(
            outcome=ReleaseOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            lease_id=request.lease_id,
        )

    # -- reconcile --------------------------------------------------------
    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        with self._lock:
            self.reconcile_calls.append(request)
        return ReconcileResult(
            outcome=ReconcileOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            resolution_ref=f"evidence-{len(self.reconcile_calls)}",
        )


# --------------------------------------------------------------------------
# controlled execution provider
# --------------------------------------------------------------------------

class ControlledExecutionProvider:
    """An ``ExecutionProvider`` whose start/observe/stop are scripted and counted.

    ``on_start`` is invoked *inside* ``start`` with the ``StartRequest`` so a
    test can observe store state at the exact moment of the side effect
    (FR-003 "先意图后副作用").
    """

    provider_id = "exec.us1"
    supported_contract_ids = frozenset({"sample.alpha@1", "sample.beta@1"})

    def __init__(
        self,
        *,
        start_mode: str = "success",       # success | raise | unknown
        stop_mode: str = "success",        # success | raise | refused | unknown
        on_start: Optional[Callable[[StartRequest], None]] = None,
    ) -> None:
        self.start_mode = start_mode
        self.stop_mode = stop_mode
        self._on_start = on_start
        self._lock = threading.Lock()
        self.start_calls: list[StartRequest] = []
        self.observe_calls: list[RunHandle] = []
        self.stop_calls: list[StopRequest] = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id="exec.us1",
            display_name="controlled execution",
            version="1.0",
            reconcile_support=ReconcileSupport.UNSUPPORTED,
        )

    def start(self, request: StartRequest) -> StartResult:
        with self._lock:
            self.start_calls.append(request)
        if self._on_start is not None:
            self._on_start(request)
        if self.start_mode == "raise":
            raise TimeoutError("simulated lost start receipt (no acknowledgement)")
        if self.start_mode == "unknown":
            return StartResult(
                outcome=StartOutcome.UNKNOWN,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
            )
        return StartResult(
            outcome=StartOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            run_safe_handle=f"run-{len(self.start_calls)}",
        )

    def observe(self, handle: RunHandle) -> Observation:
        with self._lock:
            self.observe_calls.append(handle)
        return Observation(
            execution_id=handle.execution_id, kind=ObservationKind.RUNNING
        )

    def stop(self, request: StopRequest) -> StopResult:
        with self._lock:
            self.stop_calls.append(request)
        if self.stop_mode == "raise":
            raise RuntimeError("simulated primary stop failure")
        if self.stop_mode == "refused":
            return StopResult(
                outcome=StopOutcome.REFUSED,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
                error_code="controlled_stop_refused",
            )
        if self.stop_mode == "unknown":
            return StopResult(
                outcome=StopOutcome.UNKNOWN,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
            )
        return StopResult(
            outcome=StopOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
        )


# --------------------------------------------------------------------------
# plan / contribution factories
# --------------------------------------------------------------------------

def one_own_plan(
    request_key: str = "req-1",
    digest: str = DIGEST_A,
    *,
    work_id: str = "work-0001",
) -> ExecutionPlan:
    """A single OWN ``src`` requirement — the minimal well-formed dispatch plan."""
    return ExecutionPlan(
        request_key=request_key,
        digest=digest,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id=work_id,
        resources=(
            ResourceRequirement(
                slot="src",
                contract_id="sample.alpha@1",
                provider_id="res.alpha",
                dependencies=(),
                ownership=OwnershipKind.OWN,
            ),
        ),
    )


def two_slot_plan(
    request_key: str = "req-2",
    digest: str = DIGEST_A,
    *,
    a_provider: str = "res.alpha",
    b_provider: str = "res.beta",
    a_ownership: OwnershipKind = OwnershipKind.OWN,
    b_ownership: OwnershipKind = OwnershipKind.OWN,
) -> ExecutionPlan:
    """Two independent slots (a then b) over the same execution provider."""
    return ExecutionPlan(
        request_key=request_key,
        digest=digest,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id="work-0001",
        resources=(
            ResourceRequirement(
                slot="a",
                contract_id="sample.alpha@1",
                provider_id=a_provider,
                dependencies=(),
                ownership=a_ownership,
            ),
            ResourceRequirement(
                slot="b",
                contract_id="sample.beta@1",
                provider_id=b_provider,
                dependencies=(),
                ownership=b_ownership,
            ),
        ),
    )


def contribution_set(
    resource_providers: tuple,
    execution_providers: tuple,
    *,
    contracts: tuple = (AlphaContractV1, BetaContractV1),
) -> CoreContributionSet:
    """One batch bundling both contracts + the given providers (self-contained,
    so contract-reference integrity is satisfied within the batch)."""
    return CoreContributionSet(
        contracts=contracts,
        resource_providers=tuple(resource_providers),
        execution_providers=tuple(execution_providers),
    )
