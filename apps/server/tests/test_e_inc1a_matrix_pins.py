"""E-INC1a matrix/contract pins (approved scope `approvals/E-INC1a.md`, a-4).

Green pins only: every assertion here must pass against the INC1a product code.
Covers (E-D2 v1.3 numbering):
* a-1 contract types importable, frozen, tristate spellings pairwise distinct;
* word-ban: the neutral contract module carries no product-domain vocabulary;
* bool shell: deleted in E-INC1b b-1 - counter-pins prove the tristate verb is
  the only cancel answer surface (O-3 fulfilled, M-1 public shape untouched);
* R4/R5/R8/R9/R11 on the E-local observe projection (supplement A semantics:
  pure read, NOT_KNOWN is bounded knowledge, late terminal seals, cleanup never
  upgrades, terminal states are absorbing);
* probe ban: observe dispatches nothing, ever;
* no-laundering: after an unknown outcome retires the run, replay still answers
  unknown (a vanished run must never be pressed into refused);
* submit: zero business-Core writes, opaque correlation passthrough, replay
  never re-dispatches, typed pre-start refusal leaves nothing registered;
* a-6: `closure` seam assembles exactly the declaration; the literal view
  layout is frozen at one shell and zero elsewhere (anti-growth lock).

Run (from the repo root, `source/`; in-tree persistent home for E INC1a pins,
packaging round per `C-notice-inc1a-packaging.md`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../tmp/venv/bin/python -m pytest tests/server/test_e_inc1a_matrix_pins.py -q
"""
from __future__ import annotations

import inspect
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ordessa_server_compat.execution import (
    SidecarExecutionBackend, TurnExecutionPort, execution_contract,
)
from ordessa_server_compat.execution import sidecar as sidecar_module
from ordessa_server_compat.execution import sidecar_backend as sb
from ordessa_server_compat.execution.execution_contract import (
    CancelOutcome, DeadlinePolicy, EvidenceClass, ExecutionObservation,
    ExecutionReceipt, ExecutionRequest, NeutralBinding, ObservationState,
)
from ordessa_server_compat.execution.sidecar import sidecar_bundle_files
from ordessa_server_compat.execution.sidecar_backend import _Run


def _backend() -> SidecarExecutionBackend:
    return SidecarExecutionBackend(
        None, None, None, port_factory=lambda context, on_event: None,
    )


def _inject(backend, key: str, port, *, native_id: str | None = None) -> _Run:
    run = _Run(
        turn_id=key, work_id="w-" + key, core_execution_id="x-" + key,
        dispatch_id="d-" + key, port=port,
        native_id="n-" + key if native_id is None else native_id,
        done=threading.Event(),
    )
    with backend._lock:
        backend._active[key] = run
    return run


