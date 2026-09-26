"""MB-E2b modular lifecycle pins — neutral coordination ledger, single implementation.

Approval `MB-E2b-lifecycle-release.md` (baseline 0c042f54): the neutral run
bookkeeping (`NeutralRun`, key claim/release/replay, the tristate cancel state
machine, observation classification, evidence append) and the per-library
first-run lock live exactly once in ``pacthold.execution``; the historical
``ordessa_server.execution`` entries are thin one-way delegations, module
aliases onto the SAME ledger objects and lock, and same-object re-exports.
These pins lock the equal-move:

* identity — `_NeutralRun`/`first_run_gate`/lock classes and constants are the
  same objects through old and new entries;
* single implementation — an AST walk finds each moved definition exactly
  once, in the new package only; the old carriers hold no second definition
  and (for the cancel receipts) no second writer outside the tracker;
* alias, not copy — `backend._neutral_runs is backend._lifecycle.runs` (and
  the receipt ledger, the active-run ledger and the shared lock likewise);
* dependency direction — the new lifecycle/first_run_lock modules import
  nothing outside the standard library and ``pacthold.execution.*``;
* behaviour — the tracker's own verbs keep the block-1 semantics (replay,
  refusal release, tristate cancel, opaque business runs through the same
  machine).

Run (from this task tree root, `work/e2b/`):
    PYTHONPATH=src:$(ls -d plugins/*/src | paste -sd:) \
    ../../tmp/venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/server/test_e_modular_execution_lifecycle.py
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import threading
from pathlib import Path
from typing import Any

import pacthold.execution.first_run_lock as new_lock
import pacthold.execution.lifecycle as lifecycle
import ordessa_server_compat.execution.first_run_lock as old_lock
import ordessa_server_compat.execution.sidecar_backend as sb_module
from pacthold.execution.contracts import (
    CancelOutcome, EvidenceClass, ExecutionRequest, NeutralBinding,
    ObservationState,
)
from ordessa_server_compat.execution import SidecarExecutionBackend

STDLIB_ALLOWED_ROOTS = frozenset({
    "__future__", "dataclasses", "datetime", "enum", "threading", "types",
    "typing", "uuid",
})


def _module_path(module: object) -> Path:
    return Path(getattr(module, "__file__")).resolve()  # type: ignore[attr-defined]


def _class_defs(path: Path) -> list[str]:
    return [
        node.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    ]


def _receipt_writers(path: Path, ledger_attr: str) -> set[str]:
    """Function names containing a ``<ledger_attr>[...] = ...`` store."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    writers: set[str] = set()
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.FunctionDef):
            continue
        for node in ast.walk(outer):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == ledger_attr
                for target in node.targets
            ):
                writers.add(outer.name)
    return writers


def _backend() -> SidecarExecutionBackend:
    return SidecarExecutionBackend(
        None, None, None, port_factory=lambda context, on_event: None,
    )


def _request(key: str) -> ExecutionRequest:
    return ExecutionRequest(
        execution_key=key, bundle_ref="sha256:bundle",
        resource_bindings=(NeutralBinding("c.ws", "sha256:obj", "tok-1"),),
        correlation={"anything": "caller-owned"},
    )


class _Port:
    def __init__(self) -> None:
        self.opens = 0
        self.cancels = 0

    def open_execution(self, key: str) -> str:
        self.opens += 1
        return "native-1"

    def cancel(self, key: str) -> bool:
        self.cancels += 1
        return True


# --- identity ---------------------------------------------------------------

def test_first_run_lock_reexports_same_objects() -> None:
    assert old_lock.first_run_gate is new_lock.first_run_gate
    assert old_lock.FirstRunGate is new_lock.FirstRunGate
    assert old_lock.FirstRunLockTimeout is new_lock.FirstRunLockTimeout
    assert old_lock.FIRST_RUN_WAIT_SECONDS is new_lock.FIRST_RUN_WAIT_SECONDS
    # the gate is one process-wide singleton whichever entry built it
    assert old_lock.first_run_gate() is new_lock.first_run_gate()


def test_neutral_run_same_object_through_backend_module() -> None:
    assert sb_module._NeutralRun is lifecycle.NeutralRun


# --- single implementation --------------------------------------------------

def test_first_run_lock_definitions_live_once() -> None:
    assert sorted(_class_defs(_module_path(new_lock))) == [
        "FirstRunGate", "FirstRunLockTimeout", "_Hold",
    ]
    # the old path is a pure re-export carrier: no class definitions at all
    assert _class_defs(_module_path(old_lock)) == []


