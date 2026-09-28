"""US1 recovery negatives — unresolved facts at close, restart without spawn and
evidence-only reconciliation (specs/010-platform-core T010; FR-004, FR-014,
data-model.md "Recovery / Historical Storage" plus the Operation/Lease
transition rules).

The Recovery rule under test, verbatim from data-model.md:

    凭安全句柄核实未确认运行，不默认 spawn，无 reconciliation 则明确人工处置。

and from Transitions: ``unknown 仅凭证据转 succeeded/refused，不超时猜测、不自动重做``.

Everything is driven through the real T008 dispatcher over a *file-backed* store,
then re-opened by a second ``CoreRuntime`` on the same file — restart fidelity is
what separates this file from the US1 idempotency suite.

Test map
  close-time persistence (FR-003/FR-007, contract "Store 关闭前落未解决事实")
  - ``test_unresolved_leases_are_persisted_and_match_the_shutdown_report``
  - ``test_close_persists_no_new_fact_and_keeps_row_digests``
  restart reconciliation, never spawn (FR-004, Recovery)
  - ``test_restarted_runtime_ledger_matches_the_persisted_facts``
  - ``test_restart_never_contacts_providers``
  - ``test_restart_keeps_unknown_start_operation_unknown``
  - ``test_restart_replay_never_redispatches_an_unknown_start``
  - ``test_no_evidence_free_path_cleanups_an_unresolved_lease``
  evidence-only advance (Transitions: unknown 仅凭证据)
  - ``test_reconcile_success_advances_only_the_reconciled_lease``
  - ``test_reconcile_request_identity_comes_from_persisted_facts``
  - ``test_refused_or_unknown_reconcile_evidence_advances_nothing``
  - ``test_reconcile_unsupported_provider_is_typed_refusal_with_zero_calls``
  - ``test_reconcile_never_spawns_releases_or_stops``
  - ``test_reconcile_requires_the_lease_provider_to_be_registered``
  typed refusal where no evidence can exist (明确人工处置)
  - ``test_reconcile_of_a_held_acquired_lease_is_refused``
  - ``test_reconcile_of_a_handleless_unknown_lease_requires_explicit_disposition``
  - ``test_reconcile_of_a_start_operation_is_refused``
  反例守卫 (场景 6: 防假绿自测)
  - ``test_spawn_tripwire_actually_trips``
"""
from __future__ import annotations

import hashlib

import pytest

from pacthold.public import (
    AcquireRequest,
    CoreRuntime,
    CoreStore,
    DispatchError,
    ExecutionPlan,
    ExecutionState,
    LeaseState,
    OperationState,
    OwnershipKind,
    OwnerBusyError,
    ProviderNotRegisteredError,
    ReconcileOutcome,
    ReconcileRequest,
    ReconcileResult,
    ReconcileSupport,
    ReconcileUnsupportedError,
    ReleaseOutcome,
    ReleaseRequest,
    ReleaseResult,
    ResourceRequirement,
    RunHandle,
    StartRequest,
    StopRequest,
    UnknownExecutionError,
    UnknownOperationError,
)
from us1_doubles import (
    ControlledExecutionProvider,
    ControlledResourceProvider,
    contribution_set,
    one_own_plan,
)

OWNER = "owner-us1-recovery"


# ---------------------------------------------------------------------------
# doubles local to this file (us1_doubles.py stays untouched)
# ---------------------------------------------------------------------------


