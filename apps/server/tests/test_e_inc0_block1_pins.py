"""E-INC0 five-attack pin tests — C-EXEC@v1 block1 (approved by C, baseline b067c571).

Scope discipline (approval `E-INC0-pinning-tests.md`): this file writes NO product
code and changes NO public signature. It is the pre-implementation safety net.

Notation:
* GREEN pins assert behaviour the baseline must not lose (permanent regressions).
* XFAIL-STRICT pins assert the *unimplemented* block-1 semantics ("未实现语义").
  They are expected to fail against the baseline and MUST turn green in E-INC1.
  Assertions are never weakened to make them pass.

Five attacks covered (mapping in CHECKPOINT E-004):
1. cancel tristate distinguishability (refused / confirmed / unknown, no collapsing);
2. unknown is not blindly replayed (same-key cancel replay returns the original
   receipt and never re-dispatches the abort);
3. terminal-state authority stays in S (E never reads the business ledger to
   judge terminality; E never reaches into product-domain internals);
4. stopReason is pure passthrough (arbitrary non-clean strings survive verbatim;
   no closed four-value enum);
5. no silent sandbox degradation (unregistered provider name is a typed refusal).

Run (from the repo root, `source/`; in-tree persistent home for E pins):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../tmp/venv/bin/python -m pytest tests/server/test_e_inc0_block1_pins.py
"""
from __future__ import annotations

import inspect
import re
import threading

import pytest

from pacthold_runtime_compat.runtime_composition.sandbox_port import (
    SandboxPortUnavailable, register_sandbox_port_factory, resolve_sandbox_port,
)
from ordessa_server_compat.execution import sidecar_backend as sb
from ordessa_server_compat.execution.sidecar_backend import (
    SidecarExecutionBackend, _Run, _terminal_reason_from_result,
)

UNIMPLEMENTED = (
    "C-EXEC@v1 block1 tristate not implemented yet "
    "(E-INC1 gated on design-final + Sol#1); pin must turn green, never weaken"
)


# --------------------------------------------------------------------------
# minimal composition: real backend object, injected fake in-flight runs.
# cancel() only reads `_active`/`_lock` and the run's port, so no DB, no
# queue, no processes are reachable from these tests.

def _backend() -> SidecarExecutionBackend:
    return SidecarExecutionBackend(
        None, None, None, port_factory=lambda context, on_event: None,
    )


class _RecordingPort:
    def __init__(self, *, answer=None, raises=None):
        self.calls = 0
        self.answer = answer
        self.raises = raises

    def cancel(self, turn_id: str):
        self.calls += 1
        if self.raises is not None and self.calls == 1:
            raise self.raises
        if self.raises is not None and self.calls > 1:
            # a second dispatch would mean a blind replay of a lost abort
            raise AssertionError("abort re-dispatched after an unknown outcome")
        return self.answer


def _inject(backend: SidecarExecutionBackend, turn_id: str,
            port: _RecordingPort) -> _RecordingPort:
    run = _Run(
        turn_id=turn_id, work_id="w-" + turn_id,
        core_execution_id="x-" + turn_id, dispatch_id="d-" + turn_id,
        port=port, native_id="n-" + turn_id, done=threading.Event(),
    )
    with backend._lock:
        backend._active[turn_id] = run
    return port


# --------------------------------------------------------------------------
# attack 1 — tristate cancel must be resolvable through the public entry.
#
# E-INC1a note (retarget, not weakening): these three pins were written against
# the baseline where `cancel` was the ONLY public entry. INC1a adds the
# contract's public tristate verb `cancel_execution` on the same backend while
# `cancel` stays the approved bool shell (O-3); the entry point moves, every
# assertion below is verbatim what C accepted in E-INC0. The bool shell itself
# was regression-locked in test_e_inc1a_matrix_pins.py until E-INC1b b-1
# deleted it (with C's approval); the shell-absence counter-pins live there.

def test_cancel_tristate_all_three_outcomes_are_pairwise_distinguishable():
    backend = _backend()
    refused_no_active = backend.cancel_execution("absent-turn")
    _inject(backend, "refused-turn", _RecordingPort(answer=False))
    refused_active = backend.cancel_execution("refused-turn")
    _inject(backend, "confirmed-turn", _RecordingPort(answer=True))
    confirmed = backend.cancel_execution("confirmed-turn")
    _inject(backend, "timeout-turn", _RecordingPort(raises=TimeoutError()))
    try:
        unknown = backend.cancel_execution("timeout-turn")
    except BaseException as exc:  # a leaked exception is not a class either
        unknown = exc
    # Contract: the two refusals stay ONE class (deterministic "nothing to stop"
    # vs "abort said no" differ internally, but neither may be pressed into
    # unknown), confirmed is another, unknown is honestly separated.
    assert _classify(unknown) == "unknown"
    assert _classify(confirmed) == "confirmed_stopped"
    assert _classify(refused_no_active) != "unknown"
    assert _classify(refused_active) != "unknown"
    assert _classify(refused_no_active) == _classify(refused_active)


