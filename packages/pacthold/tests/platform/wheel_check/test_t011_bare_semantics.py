"""specs/010 T011 (SC-004) — bare-wheel rerun of three core-semantics negatives.

Self-contained mini doubles (``pacthold.public`` + pytest only, no repo path
assumptions) replaying three semantics already pinned in the platform suite,
now against the *installed pacthold wheel* in a venv that has no business
distribution at all:

1. same-key replay never dispatches a second start
   (mirrors test_us1_operations_idempotency.test_same_key_same_digest_is_idempotent_no_second_dispatch);
2. an unknown start receipt is never auto-retried and never triggers an
   unsafe release on replay
   (mirrors test_us1_operations_idempotency.test_same_operation_key_replay_never_restarts_or_releases);
3. restart spawn tripwire: rebuilding a runtime from the persisted store and
   querying/closing it must not touch any provider verb
   (mirrors test_us1_recovery_negatives.test_restart_never_contacts_providers).

Overlap with step 5: the suite-wide bare run collects this directory too, so
these three IDs also appear in /tmp/a-t011-junit.xml — that is intentional,
this file is the targeted SC-004 evidence inside the same green run.
"""
from __future__ import annotations

import dataclasses

import pytest

from pacthold.public import (
    AcquireOutcome,
    AcquireRequest,
    AcquireResult,
    CoreContributionSet,
    CoreRuntime,
    CoreStore,
    ExecutionPlan,
    ExecutionState,
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

CONTRACT_ID = "sample.wheel@1"
PLAN_DIGEST = "d" * 64
OWNER = "owner-wheel"


@dataclasses.dataclass(frozen=True)
class WheelContractV1:
    contract_id: dataclasses.ClassVar[str] = CONTRACT_ID
    value: str = ""


class MiniResourceProvider:
    def __init__(self, provider_id: str = "res.wheel") -> None:
        self.provider_id = provider_id
        self.supported_contract_ids = frozenset({CONTRACT_ID})
        self.acquire_calls: list = []
        self.release_calls: list = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id, display_name="wheel mini resource", version="1.0",
            reconcile_support=ReconcileSupport.SUPPORTED,
        )

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        self.acquire_calls.append(request)
        lease_id = f"wheel-lease-{len(self.acquire_calls)}"
        return AcquireResult(
            outcome=AcquireOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, lease_id=lease_id,
            safe_handle=f"wheel-handle-{lease_id}", lease_state=LeaseState.ACQUIRED,
        )

    def release(self, request: ReleaseRequest) -> ReleaseResult:
        self.release_calls.append(request)
        return ReleaseResult(
            outcome=ReleaseOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, lease_id=request.lease_id,
        )

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        return ReconcileResult(
            outcome=ReconcileOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, resolution_ref="wheel-evidence",
        )


class MiniExecutionProvider:
    provider_id = "exec.wheel"
    supported_contract_ids = frozenset({CONTRACT_ID})

    def __init__(self, *, start_mode: str = "success") -> None:
        self.start_mode = start_mode
        self.start_calls: list = []
        self.stop_calls: list = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id, display_name="wheel mini execution", version="1.0",
            reconcile_support=ReconcileSupport.UNSUPPORTED,
        )

    def start(self, request: StartRequest) -> StartResult:
        self.start_calls.append(request)
        if self.start_mode == "raise":  # lost receipt → UNKNOWN, never guessed
            raise TimeoutError("simulated lost start acknowledgement")
        return StartResult(
            outcome=StartOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, run_safe_handle="wheel-run-1",
        )

    def observe(self, handle: RunHandle) -> Observation:
        return Observation(execution_id=handle.execution_id, kind=ObservationKind.RUNNING)

    def stop(self, request: StopRequest) -> StopResult:
        self.stop_calls.append(request)
        return StopResult(
            outcome=StopOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id,
        )


class SpawnTripwireResourceProvider(MiniResourceProvider):
    def acquire(self, request):
        raise AssertionError("bare-wheel tripwire: restart must not acquire")

    def release(self, request):
        raise AssertionError("bare-wheel tripwire: restart must not release")

    def reconcile(self, request):
        raise AssertionError("bare-wheel tripwire: restart must not reconcile on its own")


