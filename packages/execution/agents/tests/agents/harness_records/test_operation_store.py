"""SQLite transaction evidence only: no native provider/service execution."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import select
import signal
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite, DomainRevisionConflict
from ordessa_execution_api.environment.errors import IdentityMismatchError, UnknownResultError, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import (
    OperationIntent, StepIntent, UsageMutation, OperationRevisionConflict,
    OperationStorePort, operation_holder, node_holder, safe_json,
)
from pacthold.adapters.sqlite.environment.store import SqliteStorePort, KeyConflictError


def key(id="r", env="env", principal="principal"):
    return RequestKey(env, principal, id)


def recipe(request=None, id="operation"):
    request = request or key()
    env = request.environment_namespace
    steps = tuple(StepIntent(name, {"environmentNamespace": env, "providerId": "fixture",
                                    "version": 1, "generation": 1}, "input-" + name, "correlation-" + name)
                  for name in ("first", "second"))
    return OperationIntent(id, "controlled-storage-fixture", None,
                           {"environmentNamespace": env, "directoryBindingRef": "fixture"},
                           steps, node_holder(env, "node", 0))


def acquisition(request, intent, revision=0, expected=None, state="active"):
    return UsageMutation("usage", revision, expected, operation_holder(request, intent.operation_ref),
                         {"environmentNamespace": request.environment_namespace, "resourceId": "fixture"},
                         ("use",), state)


def transfer(request, intent, revision=1):
    return UsageMutation("usage", revision, operation_holder(request, intent.operation_ref), intent.node_ref,
                         {"environmentNamespace": request.environment_namespace, "resourceId": "fixture"},
                         ("use",), "active")


def conclude(store, request, intent):
    for step in intent.steps:
        assert store.claim_operation_step(request, "digest", step).claimed
        store.record_operation_step(request, "digest", step.step_id, step.input_digest, 1,
                                    "concluded", {"evidenceRef": "controlled-fixture-" + step.step_id})


def publication(store, request, intent, revision=None, usages=None):
    revision = revision if revision is not None else store.read_operation(request).revision
    return store.publish_operation(request, "digest", revision, ("first", "second"),
                                   (DomainWrite("fixture.nodes", "node", 0, {"controlled": True}),),
                                   usages if usages is not None else (transfer(request, intent),),
                                   {"nodeRef": dict(intent.node_ref)})


def test_complete_publication_replay_and_reopen(tmp_path):
    path = tmp_path / "state.sqlite"
    store = SqliteStorePort(path)
    request, intent = key(), recipe()
    assert isinstance(store, OperationStorePort)
    store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
    conclude(store, request, intent)
    revision = store.read_operation(request).revision
    published = publication(store, request, intent, revision)
    assert published.status == "published" and published.outcome == "concluded"
    assert publication(store, request, intent, revision) == published
    assert store._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 2
    assert store._conn.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 2
    store.close()
    reopened = SqliteStorePort(path)
    try:
        assert reopened.read_operation(request) == published
        assert not reopened.claim_operation_step(request, "digest", intent.steps[0]).claimed
        assert reopened.reserve_operation(request, "digest", intent) == published
        with pytest.raises(KeyConflictError):
            reopened.reserve_operation(request, "changed", intent)
        with pytest.raises(IdentityMismatchError):
            reopened.publish_operation(request, "digest", revision, ("first", "second"), (), (), {"different": True})
    finally:
        reopened.close()


def test_one_claim_winner_and_order_even_without_prerequisites(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent)
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, "digest", intent.steps[1])
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: store.claim_operation_step(request, "digest", intent.steps[0]).claimed, range(24)))
        assert results.count(True) == 1 and results.count(False) == 23
        before = store.read_operation(request)
        for _ in range(3):
            assert store.read_operation_step(request, "first").outcome == "possibly-dispatched"
        assert store.read_operation(request) == before
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, "digest", intent.steps[1])
        unknown = store.record_operation_step(request, "digest", "first", "input-first", 1, "unknown", {})
        assert unknown.revision == 2
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, "digest", intent.steps[1])
        known = store.record_operation_step(request, "digest", "first", "input-first", 2, "concluded", {"evidenceRef": "manual-fixture"})
        assert store.record_operation_step(request, "digest", "first", "input-first", 2, "concluded", {"evidenceRef": "manual-fixture"}) == known
        assert store.claim_operation_step(request, "digest", intent.steps[1]).claimed
    finally:
        store.close()


def test_operation_identity_target_reservation_and_full_request_scope(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    target = DomainWrite("fixture.reservations", "target", 0, {"owner": dict(operation_holder(request, intent.operation_ref))})
    try:
        store.reserve_operation(request, "digest", intent, (target,))
        for rival in (key("new"), key("r", principal="other")):
            with pytest.raises(DomainRevisionConflict):
                store.reserve_operation(rival, "digest", recipe(rival))
            assert store.read_operation(rival) is None
        rival = key("new")
        with pytest.raises(DomainRevisionConflict):
            store.reserve_operation(rival, "digest", recipe(rival, "different"), (target,))
        other = key(env="other")
        assert store.reserve_operation(other, "digest", recipe(other)).revision == 1
        assert store.read_operation(key(principal="absent")) is None
        with pytest.raises(KeyConflictError):
            store.commit_domain_change(request, "other-kind", (), {})
        spent = key("domain")
        store.commit_domain_change(spent, "digest", (), {})
        with pytest.raises(UnknownResultError):
            store.reserve_operation(spent, "digest", recipe(spent, "domain-op"))
    finally:
        store.close()


def test_json_snapshot_and_invalid_recipe():
    source = {"environmentNamespace": "env", "nested": {"values": [1]}}
    step = StepIntent("a", source, "digest", "corr")
    source["nested"]["values"].append(2)
    assert step.to_dict()["pinnedProviderRef"]["nested"]["values"] == [1]
    with pytest.raises(TypeError):
        step.pinned_provider_ref["nested"]["x"] = 1
    for value in (float("nan"), b"bad", lambda: None):
        with pytest.raises(ValueError):
            safe_json({"bad": value})
    with pytest.raises(ValueError):
        OperationIntent("o", "k", None, {"environmentNamespace": "env"},
                        (StepIntent("a", {"environmentNamespace": "env"}, "d", "c", ("later",)),))


@pytest.mark.parametrize("field", ["provider-generation", "context", "epoch"])
def test_changed_frozen_operation_intent_is_unavailable_and_never_claimed(tmp_path, field):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent)
        row = store._conn.execute("SELECT operation_json,operation_intent_digest FROM env_requests").fetchone()
        changed = json.loads(row["operation_json"])
        if field == "provider-generation":
            changed["steps"][0]["pinnedProviderRef"]["generation"] = 2
        elif field == "context":
            changed["contextRef"]["directoryBindingRef"] = "different-binding"
        else:
            changed["managementEpoch"] = 1
            for step in changed["steps"]:
                step["managementEpoch"] = 1
        # All variants remain valid DTOs: rejection must verify the frozen content.
        altered = OperationIntent.from_dict(changed)
        store._conn.execute("UPDATE env_requests SET operation_json=?", (safe_json(changed),))
        store._conn.commit()
        assert store._conn.execute("SELECT operation_intent_digest FROM env_requests").fetchone()[0] == row["operation_intent_digest"]
        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(request, "digest", altered.steps[0])
        with pytest.raises(GuaranteeUnavailableError):
            store.reserve_operation(request, "digest", intent)
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
        assert store._conn.execute("SELECT operation_revision FROM env_requests").fetchone()[0] == 1
    finally:
        store.close()


def test_independent_sqlite_connections_race_and_fixed_recipe(tmp_path):
    path = tmp_path / "race.sqlite"
    first = SqliteStorePort(path, writer_token="owned-fixture")
    second = SqliteStorePort(path, writer_token="owned-fixture")
    request, intent = key(), recipe()
    barrier = Barrier(2)
    try:
        first.reserve_operation(request, "digest", intent)
        changed = recipe(id="changed")
        with pytest.raises(IdentityMismatchError):
            first.reserve_operation(request, "digest", changed)
        def claim(store):
            barrier.wait(timeout=5)
            return store.claim_operation_step(request, "digest", intent.steps[0]).claimed
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(claim, first), pool.submit(claim, second)
            assert sorted((a.result(timeout=10), b.result(timeout=10))) == [False, True]
        assert first.read_operation(request).revision == 2
        assert second.read_operation_step(request, "first").revision == 1
    finally:
        try:
            first.close()
        finally:
            # This synthetic peer reuses the same fixture writer token as the
            # original owner. Dispose only this test-created connection; the
            # shared marker is released by the owner path above. A purported
            # second release must still be refused, so no flag is set here.
            second._conn.close()


@pytest.mark.parametrize("failure", ["usage-cas", "trigger"])
def test_publication_failure_rolls_back_domains_usages_result(tmp_path, failure):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
        conclude(store, request, intent)
        before = store.read_operation(request)
        if failure == "trigger":
            store._conn.execute("CREATE TRIGGER reject_publish BEFORE UPDATE ON env_requests WHEN NEW.dispatch_state='operation-published' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
            error = sqlite3.IntegrityError
            usage = transfer(request, intent)
        else:
            error = OperationRevisionConflict
            usage = transfer(request, intent, revision=99)
        with pytest.raises(error):
            publication(store, request, intent, usages=(usage,))
        assert store.read_operation(request) == before
        assert store.read_domain("env", "fixture.nodes", "node") is None
        row = store._conn.execute("SELECT revision,holder_ref FROM env_usages").fetchone()
        assert row[0] == 1 and json.loads(row[1]) == dict(operation_holder(request, intent.operation_ref))
    finally:
        store.close()


def test_usage_scope_unknown_release_and_nonpublication_outcomes(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        bad = UsageMutation("usage", 0, None, {"kind": "operation", "environmentNamespace": "env", "operationId": "operation"},
                            {"environmentNamespace": "env"}, ("use",), "active")
        with pytest.raises(IdentityMismatchError):
            store.reserve_operation(request, "digest", intent, usages=(bad,))
        assert store.read_operation(request) is None
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
        store.claim_operation_step(request, "digest", intent.steps[0])
        release = acquisition(request, intent, 1, operation_holder(request, intent.operation_ref), "released")
        with pytest.raises(UnknownResultError):
            store.record_operation_step(request, "digest", "first", "input-first", 1, "unknown", {}, usages=(release,))
        before = store.read_operation(request)
        with pytest.raises(UnknownResultError):
            store.record_operation_outcome(request, "digest", before.revision, "cancelled", {"evidenceRef": "fixture"})
        assert store.read_operation(request) == before
        wider = UsageMutation("usage", 1, operation_holder(request, intent.operation_ref),
                              operation_holder(request, intent.operation_ref),
                              {"environmentNamespace": "env", "resourceId": "fixture"}, ("execute",), "active")
        with pytest.raises(IdentityMismatchError):
            store.record_operation_step(request, "digest", "first", "input-first", 1, "concluded", {"evidenceRef": "fixture"}, usages=(wider,))
        assert store.read_operation_step(request, "first").revision == 1
        untouched = key("untouched")
        store.reserve_operation(untouched, "digest", recipe(untouched, "untouched-op"))
        refused = store.record_operation_outcome(untouched, "digest", 1, "refused", {"evidenceRef": "fixture-refusal"})
        assert refused.status == "refused" and refused.outcome == "concluded"
        assert store.record_operation_outcome(untouched, "digest", 1, "refused", {"evidenceRef": "fixture-refusal"}) == refused
    finally:
        store.close()


@pytest.mark.parametrize("kind", ["operation", "domain"])
@pytest.mark.parametrize("method", ["append_receipt", "commit_activity", "revise_current", "commit_creation_and_usage"])
def test_old_bare_id_mutations_cannot_damage_scoped_records(tmp_path, kind, method):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        if kind == "operation":
            store.reserve_operation(request, "digest", intent)
        else:
            store.commit_domain_change(request, "digest", (), {"profileId": "fixture"})
        before = store.read_request(request)
        args = ("r", {}, {}) if method == "commit_creation_and_usage" else ("r", {})
        with pytest.raises(GuaranteeUnavailableError):
            getattr(store, method)(*args)
        assert store.read_request(request) == before
    finally:
        store.close()


def test_old_creation_cannot_replace_scoped_usage_and_rolls_back_objects(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
        before = tuple(store._conn.execute("SELECT * FROM env_usages").fetchone())
        with pytest.raises(GuaranteeUnavailableError):
            store.commit_creation_and_usage("old-id", {"env:old:0:object": "active"}, {"usage": "released"})
        assert tuple(store._conn.execute("SELECT * FROM env_usages").fetchone()) == before
        assert store._conn.execute("SELECT COUNT(*) FROM env_objects").fetchone()[0] == 0
        assert store.lookup_history("old-id") is None
    finally:
        store.close()


@pytest.mark.parametrize("new_state", ["active", "unknown"])
def test_released_usage_cannot_revive_or_transfer_and_new_id_is_required(tmp_path, new_state):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    owner = operation_holder(request, intent.operation_ref)
    try:
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
        store.claim_operation_step(request, "digest", intent.steps[0])
        released = acquisition(request, intent, 1, owner, "released")
        store.record_operation_step(request, "digest", "first", "input-first", 1, "concluded",
                                    {"evidenceRef": "controlled-release"}, usages=(released,))
        before = store.read_operation(request)
        with pytest.raises(IdentityMismatchError):
            store.claim_operation_step(request, "digest", intent.steps[1],
                                       (acquisition(request, intent, 2, owner, new_state),))
        assert store.read_operation(request) == before
        assert store.read_operation_step(request, "second") is None
        # Reacquisition is represented by a distinct durable Usage identity.
        fresh = UsageMutation("fresh-usage", 0, None, owner,
                              {"environmentNamespace": "env", "resourceId": "fixture"}, ("use",), "active")
        release_again = acquisition(request, intent, 2, owner, "released")
        assert store.claim_operation_step(request, "digest", intent.steps[1], (release_again, fresh)).claimed
        assert store._conn.execute("SELECT revision FROM env_usages WHERE usage_id='usage'").fetchone()[0] == 2
        store.record_operation_step(request, "digest", "second", "input-second", 1, "concluded", {"evidenceRef": "fixture-second"})
        before = store.read_operation(request)
        with pytest.raises(IdentityMismatchError):
            publication(store, request, intent, usages=(transfer(request, intent, 2),))
        assert store.read_operation(request) == before
        assert store.read_domain("env", "fixture.nodes", "node") is None
        row = store._conn.execute("SELECT state,revision,holder_ref FROM env_usages WHERE usage_id='usage'").fetchone()
        assert row[0] == "released" and row[1] == 2 and json.loads(row[2]) == dict(owner)
    finally:
        store.close()


def test_unknown_usage_requires_concluded_evidence_before_active(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    owner = operation_holder(request, intent.operation_ref)
    try:
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent, state="unknown"),))
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, "digest", intent.steps[0], (acquisition(request, intent, 1, owner),))
        assert store.read_operation_step(request, "first") is None
        store.claim_operation_step(request, "digest", intent.steps[0])
        store.record_operation_step(request, "digest", "first", "input-first", 1, "concluded",
                                    {"evidenceRef": "controlled-reconciliation"}, usages=(acquisition(request, intent, 1, owner),))
        row = store._conn.execute("SELECT state,revision FROM env_usages").fetchone()
        assert tuple(row) == ("active", 2)
    finally:
        store.close()


@pytest.mark.parametrize("field", ["recipe", "knowledge", "index", "step", "fake-conclusion"])
def test_corrupted_records_fail_closed(tmp_path, field):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent)
        store.claim_operation_step(request, "digest", intent.steps[0])
        if field == "recipe":
            store._conn.execute("UPDATE env_requests SET operation_json='{}'")
        elif field == "knowledge":
            store._conn.execute("UPDATE env_requests SET current=?", (safe_json({"revision": 2, "outcome": "concluded"}),))
        elif field == "index":
            store._conn.execute("DELETE FROM env_domain_records WHERE namespace='core.operation-identities'")
        elif field == "step":
            value = intent.steps[0].to_dict()
            value["pinnedProviderRef"]["version"] = 999
            store._conn.execute("UPDATE env_request_steps SET intent_json=?", (safe_json(value),))
        else:
            store._conn.execute("UPDATE env_request_steps SET outcome='concluded'")
        store._conn.commit()
        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation_step(request, "first")
    finally:
        store.close()


def test_legacy_unknown_row_and_reservation_failure_are_not_new_operations(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        assert store.claim_dispatch(request, "digest")
        with pytest.raises(UnknownResultError):
            store.reserve_operation(request, "digest", intent)
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
        rival = key("rival")
        store._conn.execute("CREATE TRIGGER reject_reserve BEFORE INSERT ON env_requests WHEN NEW.operation_json IS NOT NULL BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            store.reserve_operation(rival, "digest", recipe(rival, "rival-op"),
                                    (DomainWrite("fixture.reservations", "rival", 0, {}),),
                                    (acquisition(rival, recipe(rival, "rival-op")),))
        assert store.read_operation(rival) is None
        assert store.read_domain("env", "core.operation-identities", "rival-op") is None
        assert store.read_domain("env", "fixture.reservations", "rival") is None
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize("field", ["result", "step-evidence", "result-with-new-digest"])
def test_result_and_step_evidence_corruption_is_detected(tmp_path, field):
    import hashlib
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, intent = key(), recipe()
    try:
        store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
        conclude(store, request, intent)
        publication(store, request, intent)
        if field == "step-evidence":
            store._conn.execute("UPDATE env_request_steps SET evidence_json=? WHERE step_id='first'",
                                (safe_json({"evidenceRef": "forged"}),))
            store._conn.commit()
            with pytest.raises(GuaranteeUnavailableError):
                store.read_operation_step(request, "first")
        else:
            receipt = json.loads(store._conn.execute("SELECT receipt FROM env_requests").fetchone()[0])
            receipt["operation_result"]["nodeRef"]["instanceId"] = "forged"
            if field == "result-with-new-digest":
                receipt["operation_result_digest"] = hashlib.sha256(safe_json(receipt["operation_result"]).encode()).hexdigest()
            store._conn.execute("UPDATE env_requests SET receipt=?", (safe_json(receipt),))
            store._conn.commit()
            with pytest.raises(GuaranteeUnavailableError):
                store.read_operation(request)
            with pytest.raises(GuaranteeUnavailableError):
                publication(store, request, intent)
    finally:
        store.close()


@pytest.mark.parametrize("boundary", ["claim", "publication"])
def test_owned_process_sigkill_preserves_spent_claim_and_atomic_publication(tmp_path, boundary):
    path = tmp_path / "crash.sqlite"
    store = SqliteStorePort(path)
    request, intent = key(), recipe()
    store.reserve_operation(request, "digest", intent, usages=(acquisition(request, intent),))
    if boundary == "publication":
        conclude(store, request, intent)
    before = store.read_operation(request)
    store.close()
    script = '''
import json, sys, threading
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import DomainWrite
from ordessa_execution_api.environment.operations import UsageMutation, operation_holder
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
s=SqliteStorePort(sys.argv[1]); r=RequestKey("env","principal","r"); op=s.read_operation(r); i=op.intent
if sys.argv[2]=="claim":
    assert s.claim_operation_step(r,"digest",i.steps[0]).claimed
    print("BOUNDARY",flush=True); threading.Event().wait(120)
else:
    def pause():
        print("BOUNDARY",flush=True); threading.Event().wait(120); return 0
    s._conn.create_function("pause_publication",0,pause)
    s._conn.execute("CREATE TRIGGER pause_publish BEFORE UPDATE ON env_requests WHEN NEW.dispatch_state='operation-published' BEGIN SELECT pause_publication(); END")
    s._conn.commit()
    usage=UsageMutation("usage",1,operation_holder(r,i.operation_ref),i.node_ref,{"environmentNamespace":"env","resourceId":"fixture"},("use",),"active")
    s.publish_operation(r,"digest",op.revision,("first","second"),(DomainWrite("fixture.nodes","node",0,{"controlled":True}),),(usage,),{"nodeRef":dict(i.node_ref)})
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(path), boundary], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0], "owned fixture failed to reach boundary"
        assert child.stdout.readline().strip() == "BOUNDARY"
        child.kill()
        assert child.wait(timeout=10) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    # Explicit takeover is confined to this fixture after confirmed child death.
    recovered = SqliteStorePort(path, allow_takeover=True)
    try:
        if boundary == "claim":
            assert not recovered.claim_operation_step(request, "digest", intent.steps[0]).claimed
            assert recovered.read_operation_step(request, "first").outcome == "possibly-dispatched"
            with pytest.raises(UnknownResultError):
                recovered.claim_operation_step(request, "digest", intent.steps[1])
        else:
            assert recovered.read_operation(request) == before
            assert recovered.read_domain("env", "fixture.nodes", "node") is None
            assert recovered._conn.execute("SELECT revision FROM env_usages").fetchone()[0] == 1
    finally:
        recovered.close()
