"""US1 operation idempotency / intent-before-side-effect (T007, red-first).

Covers FR-003 (durable intent + stable idempotency key + queryable result),
FR-004 (unknown forbids auto-retry and unsafe release), the same-key/different-
digest rejection, concurrent same-key single-dispatch, and the "intent before
side effect" ordering guarantee (data-model.md Operation row + C1).

All these drive the dispatch surface (submit/query/request_stop) and are RED at
this checkpoint because those entry points still raise ``ContractWiringPending``
until T008 wires the Operation/Lease/Execution state machine.
"""
from __future__ import annotations

import threading

import pytest

from pacthold.public import (
    ContractWiringPending,
    CoreError,
    CoreRuntime,
    CoreStore,
    ExecutionState,
    OperationState,
)
from us1_doubles import (
    DIGEST_A,
    DIGEST_B,
    ControlledExecutionProvider,
    ControlledResourceProvider,
    contribution_set,
    one_own_plan,
)

OWNER = "owner-us1"


@pytest.fixture()
def runtime(tmp_path):
    store = CoreStore(tmp_path / "core.db")
    created = CoreRuntime(store)
    yield created
    if not store.is_closed:
        created.close()


# ==========================================================================
# FR-003 / FR-004 — lost start receipt: unknown, no auto-retry, no unsafe release
# ==========================================================================


def test_lost_start_receipt_is_unknown_and_not_auto_retried(runtime):
    """provider.start raises (equivalent to a lost acknowledgement / timeout):
    the Operation becomes unknown, the Execution is not fabricated as
    cancelled, and the state is queryable.  Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan())                # RED here
    assert len(exe.start_calls) == 1

    view = runtime.query(result.execution_id)
    assert view.operation_state is OperationState.UNKNOWN
    # FR-004: unknown never becomes a synthesised cancellation
    assert view.execution_state is not ExecutionState.CANCELLED


def test_same_operation_key_replay_never_restarts_or_releases(runtime):
    """FR-004: re-submitting the same operation_key after a lost receipt must
    NOT call provider.start a second time (delta == 0) and must NOT release a
    possibly still-in-use resource.  Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    plan = one_own_plan()
    first = runtime.submit(plan)                           # RED here
    starts_after_first = len(exe.start_calls)
    releases_after_first = len(res.release_calls)

    # same request_key + same digest replay: the second start call count delta
    # must be zero and no release of the in-use lease.
    second = runtime.submit(plan)
    assert len(exe.start_calls) - starts_after_first == 0
    assert len(res.release_calls) - releases_after_first == 0
    assert second.execution_id == first.execution_id


# ==========================================================================
# FR-003 — same key different digest: typed refusal, no second dispatch
# ==========================================================================


def test_same_key_conflicting_digest_rejected_typed(runtime):
    """data-model.md ExecutionPlan: same request_key with a different digest is
    rejected and never dispatched a second time.  Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    first = runtime.submit(one_own_plan(request_key="req-x", digest=DIGEST_A))  # RED here
    assert len(exe.start_calls) == 1

    with pytest.raises(CoreError) as excinfo:
        runtime.submit(one_own_plan(request_key="req-x", digest=DIGEST_B))
    assert not isinstance(excinfo.value, ContractWiringPending), (
        "digest-conflict refusal still unwired — T008 not delivered"
    )
    # no second dispatch happened
    assert len(exe.start_calls) == 1


def test_same_key_same_digest_is_idempotent_no_second_dispatch(runtime):
    """FR-003 positive: same key + same digest returns the existing result and
    does not re-dispatch (provider.start count stays 1)."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    plan = one_own_plan(request_key="req-idem", digest=DIGEST_A)
    first = runtime.submit(plan)                           # RED here
    second = runtime.submit(plan)

    assert second.execution_id == first.execution_id
    assert len(exe.start_calls) == 1


# ==========================================================================
# FR-003 — concurrent same key: exactly one dispatcher
# ==========================================================================


def test_concurrent_same_key_single_dispatcher(runtime):
    """Operation (data-model.md): concurrent submits of one key produce exactly
    one dispatch and a single intent row; every caller sees the same execution.
    Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    plan = one_own_plan(request_key="req-conc", digest=DIGEST_A)
    results: list = []
    errors: list[BaseException] = []
    gate = threading.Barrier(4)

    def worker() -> None:
        gate.wait()
        try:
            results.append(runtime.submit(plan))           # RED here (each thread)
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    # exactly one dispatch across all concurrent callers
    assert len(exe.start_calls) == 1
    # one intent row for the key
    rows = runtime.store.query_all(
        "SELECT COUNT(*) FROM core_operation WHERE operation_key = ?",
        (plan.request_key,),
    )
    assert int(rows[0][0]) == 1
    # every caller resolved the same execution
    assert {r.execution_id for r in results} and len({r.execution_id for r in results}) == 1


# ==========================================================================
# FR-003 — intent persisted before the side effect
# ==========================================================================


def test_operation_intent_persisted_before_provider_start(runtime):
    """FR-003 "先意图后副作用": at the instant provider.start runs, the
    operation intent row is already durable with a stable operation_key and a
    planned/in_flight state.  Observed from inside the provider's start callback.
    Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    observed: dict = {}

    def probe(request) -> None:
        # called synchronously inside provider.start — the side-effect moment
        rows = runtime.store.query_all(
            "SELECT state FROM core_operation WHERE operation_key = ?",
            (request.operation_key,),
        )
        observed["rows"] = rows
        observed["operation_key"] = request.operation_key

    exe = ControlledExecutionProvider(on_start=probe)
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan())                # RED here
    assert len(exe.start_calls) == 1
    # intent was visible *before* the side effect completed
    assert observed["rows"], "no operation intent persisted before start"
    state = observed["rows"][0][0]
    assert state in {OperationState.PLANNED.value, OperationState.IN_FLIGHT.value}
    # the intent carries a stable operation_key equal to the request key
    assert observed["operation_key"] == result.operation_key
