"""US1 / FR-001 — two CoreRuntime instances never interfere (T007, red-first).

Each runtime owns exactly one ``CoreStore`` and one instance-scoped registry;
there is no process-global connection (data-model.md CoreRuntime row:
"无全局当前数据库").  The green tests below lock the isolation *mechanism* that
already ships at T004; the test that drives a full submit/registration record
through one instance and then closes it is intentionally RED because
``CoreRuntime.submit`` still refuses with ``ContractWiringPending`` until the
T008 dispatch state machine lands.

Every store is created under ``tmp_path`` — no network, no model, no shared db.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pacthold.public import (
    CoreRuntime,
    CoreStore,
    ExecutionState,
    RuntimeClosedError,
)
from us1_doubles import (
    ControlledExecutionProvider,
    ControlledResourceProvider,
    contribution_set,
    one_own_plan,
)

OWNER = "owner-us1"


# --------------------------------------------------------------------------
# green mechanism guards (no dispatch required)
# --------------------------------------------------------------------------


def test_core_runtime_has_no_global_default_store():
    """FR-001 negative: a runtime cannot be built against a shared global —
    construction requires an explicit instance store."""
    with pytest.raises(TypeError):
        CoreRuntime()  # type: ignore[call-arg]


def test_two_stores_are_physically_separate_files(tmp_path: Path):
    """Positive isolation + leak negative: data written through one store is
    never visible through the other (a shared global connection would leak)."""
    store_a = CoreStore(tmp_path / "a.db")
    store_b = CoreStore(tmp_path / "b.db")
    try:
        with store_a.transaction():
            store_a.execute("CREATE TABLE facts (v TEXT NOT NULL)")
            store_a.execute("INSERT INTO facts VALUES (?)", ("A-MARKER",))
        assert store_a.query_all("SELECT v FROM facts") == [("A-MARKER",)]
        # B is a different file: it sees neither A's table nor A's marker.
        assert store_b.query_all("SELECT name FROM sqlite_master WHERE type='table'") == []
        assert store_b.path != store_a.path
    finally:
        store_a.close()
        store_b.close()


def test_registries_are_instance_scoped(tmp_path: Path):
    """Committing providers on runtime A leaves runtime B's registry empty."""
    runtime_a = CoreRuntime(CoreStore(tmp_path / "a.db"))
    runtime_b = CoreRuntime(CoreStore(tmp_path / "b.db"))
    try:
        res, exe = ControlledResourceProvider("res.alpha"), ControlledExecutionProvider()
        runtime_a.stage(OWNER, contribution_set((res,), (exe,))).commit()
        snap_a = runtime_a.registry_snapshot()
        snap_b = runtime_b.registry_snapshot()
        assert "sample.alpha@1" in snap_a.contract_ids
        assert snap_a.resource_provider_ids == ("res.alpha",)
        # zero cross-instance leak
        assert snap_b.contract_ids == ()
        assert snap_b.resource_provider_ids == ()
        assert snap_b.execution_provider_ids == ()
    finally:
        runtime_a.close()
        runtime_b.close()


def test_closing_one_instance_does_not_touch_the_other(tmp_path: Path):
    """close(A) must not disturb B's registry/leases (FR-014: instance shutdown
    is not implicitly propagated).  Uses only the already-shipped registration
    and shutdown surface, so this guard is GREEN now."""
    runtime_a = CoreRuntime(CoreStore(tmp_path / "a.db"))
    runtime_b = CoreRuntime(CoreStore(tmp_path / "b.db"))
    try:
        res, exe = ControlledResourceProvider("res.alpha"), ControlledExecutionProvider()
        runtime_a.stage(OWNER, contribution_set((res,), (exe,))).commit()
        runtime_b.stage(OWNER, contribution_set((res,), (exe,))).commit()

        report = runtime_a.close()
        assert report.cleanup_failures == ()
        # B is untouched by A's shutdown (the batch bundled both contracts)
        snap_b = runtime_b.registry_snapshot()
        assert snap_b.contract_ids == ("sample.alpha@1", "sample.beta@1")
        assert snap_b.resource_provider_ids == ("res.alpha",)
        assert runtime_b.owner_busy(OWNER) is True
    finally:
        runtime_b.close()


# --------------------------------------------------------------------------
# RED: a closed instance must refuse dispatch with RuntimeClosedError
# --------------------------------------------------------------------------


def test_closed_instance_refuses_dispatch_surface(tmp_path: Path):
    """FR-001: after close(A) the dispatch entry points must refuse with
    ``RuntimeClosedError`` (the wired machine's ``_ensure_open`` gate).  Red now
    because submit/query/request_stop still raise ``ContractWiringPending``
    before honouring the closed state — T008 delivery."""
    runtime = CoreRuntime(CoreStore(tmp_path / "a.db"))
    res, exe = ControlledResourceProvider("res.alpha"), ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    runtime.close()

    with pytest.raises(RuntimeClosedError):
        runtime.submit(one_own_plan())          # RED: raises ContractWiringPending
    with pytest.raises(RuntimeClosedError):
        runtime.query("exec-0001")              # RED
    with pytest.raises(RuntimeClosedError):
        runtime.request_stop("exec-0001", "op-1")  # RED


# --------------------------------------------------------------------------
# RED: full lifecycle through one instance, then close, other keeps working
# --------------------------------------------------------------------------


def test_instance_a_full_record_then_close_leaves_b_operational(tmp_path: Path):
    """FR-001 independent test: A registers + submits + records a run, then
    close(A); B must read/write normally and A's store file must carry no trace
    of B.  Red until T008 wires submit (raises ContractWiringPending)."""
    store_a = CoreStore(tmp_path / "a.db")
    store_b = CoreStore(tmp_path / "b.db")
    runtime_a = CoreRuntime(store_a)
    runtime_b = CoreRuntime(store_b)
    res_a, exe_a = ControlledResourceProvider("res.alpha"), ControlledExecutionProvider()
    res_b, exe_b = ControlledResourceProvider("res.alpha"), ControlledExecutionProvider()
    runtime_a.stage(OWNER, contribution_set((res_a,), (exe_a,))).commit()
    runtime_b.stage(OWNER, contribution_set((res_b,), (exe_b,))).commit()
    try:
        result_a = runtime_a.submit(one_own_plan())          # RED here
        execution_id_a = result_a.execution_id
        assert len(exe_a.start_calls) == 1

        report = runtime_a.close()
        # close lists unresolved facts, never synthesises a terminal state
        assert execution_id_a in report.unresolved_executions
        assert store_a.is_closed

        # B is fully operational after A closed
        result_b = runtime_b.submit(one_own_plan(request_key="req-b"))
        assert result_b.execution_id != execution_id_a
        assert result_b.execution_state is ExecutionState.ACTIVE
        assert len(exe_b.start_calls) == 1

        # A's store file carries no trace of B (separate db files)
        assert store_a.path != store_b.path
    finally:
        if not store_a.is_closed:
            store_a.close()
        runtime_b.close()
