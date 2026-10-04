"""Product-level crash recovery for the Agent reliable-submission boundary.

The child runs the real Server product, wire registry, Agent journal and
Environment store. Only the native submit edge is the SQLite-backed
controlled fixture. A SIGKILL at each durable boundary exercises OS data-root
ownership and same-request query recovery without restarting with a copied
SQL writer token.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "scripts" / "packaging"
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))

from controlled_native_fixture import (  # noqa: E402
    ControlledNativeFixture,
    controlled_product_composition,
    test_protected_fingerprint as _test_fingerprint_fixture,
)


TARGET_LOCATION = {
    "kind": "draft",
    "connectionId": "crash-controlled-connection",
    "draftId": "crash-controlled-draft",
}
SUBMISSION_ID = "product-crash-stable-submission"


def _runtime(data_root: Path, native: ControlledNativeFixture):
    composition = controlled_product_composition(
        native_submit_port=native,
        fingerprint_port=_test_fingerprint_fixture(),
    )
    return composition.default_runtime(data_root, include_profile=False)


def _wait_for_checkpoint(process: subprocess.Popen, checkpoint: Path, stderr: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if checkpoint.exists():
            return
        if process.poll() is not None:
            detail = stderr.read_text(encoding="utf-8", errors="replace") if stderr.exists() else ""
            raise AssertionError(f"crash worker exited before checkpoint ({process.returncode}): {detail}")
        time.sleep(0.025)
    raise AssertionError("crash worker did not reach the requested durable boundary")


@pytest.mark.parametrize(
    ("boundary", "expected_stage", "expected_effects"),
    [
        ("mapping", "mapped", 0),
        ("possibly_submitted", "possibly-submitted", 0),
        ("backend_intent", "possibly-submitted", 0),
        ("native_effect", "possibly-submitted", 1),
        ("domain_result", "completed", 1),
    ],
)
def test_product_sigkill_reopens_only_after_os_owner_and_queries_without_redispatch(
    tmp_path: Path, boundary: str, expected_stage: str, expected_effects: int,
):
    data_root = tmp_path / "server-data"
    effects_db = tmp_path / "controlled-native-effects.sqlite"
    checkpoint = tmp_path / "worker-at-boundary"
    stderr = tmp_path / "worker.stderr"

    # The isolated worker process runs actual product composition and wire.
    # Its only test instrumentation pauses after the named durable boundary;
    # the parent then sends SIGKILL, so no Python cleanup can release locks or
    # close SQLite stores on the worker's behalf.
    worker = r'''
import json, os, sys, time
from pathlib import Path
root, effects, checkpoint, boundary = map(Path, sys.argv[1:5])
boundary = str(boundary)
sys.path.insert(0, str(root / "scripts" / "packaging"))
from controlled_native_fixture import ControlledNativeFixture, controlled_product_composition, test_protected_fingerprint
from ordessa_agent.submission_journal import SubmissionJournal

def pause_here():
    checkpoint.write_text(boundary, encoding="ascii")
    while True:
        time.sleep(30)

if boundary == "mapping":
    original = SubmissionJournal.capture
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        pause_here()
        return result
    SubmissionJournal.capture = wrapped
elif boundary == "possibly_submitted":
    original = SubmissionJournal.mark_possibly_submitted
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        pause_here()
        return result
    SubmissionJournal.mark_possibly_submitted = wrapped
elif boundary == "backend_intent":
    from ordessa_persistence_sqlite import SqliteStorePort
    original = SqliteStorePort.claim_dispatch
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        pause_here()
        return result
    SqliteStorePort.claim_dispatch = wrapped
elif boundary == "native_effect":
    original = ControlledNativeFixture.submit_existing
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        pause_here()
        return result
    ControlledNativeFixture.submit_existing = wrapped
elif boundary == "domain_result":
    original = SubmissionJournal.record_completed
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        pause_here()
        return result
    SubmissionJournal.record_completed = wrapped
else:
    raise AssertionError("unknown crash boundary")

native = ControlledNativeFixture(effects, mode="existing")
composition = controlled_product_composition(
    native_submit_port=native,
    fingerprint_port=test_protected_fingerprint(),
)
runtime = composition.default_runtime(root, include_profile=False)
runtime.start()
resolved = runtime.wire.dispatch("agent.session.resolve", {"location": {
    "kind": "draft", "connectionId": "crash-controlled-connection",
    "draftId": "crash-controlled-draft",
}})
target = resolved["target"]
native.bind_backend_target(target)
runtime.wire.dispatch("agent.submitInput", {
    "target": target,
    "draftRevision": 1,
    "capture": {
        "submissionId": "product-crash-stable-submission",
        "draft": {"draftId": "crash-controlled-draft", "draftRevision": 1,
                  "text": "crash recovery request", "attachmentIds": []},
        "configOperationIds": [], "schema": "agent-input/v1", "mode": "existing",
    },
})
raise AssertionError("worker unexpectedly passed the requested crash boundary")
'''
    env = os.environ.copy()
    inherited_paths = [item for item in sys.path if item]
    if env.get("PYTHONPATH"):
        inherited_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(inherited_paths))
    with stderr.open("wb") as error_stream:
        process = subprocess.Popen(
            [sys.executable, "-c", worker, str(data_root), str(effects_db),
             str(checkpoint), boundary],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=error_stream,
        )
        try:
            _wait_for_checkpoint(process, checkpoint, stderr)

            # A second live product writer is refused by the real OS lock;
            # it cannot use a SQL token or matching process-local identity to
            # join the active writer.
            native_for_refusal = ControlledNativeFixture(effects_db, mode="existing")
            with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
                _runtime(data_root, native_for_refusal)

            process.kill()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    native = ControlledNativeFixture(effects_db, mode="existing")
    recovered = _runtime(data_root, native)
    try:
        # build_runtime takes the OS data-root lock before Environment or
        # domain stores may claim a stale SQL writer marker.
        recovered.start()
        target = recovered.wire.dispatch("agent.session.resolve", {"location": TARGET_LOCATION})["target"]
        native.bind_backend_target(target)
        query = recovered.wire.dispatch("agent.submission.query", {
            "target": target, "submissionId": SUBMISSION_ID,
        })
        assert query["submissionId"] == SUBMISSION_ID
        assert query["resend"] is False
        assert query["outcome"] == ("accepted" if expected_effects else "unknown")
        effect_counts = native.all_effect_counts()
        assert sum(effect_counts.values()) == expected_effects
        assert len(effect_counts) == expected_effects
        if expected_effects:
            assert {key[2] for key in effect_counts} == {SUBMISSION_ID}

        # Verify the journal reached exactly the intended durable window.
        import sqlite3
        with sqlite3.connect(data_root / "plugins" / "agent" / "submissions.sqlite") as connection:
            rows = connection.execute(
                "SELECT stage FROM agent_submission_journal WHERE request_id=?",
                (SUBMISSION_ID,),
            ).fetchall()
        assert rows == [(expected_stage,)]
        assert native.all_effect_counts() == effect_counts

        # A read-only query must leave the native edge untouched.
        before = native.all_effect_counts()
        repeated = recovered.wire.dispatch("agent.submission.query", {
            "target": target, "submissionId": SUBMISSION_ID,
        })
        assert repeated["outcome"] == query["outcome"]
        assert repeated["resend"] is False
        assert native.all_effect_counts() == before
    finally:
        recovered.stop()
