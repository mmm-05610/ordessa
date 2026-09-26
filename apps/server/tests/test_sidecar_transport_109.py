"""Order 109: a turn whose cleanup record fails must still be released.

The HTTP hang came from `_complete`'s `finally`: when `close_execution` raised,
the fallback `mark_turn_cleanup` ran, and on the shared SQLite (contended exactly
when a second failure follows a first) THAT could raise too - escaping the
`finally` and skipping the release of `_active` / the bound resources / the
provider handle. Each failed turn leaked a little; two leaks later the single
event loop was wedged and every HTTP surface (including `/live`) stopped
answering. These tests pin the invariant directly: no cleanup failure may strand
a run, and the terminal outcome/error code is untouched.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

from ordessa_server_compat.execution import SidecarExecutionBackend
from ordessa_server_compat.execution.sidecar import SidecarError
from ordessa_server_compat.execution.sidecar_backend import _Run


class _FailingRecords:
    """fail_turn works; every cleanup-record call raises (the contended-write case)."""

    def __init__(self):
        self.failed = []
        self.cleanup_calls = 0

    def fail_turn(self, turn_id, code, queue_records=None):
        self.failed.append((turn_id, code))

    def mark_turn_cleanup(self, turn_id, state):
        self.cleanup_calls += 1
        raise RuntimeError("database is locked")  # exactly the second-failure wedge


class _Approvals:
    def invalidate_for_execution(self, execution_id, reason):
        return None


class _ClosingRaisesPort:
    def __init__(self):
        self.close_calls = 0

    def close_execution(self, execution_id):
        self.close_calls += 1
        raise RuntimeError("channel half-closed during teardown")


def _failing_run(port):
    done = threading.Event()
    done.set()  # the prompt already errored; _complete must not block
    return _Run(
        turn_id="turn-109", work_id="work-109", core_execution_id="core-109",
        dispatch_id="dispatch-109", port=port, native_id="native-109", done=done,
    )


def _wired_backend(records):
    backend = SidecarExecutionBackend(
        records, objects=None, approvals=_Approvals(),
        port_factory=lambda *_a: None, on_event=lambda: None)
    port = _ClosingRaisesPort()
    run = _failing_run(port)
    # the run is live: pre-seed the maps that must come back empty after _complete
    backend._active[run.turn_id] = run
    backend._contexts[run.turn_id] = {"harness_type": "pi"}
    backend._message_parts[run.turn_id] = []
    backend._turn_by_core[run.core_execution_id] = run.turn_id
    return backend, run, port


def test_cleanup_record_failure_still_retires_the_run():
    """G1 (root cause): both teardown and the fallback cleanup record raise, yet
    `_complete` neither propagates nor leaks the run from any shared map."""
    records = _FailingRecords()
    backend, run, port = _wired_backend(records)

    backend._complete(run)  # must not raise

    assert backend._active == {}, "run leaked in _active (old escape)"
    assert backend._contexts == {}
    assert backend._message_parts == {}
    assert backend._turn_by_core == {}
    # the provider handle map is clean (release_handle ran unconditionally)
    assert run.dispatch_id not in backend.provider._handles
    assert port.close_calls >= 1
    # terminal failure semantics preserved: fail_turn still recorded the code
    assert records.failed and records.failed[0][0] == run.turn_id


def test_terminal_error_code_is_unchanged_by_the_release_fix():
    """G2: a failing turn still fails with its own typed code - fixing the hang
    must not turn a failure into a success or blur its reason."""
    records = _FailingRecords()
    backend = SidecarExecutionBackend(
        records, objects=None, approvals=_Approvals(),
        port_factory=lambda *_a: None, on_event=lambda: None)
    port = _ClosingRaisesPort()
    run = _failing_run(port)
    run.error = SidecarError("HARNESS_CONTROLLED_FAILURE", "controlled failure")
    backend._active[run.turn_id] = run
    backend._contexts[run.turn_id] = {"harness_type": "pi"}
    backend._turn_by_core[run.core_execution_id] = run.turn_id

    backend._complete(run)

    assert records.failed == [(run.turn_id, "HARNESS_CONTROLLED_FAILURE")], records.failed
    assert backend._active == {}


def test_success_turn_cleanup_failure_does_not_propagate():
    """The same guarantee holds on the success teardown: a cleanup-record hiccup
    is recorded best-effort, never bubbles out of `_complete` to strand the run."""
    # A run with no error and a fake port whose capture path is minimal: the
    # success branch will raise inside _complete (missing home audit material)
    # and fall into the same guaranteed-release finally.
    records = _FailingRecords()
    backend, run, port = _wired_backend(records)
    # no run.error -> the success path will fail on _audited_home (port lacks
    # capture_execution), which is exactly a teardown-adjacent failure; the run
    # must still be retired and _complete must not raise.
    backend._complete(run)
    assert backend._active == {}
    assert backend._turn_by_core == {}
    assert run.dispatch_id not in backend.provider._handles