class ScriptedResourceProvider(ControlledResourceProvider):
    """``ControlledResourceProvider`` + an ``unknown`` release mode and a
    scriptable ``reconcile`` verdict, so each test names exactly the evidence
    situation it exercises."""

    def __init__(
        self,
        provider_id: str,
        *,
        release_mode: str = "success",
        reconcile_mode: str = "success",
        reconcile_support: ReconcileSupport = ReconcileSupport.SUPPORTED,
        **kw,
    ) -> None:
        super().__init__(
            provider_id,
            release_mode="success" if release_mode == "unknown" else release_mode,
            **kw,
        )
        self.scripted_release_mode = release_mode
        self.reconcile_mode = reconcile_mode
        self._reconcile_support = reconcile_support

    def release(self, request: ReleaseRequest) -> ReleaseResult:
        if self.scripted_release_mode != "unknown":
            return super().release(request)
        with self._lock:
            self.release_calls.append(request)
        # an unknown release stays queryable and is never auto-retried
        return ReleaseResult(
            outcome=ReleaseOutcome.UNKNOWN,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
        )

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        with self._lock:
            self.reconcile_calls.append(request)
        if self.reconcile_mode == "refused":
            return ReconcileResult(
                outcome=ReconcileOutcome.REFUSED,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
                error_code="cannot_verify",
            )
        if self.reconcile_mode == "unknown":
            return ReconcileResult(
                outcome=ReconcileOutcome.UNKNOWN,
                operation_key=request.operation_key,
                execution_id=request.execution_id,
            )
        return ReconcileResult(
            outcome=ReconcileOutcome.SUCCESS,
            operation_key=request.operation_key,
            execution_id=request.execution_id,
            resolution_ref=f"evidence-{len(self.reconcile_calls)}",
        )


class SpawnTripwireResourceProvider(ControlledResourceProvider):
    """Registration-shaped provider that fails the test on any side effect.

    Restart must be pure bookkeeping: if the core acquires, releases or
    reconciles on its own while reconstructing or querying, this raises and the
    test goes red — the "调用计数非零即红" requirement expressed as a tripwire
    rather than a count a future edit could forget to read.
    """

    def acquire(self, request: AcquireRequest):
        raise AssertionError("restart must not acquire: the core re-acquired a resource")

    def release(self, request: ReleaseRequest):
        raise AssertionError("restart must not release: unsafe cleanup of a held lease")

    def reconcile(self, request: ReconcileRequest):
        raise AssertionError("restart must not reconcile on its own: evidence is explicit")


class SpawnTripwireExecutionProvider(ControlledExecutionProvider):
    def start(self, request: StartRequest):
        raise AssertionError("restart must not start: the core auto-spawned a run")

    def observe(self, handle: RunHandle):
        raise AssertionError("the core must not observe during restart bookkeeping")

    def stop(self, request: StopRequest):
        raise AssertionError("the core must not stop during restart bookkeeping")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "core.db"


def _columns(store: CoreStore, table: str) -> list[str]:
    return [row[1] for row in store.query_all(f"PRAGMA table_info({table})")]


def _digest_row(store: CoreStore, table: str, key_column: str, key: str) -> str:
    """sha256 over EVERY column of one row (``updated_at`` included, so any
    write to that row changes the digest)."""
    columns = _columns(store, table)
    rows = store.query_all(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {key_column} = ?", (key,)
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _digest_all_rows(store: CoreStore, table: str) -> str:
    columns = _columns(store, table)
    rows = store.query_all(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {columns[0]}"
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _lease_facts(store: CoreStore) -> dict[str, str]:
    """identifier -> lease_state for every persisted lease fact that is still
    unresolved.  A lease with no provider-reported id is named by its operation
    key, the durable queryable identity of the unknown (data-model: unknown
    stays queryable via (execution_id, operation_key))."""
    rows = store.query_all(
        "SELECT lease_id, operation_key, lease_state FROM core_operation "
        "WHERE kind = 'acquire' AND lease_state IS NOT NULL"
    )
    facts: dict[str, str] = {}
    for lease_id, operation_key, lease_state in rows:
        if not LeaseState(lease_state).is_unresolved():
            continue
        facts[lease_id or operation_key] = lease_state
    return facts


def single_slot_plan(request_key: str, slot: str, contract_id: str, provider_id: str,
                     digest: str) -> ExecutionPlan:
    return ExecutionPlan(
        request_key=request_key,
        digest=digest,
        provider_id="exec.us1",
        provider_version="1.0",
        work_id="work-recovery",
        resources=(
            ResourceRequirement(
                slot=slot,
                contract_id=contract_id,
                provider_id=provider_id,
                ownership=OwnershipKind.OWN,
            ),
        ),
    )


def drive_release_unknown(runtime: CoreRuntime) -> tuple:
    """Real dispatch into the exact recovery situation T010 targets: the run was
    stopped, but the release receipt was lost, leaving a lease in
    ``release_unknown`` with a persisted safe handle."""
    res = ScriptedResourceProvider("res.alpha", release_mode="unknown")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-release-unknown"))
    stop = runtime.request_stop(result.execution_id, result.operation_key)
    assert stop.cleanup_failures, stop
    view = runtime.query(result.execution_id)
    assert [lease.lease_state for lease in view.leases] == [LeaseState.RELEASE_UNKNOWN]
    return result, view, res, exe


def drive_held_lease(runtime: CoreRuntime, request_key: str = "req-held") -> tuple:
    """A run that started and still holds its acquired lease."""
    res = ScriptedResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key=request_key))
    view = runtime.query(result.execution_id)
    assert view.leases[0].lease_state is LeaseState.ACQUIRED
    return result, view, res, exe