class _AnySpy:
    """Counts every attribute call - used to prove zero dispatch."""

    def __init__(self, *, cancel_answer=None, cancel_raises=None):
        self.counts: dict[str, int] = {}
        self.cancel_answer = cancel_answer
        self.cancel_raises = cancel_raises

    def _hit(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1

    def cancel(self, key):
        self._hit("cancel")
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return self.cancel_answer

    def __getattr__(self, name):
        def _seen(*args, **kwargs):
            self._hit(name)
            raise AssertionError(f"observe/submit unexpectedly dispatched {name!r}")
        return _seen


# --------------------------------------------------------------------------
# a-1 — contract shapes.

def test_cancel_outcome_three_values_are_pairwise_distinct():
    values = {item.value for item in CancelOutcome}
    assert values == {"confirmed_stopped", "refused_no_active_run", "unknown"}


def test_execution_request_is_frozen_and_correlation_is_read_through():
    request = ExecutionRequest(
        execution_key="k1", bundle_ref="sha256:abc",
        resource_bindings=(NeutralBinding("c.one", "sha256:d", "mount-1"),),
        capability_demand=frozenset({"cap.a"}),
        deadline_policy=DeadlinePolicy(idle_timeout_seconds=30.0),
        correlation={"trace": "caller-own"},
    )
    with pytest.raises(Exception):
        request.execution_key = "k2"  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.correlation["trace"] = "rewritten"  # type: ignore[index]
    assert request.correlation["trace"] == "caller-own"


def test_contract_module_carries_no_product_vocabulary():
    src = inspect.getsource(execution_contract)
    banned = re.findall(r"\b(session|sessions|turn|turns|profile|profiles)\b", src, re.I)
    assert not banned, f"neutral contract carries product words: {banned}"


# --------------------------------------------------------------------------
# INC1b b-1 counter-evidence family (absorbs the deleted O-3 shell-collapse
# test): the bool shell is gone and the tristate verb is the ONLY cancel
# answer surface. The collapse truths that the shell used to pin
# (confirmed-only-true, unknown-never-leaks) survive verbatim as
# cancel_execution answers in this file's tristate and no-laundering pins.

def test_bool_cancel_shell_is_permanently_gone():
    assert not hasattr(TurnExecutionPort, "cancel")
    assert not hasattr(SidecarExecutionBackend, "cancel")
    assert not hasattr(_backend(), "cancel")


def test_cancel_answer_surface_is_exactly_the_tristate_verb():
    cancel_surface = [m for m in dir(TurnExecutionPort) if "cancel" in m.lower()]
    assert cancel_surface == ["cancel_execution"]
    for verb in ("submit", "cancel_execution", "observe_execution"):
        assert callable(getattr(_backend(), verb))


# --------------------------------------------------------------------------
# R4 - affirmative observations project; R5 - NOT_KNOWN is bounded knowledge.

def test_r4_running_projections_are_evidence_graduated():
    backend = _backend()
    _inject(backend, "k-ack", _AnySpy(), native_id="")
    observation = backend.observe_execution("k-ack")
    assert (observation.state, observation.evidence) == (
        ObservationState.RUNNING, EvidenceClass.DISPATCH_ACK)
    _inject(backend, "k-live", _AnySpy())
    observation = backend.observe_execution("k-live")
    assert (observation.state, observation.evidence) == (
        ObservationState.RUNNING, EvidenceClass.NATIVE_REPORT)
    assert isinstance(observation.observed_at, datetime)


def test_r5_absent_key_is_not_known_never_a_refusal_or_a_proof():
    backend = _backend()
    spy_port = _AnySpy()
    backend.port_factory = lambda context, on_event: spy_port
    observation = backend.observe_execution("never-ever")
    assert (observation.state, observation.evidence) == (
        ObservationState.NOT_KNOWN_TO_E, EvidenceClass.NONE)
    assert spy_port.counts == {}  # observe proves nothing by probing


def test_r5_no_laundering_unknown_survives_the_run_disappearing():
    backend = _backend()
    port = _AnySpy(cancel_raises=TimeoutError())
    _inject(backend, "t2", port)
    first = backend.cancel_execution("t2")
    with backend._lock:
        backend._active.pop("t2")  # the completion path retires runs
    replay = backend.cancel_execution("t2")
    assert first is CancelOutcome.UNKNOWN
    assert replay is CancelOutcome.UNKNOWN
    assert port.counts.get("cancel", 0) == 1


# --------------------------------------------------------------------------
# R8 - a late terminal fact seals; R9 - cleanup/completion chatter never
# upgrades; R11 - terminal answers are absorbing; probe ban everywhere.

def test_r8_late_terminal_fact_outranks_a_confirmed_stop():
    backend = _backend()
    run = _inject(backend, "t8", _AnySpy(cancel_answer=True))
    run.cancel_confirmed = True
    assert backend.observe_execution("t8").state is ObservationState.STOPPED_CONFIRMED
    run.result = {"ok": True, "stopReason": "end_turn"}  # terminal fact arrives late
    observation = backend.observe_execution("t8")
    assert (observation.state, observation.evidence) == (
        ObservationState.TERMINAL, EvidenceClass.TERMINAL_RECEIPT)


def test_r9_settling_without_a_terminal_fact_never_upgrades():
    backend = _backend()
    run = _inject(backend, "t9", _AnySpy(cancel_answer=True))
    run.cancel_confirmed = True
    run.done.set()  # the workers settled; that is cleanup, not a terminal fact
    observation = backend.observe_execution("t9")
    assert (observation.state, observation.evidence) == (
        ObservationState.STOPPED_CONFIRMED, EvidenceClass.CANCEL_CONFIRMATION)


def test_r11_terminal_is_absorbing_across_further_cancels_and_observations():
    backend = _backend()
    run = _inject(backend, "t11", _AnySpy(cancel_answer=False))
    run.result = {"ok": True}
    before = backend.observe_execution("t11")
    backend.cancel_execution("t11")
    after = backend.observe_execution("t11")
    assert before.state is after.state is ObservationState.TERMINAL
    assert (after.state, after.evidence) == (
        ObservationState.TERMINAL, EvidenceClass.TERMINAL_RECEIPT)


def test_probe_ban_observe_touches_no_port_and_writes_no_receipt():
    backend = _backend()
    spy = _AnySpy(cancel_answer=True)
    _inject(backend, "t-silent", spy)
    for _ in range(3):
        backend.observe_execution("t-silent")
    assert spy.counts == {}
    assert "t-silent" not in backend._cancel_receipts


# --------------------------------------------------------------------------
# submit - neutral start, zero business-Core writes, honest replay.

class _NeutralPort:
    def __init__(self, *, open_answer="native-1", open_raises=None):
        self.open_calls = 0
        self.sink = None
        self.open_answer = open_answer
        self.open_raises = open_raises
        self.cancel_answer = True

    def open_execution(self, key):
        self.open_calls += 1
        if self.open_raises is not None:
            raise self.open_raises
        return self.open_answer

    def cancel(self, key):
        return self.cancel_answer


def _request(key: str = "exec-key-1") -> ExecutionRequest:
    return ExecutionRequest(
        execution_key=key, bundle_ref="sha256:bundle",
        resource_bindings=(NeutralBinding("c.ws", "sha256:obj", "tok-1"),),
        capability_demand=frozenset({"cap.a", "cap.b"}),
        correlation={"anything": "caller-owned"},
    )


def test_submit_maps_neutral_request_and_never_touches_business_core(monkeypatch):
    backend = _backend()
    created = []
    monkeypatch.setattr(
        backend.work_service, "create_work",
        lambda *a, **k: created.append(("work", a)) or pytest.fail("E minted a business work row"))
    monkeypatch.setattr(
        backend.execution_service, "create_execution",
        lambda *a, **k: pytest.fail("E minted a business execution row"))
    ports = []

    def factory(context, on_event):
        ports.append((context, on_event))
        return _NeutralPort()

    backend.port_factory = factory
    receipt = backend.submit(_request())
    assert isinstance(receipt, ExecutionReceipt)
    assert (receipt.execution_key, receipt.replayed) == ("exec-key-1", False)
    context, _sink = ports[0]
    assert context["execution_key"] == "exec-key-1"
    assert context["bundle_ref"] == "sha256:bundle"
    assert context["capability_demand"] == ["cap.a", "cap.b"]
    assert context["resource_bindings"] == [
        {"contract_id": "c.ws", "object_digest": "sha256:obj", "mount_token": "tok-1"}]
    assert context["correlation"] == {"anything": "caller-owned"}  # passthrough, unparsed
    assert created == []


def test_submit_replay_returns_original_receipt_and_never_re_dispatches():
    backend = _backend()
    port = _NeutralPort()
    factory_calls = []

    def factory(context, on_event):
        factory_calls.append(context)
        return port

    backend.port_factory = factory
    first = backend.submit(_request())
    second = backend.submit(_request())
    assert second.replayed is True
    assert second.dispatch_id == first.dispatch_id
    assert port.open_calls == 1
    assert len(factory_calls) == 1  # replay does not even rebuild the seam


def test_submit_typed_refusal_before_dispatch_registers_nothing():
    backend = _backend()

    def factory(context, on_event):
        raise ValueError("CAPABILITY_REFUSED_BEFORE_START")

    backend.port_factory = factory
    with pytest.raises(ValueError, match="CAPABILITY_REFUSED_BEFORE_START"):
        backend.submit(_request())
    assert backend.observe_execution("exec-key-1").state is ObservationState.NOT_KNOWN_TO_E
    assert backend.cancel_execution("exec-key-1") is CancelOutcome.REFUSED_NO_ACTIVE_RUN


def test_submit_uncertain_start_is_registered_and_not_re_dispatched():
    backend = _backend()
    port = _NeutralPort(open_raises=RuntimeError("channel lost mid-start"))
    backend.port_factory = lambda context, on_event: port
    with pytest.raises(RuntimeError, match="channel lost"):
        backend.submit(_request())
    # an uncertain start stays tracked; a replay returns the original dispatch
    # receipt and must never start a second time (a second open would blur
    # "maybe it is running" into "two are running").
    replay = backend.submit(_request())
    assert (replay.replayed, replay.execution_key) == (True, "exec-key-1")
    assert port.open_calls == 1
    observation = backend.observe_execution("exec-key-1")
    assert (observation.state, observation.evidence) == (
        ObservationState.RUNNING, EvidenceClass.DISPATCH_ACK)


def test_neutral_events_are_captured_as_monotonic_native_evidence():
    backend = _backend()
    held = {}

    class _Capturing(_NeutralPort):
        def open_execution(self, key):
            self.sink_opened = True
            return super().open_execution(key)

    def factory(context, on_event):
        port = _Capturing()
        held["sink"] = on_event
        return port

    backend.port_factory = factory
    backend.submit(_request())
    assert backend.observe_execution("exec-key-1").evidence is EvidenceClass.DISPATCH_ACK
    held["sink"]("exec-key-1", "message.delta", {"text": "x"})
    once = backend.observe_execution("exec-key-1")
    assert (once.state, once.evidence) == (
        ObservationState.RUNNING, EvidenceClass.NATIVE_REPORT)
    held["sink"]("exec-key-1", "tool.update", {"state": "completed"})
    twice = backend.observe_execution("exec-key-1")
    assert twice.state is once.state and twice.evidence is once.evidence
    run = backend._neutral_runs["exec-key-1"]
    assert len(run.evidence) == 2  # append-only, never rewritten
    assert backend.cancel_execution("exec-key-1") is CancelOutcome.CONFIRMED_STOPPED
    assert backend.observe_execution("exec-key-1").state is ObservationState.STOPPED_CONFIRMED


# --------------------------------------------------------------------------
# concurrency attacks (E self fault-attack, same approved semantics:
# "a replay never re-dispatches" must hold under racing callers, not just
# sequential ones).

class _SlowCancelPort:
    """cancel blocks until released, so a second caller queues on the run."""

    def __init__(self):
        import threading
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def cancel(self, key):
        with self.lock:
            self.calls += 1
            first = self.calls == 1
        if first:
            self.entered.set()
            self.release.wait(5)
        return True


def test_concurrent_cancel_never_dispatches_the_abort_twice():
    """Receipt-vs-dispatch window attack: while the first answer is in flight,
    every racing caller must either wait for it or read the recorded receipt -
    the abort envelope goes out exactly once per key."""
    import sys as _sys
    previous = _sys.getswitchinterval()
    _sys.setswitchinterval(0.0001)  # widen the historical race window
    try:
        for _round in range(30):
            backend = _backend()
            port = _SlowCancelPort()
            _inject(backend, "race-key", port)
            outcomes = []
            threads = [
                threading.Thread(target=lambda: outcomes.append(
                    backend.cancel_execution("race-key")))
                for _ in range(6)
            ]
            threads[0].start()
            assert port.entered.wait(5)
            for thread in threads[1:]:
                thread.start()
            port.release.set()
            for thread in threads:
                thread.join(5)
            assert port.calls == 1, (
                "abort re-dispatched under concurrent cancels of one key")
            assert set(outcomes) == {CancelOutcome.CONFIRMED_STOPPED}
            del backend, port, threads, outcomes
    finally:
        _sys.setswitchinterval(previous)


class _SlowFactoryPort:
    def __init__(self, *, gate):
        self.gate = gate
        self.open_calls = 0

    def open_execution(self, key):
        self.open_calls += 1
        return "native-x"

    def cancel(self, key):
        return True


def test_concurrent_submit_never_starts_the_same_key_twice():
    """Check-then-register window attack: two callers submitting one key while
    the first is still inside the factory seam must produce exactly one start
    dispatch; the loser gets the (same-key) receipt, never a second port."""
    opens = []

    def slow_factory(context, on_event):
        # held open in the factory: the second caller passes the tracking
        # check here too under the old check-then-register ordering.
        gate.wait(5)
        port = _SlowFactoryPort(gate=gate)
        opens.append(port)
        return port

    import sys as _sys
    previous = _sys.getswitchinterval()
    _sys.setswitchinterval(0.0001)
    try:
        for _round in range(20):
            backend = _backend()
            backend.port_factory = slow_factory
            gate = threading.Event()
            receipts = []
            errors = []

            def call():
                try:
                    receipts.append(backend.submit(_request()))
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=call) for _ in range(4)]
            for thread in threads:
                thread.start()
            gate.set()
            for thread in threads:
                thread.join(5)
            assert not errors, errors
            keys = {receipt.dispatch_id for receipt in receipts}
            assert len(opens) == 1, "same key started through two ports"
            assert len(keys) == 1  # every caller got the one dispatch
            del backend, receipts, errors, threads, keys
            opens.clear()
    finally:
        _sys.setswitchinterval(previous)