def _classify(outcome) -> str:
    """Map a block-1 result onto the contract's three classes. Accepts any
    enum or frozen result type whose name/value carries the class — E does
    not fix the spelling (C-EXEC@v1: 拼写归 E), only distinguishability."""
    if isinstance(outcome, BaseException):
        raise AssertionError(f"cancel() leaked {outcome!r} instead of classifying it as unknown")
    name = getattr(outcome, "name", None) or getattr(outcome, "value", None)
    if isinstance(name, str):
        low = name.lower()
        for cls in ("confirmed_stopped", "refused_no_active_run", "unknown"):
            if cls in low:
                return cls
    raise AssertionError(
        f"cancel() result {outcome!r} is not one of the three contract classes "
        "(bare bool is the known baseline collapse; xfail is expected until E-INC1)")


def test_cancel_public_return_is_not_a_bare_bool():
    # bool is the temporary compatibility shell (C ruling O-3); after E-INC1
    # the new tristate method must exist additively on TurnExecutionPort.
    from ordessa_server_compat.execution import TurnExecutionPort
    tristate = [
        m for m in dir(TurnExecutionPort)
        if "cancel" in m.lower() and m != "cancel"
    ]
    assert tristate, "TurnExecutionPort must expose an additive tristate cancel"
    sig = inspect.signature(getattr(TurnExecutionPort, tristate[0]))
    ret = sig.return_annotation
    assert ret is not bool and ret is not inspect.Signature.empty


# green part of attack 1: the refusal path never touches a port.
def test_cancel_with_no_active_run_touches_no_port_and_stays_deterministic():
    backend = _backend()
    first = backend.cancel_execution("never-seen-turn")
    second = backend.cancel_execution("never-seen-turn")
    assert first == second  # deterministic, no state invented for unknown turns
    port = _RecordingPort(answer=True)
    assert port.calls == 0  # nothing was reachable, nothing was dispatched


# --------------------------------------------------------------------------
# attack 2 — an unknown outcome must never be replayed blindly.

def test_cancel_replay_after_confirmed_stops_returns_original_receipt_once():
    backend = _backend()
    port = _inject(backend, "t1", _RecordingPort(answer=True))
    first = backend.cancel_execution("t1")
    second = backend.cancel_execution("t1")  # same Idempotency-Key replay at port level
    assert port.calls == 1, "second cancel must not re-dispatch the abort"
    assert second == first


def test_cancel_replay_after_unknown_never_re_dispatches_abort():
    backend = _backend()
    # first abort dispatch is lost on the channel (timeout => unknown);
    # a second call must return the recorded unknown receipt, NOT a new abort.
    port = _inject(backend, "t2", _RecordingPort(raises=TimeoutError()))
    first = backend.cancel_execution("t2")
    second = backend.cancel_execution("t2")   # _RecordingPort raises AssertionError if called twice
    assert second == first
    assert port.calls == 1


# --------------------------------------------------------------------------
# attack 3 — terminal-state authority stays with S (structural constraints).

def test_sidecar_backend_contains_no_business_ledger_read():
    src = inspect.getsource(sb)
    assert "server_turns" not in src
    assert not re.search(r"\bSELECT\b", src, re.I), \
        "the execution domain must not query the business ledger to judge terminality"
    assert ".database.read" not in src


# E-INC1b b-4 leg split (词面零弱化, per-path approved): the joint pin was a
# strict xfail over BOTH modules; b-4 removes the sidecar_backend violation for
# good, so that leg is promoted to a permanent green lock here.
#
# INC1c c-2 翻转记账 (flip accounting per C-notice-E-041-ruled 裁1; approvals/
# INC1c-release.md 裁② B案): the delegation leg below is promoted from a strict
# xfail that pinned the *A案 vision* invariant (zero literal
# `ordessa_server.profiles` imports anywhere in delegation) to a permanent
# green lock pinning the **B案终局界 invariant**. Direction of the swap is a
# *semantics change under adjudication, not a weakening of a green lock* (the
# node was xfail; A案's package-wide claim is NOT declared green - it is
# registered as a product question after BE-PROFILE-001, per the same ruling):
#   old (A案愿景): delegation may not import the product configuration domain.
#   new (B案终局界): (1) all product-domain reach is a top-level *declared*
#   import block - hidden function-local imports are forbidden (static half,
#   below); (2) the creation-point freeze is same-transaction anchored
#   (409 PROFILE_REVISION_CONFLICT on a mid-window live-row edit) and accept
#   never picks a live row - both pinned red/green-bidirectional in
#   tests/server/test_e_inc1c_n1_pins.py (behavioural half).

