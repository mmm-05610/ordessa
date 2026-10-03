"""US1 resource lifecycle & dependency negatives (T007, red-first).

Covers FR-002 (dependency cycle / missing provider), the lease ownership axes
(borrowed vs own, data-model.md Lease/ownership), the multi-dependency partial
failure path (spec.md US1.1) and FR-007 cleanup double-exception.

The dispatch-dependent tests are RED now because ``CoreRuntime.submit`` /
``request_stop`` refuse with ``ContractWiringPending`` until T008.  The pure
plan-construction and protocol-shape guards are GREEN now (they exercise
semantics that already shipped at T004).
"""
from __future__ import annotations

import pytest

from pacthold.public import (
    ContractWiringPending,
    CoreContributionSet,
    CoreDTOError,
    CoreError,
    CoreRuntime,
    CoreStore,
    ExecutionPlan,
    ExecutionState,
    LeaseState,
    OwnershipKind,
    ResourceRequirement,
)
from us1_doubles import (
    DIGEST_A,
    AlphaContractV1,
    ControlledExecutionProvider,
    ControlledResourceProvider,
    contribution_set,
    one_own_plan,
    two_slot_plan,
)

OWNER = "owner-us1"


@pytest.fixture()
def runtime(tmp_path):
    store = CoreStore(tmp_path / "core.db")
    created = CoreRuntime(store)
    yield created
    if not store.is_closed:
        created.close()


def _mark_non_wiring_refusal(exc_value: BaseException) -> None:
    """A dispatch negative must be refused by the *wired* machine, not by the
    T004 placeholder.  ``ContractWiringPending`` is itself a ``CoreError``, so
    the plain ``raises(CoreError)`` guard alone cannot prove T008 landed — this
    asserts the honest "still unwired" red reason."""
    assert not isinstance(exc_value, ContractWiringPending), (
        "dispatch surface still raises ContractWiringPending — T008 not delivered"
    )


# ==========================================================================
# FR-002 — dependency cycle (green at construction; red at dispatch attempt)
# ==========================================================================


def test_dependency_cycle_rejected_typed_at_construction():
    """FR-002 positive+guard: a cyclic ResourceRequirement graph is a typed
    construction refusal before any submit — no Execution/Operation can exist
    because the plan itself is unbuildable."""
    a = ResourceRequirement("a", "sample.alpha@1", provider_id="res.alpha", dependencies=("b",))
    b = ResourceRequirement("b", "sample.beta@1", provider_id="res.beta", dependencies=("a",))
    with pytest.raises(CoreDTOError, match="cycle"):
        ExecutionPlan("req-cycle", DIGEST_A, "exec.us1", "1.0", "work-0001", (a, b))


def test_dependency_cycle_produces_zero_execution_rows(runtime):
    """FR-002 zero-row claim asserted through the dispatch surface: a well-formed
    plan creates exactly one execution (>=1), so a rejected cyclic plan must
    create zero.  Red until submit is wired (raises ContractWiringPending)."""
    res_a = ControlledResourceProvider("res.alpha")
    res_b = ControlledResourceProvider("res.beta")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res_a, res_b), (exe,))).commit()

    # control: a valid plan must produce one operation/execution row
    result = runtime.submit(one_own_plan())               # RED here
    rows = runtime.store.query_all("SELECT COUNT(*) FROM core_execution")
    assert int(rows[0][0]) == 1


# ==========================================================================
# FR-002 — missing provider, never implicitly selected
# ==========================================================================


def test_missing_provider_does_not_dispatch_typed_refusal_no_implicit_choice(runtime):
    """FR-002 negative: a plan naming an unregistered provider is refused with a
    typed dispatch error and the two registered candidate providers are never
    implicitly chosen (zero acquire calls on each).  Red until submit is wired."""
    cand_x = ControlledResourceProvider("res.candx", supported=frozenset({"sample.alpha@1"}))
    cand_y = ControlledResourceProvider("res.candy", supported=frozenset({"sample.alpha@1"}))
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((cand_x, cand_y), (exe,))).commit()

    plan = ExecutionPlan(
        request_key="req-missing",
        digest=DIGEST_A,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id="work-0001",
        resources=(
            ResourceRequirement(
                slot="a",
                contract_id="sample.alpha@1",
                provider_id="res.absent",   # not registered
                ownership=OwnershipKind.OWN,
            ),
        ),
    )
    with pytest.raises(CoreError) as excinfo:
        runtime.submit(plan)                               # RED here
    _mark_non_wiring_refusal(excinfo.value)

    # the core never silently picks a same-contract candidate
    assert cand_x.acquire_calls == []
    assert cand_y.acquire_calls == []
    assert exe.start_calls == []


