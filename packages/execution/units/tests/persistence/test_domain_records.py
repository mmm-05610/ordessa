"""Real SQLite domain CAS and exact-request replay, without external effects."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import sqlite3

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.database.records import (
    DomainWrite,
    DomainRevisionConflict,
    DomainStorePort,
)
from ordessa_execution_api.environment.errors import UnknownResultError, GuaranteeUnavailableError
from ordessa_units.persistence.sqlite.store import SqliteUnitStore, KeyConflictError


def key(request_id, environment="env-a", principal="user:local:a"):
    return RequestKey(environment, principal, request_id)


def write(record_id="one", revision=0, namespace="catalog", value=None):
    return DomainWrite(namespace, record_id, revision, value or {"name": record_id})


def test_atomic_multiple_records_and_reopen_replay(tmp_path):
    path = tmp_path / "state.sqlite"
    store = SqliteUnitStore(path)
    assert isinstance(store, DomainStorePort)
    request = key("create")
    expected = {"profile": "one", "revision": 1}
    assert store.commit_domain_change(request, "digest", (write(), write("two")), expected) == expected
    assert store.read_domain("env-a", "catalog", "one") == {
        "record_id": "one", "revision": 1, "value": {"name": "one"}}
    assert [row["record_id"] for row in store.list_domain("env-a", "catalog")] == ["one", "two"]
    store.close()
    reopened = SqliteUnitStore(path)
    try:
        # Replay never executes the now-conflicting original absent-only writes.
        assert reopened.commit_domain_change(request, "digest", (write(), write("two")), expected) == expected
        assert reopened.read_domain_result(request, "digest") == expected
        assert reopened.read_domain_result(key("absent"), "digest") is None
        with pytest.raises(KeyConflictError):
            reopened.read_domain_result(request, "changed")
        assert reopened.read_domain("env-a", "catalog", "one")["revision"] == 1
        assert reopened.read_request(request)["current"]["outcome"] == "concluded"
        with pytest.raises(KeyConflictError):
            reopened.commit_domain_change(request, "different-kind-or-input", (write("three"),), {})
        assert reopened.read_domain("env-a", "catalog", "three") is None
    finally:
        reopened.close()


def test_environment_namespace_and_principal_are_independent(tmp_path):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        for environment, namespace, principal in [
            ("env-a", "catalog", "user:local:a"),
            ("env-b", "catalog", "user:local:a"),
            ("env-a", "other", "user:local:a"),
            ("env-a", "third", "user:local:b"),
        ]:
            request_id = "other-namespace" if namespace == "other" else "same"
            store.commit_domain_change(key(request_id, environment, principal), namespace + environment,
                                       (write(namespace=namespace),), {"namespace": namespace})
        assert len(store.list_domain("env-a", "catalog")) == 1
        assert len(store.list_domain("env-b", "catalog")) == 1
        assert store.list_domain("env-c", "catalog") == ()
        assert store.read_request(key("same", principal="user:local:missing")) is None
    finally:
        store.close()


def test_cas_competition_has_one_winner(tmp_path):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        store.commit_domain_change(key("initial"), "initial", (write(),), {})
        def compete(index):
            try:
                store.commit_domain_change(key(f"race-{index}"), str(index),
                                           (write(revision=1, value={"winner": index}),), {"winner": index})
                return "written"
            except DomainRevisionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(compete, range(16)))
        assert results.count("written") == 1
        assert results.count("conflict") == 15
        assert store.read_domain("env-a", "catalog", "one")["revision"] == 2
    finally:
        store.close()


def _close_shared_writer(store):
    """Test-only close for a store that deliberately shares one writer identity.

    Only a genuinely released row (no ``env_writer_lock`` row at all) is
    tolerated — that is the sibling having released it first. If the lock row
    still exists (owner changed, or any other release conflict) the error
    propagates; the message alone cannot distinguish those two states. Closing
    the raw connection here is test-only and does NOT claim a successful release.
    """
    try:
        store.close()
    except GuaranteeUnavailableError:
        row = store._conn.execute(
            "SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()
        if row is not None:
            raise
        store._conn.close()


def test_shared_writer_close_refuses_a_changed_owner(tmp_path):
    """The test cleanup tolerates only a genuinely released row.

    ``release_writer`` raises the same message for "row absent" and "owner
    differs"; the cleanup must read the actual row and propagate when a lock row
    still exists with a changed owner. Production release is unchanged.
    """
    path = tmp_path / "state.sqlite"
    first = SqliteUnitStore(path, writer_token="owner-a")
    try:
        first.commit_domain_change(key("initial"), "initial", (write(),), {})
        second = SqliteUnitStore(path, writer_token="owner-b", allow_takeover=True)
        try:
            with pytest.raises(GuaranteeUnavailableError):
                _close_shared_writer(first)
            assert first._conn.execute(
                "SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()[0] == "owner-b"
        finally:
            second.close()
    finally:
        first._conn.close()


def _process_cas(path, index, ready, start, outcomes):
    # Deliberately share one controlled writer identity to isolate SQLite CAS
    # across independent connections; this is not product takeover evidence.
    store = SqliteUnitStore(path, writer_token="controlled-cas-owner")
    try:
        ready.put(index)
        assert start.wait(10)
        try:
            store.commit_domain_change(key(f"process-{index}"), str(index),
                                       (write(revision=1, value={"winner": index}),), {})
            outcomes.put("written")
        except DomainRevisionConflict:
            outcomes.put("conflict")
    finally:
        _close_shared_writer(store)


def test_two_process_sqlite_cas_has_one_winner(tmp_path):
    path = tmp_path / "state.sqlite"
    store = SqliteUnitStore(path, writer_token="controlled-cas-owner")
    store.commit_domain_change(key("initial"), "initial", (write(),), {})
    context = multiprocessing.get_context("spawn")
    ready, outcomes, start = context.Queue(), context.Queue(), context.Event()
    children = [context.Process(target=_process_cas, args=(path, index, ready, start, outcomes))
                for index in range(2)]
    try:
        for child in children:
            child.start()
        assert {ready.get(timeout=10), ready.get(timeout=10)} == {0, 1}
        start.set()
        assert sorted([outcomes.get(timeout=10), outcomes.get(timeout=10)]) == ["conflict", "written"]
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert store.read_domain("env-a", "catalog", "one")["revision"] == 2
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
            child.join(timeout=2)
        ready.close()
        outcomes.close()
        _close_shared_writer(store)


@pytest.mark.parametrize("state", ["possibly-dispatched", "legacy", "concluded-without-domain-result"])
def test_spent_incomplete_requests_never_write(tmp_path, state):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    request = key("spent")
    try:
        if state == "legacy":
            store.reserve_request(request, "digest")
        else:
            # Exact historical rows, not a restored arbitrary dispatch API.
            store.reserve_request(request, "digest")
            with store.transaction() as connection:
                if state == "concluded-without-domain-result":
                    connection.execute("UPDATE env_requests SET dispatch_state='concluded', receipt=?, current=?",
                        ('{"delivery":"acknowledged"}', '{"outcome":"concluded","revision":1}'))
                else:
                    connection.execute("UPDATE env_requests SET dispatch_state='possibly-dispatched'")
        with pytest.raises(UnknownResultError):
            store.commit_domain_change(request, "digest", (write(),), {})
        with pytest.raises(UnknownResultError):
            store.read_domain_result(request, "digest")
        assert store.list_domain("env-a", "catalog") == ()
    finally:
        store.close()


def test_duplicate_writes_and_invalid_json_are_rejected_before_changes(tmp_path):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        with pytest.raises(ValueError):
            store.commit_domain_change(key("duplicate"), "digest", (write(), write()), {})
        with pytest.raises(ValueError):
            store.commit_domain_change(key("nan"), "digest", (write(value={"n": float("nan")}),), {})
        with pytest.raises(ValueError):
            store.commit_domain_change(key("result-nan"), "digest", (write(),), {"n": float("nan")})
        assert store.list_domain("env-a", "catalog") == ()
        for request_id in ("duplicate", "nan", "result-nan"):
            assert store.read_request(key(request_id)) is None
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["second-record", "request-result"])
def test_sql_failure_rolls_back_all_rows_and_request(tmp_path, failure):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        with store.transaction() as conn:
            if failure == "second-record":
                conn.execute("CREATE TRIGGER fail_domain BEFORE INSERT ON env_domain_records "
                             "WHEN NEW.record_id='two' BEGIN SELECT RAISE(ABORT, 'injected'); END")
            else:
                conn.execute("CREATE TRIGGER fail_request BEFORE INSERT ON env_requests "
                             "BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with pytest.raises(sqlite3.IntegrityError):
            store.commit_domain_change(key("fail"), "digest", (write(), write("two")), {})
        assert store.list_domain("env-a", "catalog") == ()
        assert store.read_request(key("fail")) is None
        with store.transaction() as conn:
            conn.execute("DROP TRIGGER " + ("fail_domain" if failure == "second-record" else "fail_request"))
        assert store.commit_domain_change(key("fail"), "digest", (write(), write("two")), {}) == {}
    finally:
        store.close()


def test_later_cas_failure_rolls_back_earlier_write(tmp_path):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        store.commit_domain_change(key("init"), "init", (write("two"),), {})
        with pytest.raises(DomainRevisionConflict):
            store.commit_domain_change(key("fail"), "digest", (write(), write("two")), {})
        assert store.read_domain("env-a", "catalog", "one") is None
        assert store.read_domain("env-a", "catalog", "two")["revision"] == 1
        assert store.read_request(key("fail")) is None
    finally:
        store.close()


def test_nested_commit_refuses_without_committing_outer_transaction(tmp_path):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    try:
        with pytest.raises(RuntimeError):
            with store.transaction() as conn:
                conn.execute("INSERT INTO env_meta(key,value) VALUES ('outer','pending')")
                with pytest.raises(GuaranteeUnavailableError):
                    store.commit_domain_change(key("nested"), "digest", (write(),), {})
                raise RuntimeError("rollback outer")
        assert store.read_request(key("nested")) is None
        with store.transaction() as conn:
            assert conn.execute("SELECT value FROM env_meta WHERE key='outer'").fetchone() is None
    finally:
        store.close()
