"""T013 C2 regressions for the Agent-owned durable submission mapping.

The subprocess fixture keeps the domain journal and Environment StorePort in
different SQLite files, then is killed at each side of the cross-store
handshake. Recovery is read-only and must never repeat the Harness effect.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ordessa_environment_api import RequestKey


def _request() -> RequestKey:
    return RequestKey(
        environment_namespace="env-a",
        principal_scope="user:local:closeout",
        request_id="req-closeout-1",
        comparison={"target": "session:S1", "binding": "binding:g1"},
    )


def _capture(text: str = "captured text"):
    return {
        "draftId": "draft-1",
        "draftRevision": 7,
        "text": text,
        "configOperationIds": ["op-model-3"],
        "baseRevision": "native-r4",
        "target": {"logical": "session:S1", "generation": 1},
        "binding": {"native": "instance-1", "generation": 2},
        "schema": "agent-input/v1",
        "guarantee": "reliable",
    }


def _capabilities():
    from ordessa_agent.submission_journal import ReliableCapabilities

    return ReliableCapabilities(
        backend_durable=True,
        conditional_submit=True,
        immutable_attachments=True,
    )


def _fingerprint():
    from ordessa_persistence_sqlite import ProtectedFingerprintHmac

    return ProtectedFingerprintHmac(
        {"fixture-key": b"fixture-only-key"}, active_key_id="fixture-key",
    )


def test_capture_freezes_attachment_bytes_and_same_key_digest(tmp_path):
    from ordessa_agent.submission_journal import SubmissionJournal
    from ordessa_persistence_sqlite import SqliteStorePort

    attachment = bytearray(b"original attachment")
    store = SqliteStorePort(tmp_path / "domain.sqlite", writer_token="domain-test")
    journal = SubmissionJournal(store, fingerprint_port=_fingerprint())
    capture = _capture()
    record = journal.capture(
        _request(), capture,
        attachments={"report.bin": attachment},
        capabilities=_capabilities(),
    )
    digest = record.digest

    attachment[:] = b"mutated attachment"
    capture["text"] = "edited after capture"
    persisted = journal.read(_request())

    assert persisted is not None
    assert persisted.digest == digest == record.digest
    assert persisted.attachments["report.bin"] == b"original attachment"
    assert b"mutated attachment" not in persisted.encoded_input.encode()
    assert b"edited after capture" not in persisted.encoded_input.encode()
    same = journal.capture(
        _request(), _capture(), attachments={"report.bin": b"original attachment"},
        capabilities=_capabilities(),
    )
    assert same.digest == digest
    store.close()


def test_same_request_with_different_frozen_content_is_a_conflict(tmp_path):
    from ordessa_agent.submission_journal import JournalConflictError, SubmissionJournal
    from ordessa_persistence_sqlite import SqliteStorePort

    store = SqliteStorePort(tmp_path / "domain.sqlite", writer_token="domain-test")
    journal = SubmissionJournal(store, fingerprint_port=_fingerprint())
    journal.capture(
        _request(), _capture(), attachments={"report.bin": b"A"},
        capabilities=_capabilities(),
    )

    with pytest.raises(JournalConflictError):
        journal.capture(
            _request(), _capture(), attachments={"report.bin": b"B"},
            capabilities=_capabilities(),
        )
    store.close()


def test_missing_reliable_capability_is_typed_unsupported(tmp_path):
    from ordessa_agent.submission_journal import (
        ReliableCapabilities,
        ReliableSubmissionUnsupported,
        SubmissionJournal,
    )
    from ordessa_persistence_sqlite import SqliteStorePort

    store = SqliteStorePort(tmp_path / "domain.sqlite", writer_token="domain-test")
    journal = SubmissionJournal(store)
    missing = ReliableCapabilities(
        backend_durable=True,
        conditional_submit=False,
        immutable_attachments=True,
    )

    with pytest.raises(ReliableSubmissionUnsupported):
        SubmissionJournal(store, fingerprint_port=_fingerprint()).capture(
            _request(), _capture(), attachments={}, capabilities=missing,
        )
    with pytest.raises(ReliableSubmissionUnsupported):
        journal.capture(_request(), _capture(), attachments={}, capabilities=_capabilities())
    assert journal.read(_request()) is None
    store.close()


@pytest.mark.parametrize(
    "kill_after, expected_effects, expected_backend_intent, expected_stage",
    [
        ("mapping", 0, False, "mapped"),
        ("possibly_submitted", 0, False, "possibly-submitted"),
        ("backend_intent", 0, True, "possibly-submitted"),
        ("native_effect", 1, True, "possibly-submitted"),
        ("domain_result", 1, True, "completed"),
    ],
)
def test_sigkill_windows_recover_by_query_without_redispatch(
    tmp_path, kill_after, expected_effects, expected_backend_intent, expected_stage,
):
    domain_db = tmp_path / "domain.sqlite"
    backend_db = tmp_path / "environment.sqlite"
    effects_db = tmp_path / "harness-effects.sqlite"
    marker = tmp_path / "child-paused"
    worker = r'''
import sqlite3, sys, time
from dataclasses import dataclass
from pathlib import Path
from ordessa_agent.submission_journal import ReliableCapabilities, SubmissionJournal
from ordessa_environment_api import RequestKey
from ordessa_environment_api.guarantee import GuaranteeLevel
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import Environment, InstallationRecord

@dataclass(frozen=True)
class Contract:
    contract_id: str = "demo.submit@1"

class AllowPolicy:
    def admit_invoke(self, principal, surface, guarantee):
        return True
    def admit_object_access(self, principal, object_ref, mode):
        return True

domain_path, backend_path, effects_path, marker_path, pause_at = sys.argv[1:]
def pause(stage):
    if pause_at == stage:
        Path(marker_path).write_text(stage)
        while True:
            time.sleep(1)
domain = SqliteStorePort(domain_path, writer_token="domain-child")
backend = SqliteStorePort(backend_path, writer_token="backend-child")
fingerprint = ProtectedFingerprintHmac({"fixture-key": b"fixture-only-key"}, active_key_id="fixture-key")
journal = SubmissionJournal(domain, fingerprint_port=fingerprint)
request = RequestKey("env-a", "user:local:closeout", "req-closeout-1",
                     {"target": "session:S1", "binding": "binding:g1"})
capabilities = ReliableCapabilities(True, True, True)
record = journal.capture(request, {
    "draftId": "draft-1", "draftRevision": 7, "text": "captured text",
    "configOperationIds": ["op-model-3"], "baseRevision": "native-r4",
    "target": {"logical": "session:S1", "generation": 1},
    "binding": {"native": "instance-1", "generation": 2},
    "schema": "agent-input/v1", "guarantee": "reliable",
}, attachments={"report.bin": b"original attachment"}, capabilities=capabilities)
pause("mapping")
journal.mark_possibly_submitted(request, record.digest)
pause("possibly_submitted")
env = Environment("env-a", store=backend, fingerprint_port=fingerprint, policy=AllowPolicy())
env.install(InstallationRecord("submit-plugin", "d" * 64))
env.enable("submit-plugin")
env.activate("submit-plugin", CoreContributionSet(contracts=(Contract,)))
def native_effect():
    pause("backend_intent")
    with sqlite3.connect(effects_path) as effects:
        effects.execute("CREATE TABLE IF NOT EXISTS effects (request_id TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        effects.execute("INSERT INTO effects VALUES (?, 1) ON CONFLICT(request_id) DO UPDATE SET count=count+1",
                        (request.request_id,))
    pause("native_effect")
env.invoke("demo.submit", request, guarantee=GuaranteeLevel.RELIABLE,
          input_digest=record.digest, handler=native_effect)
journal.record_config_apply(request, {"outcome": "applied", "operationIds": ["op-model-3"]})
journal.record_input_acceptance(request, {"outcome": "accepted"})
journal.record_run_result(request, {"outcome": "running", "runId": "run-1"})
journal.record_completed(request)
pause("domain_result")
'''
    child = subprocess.Popen(
        [sys.executable, "-c", worker, str(domain_db), str(backend_db), str(effects_db), str(marker), kill_after],
    )
    deadline = time.monotonic() + 15
    while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists(), f"worker did not reach kill window {kill_after!r}; rc={child.poll()}"
    assert marker.read_text() == kill_after
    os.kill(child.pid, signal.SIGKILL)
    assert child.wait(timeout=10) == -signal.SIGKILL

    from ordessa_agent.submission_journal import SubmissionJournal
    from ordessa_persistence_sqlite import SqliteStorePort

    domain = SqliteStorePort(domain_db, writer_token="domain-parent", allow_takeover=True)
    backend = SqliteStorePort(backend_db, writer_token="backend-parent", allow_takeover=True)
    journal = SubmissionJournal(domain)
    record = journal.read(_request())
    assert record is not None
    assert record.stage == expected_stage
    history = backend.lookup_history(_request().request_id)
    assert (history is not None) is expected_backend_intent

    # Reconciliation may query the existing backend request, but never receives
    # or invokes the native/Harness submit callback.
    before = 0
    if effects_db.exists():
        with __import__("sqlite3").connect(effects_db) as effects:
            row = effects.execute("SELECT count FROM effects WHERE request_id=?", (_request().request_id,)).fetchone()
            before = row[0] if row else 0
    journal.reconcile(_request(), lambda request: backend.lookup_history(request.request_id))
    after = before
    if effects_db.exists():
        with __import__("sqlite3").connect(effects_db) as effects:
            row = effects.execute("SELECT count FROM effects WHERE request_id=?", (_request().request_id,)).fetchone()
            after = row[0] if row else 0
    assert before == after == expected_effects
    domain.close()
    backend.close()