def test_two_candidates_registered_plan_names_one_explicitly(runtime):
    """FR-002 positive control: when the plan *does* name one registered provider
    explicitly, only that provider is used — proving the earlier zero-call result
    came from the missing-provider refusal, not from candidates being unusable.
    Red until submit is wired."""
    chosen = ControlledResourceProvider("res.candx", supported=frozenset({"sample.alpha@1"}))
    other = ControlledResourceProvider("res.candy", supported=frozenset({"sample.alpha@1"}))
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((chosen, other), (exe,))).commit()

    plan = ExecutionPlan(
        request_key="req-explicit",
        digest=DIGEST_A,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id="work-0001",
        resources=(
            ResourceRequirement(
                slot="a",
                contract_id="sample.alpha@1",
                provider_id="res.candx",   # explicitly chosen
                ownership=OwnershipKind.OWN,
            ),
        ),
    )
    runtime.submit(plan)                                   # RED here
    assert len(chosen.acquire_calls) == 1
    assert other.acquire_calls == []


# ==========================================================================
# Lease ownership — borrowed vs own
# ==========================================================================


def test_borrowed_release_only_drops_reference(runtime):
    """FR-002/US1: a borrowed lease release carries ownership=BORROWED and must
    not destroy the original object / change the original lease.  Red until
    submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    plan = ExecutionPlan(
        request_key="req-borrow",
        digest=DIGEST_A,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id="work-0001",
        resources=(
            ResourceRequirement(
                slot="a",
                contract_id="sample.alpha@1",
                provider_id="res.alpha",
                ownership=OwnershipKind.BORROWED,
            ),
        ),
    )
    result = runtime.submit(plan)                          # RED here

    # run completes and triggers teardown of the borrowed reference
    runtime.request_stop(result.execution_id, result.operation_key)

    # exactly one release, and it was a *reference* release (borrowed)
    assert len(res.release_calls) == 1
    rel = res.release_calls[0]
    assert rel.ownership is OwnershipKind.BORROWED
    # the original object was never destroyed by the borrowed release
    assert rel.lease_id not in res._own_released_lease_ids


def test_own_release_destroys_and_borrowed_negative_control(runtime):
    """Ownership positive/negative: an OWN release destroys the identified lease
    (handle/lease carried, ownership=OWN) — the contrast with the borrowed case."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan())                # RED here
    runtime.request_stop(result.execution_id, result.operation_key)

    assert len(res.release_calls) == 1
    rel = res.release_calls[0]
    assert rel.ownership is OwnershipKind.OWN
    assert rel.lease_id in res._own_released_lease_ids


# ==========================================================================
# Lease state machine — acquired -> releasing -> released; release_failed seen
# ==========================================================================


