"""US1 lifecycle negatives — terminal immutability, Session resume and the
transport/execution wall (specs/010-platform-core T010; FR-004, FR-014,
spec.md US1.3, data-model.md "Transitions" and Execution "终态不可逆").

Every scenario here drives the *real* T008 dispatch machine
(``CoreRuntime.submit`` / ``query`` / ``request_stop`` / ``close``) over a
per-test ``tmp_path`` ``CoreStore``; nothing uses the ``_note_*`` ledger
placeholders that the T004 contract tests used, so the facts under test are
the ones the dispatcher itself persisted.

Coverage map (positive + negative per requirement):

* FR-004 "Execution 终态不可改写"
  - ``test_terminal_execution_survives_every_write_path_unchanged`` — the stop /
    replay / finalization-write paths all refuse and the storage-layer record is
    byte-identical before and after (row digest over every column).
  - ``test_forged_terminal_row_is_never_rewritten_by_core_paths`` — a terminal
    record produced outside the dispatcher (direct SQL) is still immutable.
  - ``test_digest_probe_detects_control_write_on_non_terminal_execution`` —
    anti-fake-green guard: the same digest probe DOES notice a legitimate write
    to a non-terminal row, so the immutability tests above cannot pass because
    the probe is blind (若允许覆写则红).
* US1.3 / C1 "Session resume 新 Execution，不复用终态 ID"
  - ``test_resume_creates_new_execution_and_leaves_terminal_record_untouched``
  - ``test_resume_association_defaults_to_absent`` (the link is optional)
  - ``test_resume_under_terminal_request_key_is_refused`` — the terminal
    execution's own key can never be reused to rewrite it.
* FR-014 "通道关闭 / 执行停止 / UI 卸载 MUST 不隐式互推"
  - ``test_transport_dead_observation_does_not_change_execution_state``
  - ``test_stop_failure_over_dead_transport_never_fabricates_cancelled``
  - ``test_stop_refused_by_transport_never_fabricates_cancelled``
  - ``test_execution_terminalization_does_not_close_or_fabricate_transport_channel``
  - ``test_close_does_not_stop_active_execution_or_release_leases``
  - ``test_unregister_with_active_execution_refused_and_stops_nothing``
  - ``test_stop_requested_execution_is_not_terminal_and_stays_queryable``
  - ``test_start_unknown_delegates_no_stop_and_releases_no_lease``
"""
from __future__ import annotations

import hashlib

import pytest

from pacthold.public import (
    CoreRuntime,
    CoreStore,
    ExecutionPlan,
    ExecutionState,
    LeaseState,
    Observation,
    ObservationKind,
    OperationState,
    OwnerBusyError,
    OwnershipKind,
    PlanDigestConflictError,
    ResourceRequirement,
    RunHandle,
    TerminalExecutionError,
)
from us1_doubles import (
    DIGEST_A,
    DIGEST_B,
    ControlledExecutionProvider,
    ControlledResourceProvider,
    contribution_set,
    one_own_plan,
    two_slot_plan,
)

OWNER = "owner-us1-lifecycle"
TRANSPORT_DEAD = "transport-dead"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def runtime(tmp_path):
    store = CoreStore(tmp_path / "core.db")
    created = CoreRuntime(store)
    yield created
    if not store.is_closed:
        created.close()


def _table_columns(store: CoreStore, table: str) -> list[str]:
    return [row[1] for row in store.query_all(f"PRAGMA table_info({table})")]