# --------------------------------------------------------------------------
# forced-interleave pins (Sol#2 return-to-E item 3: a concurrency pin must
# be able to falsify - red against the pre-hardening code by construction,
# not by scheduler luck). These drive the exact historical windows with
# events and a scheduling stub, so the answer does not depend on thread
# timing luck; they hold a bounded timeout open instead of dead-locking.

class _ScheduledAbortPort:
    """The holder's cancel only answers once the racer is at the door; the
    racer's (second) dispatch is the witness the window was entered."""

    def __init__(self, events):
        self.calls = 0
        self.events = events

    def cancel(self, key):
        self.calls += 1
        if threading.current_thread().name == "MainThread":
            assert self.events["racer_arrived"].wait(2.0), "racer never reached the door"
        else:
            self.events["racer_dispatched"].set()
        return True


class _GateLock:
    """Stand-in for the registry lock that runs a scheduling hook before
    every acquisition - the manual unlock-window stub demanded by Sol#2."""

    def __init__(self, gate):
        self._inner = threading.Lock()
        self._counts = {}
        self._gate = gate

    def __enter__(self):
        name = threading.current_thread().name
        count = self._counts[name] = self._counts.get(name, 0) + 1
        self._gate(name, count)
        self._inner.acquire()
        return self

    def __exit__(self, *exc):
        self._inner.release()
        return False