# ===========================================================================
# close: unresolved leases are durable and the report matches the store
# ===========================================================================


def test_unresolved_leases_are_persisted_and_match_the_shutdown_report(db_path):
    """Contract "Store 关闭前落未解决事实" + FR-003: an ``acquired`` lease and an
    ``acquire_unknown`` lease are each individually queryable in the store after
    close, and the ShutdownReport names exactly those facts — no more, no fewer."""
    store = CoreStore(db_path)
    runtime = CoreRuntime(store)
    held = ScriptedResourceProvider("res.alpha", acquire_mode="success")
    stuck = ScriptedResourceProvider("res.beta", acquire_mode="unknown")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((held, stuck), (exe,))).commit()

    live = runtime.submit(one_own_plan(request_key="req-held-lease"))
    stuck_plan = single_slot_plan("req-stuck-lease", "ctx", "sample.beta@1", "res.beta", "c" * 64)
    stuck_result = runtime.submit(stuck_plan)
    assert stuck_result.execution_state is ExecutionState.FAILED
    assert stuck_result.failed_slot == "ctx"
    stuck_key = runtime.query(stuck_result.execution_id).leases[0].operation_key
    assert runtime.query(stuck_result.execution_id).leases[0].lease_id is None

    report = runtime.close()

    # straight through a fresh store on the same file: the facts are row-level,
    # and close() had to have written them before it released the connection.
    reopened = CoreStore(db_path)
    try:
        facts = _lease_facts(reopened)
        assert set(report.unresolved_leases) == set(facts)
        assert len(report.unresolved_leases) == 2
        assert facts[stuck_key] == LeaseState.ACQUIRE_UNKNOWN.value
        assert held.release_calls == []  # unknown pins it: no unsafe release
        assert stuck.release_calls == []
        assert live.execution_id in report.unresolved_executions

        assert reopened.query_all(
            "SELECT operation_key, lease_state, lease_id, safe_handle "
            "FROM core_operation WHERE execution_id = ?",
            (stuck_result.execution_id,),
        ) == [(stuck_key, LeaseState.ACQUIRE_UNKNOWN.value, None, None)]
    finally:
        reopened.close()


def test_close_persists_no_new_fact_and_keeps_row_digests(db_path):
    """FR-014 shutdown leg: close lists unresolved work and writes nothing — every
    execution and operation row digest survives close and a reopen."""
    store = CoreStore(db_path)
    runtime = CoreRuntime(store)
    result, _view, res, exe = drive_held_lease(runtime, request_key="req-close-digest")
    runtime.request_stop(result.execution_id, result.operation_key)

    exec_digest = _digest_row(store, "core_execution", "id", result.execution_id)
    ops_digest = _digest_row(store, "core_operation", "execution_id", result.execution_id)
    all_execs = _digest_all_rows(store, "core_execution")
    all_ops = _digest_all_rows(store, "core_operation")

    report = runtime.close()

    reopened = CoreStore(db_path)
    try:
        assert _digest_row(reopened, "core_execution", "id", result.execution_id) == exec_digest
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
        assert _digest_all_rows(reopened, "core_execution") == all_execs
        assert _digest_all_rows(reopened, "core_operation") == all_ops
        assert report.cleanup_failures == ()
        assert len(exe.stop_calls) == 1 and len(res.release_calls) == 1  # user-initiated
    finally:
        reopened.close()


# ===========================================================================
# restart: reconcile only, never spawn
# ===========================================================================


