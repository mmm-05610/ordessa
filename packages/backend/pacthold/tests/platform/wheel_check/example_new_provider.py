"""specs/010 T011 — SC-001 zero-modification onboarding demo (bare wheel).

Runs in venv #2 which holds ONLY the ``pacthold`` wheel (+pytest).  It wires a
brand-new controlled resource provider and a brand-new controlled execution
provider through the *published* surface ``pacthold.public`` and drives the
full lifecycle: stage -> commit -> submit -> query -> same-key replay ->
request_stop -> close, against a tmp ``CoreStore`` file.

Zero-modification proof:
  * this file lives OUTSIDE ``src`` (tests/platform/wheel_check); ``git diff``
    against HEAD shows no source change was needed to onboard a new provider;
  * the AST self-check below fails the run if this module ever imports
    anything beyond ``pacthold.public`` and the standard library — reaching
    into a non-public pacthold module (or any business distribution) turns
    the demo red on the spot.

Exit code 0 == every lifecycle claim held; any assertion error exits non-zero.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib
import sys
import tempfile

# ---------------------------------------------------------------------------
# import-surface self-check (SC-001 guard): pacthold.public + stdlib only
# ---------------------------------------------------------------------------


def _assert_import_surface(path: str) -> None:
    """Reject any import that is not stdlib or exactly ``pacthold.public``."""
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"), filename=path)
    offenders: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — not the public facade
                offenders.append(f"{'.' * node.level}{node.module or ''}")
                continue
            names = [node.module or ""]
        for name in names:
            top = name.split(".")[0]
            if name == "pacthold.public":
                continue
            if top == "pacthold":  # any non-public pacthold module
                offenders.append(name)
            elif top not in sys.stdlib_module_names:
                offenders.append(f"{name} (non-stdlib)")
    if offenders:
        raise AssertionError(
            "SC-001 violation: demo imports beyond pacthold.public+stdlib: "
            + ", ".join(sorted(set(offenders)))
        )


_assert_import_surface(__file__)

from pacthold.public import (  # noqa: E402  (import AFTER the self-check)
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

# ---------------------------------------------------------------------------
# brand-new contract + providers, written only against the published surface
# ---------------------------------------------------------------------------

CONTRACT_ID = "sample.demo@1"
RESOURCE_PROVIDER_ID = "res.demo"
EXECUTION_PROVIDER_ID = "exec.demo"
PLAN_DIGEST = "c" * 64


@dataclasses.dataclass(frozen=True)
class DemoContractV1:
    contract_id: dataclasses.ClassVar[str] = CONTRACT_ID
    value: str = ""


class DemoResourceProvider:
    """A freshly onboarded controlled resource provider (C1 protocol shape)."""

    provider_id = RESOURCE_PROVIDER_ID
    supported_contract_ids = frozenset({CONTRACT_ID})

    def __init__(self) -> None:
        self.acquire_calls: list[AcquireRequest] = []
        self.release_calls: list[ReleaseRequest] = []
        self.reconcile_calls: list[ReconcileRequest] = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id,
            display_name="T011 demo resource provider",
            version="1.0",
            reconcile_support=ReconcileSupport.SUPPORTED,
        )

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        self.acquire_calls.append(request)
        lease_id = f"demo-lease-{len(self.acquire_calls)}"
        return AcquireResult(
            outcome=AcquireOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            lease_id=lease_id,
            safe_handle=f"demo-handle-{lease_id}",
            lease_state=LeaseState.ACQUIRED,
        )

    def release(self, request: ReleaseRequest) -> ReleaseResult:
        self.release_calls.append(request)
        return ReleaseResult(
            outcome=ReleaseOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            lease_id=request.lease_id,
        )

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        self.reconcile_calls.append(request)
        return ReconcileResult(
            outcome=ReconcileOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            resolution_ref=f"demo-evidence-{len(self.reconcile_calls)}",
        )


class DemoExecutionProvider:
    """A freshly onboarded controlled execution provider (C1 protocol shape)."""

    provider_id = EXECUTION_PROVIDER_ID
    supported_contract_ids = frozenset({CONTRACT_ID})

    def __init__(self) -> None:
        self.start_calls: list[StartRequest] = []
        self.observe_calls: list[RunHandle] = []
        self.stop_calls: list[StopRequest] = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id,
            display_name="T011 demo execution provider",
            version="1.0",
            reconcile_support=ReconcileSupport.UNSUPPORTED,
        )

    def start(self, request: StartRequest) -> StartResult:
        self.start_calls.append(request)
        return StartResult(
            outcome=StartOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            run_safe_handle=f"demo-run-{len(self.start_calls)}",
        )

    def observe(self, handle: RunHandle) -> Observation:
        self.observe_calls.append(handle)
        return Observation(execution_id=handle.execution_id, kind=ObservationKind.RUNNING)

    def stop(self, request: StopRequest) -> StopResult:
        self.stop_calls.append(request)
        return StopResult(
            outcome=StopOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
        )


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="a-t011-sc001-")
    store = CoreStore(pathlib.Path(tmpdir) / "core.db")
    runtime = CoreRuntime(store)
    res = DemoResourceProvider()
    exe = DemoExecutionProvider()

    print("== T011 SC-001 zero-modification onboarding demo (bare wheel) ==")
    print(f"pacthold origin: {sys.modules['pacthold'].__file__}")

    # stage + commit: onboarding a brand-new provider touches no source file.
    registration = runtime.stage(
        "owner-demo",
        CoreContributionSet(
            contracts=(DemoContractV1,),
            resource_providers=(res,),
            execution_providers=(exe,),
        ),
    )
    registration.commit()
    snapshot = runtime.registry_snapshot()
    assert CONTRACT_ID in snapshot.contract_ids, snapshot
    assert RESOURCE_PROVIDER_ID in snapshot.resource_provider_ids, snapshot
    assert EXECUTION_PROVIDER_ID in snapshot.execution_provider_ids, snapshot
    print(f"stage/commit OK  contracts={snapshot.contract_ids} "
          f"resource={snapshot.resource_provider_ids} exec={snapshot.execution_provider_ids}")

    plan = ExecutionPlan(
        request_key="req-demo-1",
        digest=PLAN_DIGEST,
        provider_id=EXECUTION_PROVIDER_ID,
        provider_version="1.0",
        work_id="work-demo-0001",
        resources=(
            ResourceRequirement(
                slot="src",
                contract_id=CONTRACT_ID,
                provider_id=RESOURCE_PROVIDER_ID,
                dependencies=(),
                ownership=OwnershipKind.OWN,
            ),
        ),
    )

    # submit: acquire (OWN lease) then start, intent before side effect.
    first = runtime.submit(plan)
    assert first.execution_state is ExecutionState.ACTIVE, first
    assert len(res.acquire_calls) == 1 and len(exe.start_calls) == 1, (res, exe)
    print(f"submit OK  execution_id={first.execution_id} state={first.execution_state.value} "
          f"acquires={len(res.acquire_calls)} starts={len(exe.start_calls)}")

    # query: the dispatched facts are durable and queryable.
    view = runtime.query(first.execution_id)
    assert view.execution_state is ExecutionState.ACTIVE, view
    print(f"query OK   execution_state={view.execution_state.value} "
          f"operation_state={view.operation_state.value} leases={len(view.leases)}")

    # same-key replay: idempotent, never a second dispatch.
    replay = runtime.submit(plan)
    assert replay.execution_id == first.execution_id, (replay, first)
    assert len(exe.start_calls) == 1 and len(res.acquire_calls) == 1, (exe.start_calls, res.acquire_calls)
    print(f"replay OK  same execution_id={replay.execution_id}, starts still {len(exe.start_calls)}")

    # request_stop: delegated stop, then OWN lease released.
    stop = runtime.request_stop(first.execution_id, first.operation_key)
    assert len(exe.stop_calls) == 1, exe.stop_calls
    assert len(res.release_calls) == 1 and res.release_calls[0].ownership is OwnershipKind.OWN, res.release_calls
    assert stop.execution_state is ExecutionState.STOP_REQUESTED, stop
    print(f"request_stop OK  stops={len(exe.stop_calls)} releases={len(res.release_calls)} "
          f"execution_state={stop.execution_state.value} cleanup_failures={stop.cleanup_failures}")

    # close: leases resolved; the run stays non-terminal-but-honest (no
    # fabricated cancelled), so it is reported as unresolved — exactly what
    # FR-007 requires of a close that never silently rewrites facts.
    report = runtime.close()
    assert report.unresolved_leases == (), report
    assert first.execution_id in report.unresolved_executions, report
    assert report.cleanup_failures == (), report
    print(f"close OK   unresolved_leases={report.unresolved_leases} "
          f"unresolved_executions={report.unresolved_executions} "
          f"(stop ack never fabricates a terminal state)")

    print("VERDICT: SC-001 DEMO GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
