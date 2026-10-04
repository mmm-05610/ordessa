"""Additive atomic C2 dispatch-claim/read namespace regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import pytest

from ordessa_environment_api import RequestKey
from ordessa_persistence_sqlite import KeyConflictError, SqliteStorePort


def _key(request_id: str, *, environment: str = "env-closeout", principal: str = "user:local:test"):
    return RequestKey(environment_namespace=environment, principal_scope=principal,
                      request_id=request_id)


def test_atomic_dispatch_claim_is_first_writer_only_and_survives_restart(tmp_path):
    path = tmp_path / "claims.sqlite3"
    store = SqliteStorePort(path)
    request = _key("claim-once")
    assert store.claim_dispatch(request, "a" * 64) is True
    store.close()

    reopened = SqliteStorePort(path, allow_takeover=True)
    assert reopened.claim_dispatch(request, "a" * 64) is False
    with pytest.raises(KeyConflictError):
        reopened.claim_dispatch(request, "b" * 64)
    reopened.close()


def test_claim_and_history_keys_include_environment_and_principal_namespaces(tmp_path):
    store = SqliteStorePort(tmp_path / "claims.sqlite3")
    assert store.claim_dispatch(_key("same-id", environment="env-a"), "a" * 64)
    assert store.claim_dispatch(_key("same-id", environment="env-b"), "a" * 64)
    assert store.claim_dispatch(_key("same-id", principal="user:local:second"), "a" * 64)

    assert store.read_request(_key("same-id", environment="env-a")) is not None
    assert store.read_request(_key("same-id", environment="env-b")) is not None
    assert store.read_request(_key("same-id", principal="user:local:second")) is not None
    assert store.read_request(_key("same-id", principal="user:local:missing")) is None
    store.close()


def test_concurrent_identical_claims_have_exactly_one_dispatch_owner(tmp_path):
    store = SqliteStorePort(tmp_path / "claims.sqlite3")
    request = _key("concurrent")
    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(lambda _: store.claim_dispatch(request, "c" * 64), range(48)))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 47
    store.close()


def test_dispatch_result_read_is_scoped_and_unknown_claim_is_not_replayable(tmp_path):
    path = tmp_path / "claims.sqlite3"
    store = SqliteStorePort(path)
    request = _key("pending-result")
    assert store.claim_dispatch(request, "d" * 64)
    pending = store.read_request(request)
    assert pending["state"] == "possibly-dispatched"
    assert pending["current"]["outcome"] == "unknown"
    assert store.record_dispatch_result(request, {"delivery": "acknowledged"},
                                        {"outcome": "concluded", "revision": 1})
    assert store.read_request(request)["current"]["outcome"] == "concluded"
    assert store.read_request(_key("pending-result", environment="different-env")) is None
    store.close()


def test_transaction_context_holds_connection_lock_until_commit(tmp_path):
    store = SqliteStorePort(tmp_path / "claims.sqlite3")
    started = Event()
    finished = Event()
    failures = []

    def competing_claim():
        started.set()
        try:
            store.claim_dispatch(_key("context-serialized"), "e" * 64)
        except BaseException as exc:
            failures.append(exc)
        finally:
            finished.set()

    try:
        with store.transaction() as conn:
            conn.execute("INSERT INTO env_meta(key, value) VALUES ('closeout-lock', 'held')")
            worker = Thread(target=competing_claim)
            worker.start()
            assert started.wait(timeout=1)
            # The transaction owns the connection through the complete context.
            # A competing dispatch claim must wait rather than join or corrupt it.
            assert not finished.wait(timeout=0.1)
        assert finished.wait(timeout=2)
        worker.join(timeout=2)
        assert not failures
        assert store.read_request(_key("context-serialized")) is not None
    finally:
        store.close()