def _digest_row(store: CoreStore, table: str, key_column: str, key: str) -> str:
    """sha256 over EVERY column (timestamps included) of one row.

    Any write that mutates the record changes the digest, because
    ``_update_operation`` / ``_set_execution_state`` always refresh
    ``updated_at``; an unchanged digest therefore proves byte-level immutability
    rather than "the field I happened to look at is unchanged".
    """
    columns = _table_columns(store, table)
    rows = store.query_all(
        f"SELECT {', '.join(columns)} FROM {table} WHERE {key_column} = ?", (key,)
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _digest_operations(store: CoreStore, execution_id: str) -> str:
    columns = _table_columns(store, "core_operation")
    rows = store.query_all(
        f"SELECT {', '.join(columns)} FROM core_operation WHERE execution_id = ? "
        "ORDER BY operation_key",
        (execution_id,),
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _execution_fields(store: CoreStore, execution_id: str) -> dict:
    columns = _table_columns(store, "core_execution")
    rows = store.query_all(
        f"SELECT {', '.join(columns)} FROM core_execution WHERE id = ?", (execution_id,)
    )
    return dict(zip(columns, rows[0]))


def _fail_first_round(runtime: CoreRuntime) -> tuple:
    """Drive one real dispatch to a genuine terminal (FAILED) execution:
    slot A acquires, slot B refuses, nothing starts (spec.md US1.1 path), so the
    Execution is persisted terminal without any test-side forgery."""
    res_a = ControlledResourceProvider("res.alpha", acquire_mode="success")
    res_b = ControlledResourceProvider("res.beta", acquire_mode="refused")
    exe = ControlledExecutionProvider()
    runtime.stage(
        OWNER, contribution_set((res_a, res_b), (exe,))
    ).commit()
    result = runtime.submit(two_slot_plan(request_key="req-terminal"))
    assert result.execution_state is ExecutionState.FAILED  # real terminal
    assert exe.start_calls == []
    return res_a, res_b, exe, result


class TransportAwareExecutionProvider(ControlledExecutionProvider):
    """``ControlledExecutionProvider`` + explicit transport-channel bookkeeping.

    The channel is a *provider-side* fact: it opens when a run starts and only
    the provider can close it.  FR-014 needs a second axis to compare against
    the execution axis, because the core has no transport concept at all — the
    assertion is then "the core never moved this axis", which a black-box count
    cannot express.

    ``observation_kind`` scripts what ``observe`` honestly reports;
    ``ObservationKind.NOT_KNOWN`` + ``transport-dead`` evidence stands for the
    "transport dead" family (no ``ObservationKind`` may name an execution
    verdict — the vocabularies are deliberately not merged).
    """

    def __init__(self, *, observation_kind: ObservationKind = ObservationKind.RUNNING, **kw):
        super().__init__(**kw)
        self.observation_kind = observation_kind
        self.transport_open: set[str] = set()
        self.channel_events: list[str] = []

    def start(self, request):
        result = super().start(request)
        if result.outcome.value == "success":
            self.transport_open.add(request.execution_id)
            self.channel_events.append(f"open:{request.execution_id}")
        return result

    def observe(self, handle: RunHandle) -> Observation:
        with self._lock:
            self.observe_calls.append(handle)
        return Observation(
            execution_id=handle.execution_id,
            kind=self.observation_kind,
            evidence_ref=TRANSPORT_DEAD
            if self.observation_kind is ObservationKind.NOT_KNOWN
            else None,
        )


def resume_plan(
    request_key: str,
    *,
    previous_execution_ref: str | None = None,
    work_id: str = "work-0001",
    digest: str = DIGEST_A,
) -> ExecutionPlan:
    """A resume submission: fresh request_key over the same Work, optionally
    carrying the ``previous_execution_ref`` association (data-model.md Recovery)."""
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
        previous_execution_ref=previous_execution_ref,
    )


# ===========================================================================
# FR-004 — a terminal Execution is irreversible on every write path
# ===========================================================================


def test_terminal_execution_survives_every_write_path_unchanged(runtime):
    """FR-004: once an Execution is terminal, stop / replay / a finalization-style
    state write all refuse or return the existing record, and the persisted row
    plus every Operation row stay byte-identical (row digest before == after)."""
    res_a, res_b, exe, old = _fail_first_round(runtime)
    execution_id = old.execution_id
    row_digest = _digest_row(runtime.store, "core_execution", "id", execution_id)
    ops_digest = _digest_operations(runtime.store, execution_id)
    releases_before = len(res_a.release_calls)
    acquires_before = len(res_a.acquire_calls) + len(res_b.acquire_calls)
    starts_before = len(exe.start_calls)

    # (1) stop path: a stop request may not rewrite a terminal state.
    with pytest.raises(TerminalExecutionError):
        runtime.request_stop(execution_id, old.operation_key)

    # (2) replay path: the same key/digest replays the terminal record verbatim.
    replay = runtime.submit(two_slot_plan(request_key="req-terminal"))
    assert replay.execution_id == execution_id
    assert replay.execution_state is ExecutionState.FAILED
    assert replay.failed_slot == "b"

    # (3) observation path: reporting anything about the run cannot move it.
    exe.observe(RunHandle(execution_id, "exec.us1", "handle-x"))
    assert runtime.query(execution_id).execution_state is ExecutionState.FAILED

    # (4) finalization write: every execution-state write funnels through the
    # dispatcher's storage-layer writer, so probing it probes the last wall.
    for state in (ExecutionState.SUCCEEDED, ExecutionState.CANCELLED,
                  ExecutionState.ACTIVE, ExecutionState.FAILED):
        with pytest.raises(TerminalExecutionError):
            runtime._dispatch._set_execution_state(execution_id, state)

    # nothing was written, nothing was re-dispatched, nothing was reclaimed.
    assert _digest_row(runtime.store, "core_execution", "id", execution_id) == row_digest
    assert _digest_operations(runtime.store, execution_id) == ops_digest
    assert len(res_a.release_calls) == releases_before
    assert len(res_a.acquire_calls) + len(res_b.acquire_calls) == acquires_before
    assert len(exe.start_calls) == starts_before


def test_forged_terminal_row_is_never_rewritten_by_core_paths(runtime):
    """Negative guard for FR-004: a terminal record that did not come from the
    dispatcher's own failure path — a ``cancelled`` row written directly through
    SQL, standing in for any terminalization source — is equally immutable, and
    shutdown reports it as what it is (terminal), never as unresolved work."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    live = runtime.submit(one_own_plan(request_key="req-forge"))
    execution_id = live.execution_id

    # forge: mark the run terminal behind the dispatcher's back.
    with runtime.store.transaction():
        runtime.store.execute(
            "UPDATE core_execution SET state = ? WHERE id = ?",
            (ExecutionState.CANCELLED.value, execution_id),
        )
    row_digest = _digest_row(runtime.store, "core_execution", "id", execution_id)
    ops_digest = _digest_operations(runtime.store, execution_id)

    with pytest.raises(TerminalExecutionError):
        runtime.request_stop(execution_id, live.operation_key)
    with pytest.raises(TerminalExecutionError):
        runtime._dispatch._set_execution_state(execution_id, ExecutionState.ACTIVE)
    replayed = runtime.submit(one_own_plan(request_key="req-forge"))
    assert replayed.execution_state is ExecutionState.CANCELLED

    assert _digest_row(runtime.store, "core_execution", "id", execution_id) == row_digest
    assert _digest_operations(runtime.store, execution_id) == ops_digest
    # stop was refused before reaching the provider; no release without evidence
    assert exe.stop_calls == []
    assert res.release_calls == []

    report = runtime.close()
    assert execution_id not in report.unresolved_executions  # terminal, not unresolved
    assert execution_id not in report.unresolved_leases


def test_digest_probe_detects_control_write_on_non_terminal_execution(runtime):
    """T010 anti-fake-green self-test (反例守卫 for FR-004): the immutability
    assertions above are only meaningful if the digest probe can actually see a
    rewrite.  On a NON-terminal execution the same writer must succeed and the
    digest must change — if overwriting a terminal row were silently allowed, or
    the probe blind, this test and those would not both be green."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-control"))
    execution_id = result.execution_id
    assert runtime.query(execution_id).execution_state is ExecutionState.ACTIVE

    before = _digest_row(runtime.store, "core_execution", "id", execution_id)
    runtime._dispatch._set_execution_state(execution_id, ExecutionState.STOP_REQUESTED)
    after = _digest_row(runtime.store, "core_execution", "id", execution_id)

    assert after != before, "digest probe is blind: immutability tests would fake green"
    assert runtime.query(execution_id).execution_state is ExecutionState.STOP_REQUESTED
    assert res.release_calls == []