def test_forced_interleave_cancel_receipt_window_is_closed():
    """Receipt-before-release, enforced by schedule: the racer is parked at
    the run's cancel lock while the holder dispatches; it is released into
    the historical gap between dispatch and receipt. Pre-hardening code can
    only answer this with a second abort (red); the fixed code answers with
    the receipt the holder wrote before releasing the lock (green)."""
    events = {
        "racer_arrived": threading.Event(),
        "holder_in_cancel_lock": threading.Event(),
        "racer_dispatched": threading.Event(),
    }

    def gate(name, count):
        # holder lock acquisitions on the cancel path are exactly:
        # 1 outer check, 2 re-check under the run's cancel lock, 3 receipt.
        if name == "MainThread" and count == 2:
            events["holder_in_cancel_lock"].set()
        elif name == "MainThread" and count == 3:
            # hold the receipt open for the racer, once, deterministically:
            # only a window where the receipt lands outside the cancel lock
            # lets the racer walk into a second dispatch.
            events["racer_dispatched"].wait(1.0)

    backend = _backend()
    port = _ScheduledAbortPort(events)
    _inject(backend, "sched-key", port)
    backend._lock = _GateLock(gate)

    racer_outcomes = []

    def racer():
        events["racer_arrived"].set()
        events["holder_in_cancel_lock"].wait(5.0)
        racer_outcomes.append(backend.cancel_execution("sched-key"))

    thread = threading.Thread(target=racer, name="cancel-racer")
    thread.start()
    holder = backend.cancel_execution("sched-key")
    thread.join(10)
    assert port.calls == 1, "abort re-dispatched through the receipt window"
    assert holder is CancelOutcome.CONFIRMED_STOPPED
    assert racer_outcomes == [CancelOutcome.CONFIRMED_STOPPED]  # the racer must
    # not invent its own answer - it inherits the recorded receipt