def test_restarted_runtime_ledger_matches_the_persisted_facts(db_path):
    """A second CoreRuntime over the same file sees the SAME unresolved facts as
    the store: its shutdown report, busy answer and unregister refusal are all
    derived from durable records, not from a process that kept its memory."""
    first = CoreRuntime(CoreStore(db_path))
    result, _view, _res, _exe = drive_held_lease(first, request_key="req-restart-ledger")
    first.close()

    reopened = CoreStore(db_path)
    expected = _lease_facts(reopened)
    assert expected, "the unresolved lease fact must be durable"

    second = CoreRuntime(reopened)
    second.stage(
        OWNER, contribution_set((ScriptedResourceProvider("res.alpha"),),
                                (ControlledExecutionProvider(),))
    ).commit()
    try:
        assert second.owner_busy(OWNER) is True
        with pytest.raises(OwnerBusyError):
            second.unregister(OWNER)
        assert second.query(result.execution_id).execution_state is ExecutionState.ACTIVE
        report = second.close()
        assert set(report.unresolved_leases) == set(expected)
        assert result.execution_id in report.unresolved_executions
    finally:
        if not reopened.is_closed:
            second.close()


def test_restart_never_contacts_providers(db_path):
    """data-model Recovery "不默认 spawn": constructing the restarted runtime and
    running its first query/close leaves every provider method untouched — the
    registered doubles raise on any side effect."""
    first = CoreRuntime(CoreStore(db_path))
    result, _view, _res, _exe = drive_held_lease(first, request_key="req-restart-zero")
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)  # construction: must not spawn
    trip_res = SpawnTripwireResourceProvider("res.alpha")
    trip_exe = SpawnTripwireExecutionProvider()
    second.stage(OWNER, contribution_set((trip_res,), (trip_exe,))).commit()

    view = second.query(result.execution_id)  # first query: must not spawn
    assert view.execution_state is ExecutionState.ACTIVE
    assert view.leases[0].lease_state is LeaseState.ACQUIRED
    assert second.owner_busy(OWNER) is True
    report = second.close()
    assert view.execution_id in report.unresolved_executions
    assert trip_res.release_calls == []


def test_restart_keeps_unknown_start_operation_unknown(db_path):
    """FR-004 across a restart: a lost start receipt stays ``unknown`` and the
    execution stays ``start_unknown`` — restart neither guesses a verdict nor
    times one out."""
    store = CoreStore(db_path)
    first = CoreRuntime(store)
    res = ScriptedResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    first.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = first.submit(one_own_plan(request_key="req-lost-receipt"))
    assert result.execution_state is ExecutionState.START_UNKNOWN
    first.close()

    reopened = CoreStore(db_path)
    ops_digest = _digest_row(reopened, "core_operation", "execution_id", result.execution_id)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    exe2 = ControlledExecutionProvider()
    second.stage(OWNER, contribution_set((res2,), (exe2,))).commit()
    try:
        view = second.query(result.execution_id)
        assert view.execution_state is ExecutionState.START_UNKNOWN
        assert view.operation_state is OperationState.UNKNOWN
        assert not view.execution_state.is_terminal()
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
        assert res2.acquire_calls == [] and exe2.start_calls == []
    finally:
        second.close()


def test_restart_replay_never_redispatches_an_unknown_start(db_path):
    """FR-004 "不自动重做": replaying the same key on the restarted runtime returns
    the same unknown execution with zero provider calls — an auto-retry here
    would push the start counter non-zero and go red."""
    first = CoreRuntime(CoreStore(db_path))
    res = ScriptedResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    first.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = first.submit(one_own_plan(request_key="req-restart-replay"))
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    exe2 = ControlledExecutionProvider()
    second.stage(OWNER, contribution_set((res2,), (exe2,))).commit()
    try:
        replay = second.submit(one_own_plan(request_key="req-restart-replay"))
        assert replay.execution_id == result.execution_id
        assert replay.execution_state is ExecutionState.START_UNKNOWN
        assert exe2.start_calls == []
        assert res2.acquire_calls == []
        assert res2.release_calls == []
        assert second.query(result.execution_id).operation_state is OperationState.UNKNOWN
    finally:
        second.close()