# ===========================================================================
# US1.3 — Session resume: a NEW Execution, the old record untouched
# ===========================================================================


def test_resume_creates_new_execution_and_leaves_terminal_record_untouched(runtime):
    """spec.md US1.3 / data-model.md Recovery: resuming the Work of a terminated
    Execution submits a NEW execution_id (terminal ids are never reused), carries
    ``previous_execution_ref``, and does not touch the terminal record by one byte."""
    _res_a, res_b, exe, old = _fail_first_round(runtime)
    previous_id = old.execution_id
    row_digest = _digest_row(runtime.store, "core_execution", "id", previous_id)
    ops_digest = _digest_operations(runtime.store, previous_id)
    work_id = _execution_fields(runtime.store, previous_id)["work_id"]

    # the resumed round must be able to acquire: slot B now accepts.
    res_b.acquire_mode = "success"

    resumed = runtime.submit(
        resume_plan("req-resume", previous_execution_ref=previous_id, work_id=work_id)
    )
    assert resumed.execution_id != previous_id
    assert resumed.execution_state is ExecutionState.ACTIVE

    view = runtime.query(resumed.execution_id)
    assert view.previous_execution_ref == previous_id
    assert view.work_id == work_id
    # the resume is a real new dispatch, not a resurrection of the old one
    assert len(exe.start_calls) == 1

    # original terminal record: unchanged, field by field and digest-wise; the
    # refused round never started, so no start operation row exists either.
    old_view = runtime.query(previous_id)
    assert old_view.execution_state is ExecutionState.FAILED
    assert old_view.operation_state is None
    assert old_view.failed_slot == "b"
    assert _digest_row(runtime.store, "core_execution", "id", previous_id) == row_digest
    assert _digest_operations(runtime.store, previous_id) == ops_digest