class _StartWitnessPort:
    def __init__(self, opens, witness):
        self.opens = opens
        self.witness = witness

    def open_execution(self, key):
        self.opens.append(threading.current_thread().name)
        self.witness.set()
        return "native-s"

    def cancel(self, key):
        return True


def test_forced_interleave_submit_start_window_is_closed():
    """Claim-before-seam, enforced by schedule: the holder parks inside the
    factory seam (after its tracking check) until the racer has attempted its
    own start. Pre-hardening code must open twice (red); the fixed claim makes
    the racer a replay that never reaches a port (green: one open, holder's)."""
    opens = []
    a_in_gap = threading.Event()   # holder is past check/claim, inside factory
    b_opened = threading.Event()   # racer actually opened a start

    def factory(context, on_event):
        if threading.current_thread().name == "MainThread":
            a_in_gap.set()
            # stay in the historical no-registration window until the racer
            # proves it got past its own check into a start dispatch
            b_opened.wait(2.0)
        return _StartWitnessPort(opens, b_opened)

    backend = _backend()
    backend.port_factory = factory
    real_submit = backend.submit

    racer_results = []

    def racer():
        a_in_gap.wait(5.0)
        try:
            racer_results.append(real_submit(_request()))
        except BaseException as exc:  # noqa: BLE001
            racer_results.append(exc)

    thread = threading.Thread(target=racer, name="submit-racer")
    thread.start()
    holder_receipt = real_submit(_request())
    thread.join(10)

    assert len(opens) == 1, f"same key started through two ports: {opens}"
    assert opens == ["MainThread"]
    assert racer_results and isinstance(racer_results[0], ExecutionReceipt)
    assert racer_results[0].replayed is True
    assert racer_results[0].dispatch_id == holder_receipt.dispatch_id