def test_no_evidence_free_path_cleanups_an_unresolved_lease(db_path):
    """场景 5 negative half: with no reconciliation evidence, every evidence-free
    path keeps the unresolved lease pinned and queryable — close reports it,
    unregister refuses, and no provider verb runs on the way."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_id = view.leases[0].lease_id
    lease_key = view.leases[0].operation_key
    first.close()

    reopened = CoreStore(db_path)
    ops_digest = _digest_row(reopened, "core_operation", "execution_id", result.execution_id)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    exe2 = ControlledExecutionProvider()
    second.stage(OWNER, contribution_set((res2,), (exe2,))).commit()

    assert second.owner_busy(OWNER) is True
    with pytest.raises(OwnerBusyError):
        second.unregister(OWNER)
    report = second.close()
    assert lease_id in report.unresolved_leases
    assert result.execution_id in report.unresolved_executions

    fresh = CoreStore(db_path)
    try:
        assert _digest_row(fresh, "core_operation", "execution_id", result.execution_id) == ops_digest
        assert _lease_facts(fresh)[lease_id] == LeaseState.RELEASE_UNKNOWN.value
        assert res2.reconcile_calls == [] and res2.release_calls == []
        assert exe2.stop_calls == []
        # still reachable through its durable identity, exactly as data-model
        # requires of an unresolved fact
        assert fresh.query_all(
            "SELECT lease_state FROM core_operation WHERE operation_key = ?",
            (lease_key,),
        ) == [(LeaseState.RELEASE_UNKNOWN.value,)]
    finally:
        fresh.close()


# ===========================================================================
# evidence-only advance: reconcile is the seam, and it never spawns
# ===========================================================================


def test_reconcile_success_advances_only_the_reconciled_lease(db_path):
    """Transitions "unknown 仅凭证据": a SUCCESS verdict releases that one lease and
    records the resolution ref; the execution fact (``stop_requested``) and every
    other row are untouched — evidence is not a licence to synthesize a terminal
    state, and with it the owner finally unregisters."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_id = view.leases[0].lease_id
    lease_key = view.leases[0].operation_key
    exec_digest = _digest_row(first.store, "core_execution", "id", result.execution_id)
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        # pinned before the evidence: the unresolved lease keeps the owner busy
        with pytest.raises(OwnerBusyError):
            second.unregister(OWNER)

        verdict = second.reconcile(result.execution_id, lease_key)
        assert verdict.outcome is ReconcileOutcome.SUCCESS
        assert len(res2.reconcile_calls) == 1

        after = second.query(result.execution_id)
        assert after.leases[0].lease_id == lease_id  # this lease, not a new one
        assert after.leases[0].lease_state is LeaseState.RELEASED
        assert after.leases[0].reconcile_ref == verdict.resolution_ref
        assert after.execution_state is ExecutionState.STOP_REQUESTED
        assert _digest_row(reopened, "core_execution", "id", result.execution_id) == exec_digest
        # evidence is what freed the pin: the execution row itself never moved
        second.unregister(OWNER)
        assert second.registry_snapshot().resource_provider_ids == ()
        assert _lease_facts(reopened) == {}
        assert second.owner_busy(OWNER) is False
    finally:
        if not reopened.is_closed:
            second.close()


def test_reconcile_request_identity_comes_from_persisted_facts(db_path):
    """Recovery "凭安全句柄核实": the reconcile request is rebuilt from the durable
    lease_id/safe_handle of the previous process — the core invents nothing and
    asks nothing it cannot name."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    expected = (view.leases[0].lease_id, view.leases[0].safe_handle, view.leases[0].operation_key)
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        second.reconcile(result.execution_id, expected[2])
        request = res2.reconcile_calls[0]
        assert (request.execution_id, request.operation_key) == (result.execution_id, expected[2])
        assert request.lease_id == expected[0]
        assert request.safe_handle == expected[1]
        assert request.safe_handle == reopened.query_all(
            "SELECT safe_handle FROM core_operation WHERE operation_key = ?", (expected[2],)
        )[0][0]
    finally:
        second.close()


@pytest.mark.parametrize("mode", ["refused", "unknown"])
def test_refused_or_unknown_reconcile_evidence_advances_nothing(db_path, mode):
    """A provider that declines to adjudicate (refused) or still cannot tell
    (unknown) changes no state, releases nothing and keeps the lease pinned:
    only a SUCCESS verdict is evidence."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_key = view.leases[0].operation_key
    lease_id = view.leases[0].lease_id
    first.close()

    reopened = CoreStore(db_path)
    ops_digest = _digest_row(reopened, "core_operation", "execution_id", result.execution_id)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha", reconcile_mode=mode)
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        verdict = second.reconcile(result.execution_id, lease_key)
        assert verdict.outcome is (
            ReconcileOutcome.REFUSED if mode == "refused" else ReconcileOutcome.UNKNOWN
        )
        assert second.query(result.execution_id).leases[0].lease_state is LeaseState.RELEASE_UNKNOWN
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
        assert res2.release_calls == [] and res2.acquire_calls == []
        with pytest.raises(OwnerBusyError):
            second.unregister(OWNER)
        assert _lease_facts(reopened)[lease_id] == LeaseState.RELEASE_UNKNOWN.value
    finally:
        second.close()