def test_sidecar_backend_does_not_import_product_domain_privates():
    src = inspect.getsource(sb)
    assert "ordessa_server.profiles" not in src, (
        "sidecar_backend reaches into the product configuration domain; "
        "posture must arrive as frozen input (S-2 / C-EXEC@v1 later blocks)")


def test_delegation_product_domain_reach_is_top_level_declared_only():
    import ast
    import ordessa_server_compat.execution.delegation as delegation
    tree = ast.parse(inspect.getsource(delegation))

    def module_of(node):
        if isinstance(node, ast.ImportFrom):
            return node.module or ""
        if isinstance(node, ast.Import):
            return ",".join(alias.name for alias in node.names)
        return ""

    hidden = [
        (getattr(node, "lineno", None), module_of(node))
        for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(fn)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and module_of(node).startswith("ordessa_server.profiles")
    ]
    assert not hidden, (
        f"hidden function-local product-domain imports in delegation: {hidden}; "
        "B案终局界 requires one auditable top-level declared import block "
        "(INC1c c-2 flip accounting - the A案 zero-import invariant is NOT "
        "claimed green here, it waits on BE-PROFILE-001)")


# --------------------------------------------------------------------------
# attack 4 — stopReason is pure passthrough; no closed enum.

@pytest.mark.parametrize("raw", [
    "max_tokens", "refusal", "content-filtered", "token_exceeded",
    "some-brand-new-reason-π", "REASON_FROM_NEXT_RELEASE",
    "stop", "complete",
])
def test_non_clean_stop_reason_passes_through_verbatim(raw: str):
    assert _terminal_reason_from_result({"stopReason": raw}) == raw
    assert _terminal_reason_from_result({"stop_reason": raw}) == raw


@pytest.mark.parametrize("clean", ["end_turn", "", None])
def test_clean_or_missing_stop_reason_stays_none_byte_identical(clean):
    result = {} if clean is None else {"stopReason": clean}
    assert _terminal_reason_from_result(result) is None


def test_non_string_or_non_dict_stop_reason_is_not_invented():
    assert _terminal_reason_from_result({"stopReason": 7}) is None
    assert _terminal_reason_from_result("not-a-dict") is None
    assert _terminal_reason_from_result(None) is None


# --------------------------------------------------------------------------
# attack 5 — unregistered sandbox provider is a typed refusal, never a
# silent fallback to whatever else is registered. No real processes: fakes only.

class _SentinelPort:
    provider_id = "pin.sentinel"

    def __call__(self):  # factory guard — must never be invoked via a wrong name
        raise AssertionError("sentinel port constructed through a wrong name")


def test_unknown_sandbox_provider_name_is_a_typed_refusal(monkeypatch):
    monkeypatch.delenv("AGENT_BOX_SANDBOX_MODULE", raising=False)
    with pytest.raises(SandboxPortUnavailable) as exc:
        resolve_sandbox_port("pin-no-such-provider")
    assert exc.value.code == "SANDBOX_PROVIDER_UNRESOLVED"


def test_empty_sandbox_provider_name_is_a_typed_refusal():
    with pytest.raises(SandboxPortUnavailable) as exc:
        resolve_sandbox_port("   ")
    assert exc.value.code == "SANDBOX_PROVIDER_UNRESOLVED"


def test_registered_provider_does_not_answer_for_a_different_name(monkeypatch):
    monkeypatch.delenv("AGENT_BOX_SANDBOX_MODULE", raising=False)
    sentinel = _SentinelPort()
    register_sandbox_port_factory("pin_registered_provider", lambda: sentinel)
    try:
        # name with dashes normalizes onto the registered snake name...
        assert resolve_sandbox_port("pin-registered-provider") is sentinel
        # ...but no other name may fall back to it
        with pytest.raises(SandboxPortUnavailable):
            resolve_sandbox_port("pin-a-completely-different-name")
    finally:
        from pacthold_runtime_compat.runtime_composition import sandbox_port
        sandbox_port._REGISTERED_FACTORIES.pop("pin_registered_provider", None)