class _PrePortCancelPort:
    def __init__(self):
        self.cancel_calls = 0

    def open_execution(self, key):
        return "native-p8"

    def cancel(self, key):
        self.cancel_calls += 1
        return True


def _parked_in_pre_port_window():
    """Holder submit parked inside the factory seam on its own thread: the key
    is claimed (pre-port half-window open) while no port exists yet, and the
    main thread drives cancels into that window deterministically."""
    port = _PrePortCancelPort()
    in_factory = threading.Event()
    release = threading.Event()

    def factory(context, on_event):
        in_factory.set()
        assert release.wait(5.0), "holder never released from the seam"
        return port

    backend = _backend()
    backend.port_factory = factory
    return backend, port, in_factory, release


def test_forced_interleave_pre_port_cancel_answers_unknown_without_recording():
    """P8 (approved disposition (i), E-017): a cancel that arrives while the
    key is claimed but the port does not exist yet answers UNKNOWN honestly
    and records NOTHING - there was no dispatch for a receipt to guard.
    Repeated in-window cancels stay idempotent answers, never a permanent
    receipt that bricks post-start cancellation."""
    backend, port, in_factory, release = _parked_in_pre_port_window()
    holder_results = []

    def holder():
        try:
            holder_results.append(backend.submit(_request("p8-key")))
        except BaseException as exc:  # noqa: BLE001
            holder_results.append(exc)

    thread = threading.Thread(target=holder, name="submit-holder")
    thread.start()
    assert in_factory.wait(5.0), "holder never reached the seam"
    first = backend.cancel_execution("p8-key")
    second = backend.cancel_execution("p8-key")
    release.set()
    thread.join(10)

    assert first is CancelOutcome.UNKNOWN
    assert second is CancelOutcome.UNKNOWN
    assert len(holder_results) == 1 and isinstance(holder_results[0], ExecutionReceipt)
    assert holder_results[0].replayed is False
    with backend._lock:
        assert backend._cancel_receipts.get("p8-key") is None, (
            "a pre-port cancel recorded a receipt for a dispatch that never "
            "happened")
    assert port.cancel_calls == 0  # nothing was ever dispatched to cancel