def test_resume_association_defaults_to_absent(runtime):
    """``previous_execution_ref`` is optional: a plain submission (or a replay of
    it) carries no association, and the field is honestly absent rather than
    defaulted to a fabricated predecessor."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()

    plain = runtime.submit(one_own_plan(request_key="req-plain"))
    assert runtime.query(plain.execution_id).previous_execution_ref is None
    replay = runtime.submit(one_own_plan(request_key="req-plain"))
    assert replay.execution_id == plain.execution_id
    assert runtime.query(replay.execution_id).previous_execution_ref is None
    assert len(exe.start_calls) == 1

    linked = runtime.submit(resume_plan("req-linked", previous_execution_ref=plain.execution_id))
    assert runtime.query(linked.execution_id).previous_execution_ref == plain.execution_id
    assert runtime.query(plain.execution_id).previous_execution_ref is None


def test_resume_under_terminal_request_key_is_refused(runtime):
    """C1/data-model "不复用终态 ID" on the key axis: replaying the terminal
    execution's own request_key with different content is a typed refusal that
    neither dispatches nor rewrites the terminal record."""
    res_a, res_b, exe, old = _fail_first_round(runtime)
    previous_id = old.execution_id
    row_digest = _digest_row(runtime.store, "core_execution", "id", previous_id)
    ops_digest = _digest_operations(runtime.store, previous_id)
    acquires_before = len(res_a.acquire_calls) + len(res_b.acquire_calls)

    with pytest.raises(PlanDigestConflictError):
        runtime.submit(two_slot_plan(request_key="req-terminal", digest=DIGEST_B))

    assert _digest_row(runtime.store, "core_execution", "id", previous_id) == row_digest
    assert _digest_operations(runtime.store, previous_id) == ops_digest
    assert len(exe.start_calls) == 0
    assert len(res_a.acquire_calls) + len(res_b.acquire_calls) == acquires_before
    # no second execution id was minted by the refused attempt
    ids = [row[0] for row in runtime.store.query_all(
        "SELECT id FROM core_execution ORDER BY created_at")]
    assert ids == [previous_id]


# ===========================================================================
# FR-014 — transport facts and execution facts never infer each other
# ===========================================================================


def test_transport_dead_observation_does_not_change_execution_state(tmp_path):
    """FR-014 forward direction: ``provider.observe`` reporting a transport-dead
    kind of fact must not move the Execution (still ACTIVE, row digest identical,
    zero operation rows written) — an observation is not a verdict."""
    store = CoreStore(tmp_path / "core.db")
    runtime = CoreRuntime(store)
    res = ControlledResourceProvider("res.alpha")
    exe = TransportAwareExecutionProvider(observation_kind=ObservationKind.NOT_KNOWN)
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-dead"))
    execution_id = result.execution_id
    row_digest = _digest_row(store, "core_execution", "id", execution_id)
    ops_digest = _digest_operations(store, execution_id)
    ops_before = len(store.query_all(
        "SELECT operation_key FROM core_operation WHERE execution_id = ?", (execution_id,)))

    observation = exe.observe(RunHandle(execution_id, "exec.us1", "run-1"))
    assert observation.kind is ObservationKind.NOT_KNOWN
    assert observation.evidence_ref == TRANSPORT_DEAD

    view = runtime.query(execution_id)
    assert view.execution_state is ExecutionState.ACTIVE
    assert _digest_row(store, "core_execution", "id", execution_id) == row_digest
    assert _digest_operations(store, execution_id) == ops_digest
    assert len(store.query_all(
        "SELECT operation_key FROM core_operation WHERE execution_id = ?",
        (execution_id,))) == ops_before
    # the run axis is untouched too: no stop was implied by the observation
    assert exe.stop_calls == []
    assert res.release_calls == []
    assert execution_id in exe.transport_open
    runtime.close()


def test_stop_failure_over_dead_transport_never_fabricates_cancelled(tmp_path):
    """FR-014 on the dispatch path: a stop whose receipt is lost must leave the
    Execution at ``stop_requested`` — never ``cancelled``, never ``failed`` — and
    must not rewrite the start operation's persisted verdict.

    A lost stop receipt gives no proof that the native run stopped. Its OWN
    lease must remain acquired even when the release provider would answer
    success, since calling release itself may destroy a live resource.
    """
    store = CoreStore(tmp_path / "core.db")
    runtime = CoreRuntime(store)
    res = ControlledResourceProvider("res.alpha")
    exe = TransportAwareExecutionProvider(stop_mode="raise")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-stop-raise"))

    stop = runtime.request_stop(result.execution_id, result.operation_key)

    # (a) the honest, non-terminal fact survives the failed stop.
    assert stop.execution_state is ExecutionState.STOP_REQUESTED
    assert stop.execution_state not in (
        ExecutionState.CANCELLED, ExecutionState.FAILED, ExecutionState.SUCCEEDED
    )
    assert "simulated primary stop failure" in str(stop.error)
    assert stop.cleanup_failures == ()
    # (b) the start operation keeps its recorded verdict.
    assert stop.operation_state is OperationState.SUCCEEDED
    assert store.query_all(
        "SELECT state FROM core_operation WHERE operation_key = ?",
        (result.operation_key,),
    ) == [("succeeded",)]
    # (c) no cancellation vocabulary was synthesized anywhere in storage.
    assert _execution_fields(store, result.execution_id)["state"] == "stop_requested"
    assert store.query_all(
        "SELECT id FROM core_execution WHERE state IN ('cancelled', 'succeeded', 'failed')"
    ) == []
    # (d) no destructive cleanup may be attempted without stop evidence.
    lease_id = runtime.query(result.execution_id).leases[0].lease_id
    assert res.release_calls == []
    assert runtime.query(result.execution_id).leases[0].lease_state is LeaseState.ACQUIRED
    assert stop.unresolved_leases == (lease_id,)
    assert runtime.owner_busy(OWNER) is True
    # (e) execution and lease remain unresolved at close (FR-003).
    report = runtime.close()
    assert result.execution_id in report.unresolved_executions
    assert lease_id in report.unresolved_leases


def test_unknown_stop_keeps_possibly_live_own_lease(runtime):
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(stop_mode="unknown")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-stop-unknown"))
    lease_id = runtime.query(result.execution_id).leases[0].lease_id

    stop = runtime.request_stop(result.execution_id, result.operation_key)

    assert len(exe.stop_calls) == 1
    assert res.release_calls == []
    assert stop.execution_state is ExecutionState.STOP_REQUESTED
    assert stop.operation_state is OperationState.SUCCEEDED
    assert stop.unresolved_leases == (lease_id,)
    assert runtime.query(result.execution_id).leases[0].lease_state is LeaseState.ACQUIRED
    assert runtime.owner_busy(OWNER) is True


def test_stop_refused_by_transport_never_fabricates_cancelled(tmp_path):
    """Same wall, refused verdict: an explicit stop refusal (transport alive but
    the provider declines) keeps the execution at ``stop_requested`` with the
    refusal code visible; it is never rewritten into a cancellation."""
    store = CoreStore(tmp_path / "core.db")
    runtime = CoreRuntime(store)
    res = ControlledResourceProvider("res.alpha")
    exe = TransportAwareExecutionProvider(stop_mode="refused")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-stop-refused"))

    stop = runtime.request_stop(result.execution_id, result.operation_key)

    assert stop.execution_state is ExecutionState.STOP_REQUESTED
    assert stop.primary_error_code == "controlled_stop_refused"
    assert res.release_calls == []
    assert store.query_all(
        "SELECT state FROM core_execution WHERE id = ?", (result.execution_id,)
    )[0][0] == "stop_requested"
    runtime.close()


def test_execution_terminalization_does_not_close_or_fabricate_transport_channel(tmp_path):
    """FR-014 reverse direction: reaching a real terminal state (partial acquire
    failure) must not clear or synthesize the transport axis — the channel stays
    exactly as the provider left it and no provider transport action is invoked."""
    store = CoreStore(tmp_path / "core.db")
    runtime = CoreRuntime(store)
    res_a = ControlledResourceProvider("res.alpha", acquire_mode="success")
    res_b = ControlledResourceProvider("res.beta", acquire_mode="refused")
    exe = TransportAwareExecutionProvider(observation_kind=ObservationKind.RUNNING)
    runtime.stage(OWNER, contribution_set((res_a, res_b), (exe,))).commit()

    result = runtime.submit(two_slot_plan(request_key="req-terminal-transport"))
    assert result.execution_state is ExecutionState.FAILED

    # the run never started, so the transport axis never existed and was never
    # fabricated; and terminalization called no transport operation at all.
    assert exe.transport_open == set()
    assert exe.channel_events == []
    assert exe.stop_calls == []
    assert exe.observe_calls == []

    # positive control on the same double: a started run does open a channel, and
    # stopping it through the core still leaves the channel axis to the provider.
    res_b.acquire_mode = "success"
    started = runtime.submit(two_slot_plan(request_key="req-live-transport"))
    assert started.execution_state is ExecutionState.ACTIVE
    assert started.execution_id in exe.transport_open
    channels_before = set(exe.transport_open)

    runtime.request_stop(started.execution_id, started.operation_key)
    assert exe.transport_open == channels_before  # core never closes the channel
    assert exe.channel_events == [f"open:{started.execution_id}"]
    runtime.close()


def test_close_does_not_stop_active_execution_or_release_leases(tmp_path):
    """FR-014 (shutdown leg, re-proved on the real dispatch path): close lists the
    unresolved work, it does not delegate a stop and does not release the lease —
    and the ACTIVE fact survives in the store for whoever restarts."""
    path = tmp_path / "core.db"
    store = CoreStore(path)
    runtime = CoreRuntime(store)
    res = ControlledResourceProvider("res.alpha")
    exe = TransportAwareExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-close-no-stop"))
    row_digest = _digest_row(store, "core_execution", "id", result.execution_id)
    ops_digest = _digest_operations(store, result.execution_id)

    report = runtime.close()

    assert exe.stop_calls == []
    assert res.release_calls == []
    assert result.execution_id in report.unresolved_executions
    assert report.unresolved_leases  # the acquired lease is reported, not released

    reopened = CoreStore(path)
    try:
        assert _digest_row(reopened, "core_execution", "id", result.execution_id) == row_digest
        assert _digest_operations(reopened, result.execution_id) == ops_digest
        assert reopened.query_all(
            "SELECT state FROM core_execution WHERE id = ?", (result.execution_id,)
        )[0][0] == ExecutionState.ACTIVE.value
    finally:
        reopened.close()


def test_unregister_with_active_execution_refused_and_stops_nothing(runtime):
    """FR-014 / FR-007 (unregister leg, real facts): unregistering the owner of a
    live run is refused while its lease is unresolved, and the refusal is pure —
    no stop is delegated and no lease is destroyed on the way out."""
    res = ControlledResourceProvider("res.alpha")
    exe = TransportAwareExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-unregister"))

    assert runtime.owner_busy(OWNER) is True
    with pytest.raises(OwnerBusyError):
        runtime.unregister(OWNER)

    # the refusal delegated nothing and destroyed nothing
    assert exe.stop_calls == []
    assert res.release_calls == []
    assert runtime.query(result.execution_id).execution_state is ExecutionState.ACTIVE
    assert runtime.registry_snapshot().execution_provider_ids == ("exec.us1",)

    # evidence-only path: an explicit release (via a stop that the provider
    # acknowledges) resolves the lease, and only then does unregister succeed.
    runtime.request_stop(result.execution_id, result.operation_key)
    runtime.unregister(OWNER)
    assert runtime.registry_snapshot().execution_provider_ids == ()
    assert exe.stop_calls and res.release_calls


def test_stop_requested_execution_is_not_terminal_and_stays_queryable(runtime):
    """FR-004 (projection honesty): 请求停止 is neither 启动未知 nor a real
    terminal state — it survives query, survives close/reopen unchanged, and is
    reported as unresolved work."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider()
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-stop-requested"))
    runtime.request_stop(result.execution_id, result.operation_key)

    view = runtime.query(result.execution_id)
    assert view.execution_state is ExecutionState.STOP_REQUESTED
    assert not view.execution_state.is_terminal()

    report = runtime.close()
    assert result.execution_id in report.unresolved_executions
    assert view.request_key == "req-stop-requested"


def test_start_unknown_delegates_no_stop_and_releases_no_lease(runtime):
    """FR-004 on the real dispatch path: a lost start receipt (operation unknown)
    must not be stopped, retried or cleaned speculatively — stop stays undelivered
    and the lease the possibly-live run may use is never released."""
    res = ControlledResourceProvider("res.alpha")
    exe = ControlledExecutionProvider(start_mode="raise")
    runtime.stage(OWNER, contribution_set((res,), (exe,))).commit()
    result = runtime.submit(one_own_plan(request_key="req-unknown-start"))
    assert result.execution_state is ExecutionState.START_UNKNOWN

    stop = runtime.request_stop(result.execution_id, result.operation_key)

    assert exe.stop_calls == []
    assert res.release_calls == []
    assert stop.execution_state is ExecutionState.STOP_REQUESTED
    assert runtime.query(result.execution_id).operation_state is OperationState.UNKNOWN
    report = runtime.close()
    assert result.execution_id in report.unresolved_executions
    assert report.unresolved_leases