def test_reconcile_unsupported_provider_is_typed_refusal_with_zero_calls(db_path):
    """C1 "descriptor 明示 reconcile 能力，不支持 typed unsupported": asking the core to
    reconcile against a provider whose descriptor says UNSUPPORTED is a typed
    refusal with zero provider calls and zero state movement."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_key = view.leases[0].operation_key
    first.close()

    reopened = CoreStore(db_path)
    ops_digest = _digest_row(reopened, "core_operation", "execution_id", result.execution_id)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha", reconcile_support=ReconcileSupport.UNSUPPORTED)
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        with pytest.raises(ReconcileUnsupportedError):
            second.reconcile(result.execution_id, lease_key)
        assert res2.reconcile_calls == [] and res2.acquire_calls == []
        assert second.query(result.execution_id).leases[0].lease_state is LeaseState.RELEASE_UNKNOWN
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
        with pytest.raises(OwnerBusyError):
            second.unregister(OWNER)
    finally:
        second.close()


def test_reconcile_never_spawns_releases_or_stops(db_path):
    """FR-004 / "prepare/validate 禁 spawn" on the recovery seam: reconciliation is
    verification — the supporting provider is asked exactly once and no acquire,
    start, observe or stop leaves the process, even though a lease is unresolved."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_key = view.leases[0].operation_key
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    exe2 = ControlledExecutionProvider()
    second.stage(OWNER, contribution_set((res2,), (exe2,))).commit()
    try:
        second.reconcile(result.execution_id, lease_key)
        assert len(res2.reconcile_calls) == 1
        assert res2.acquire_calls == [] and res2.release_calls == []
        assert exe2.start_calls == [] and exe2.stop_calls == [] and exe2.observe_calls == []
    finally:
        second.close()