def test_lifecycle_definitions_live_once() -> None:
    defs = _class_defs(_module_path(lifecycle))
    assert defs.count("NeutralRun") == 1
    assert defs.count("NeutralRunTracker") == 1
    # the adapter module holds no second definition of the moved shapes
    sb_defs = _class_defs(_module_path(sb_module))
    for name in ("NeutralRun", "NeutralRunTracker", "FirstRunGate",
                 "FirstRunLockTimeout"):
        assert name not in sb_defs, name


def test_cancel_receipts_single_writer_is_the_tracker_verb() -> None:
    # The b5 single-source invariant, pinned at its new home: the ONLY
    # receipt-ledger store lives in lifecycle.cancel_execution, and the
    # adapter module has none (its delegations are readers).
    assert _receipt_writers(_module_path(lifecycle), "cancel_receipts") == {
        "cancel_execution",
    }
    assert _receipt_writers(_module_path(lifecycle), "_cancel_receipts") == set()
    assert _receipt_writers(_module_path(sb_module), "_cancel_receipts") == set()


# --- alias, not copy --------------------------------------------------------

def test_backend_ledgers_and_lock_are_aliases() -> None:
    backend = _backend()
    assert backend._neutral_runs is backend._lifecycle.runs
    assert backend._cancel_receipts is backend._lifecycle.cancel_receipts
    assert backend._active is backend._lifecycle.active_runs
    assert backend._lock is backend._lifecycle.lock
    # a mutation through the historical attribute is the tracker's ledger
    backend._neutral_runs["alias-key"] = lifecycle.NeutralRun(
        execution_key="alias-key", dispatch_id="neutral:x", port=None)
    assert "alias-key" in backend._lifecycle.runs


# --- dependency direction ---------------------------------------------------

def test_new_lifecycle_modules_import_stdlib_and_self_only() -> None:
    offenders: list[str] = []
    for module in (lifecycle, new_lock):
        path = _module_path(module)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in STDLIB_ALLOWED_ROOTS:
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name.split(".")[0] not in STDLIB_ALLOWED_ROOTS and not (
                    module_name == "pacthold.execution"
                    or module_name.startswith("pacthold.execution.")
                ):
                    offenders.append(f"{path.name}: from {module_name}")
    assert offenders == []


# --- value surface ----------------------------------------------------------

def test_neutral_run_field_surface_unchanged() -> None:
    assert [field.name for field in dataclasses.fields(lifecycle.NeutralRun)] == [
        "execution_key", "dispatch_id", "port", "native_id", "created_at",
        "cancel_lock", "cancel_confirmed", "start_uncertain", "evidence",
    ]


# --- behaviour through the single machine -----------------------------------

def test_tracker_submit_replay_and_receipts() -> None:
    backend = _backend()
    port = _Port()
    backend.port_factory = lambda context, on_event: port
    first = backend.submit(_request("life-key"))
    assert first.replayed is False
    assert first.dispatch_id.startswith("neutral:")
    replay = backend.submit(_request("life-key"))
    assert replay.replayed is True
    assert replay.dispatch_id == first.dispatch_id
    assert port.opens == 1  # a replay never re-dispatches the start
    assert backend.cancel_execution("life-key") is CancelOutcome.CONFIRMED_STOPPED
    assert backend.cancel_execution("life-key") is CancelOutcome.CONFIRMED_STOPPED
    assert port.cancels == 1  # the receipt guards the second abort
    observation = backend.observe_execution("life-key")
    assert observation.state is ObservationState.STOPPED_CONFIRMED
    assert observation.evidence is EvidenceClass.CANCEL_CONFIRMATION


def test_tracker_typed_refusal_releases_the_claim() -> None:
    backend = _backend()

    def refusing_factory(context, on_event):
        raise RuntimeError("typed refusal before any seam")

    backend.port_factory = refusing_factory
    try:
        backend.submit(_request("refused-key"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("the refusal must propagate")
    # nothing was dispatched: the key is honestly absent again
    assert "refused-key" not in backend._neutral_runs
    assert backend.observe_execution("refused-key").state is ObservationState.NOT_KNOWN_TO_E


def test_business_run_flows_through_the_same_cancel_machine() -> None:
    backend = _backend()
    port = _Port()
    run = sb_module._Run(
        turn_id="biz-key", work_id="w", core_execution_id="x",
        dispatch_id="d", port=port, native_id="n", done=threading.Event(),
    )
    with backend._lock:
        backend._active["biz-key"] = run
    assert backend.cancel_execution("biz-key") is CancelOutcome.CONFIRMED_STOPPED
    assert run.cancel_confirmed is True
    assert port.cancels == 1
    # the same machine answers the replay from the receipts ledger
    assert backend.cancel_execution("biz-key") is CancelOutcome.CONFIRMED_STOPPED
    assert port.cancels == 1
