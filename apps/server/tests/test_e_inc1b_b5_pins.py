"""E-INC1b b-5 pins landing with batch-β1 (N2 + N4).

Approved per-path by C in `approvals/INC1b-batch-E-approved.md` (21:19Z,
anchor `b15c435`): N2 stays in β1; N1 travels with β2 (b-4 confluence).

* N2 - the deleted bool shell was never a fact source, and after its removal
  nothing else may become one: the cancel receipts have exactly one writer,
  and a submit-replay scheduled inside the dispatch->receipt window (forced
  interleave per the P8 method - deterministic scheduling hooks, no stress
  loop) must answer from the same registered run, never minting a second
  cancellable source behind the shell's back.
* N4 - port-reply honesty characterization (approved as a pure green pin after
  the E-027 correction): `cancel_execution` classifies exactly four port
  answer shapes - truthy / explicit-False / None / raise (`accepted is None`
  precedes truthiness; a raise is laundered into the same None leg) - and each
  recorded answer is a permanent receipt. The port obligation ("cancel() must
  raise or answer falsy unless the host actually accepted the abort") stays
  C-HARNESS@v1 contract prose; E structurally cannot detect a lying truthy
  port, and this pin records that boundary rather than pretending otherwise.

Run (from `source/`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../tmp/venv/bin/python -m pytest tests/server/test_e_inc1b_b5_pins.py -q
"""
from __future__ import annotations

import ast
import inspect
import threading

from ordessa_server_compat.execution import SidecarExecutionBackend
from ordessa_server_compat.execution import sidecar_backend as sb_module
from ordessa_server_compat.execution.execution_contract import (
    CancelOutcome, ExecutionReceipt, ExecutionRequest, NeutralBinding,
    ObservationState,
)


def _request(key: str) -> ExecutionRequest:
    return ExecutionRequest(
        execution_key=key, bundle_ref="sha256:bundle",
        resource_bindings=(NeutralBinding("c.ws", "sha256:obj", "tok-1"),),
        capability_demand=frozenset({"cap.a"}),
        correlation={"anything": "caller-owned"},
    )


# ---------------------------------------------------------------------------
# N2 - single cancel fact source after the shell delete, forced interleaves.

def _public_cancel_surface(cls) -> list[str]:
    return [n for n in dir(cls)
            if "cancel" in n.lower() and not n.startswith("_")]


def test_cancel_answer_surface_collapses_to_exactly_one_public_verb():
    """The shell delete must leave ONE named cancel answer on the backend and
    one on the contract surface; a resurrected bool leg would show up here as
    a second name, not as a red window elsewhere."""
    assert _public_cancel_surface(SidecarExecutionBackend) == ["cancel_execution"]
    from ordessa_server_compat.execution import TurnExecutionPort
    assert _public_cancel_surface(TurnExecutionPort) == ["cancel_execution"]


def test_cancel_receipts_have_exactly_one_writing_function():
    """Structural single-source lock (per decisions/E2b-pin-amendments-ruling.md,
    MB-E2b equal-move): the ONLY receipt-ledger store lives inside the
    tracker's `cancel_execution` verb in ``pacthold.execution.lifecycle`` -
    the backend module's delegations, the replay and the submit paths are
    readers only, so no second writer can accumulate cancel facts outside
    the receipts' owning verb."""
    import pacthold.execution.lifecycle as lifecycle_module

    def writers_of(module, ledger_attr: str) -> set[str]:
        tree = ast.parse(inspect.getsource(module))
        found: set[str] = set()
        for outer in ast.walk(tree):
            if not isinstance(outer, ast.FunctionDef):
                continue
            for node in ast.walk(outer):
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Attribute)
                    and t.value.attr == ledger_attr
                    for t in node.targets
                ):
                    found.add(outer.name)
        return found

    assert writers_of(sb_module, "_cancel_receipts") == set()
    assert writers_of(lifecycle_module, "cancel_receipts") == {"cancel_execution"}
    # the tracker holds no store under the legacy private spelling either
    assert writers_of(lifecycle_module, "_cancel_receipts") == set()


class _GateLock:
    """Counting stand-in for the registry lock that runs a scheduling hook
    before every acquisition (P8 method: scheduled windows, never timing)."""

    def __init__(self, gate):
        self._inner = threading.Lock()
        self._counts: dict[str, int] = {}
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


class _CountingPort:
    def __init__(self):
        self.opens = 0
        self.cancel_calls = 0

    def open_execution(self, key):
        self.opens += 1
        return "native-n2"

    def cancel(self, key):
        self.cancel_calls += 1
        return True


def test_forced_interleave_submit_replay_in_receipt_gap_mints_no_second_source():
    """The submit-replay leg is scheduled into the historical gap between the
    cancel dispatch and the receipt store (holder parked at its 3rd registry
    acquisition). If a replay ever re-registered a cancellable run behind the
    receipts' back, the later cancel would reach the port a second time and
    `opens`/`cancel_calls` would move: the receipts' single source is what
    this schedules a proof for, not what a sleep loop would sample."""
    port = _CountingPort()
    backend = SidecarExecutionBackend(
        None, None, None, port_factory=lambda context, on_event: port,
    )
    receipt = backend.submit(_request("n2-key"))
    assert receipt.replayed is False

    in_gap = threading.Event()
    racer_done = threading.Event()

    def gate(name, count):
        if name == "MainThread" and count == 3:
            in_gap.set()
            assert racer_done.wait(5.0), "replay leg never completed in the gap"

    backend._lock = _GateLock(gate)
    racer: list = []

    def racer_thread():
        in_gap.wait(5.0)
        racer.append(backend.submit(_request("n2-key")))
        racer_done.set()

    thread = threading.Thread(target=racer_thread, name="replay-racer")
    thread.start()
    outcome = backend.cancel_execution("n2-key")
    thread.join(10)

    assert outcome is CancelOutcome.CONFIRMED_STOPPED
    replay = racer[0]
    assert isinstance(replay, ExecutionReceipt) and replay.replayed is True
    assert replay.dispatch_id == receipt.dispatch_id  # same registered run
    assert port.opens == 1  # the replay never reached a port at all
    assert backend._cancel_receipts["n2-key"] is CancelOutcome.CONFIRMED_STOPPED
    # one source answers after the interleave; no re-registration to answer from:
    assert backend.cancel_execution("n2-key") is CancelOutcome.CONFIRMED_STOPPED
    assert port.cancel_calls == 1