def test_forced_interleave_post_start_cancel_still_reaches_live_port():
    """P8 red-green pair: after the parked start completes, a cancel must
    reach the live port. Pre-fix code replays the recorded UNKNOWN forever
    and leaks the run (red: cancel_calls == 0); the fixed code dispatches
    once and returns CONFIRMED_STOPPED (green)."""
    backend, port, in_factory, release = _parked_in_pre_port_window()
    holder_results = []

    def holder():
        holder_results.append(backend.submit(_request("p8-key")))

    thread = threading.Thread(target=holder, name="submit-holder")
    thread.start()
    assert in_factory.wait(5.0), "holder never reached the seam"
    in_window = backend.cancel_execution("p8-key")  # answered, not recorded
    release.set()
    thread.join(10)

    assert in_window is CancelOutcome.UNKNOWN
    # the holder's submit has fully returned: the run is live behind its port
    after_start = backend.cancel_execution("p8-key")
    assert after_start is CancelOutcome.CONFIRMED_STOPPED, (
        "run leaked: post-start cancel never reached the port")
    assert port.cancel_calls == 1, "abort must dispatch exactly once"


# --------------------------------------------------------------------------
# a-6 - the closure seam and the anti-growth lock.

RUNTIME_LITERAL = "agentbox-sidecar/runtime/"


def test_execution_package_literal_layout_is_frozen_to_the_single_shell():
    package = Path(sb.__file__).parent
    offenders = []
    shell_hits = 0
    for module_file in sorted(package.glob("*.py")):
        text = module_file.read_text(encoding="utf-8")
        hits = text.count(RUNTIME_LITERAL) + text.count("subagent-bridge")
        if module_file.name == "sidecar.py":
            shell_hits = hits
        elif hits:
            offenders.append((module_file.name, hits))
    assert offenders == [], f"view-layout literals escaped the frozen shell: {offenders}"
    assert shell_hits == 7, (
        "the compatibility shell must not grow either (5 runtime paths + 2 "
        "bridge names); it is deleted whole in INC1b, not extended")


def test_closure_branch_assembles_exactly_the_declaration(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "entry.mjs").write_bytes(b"A")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "one.mjs").write_bytes(b"B")
    files = sidecar_bundle_files(
        tmp_path,
        closure=[("runtime/entry.mjs", "declared/views/entry.mjs"),
                 ("lib/one.mjs", "declared/one.mjs")],
        additional_files={"extra.txt": b"C"},
    )
    assert files == {
        "declared/views/entry.mjs": b"A",
        "declared/one.mjs": b"B",
        "extra.txt": b"C",
    }
    # the closure branch never touches the shell's SOURCE.json machinery
    assert not (tmp_path / "third_party").exists()


@pytest.mark.parametrize("bad", ["/etc/passwd", "../escape", "a//b", ""])
def test_closure_rejects_unsafe_paths(bad):
    with pytest.raises(ValueError, match="SIDECAR_BUNDLE_PATH"):
        sidecar_bundle_files(Path("."), closure=[(bad, "target.mjs")])
    with pytest.raises(ValueError, match="SIDECAR_BUNDLE_PATH"):
        sidecar_bundle_files(Path("."), closure=[("ok.mjs", bad)])


def test_closure_rejects_duplicate_targets(tmp_path):
    (tmp_path / "a.mjs").write_bytes(b"A")
    with pytest.raises(ValueError, match="SIDECAR_BUNDLE_PATH_CONFLICT"):
        sidecar_bundle_files(
            tmp_path, closure=[("a.mjs", "same"), ("a.mjs", "same")])


# --------------------------------------------------------------------------
# protocol carrier (a-2): the three contract verbs are declared with their
# annotations (the bool shell's presence was locked here until E-INC1b b-1
# deleted it; its absence is pinned in the counter-evidence family above).

def test_protocol_declares_three_new_verbs_with_contract_annotations():
    expected = {
        "submit": ExecutionReceipt,
        "cancel_execution": CancelOutcome,
        "observe_execution": ExecutionObservation,
    }
    for name, ret in expected.items():
        method = getattr(TurnExecutionPort, name)
        annotation = inspect.signature(method).return_annotation
        assert annotation == ret.__name__ or annotation is ret, name