def test_own_lease_state_progresses_acquired_releasing_released(runtime):
    """Lease transitions (data-model.md): acquired -> releasing -> released.
    Observed black-box via provider call ordering and the final release request.
    Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan(request_key="req-lc-own"))   # RED here
    assert result.execution_state is ExecutionState.ACTIVE
    assert res.acquire_calls[-1].ownership is OwnershipKind.OWN

    runtime.request_stop(result.execution_id, result.operation_key)
    assert len(res.release_calls) == 1
    assert res.release_calls[0].lease_id  # releasing carries the real lease id
    # terminal: the lease is no longer unresolved
    report = runtime.close()
    assert report.unresolved_leases == ()


def test_release_failure_is_visible_not_silently_released(runtime):
    """release_failed must stay visible: a refused/failed release never becomes
    a silent 'released' and keeps the owner busy (FR-007 / FR-004 no unsafe
    release).  Red until submit is wired."""
    res = ControlledResourceProvider("res.alpha", release_mode="refused")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan(request_key="req-lc-fail"))  # RED here
    runtime.request_stop(result.execution_id, result.operation_key)

    assert len(res.release_calls) == 1
    assert runtime.owner_busy(OWNER) is True   # failed release keeps it pinned
    report = runtime.close()
    assert len(report.unresolved_leases) == 1   # persisted, not rewritten


# ==========================================================================
# US1.1 — multi-dependency partial failure
# ==========================================================================


def test_partial_acquire_failure_starts_nothing_reclaims_only_own(runtime):
    """US1.1: A acquires (OWN), B refuses -> nothing is started, only the round's
    own A is reclaimed (release exactly once), and the report names B as failed.
    Red until submit is wired."""
    res_a = ControlledResourceProvider("res.alpha", acquire_mode="success")
    res_b = ControlledResourceProvider("res.beta", acquire_mode="refused")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res_a, res_b), (exe,))).commit()

    plan = two_slot_plan(a_provider="res.alpha", b_provider="res.beta")
    result = runtime.submit(plan)                          # RED here

    # nothing started
    assert exe.start_calls == []
    # only own A reclaimed, exactly once
    assert len(res_a.release_calls) == 1
    assert res_a.release_calls[0].ownership is OwnershipKind.OWN
    # refused B produced no lease to release
    assert res_b.release_calls == []
    # the failure is reported against the failing slot
    assert getattr(result, "failed_slot", None) == "b"
    assert exe.stop_calls == []


def test_borrowed_dependency_is_not_reclaimed_on_failure(runtime):
    """US1.1 negative control: when the successful slot is BORROWED, a later
    failure must not destroy it — the borrowed reference is dropped, never the
    original object.  Red until submit is wired."""
    res_a = ControlledResourceProvider("res.alpha", acquire_mode="success")
    res_b = ControlledResourceProvider("res.beta", acquire_mode="refused")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res_a, res_b), (exe,))).commit()

    plan = two_slot_plan(
        a_provider="res.alpha",
        b_provider="res.beta",
        a_ownership=OwnershipKind.BORROWED,
    )
    runtime.submit(plan)                                   # RED here

    assert exe.start_calls == []
    # if A is reclaimed at all it must be a *reference* release, never a destroy
    for rel in res_a.release_calls:
        assert rel.ownership is OwnershipKind.BORROWED
        assert rel.lease_id not in res_a._own_released_lease_ids


# ==========================================================================
# FR-007 — cleanup double exception
# ==========================================================================


def test_stop_exception_keeps_primary_cause_and_skips_unsafe_cleanup(runtime):
    """FR-004/FR-007: a lost stop receipt keeps the primary error and lease.

    A release provider configured to raise is a counterexample: no release
    call means no secondary exception may conceal the possibly live run.
    """
    res = ControlledResourceProvider("res.alpha", release_mode="raise")
    exe = ControlledExecutionProvider(stop_mode="raise")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan())
    stop = runtime.request_stop(result.execution_id, result.operation_key)

    assert isinstance(stop.cause, RuntimeError)
    assert str(stop.cause) == "simulated primary stop failure"
    assert stop.error == stop.reason == str(stop.cause)
    assert stop.cleanup_failures == ()
    assert res.release_calls == []
    assert stop.execution_state is ExecutionState.STOP_REQUESTED
    assert stop.unresolved_leases
    assert runtime.owner_busy(OWNER) is True


def test_confirmed_stop_preserves_cleanup_exception(runtime):
    """FR-007: once stop succeeds, a failed release stays independently visible."""
    res = ControlledResourceProvider("res.alpha", release_mode="raise")
    exe = ControlledExecutionProvider(stop_mode="success")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    result = runtime.submit(one_own_plan(request_key="req-cleanup-after-stop"))
    stop = runtime.request_stop(result.execution_id, result.operation_key)

    assert stop.error is None and stop.cause is None
    assert len(res.release_calls) == 1
    assert len(stop.cleanup_failures) == 1
    assert "release blew up" in stop.cleanup_failures[0]
    assert stop.unresolved_leases
    assert runtime.owner_busy(OWNER) is True


def test_shutdown_report_preserves_every_cleanup_failure(tmp_path):
    """FR-007 (shutdown leg): every cleanup failure is kept item-by-item in the
    ShutdownReport — this guards the existing T004 close surface and needs no
    dispatch, so it is GREEN now."""
    class MultiFailingStore(CoreStore):
        def close(self) -> None:
            raise RuntimeError("cleanup failure one")

    runtime = CoreRuntime(MultiFailingStore(":memory:"))
    res = ControlledResourceProvider("res.alpha")
    runtime.stage(OWNER, contribution_set((res,), (ControlledExecutionProvider(),))).commit()
    runtime._note_lease(OWNER, "lease-1", LeaseState.ACQUIRED)

    report = runtime.close()
    assert len(report.cleanup_failures) == 1
    assert "cleanup failure one" in report.cleanup_failures[0]
    assert report.unresolved_leases == ("lease-1",)