# ---------------------------------------------------------------------------
# N4 - pure characterization of the four port answer shapes (green pins).

class _ReplyPort:
    """Started run whose port answers cancel in exactly one configured shape."""

    def __init__(self, reply):
        self._reply = reply  # callable() -> truthy | falsy | None | raise
        self.cancel_calls = 0

    def open_execution(self, key):
        return "native-x18"

    def cancel(self, key):
        self.cancel_calls += 1
        return self._reply()


def _backend_with_started_run(reply):
    port = _ReplyPort(reply)
    backend = SidecarExecutionBackend(
        None, None, None, port_factory=lambda context, on_event: port,
    )
    receipt = backend.submit(_request("x18-key-1"))
    assert receipt.replayed is False
    return backend, port


def test_lying_truthy_port_makes_e_claim_a_stop_that_never_happened():
    """X18 ② transposed to E's boundary: a port whose cancel() answers truthily
    although the host never received the abort (driver swallowed HTTP 500).
    E structurally cannot tell - it records CONFIRMED_STOPPED permanently.
    Characterization, not a bug in E's classification: it pins WHY the port
    obligation belongs in C-HARNESS@v1 contract prose."""
    backend, port = _backend_with_started_run(lambda: True)
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.CONFIRMED_STOPPED
    assert port.cancel_calls == 1
    # terminal: a later correction of the lie cannot re-dispatch through E -
    # the receipt is the answer now. Honest ports only; E cannot save them.
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.CONFIRMED_STOPPED


def test_falsy_reply_is_recorded_as_no_active_run_even_though_the_run_is_live():
    """A provider that maps 'host busy / refused while running' to an explicit
    falsy reply makes E state REFUSED_NO_ACTIVE_RUN - a sentence about a
    DIFFERENT fact than the host reported - and records it permanently. The
    busy-raise below is the contract-correct port behavior for busy."""
    backend, port = _backend_with_started_run(lambda: False)
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.REFUSED_NO_ACTIVE_RUN
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.REFUSED_NO_ACTIVE_RUN
    assert port.cancel_calls == 1  # never re-dispatched (safety kept)...
    obs = backend.observe_execution("x18-key-1")
    assert obs.state is ObservationState.RUNNING  # ...but the run stayed live


def test_none_reply_reads_as_terminal_unknown_while_live():
    """The D-H18-adjacent shape (E-027 correction round): a bare None is its
    own branch - `accepted is None` precedes truthiness - and lands as the
    honest UNKNOWN, permanently recorded. Word-level contract duty ('None is
    never a stop') is already met by the classifier; what remains - the
    liveness cost of a terminal UNKNOWN for a transient answer loss - is the
    retriable-unknown symmetry question E-022 filed separately, NOT a
    classification change this batch may make."""
    backend, port = _backend_with_started_run(lambda: None)
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.UNKNOWN
    assert port.cancel_calls == 1
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.UNKNOWN
    assert port.cancel_calls == 1  # terminal: never re-dispatched
    obs = backend.observe_execution("x18-key-1")
    assert obs.state is ObservationState.RUNNING  # honest word, liveness gone


def test_raising_port_answers_unknown_honestly_but_bricks_retrials_by_design():
    """The by-design leg: transient exception -> UNKNOWN, recorded permanently
    ('never re-dispatched blindly'). Honest word, same liveness cost as the
    falsy and None legs: a busy timeout that the host would honor on retry can
    never be retried through E for this key."""
    def _busy():
        raise TimeoutError("host busy, abort not accepted (X18 ② shape, honest port)")

    backend, port = _backend_with_started_run(_busy)
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.UNKNOWN
    assert port.cancel_calls == 1
    assert backend.cancel_execution("x18-key-1") is CancelOutcome.UNKNOWN
    assert port.cancel_calls == 1  # terminal UNKNOWN: no second dispatch ever

    # Contrast with P8's NON-recording pre-port UNKNOWN: the ONLY UNKNOWN in
    # the design that keeps liveness, and it is exactly the one whose receipt
    # would have guarded a dispatch that never happened.


def test_four_reply_shapes_matrix_is_exhaustive_and_each_answer_is_permanent():
    """Shape lock for the attack surface: cancel_execution's classification has
    no fifth case - truthy / explicit-False / None / raise cover the port's
    whole answer space (raise laundered into the None leg), and all three
    recorded outcomes are replay-stable receipts."""
    for reply, expected in [
        (lambda: True, CancelOutcome.CONFIRMED_STOPPED),
        (lambda: False, CancelOutcome.REFUSED_NO_ACTIVE_RUN),
        (lambda: None, CancelOutcome.UNKNOWN),
        (lambda: (_ for _ in ()).throw(RuntimeError("lost")), CancelOutcome.UNKNOWN),
    ]:
        backend, port = _backend_with_started_run(reply)
        assert backend.cancel_execution("x18-key-1") is expected, reply
        assert backend.cancel_execution("x18-key-1") is expected
        assert port.cancel_calls == 1