def test_reconcile_requires_the_lease_provider_to_be_registered(db_path):
    """A restarted runtime that has not re-registered the lease's provider refuses
    with a typed error instead of treating the lease as gone; unknown ids refuse
    on their own axis."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_release_unknown(first)
    lease_key = view.leases[0].operation_key
    first.close()

    second = CoreRuntime(CoreStore(db_path))
    try:
        with pytest.raises(ProviderNotRegisteredError):
            second.reconcile(result.execution_id, lease_key)
        with pytest.raises(UnknownExecutionError):
            second.reconcile("exec-does-not-exist", lease_key)
        with pytest.raises(UnknownOperationError):
            second.reconcile(result.execution_id, "op-does-not-exist")
        assert _lease_facts(second.store)[view.leases[0].lease_id] == LeaseState.RELEASE_UNKNOWN.value
    finally:
        second.close()


def test_reconcile_of_a_held_acquired_lease_is_refused(db_path):
    """FR-004 "unknown MUST 禁止不安全释放": a lease that is simply *held*
    (``acquired``, its run possibly live) is not an unknown and must not be
    reconciled away — evidence resolves bounded knowledge, it does not free a
    resource somebody may still be using."""
    first = CoreRuntime(CoreStore(db_path))
    result, view, _res, _exe = drive_held_lease(first, request_key="req-held-refuse")
    lease_key = view.leases[0].operation_key
    ops_digest = _digest_row(first.store, "core_operation", "execution_id", result.execution_id)
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        with pytest.raises(DispatchError):
            second.reconcile(result.execution_id, lease_key)
        assert res2.reconcile_calls == []
        assert second.query(result.execution_id).leases[0].lease_state is LeaseState.ACQUIRED
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
    finally:
        second.close()


def test_reconcile_of_a_handleless_unknown_lease_requires_explicit_disposition(db_path):
    """Recovery "无 reconciliation 则明确人工处置": an acquire that ended unknown has no
    lease id and no safe handle, so there is nothing to verify against — the core
    says so with a typed refusal and keeps the fact pinned instead of fabricating
    an identity for the provider call."""
    first = CoreRuntime(CoreStore(db_path))
    stuck = ScriptedResourceProvider("res.beta", acquire_mode="unknown")
    exe = ControlledExecutionProvider()
    first.stage(OWNER, contribution_set((stuck,), (exe,))).commit()
    plan = single_slot_plan("req-handleless", "ctx", "sample.beta@1", "res.beta", "d" * 64)
    result = first.submit(plan)
    lease_key = first.query(result.execution_id).leases[0].operation_key
    ops_digest = _digest_row(first.store, "core_operation", "execution_id", result.execution_id)
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    stuck2 = ScriptedResourceProvider("res.beta")
    second.stage(OWNER, contribution_set((stuck2,), (ControlledExecutionProvider(),))).commit()
    try:
        with pytest.raises(DispatchError):
            second.reconcile(result.execution_id, lease_key)
        assert stuck2.reconcile_calls == []
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
        assert _lease_facts(reopened)[lease_key] == LeaseState.ACQUIRE_UNKNOWN.value
        with pytest.raises(OwnerBusyError):
            second.unregister(OWNER)
        report = second.close()
        assert lease_key in report.unresolved_leases
    finally:
        if not second.store.is_closed:
            second.close()


def test_reconcile_of_a_start_operation_is_refused(db_path):
    """The execution side has no reconcile verb in C1 (start/observe/stop only), so
    a start operation must not be silently folded into the lease reconciliation
    path — the core refuses with a typed error and leaves ``unknown`` intact."""
    first = CoreRuntime(CoreStore(db_path))
    res = ScriptedResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    first.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = first.submit(one_own_plan(request_key="req-start-op-reconcile"))
    ops_digest = _digest_row(first.store, "core_operation", "execution_id", result.execution_id)
    first.close()

    reopened = CoreStore(db_path)
    second = CoreRuntime(reopened)
    res2 = ScriptedResourceProvider("res.alpha")
    second.stage(OWNER, contribution_set((res2,), (ControlledExecutionProvider(),))).commit()
    try:
        with pytest.raises(DispatchError):
            second.reconcile(result.execution_id, result.operation_key)
        assert res2.reconcile_calls == []
        assert second.query(result.execution_id).operation_state is OperationState.UNKNOWN
        assert _digest_row(reopened, "core_operation", "execution_id", result.execution_id) == ops_digest
    finally:
        second.close()


# ===========================================================================
# 场景 6 — anti-fake-green guard for the "no auto spawn" claims
# ===========================================================================


def test_spawn_tripwire_actually_trips():
    """The zero-provider-call claims above rest on the tripwire doubles raising on
    any side effect.  This test proves the tripwires are live: calling them
    directly must fail.  If a refactor neutered them, the restart tests would
    fake green and this one goes red first."""
    res = SpawnTripwireResourceProvider("res.alpha")
    exe = SpawnTripwireExecutionProvider()
    acquire = AcquireRequest("op-1", "exec-1", "sample.alpha@1", "res.alpha", OwnershipKind.OWN)
    release = ReleaseRequest("op-1", "exec-1", "lease-1", OwnershipKind.OWN)
    start = StartRequest("op-1", "exec-1", "exec.us1", "a" * 64)
    stop = StopRequest("op-1", "exec-1")

    with pytest.raises(AssertionError, match="must not acquire"):
        res.acquire(acquire)
    with pytest.raises(AssertionError, match="must not release"):
        res.release(release)
    with pytest.raises(AssertionError, match="must not reconcile"):
        res.reconcile(ReconcileRequest("op-1", "exec-1", "lease-1", "handle-1"))
    with pytest.raises(AssertionError, match="must not start"):
        exe.start(start)
    with pytest.raises(AssertionError, match="must not stop"):
        exe.stop(stop)
    with pytest.raises(AssertionError, match="observe"):
        exe.observe(RunHandle("exec-1", "exec.us1", "handle-1"))