class SpawnTripwireExecutionProvider(MiniExecutionProvider):
    def start(self, request):
        raise AssertionError("bare-wheel tripwire: restart must not auto-spawn a run")

    def observe(self, handle):
        raise AssertionError("bare-wheel tripwire: restart bookkeeping must not observe")

    def stop(self, request):
        raise AssertionError("bare-wheel tripwire: restart bookkeeping must not stop")


def make_plan(request_key: str) -> ExecutionPlan:
    return ExecutionPlan(
        request_key=request_key,
        digest=PLAN_DIGEST,
        provider_id="exec.wheel",
        provider_version="1.0",
        work_id="work-wheel",
        resources=(
            ResourceRequirement(
                slot="src",
                contract_id=CONTRACT_ID,
                provider_id="res.wheel",
                dependencies=(),
                ownership=OwnershipKind.OWN,
            ),
        ),
    )


def _runtime(tmp_path) -> CoreRuntime:
    return CoreRuntime(CoreStore(tmp_path / "core.db"))


def _register(runtime: CoreRuntime, res, exe) -> None:
    runtime.stage(
        OWNER,
        CoreContributionSet(
            contracts=(WheelContractV1,),
            resource_providers=(res,),
            execution_providers=(exe,),
        ),
    ).commit()


# ==========================================================================
# 1 — same-key replay never dispatches a second start
# ==========================================================================


def test_same_key_replay_no_second_start(tmp_path):
    runtime = _runtime(tmp_path)
    res, exe = MiniResourceProvider(), MiniExecutionProvider()
    _register(runtime, res, exe)

    plan = make_plan("req-replay")
    first = runtime.submit(plan)
    second = runtime.submit(plan)

    assert second.execution_id == first.execution_id
    assert len(exe.start_calls) == 1, "same-key replay dispatched a second start"
    assert len(res.acquire_calls) == 1
    runtime.close()


# ==========================================================================
# 2 — unknown start receipt: replay neither restarts nor releases
# ==========================================================================


def test_unknown_receipt_replay_never_restarts_or_releases(tmp_path):
    runtime = _runtime(tmp_path)
    res, exe = MiniResourceProvider(), MiniExecutionProvider(start_mode="raise")
    _register(runtime, res, exe)

    plan = make_plan("req-unknown")
    first = runtime.submit(plan)
    assert first.execution_state is ExecutionState.START_UNKNOWN, first
    starts_after_first, releases_after_first = len(exe.start_calls), len(res.release_calls)

    replay = runtime.submit(plan)
    assert replay.execution_id == first.execution_id
    assert len(exe.start_calls) - starts_after_first == 0, "unknown receipt auto-retried"
    assert len(res.release_calls) - releases_after_first == 0, "unsafe release on unknown"
    assert runtime.query(first.execution_id).execution_state is ExecutionState.START_UNKNOWN
    runtime.close()


# ==========================================================================
# 3 — restart spawn tripwire: rebuilding from the store never touches a provider
# ==========================================================================


def test_restart_spawn_tripwire(tmp_path):
    db = tmp_path / "core.db"
    first = CoreRuntime(CoreStore(db))
    res, exe = MiniResourceProvider(), MiniExecutionProvider()
    _register(first, res, exe)
    result = first.submit(make_plan("req-tripwire"))
    first.close()

    second = CoreRuntime(CoreStore(db))
    trip_res = SpawnTripwireResourceProvider("res.wheel")
    trip_exe = SpawnTripwireExecutionProvider()
    _register(second, trip_res, trip_exe)

    # construction / query / close are pure bookkeeping over the store: any
    # provider verb here raises and turns this test red.
    view = second.query(result.execution_id)
    assert view.execution_state is ExecutionState.ACTIVE
    assert view.leases[0].lease_state is LeaseState.ACQUIRED
    assert second.owner_busy(OWNER) is True
    report = second.close()
    assert result.execution_id in report.unresolved_executions
    assert trip_res.acquire_calls == [] and trip_res.release_calls == []
