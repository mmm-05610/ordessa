from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest

from ordessa_harness_api import (
    ApplicationTarget, Confirmed, ErrorCode, NotFound, Plan, Refused, Unknown,
)
from ordessa_harness.application import FenceObservation, JournalError, NativeActivationReceipt, OperationJournal


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
TARGET = ApplicationTarget("server", "session", "channel", 7)


def plan(*, plan_id="plan-a", digest="a" * 64, target=TARGET):
    return Plan(plan_id, target, digest, "before-1", "native-1", 3,
                "auth-1", "secret-refs-1", (NOW + timedelta(minutes=5)).isoformat())


def journal(tmp_path):
    return OperationJournal(tmp_path / "operation.sqlite")


def owner_receipt(store, operation_id):
    manifest = "f" * 64
    store.bind_native_manifest("alice", TARGET, operation_id, manifest)
    receipt = NativeActivationReceipt(operation_id, TARGET, manifest,
                                      "native-session-1", "applied-1", "activation-1")
    store.record_native_receipt("alice", TARGET, receipt)
    store.record_native_verification("alice", TARGET, operation_id, "readback-1")
    return receipt


def test_atomic_reservation_reopen_same_key_and_cross_key_session_serial(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    observed = FenceObservation.from_plan(selected)
    first = store.reserve("alice", selected.plan_id, "submission-1", observed, now=NOW)
    assert first.result.kind == "unknown" and first.result.phase == "applying"
    reopened = journal(tmp_path)
    assert reopened.query("alice", TARGET, "submission-1") == first
    assert reopened.reserve("alice", selected.plan_id, "submission-1", observed, now=NOW + timedelta(hours=1)) == first
    busy = reopened.reserve("alice", selected.plan_id, "submission-2", observed, now=NOW)
    assert isinstance(busy, Refused) and busy.code is ErrorCode.BUSY
    next_generation = plan(plan_id="next-generation", target=replace(TARGET, runtime_generation=8))
    reopened.register_plan("alice", next_generation)
    cross_generation = reopened.reserve("alice", next_generation.plan_id, "submission-3",
                                         FenceObservation.from_plan(next_generation), now=NOW)
    assert isinstance(cross_generation, Refused) and cross_generation.code is ErrorCode.BUSY
    assert reopened.reconcile("alice", TARGET, "submission-1") == first.result
    assert isinstance(reopened.query("bob", TARGET, "submission-1"), NotFound)


def test_same_key_different_payload_refused_and_stale_fences_precede_effects(tmp_path):
    store = journal(tmp_path)
    one, two = plan(), plan(plan_id="plan-b", digest="b" * 64)
    store.register_plan("alice", one)
    store.register_plan("alice", two)
    first = store.reserve("alice", one.plan_id, "same-key", FenceObservation.from_plan(one), now=NOW)
    conflict = store.reserve("alice", two.plan_id, "same-key", FenceObservation.from_plan(two), now=NOW)
    assert isinstance(conflict, Refused) and conflict.code is ErrorCode.TARGET_CONFLICT
    assert store.query("alice", TARGET, "same-key") == first

    for changed in (
        replace(FenceObservation.from_plan(two), target=replace(TARGET, runtime_generation=8)),
        replace(FenceObservation.from_plan(two), desired_digest="c" * 64),
        replace(FenceObservation.from_plan(two), before_revision="before-2"),
        replace(FenceObservation.from_plan(two), native_version_ref="native-2"),
        replace(FenceObservation.from_plan(two), provider_generation=4),
        replace(FenceObservation.from_plan(two), authorization_revision="auth-2"),
        replace(FenceObservation.from_plan(two), secret_ref_revision="secret-refs-2"),
    ):
        refused = store.reserve("alice", two.plan_id, "fresh-key", changed, now=NOW)
        assert isinstance(refused, Refused) and refused.code is ErrorCode.STALE_PLAN
    expired = store.reserve("alice", two.plan_id, "fresh-key", FenceObservation.from_plan(two),
                            now=NOW + timedelta(minutes=5))
    assert isinstance(expired, Refused) and expired.code is ErrorCode.STALE_PLAN
    assert isinstance(store.query("alice", TARGET, "fresh-key"), NotFound)


def test_confirmed_persists_and_releases_session_for_next_key(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    observed = FenceObservation.from_plan(selected)
    first = store.reserve("alice", selected.plan_id, "one", observed, now=NOW)
    owner_receipt(store, first.operation_id)
    result = Confirmed(first.operation_id, "applied-1", "native-session-1", 7, "readback-1", ("config-generation",))
    assert store.record_result("alice", TARGET, first.operation_id, result).result == result
    reopened = journal(tmp_path)
    assert reopened.query("alice", TARGET, "one").result == result
    second = reopened.reserve("alice", selected.plan_id, "two", observed, now=NOW)
    assert second.operation_id != first.operation_id
    with pytest.raises(JournalError, match="immutable"):
        reopened.record_result("alice", TARGET, first.operation_id,
                               replace(result, applied_revision="forged"))


def test_confirmed_requires_durable_owner_receipt_and_exact_manifest(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    first = store.reserve("alice", selected.plan_id, "one",
                          FenceObservation.from_plan(selected), now=NOW)
    result = Confirmed(first.operation_id, "applied-1", "native-session-1", 7, "readback-1", ())
    with pytest.raises(JournalError, match="requires native owner receipt"):
        store.record_result("alice", TARGET, first.operation_id, result)
    store.bind_native_manifest("alice", TARGET, first.operation_id, "f" * 64)
    with pytest.raises(JournalError, match="manifest"):
        store.record_native_receipt("alice", TARGET,
            NativeActivationReceipt(first.operation_id, TARGET, "0" * 64,
                                    "native-session-1", "applied-1", "readback-1"))
    assert store.query("alice", TARGET, "one").result.kind == "unknown"
    owner_receipt(store, first.operation_id)
    with pytest.raises(JournalError, match="differs"):
        store.record_result("alice", TARGET, first.operation_id,
                            replace(result, native_session_identity="forged"))


def test_legacy_confirmed_row_without_receipt_projects_unknown_without_mutation(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    first = store.reserve("alice", selected.plan_id, "one",
                          FenceObservation.from_plan(selected), now=NOW)
    legacy = Confirmed(first.operation_id, "applied-1", "native-session-1", 7,
                       "legacy-readback", ())
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE operations SET state='confirmed', result_json=? WHERE operation_id=?",
                   (json.dumps(asdict(legacy)), first.operation_id))
    reopened = journal(tmp_path)
    projected = reopened.query("alice", TARGET, "one")
    assert projected.result.kind == "unknown"
    assert reopened.reconcile("alice", TARGET, "one").kind == "unknown"
    assert reopened.reserve("alice", selected.plan_id, "one",
                            FenceObservation.from_plan(selected), now=NOW) == projected
    next_key = reopened.reserve("alice", selected.plan_id, "two",
                                FenceObservation.from_plan(selected), now=NOW)
    assert isinstance(next_key, Refused) and next_key.code is ErrorCode.BUSY
    with pytest.raises(JournalError, match="receipt"):
        reopened.record_result("alice", TARGET, first.operation_id, legacy)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT state FROM operations WHERE operation_id=?",
                          (first.operation_id,)).fetchone()[0] == "confirmed"


def test_external_success_then_journal_write_failure_stays_unknown_without_replay(tmp_path, monkeypatch):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    observed = FenceObservation.from_plan(selected)
    first = store.reserve("alice", selected.plan_id, "one", observed, now=NOW)
    external_success_count = 1  # controlled external effect happened once
    owner_receipt(store, first.operation_id)
    original_persist = store._persist_result

    def fail_write(*args):
        original_persist(*args)
        raise OSError("injected disk failure after external success")

    monkeypatch.setattr(store, "_persist_result", fail_write)
    result = Confirmed(first.operation_id, "applied-1", "native-session-1", 7, "readback-1", ())
    with pytest.raises(OSError, match="disk failure"):
        store.record_result("alice", TARGET, first.operation_id, result)
    reopened = journal(tmp_path)
    unknown = reopened.query("alice", TARGET, "one")
    assert isinstance(unknown.result, Unknown) and unknown.result.phase == "verifying"
    assert reopened.reconcile("alice", TARGET, "one") == unknown.result
    assert reopened.reserve("alice", selected.plan_id, "one", observed, now=NOW) == unknown
    assert external_success_count == 1
    assert reopened.reserve("alice", selected.plan_id, "two", observed, now=NOW).code is ErrorCode.BUSY


def test_plan_id_is_immutable_and_principal_isolation(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    store.register_plan("alice", selected)
    with pytest.raises(JournalError, match="different principal"):
        store.register_plan("bob", selected)
    with pytest.raises(JournalError, match="different principal"):
        store.register_plan("alice", plan(digest="b" * 64))
    refused = store.reserve("bob", selected.plan_id, "one", FenceObservation.from_plan(selected), now=NOW)
    assert isinstance(refused, Refused) and refused.code is ErrorCode.AUTHORIZATION_REFUSED


def test_bool_provider_generation_cannot_satisfy_integer_fence():
    with pytest.raises(JournalError, match="provider generation"):
        replace(FenceObservation.from_plan(plan()), provider_generation=True)


def test_concurrent_same_key_creates_one_durable_operation(tmp_path):
    store = journal(tmp_path)
    selected = plan()
    store.register_plan("alice", selected)
    observed = FenceObservation.from_plan(selected)

    def reserve_once(_):
        return OperationJournal(store.path).reserve("alice", selected.plan_id, "same", observed, now=NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve_once, range(16)))
    assert len({result.operation_id for result in results}) == 1
    assert store.query("alice", TARGET, "same") == results[0]
