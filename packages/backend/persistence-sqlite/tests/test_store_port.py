"""005 gates for the SQLite StorePort (T005-03/05/06/07/09 + T005-02 fixtures).

Pinned counterexamples:

* a second writer on the same data root is REFUSED — lease age never proves
  the first writer dead; only an explicit evidence-backed release/takeover
  reopens the root;
* same request key + same digest claims once and replays; a different digest
  is a typed conflict, never a re-issue;
* a response slot is consumed exactly once per delivery revision;
* kill windows (real SIGKILL subprocesses) preserve the C2 invariants:
  pre-intent → nothing recorded; post-intent pre-dispatch → claim exists,
  outcome unknown, never resent;
* two data roots are fully isolated;
* the sealed legacy schema replays byte-for-byte, opens read-only, refuses
  future versions and never writes;
* key rotation keeps spent tombstones blocking re-dispatch while comparisons
  against the retired key go comparison-unavailable.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ordessa_persistence_sqlite import (
    KeyConflictError,
    ProtectedFingerprintHmac,
    SqliteStorePort,
    WriterLockHeldError,
)
from ordessa_persistence_sqlite.legacy_read import (
    LegacyCompatReader,
    LegacySchemaError,
    replay_archived_migrations,
)
from ordessa_environment_api import (
    ComparisonUnavailableError,
    RequestKey,
)

ARCHIVED = Path(__file__).resolve().parents[4] / "plugins/runtime-compat/src/pacthold_runtime_compat/migrations"


def _key(rid: str, env: str = "env-p") -> RequestKey:
    return RequestKey(environment_namespace=env, principal_scope="user:local:t", request_id=rid)


# -- C2 same-root writer exclusivity (T005-09) --------------------------------


def test_second_writer_on_the_same_root_is_refused_until_explicit_release(tmp_path):
    first = SqliteStorePort(tmp_path / "root.sqlite3")
    with pytest.raises(WriterLockHeldError, match="never proves that writer dead"):
        SqliteStorePort(tmp_path / "root.sqlite3")
    first.close()
    second = SqliteStorePort(tmp_path / "root.sqlite3")  # explicit release reopens
    second.close()


def test_takeover_requires_explicit_evidence_flag(tmp_path):
    first = SqliteStorePort(tmp_path / "root.sqlite3")
    with pytest.raises(WriterLockHeldError):
        SqliteStorePort(tmp_path / "root.sqlite3")
    takeover = SqliteStorePort(tmp_path / "root.sqlite3", allow_takeover=True)
    assert takeover.writer_token != first.writer_token
    takeover.close()


def test_two_data_roots_are_isolated(tmp_path):
    a = SqliteStorePort(tmp_path / "a.sqlite3")
    b = SqliteStorePort(tmp_path / "b.sqlite3")
    assert a.reserve_request(_key("r-1", env="root-a"), "x" * 64)
    # the same key id in another root is a DIFFERENT request
    assert b.reserve_request(_key("r-1", env="root-b"), "x" * 64)
    a.close(); b.close()


# -- request-key discipline (T005-03/06) ---------------------------------------


def test_same_key_same_digest_claims_once_and_replays(tmp_path):
    store = SqliteStorePort(tmp_path / "s.sqlite3")
    assert store.reserve_request(_key("r-2"), "d" * 64) is True
    assert store.reserve_request(_key("r-2"), "d" * 64) is True  # replay path
    with pytest.raises(KeyConflictError):
        store.reserve_request(_key("r-2"), "e" * 64)
    store.close()


def test_response_slot_consumed_exactly_once_per_revision(tmp_path):
    store = SqliteStorePort(tmp_path / "s.sqlite3")
    assert store.claim_response_slot("q-1", 1) is True
    assert store.claim_response_slot("q-1", 1) is False  # spent
    assert store.claim_response_slot("q-1", 2) is True   # new delivery revision
    store.close()


def test_receipts_append_and_current_revises_never_rewrites(tmp_path):
    store = SqliteStorePort(tmp_path / "s.sqlite3")
    store.reserve_request(_key("r-3"), "f" * 64)
    store.append_receipt("r-3", {"delivery": "acknowledged"})
    store.revise_current("r-3", {"outcome": "concluded", "revision": 1})
    store.revise_current("r-3", {"outcome": "disputed", "revision": 2})
    history = store.lookup_history("r-3")
    assert history["receipt"] == {"delivery": "acknowledged"}  # immutable
    assert history["current"]["outcome"] == "disputed"          # revised, not rewritten
    store.close()


# -- kill windows (T005-05, real SIGKILL) --------------------------------------

_KILL_SCRIPT = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {src!r})
    from ordessa_persistence_sqlite import SqliteStorePort
    from ordessa_environment_api import RequestKey
    store = SqliteStorePort(sys.argv[1])
    key = RequestKey(environment_namespace="env-k", principal_scope="user:local:k",
                     request_id="kill-1")
    if sys.argv[2] == "pre-intent":
        print("READY", flush=True); import time; time.sleep(30)
    store.reserve_request(key, "a" * 64)
    if sys.argv[2] == "post-intent":
        print("READY", flush=True); import time; time.sleep(30)
    store.append_receipt("kill-1", {{"delivery": "unknown"}})
    print("DONE")
""")

_SRC = str(Path(__file__).resolve().parents[1] / "src")


def _kill_at_window(tmp_path, window: str) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", _KILL_SCRIPT.format(src=_SRC), str(tmp_path / "k.sqlite3"), window],
        stdout=subprocess.PIPE, text=True,
    )
    line = proc.stdout.readline().strip()
    assert line == "READY"
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)


def test_kill_before_intent_leaves_no_record(tmp_path):
    _kill_at_window(tmp_path, "pre-intent")
    store = SqliteStorePort(tmp_path / "k.sqlite3", allow_takeover=True)  # dead writer, evidence = SIGKILL
    assert store.lookup_history("kill-1") is None
    store.close()


def test_kill_after_intent_keeps_claim_with_unknown_outcome(tmp_path):
    _kill_at_window(tmp_path, "post-intent")
    store = SqliteStorePort(tmp_path / "k.sqlite3", allow_takeover=True)
    history = store.lookup_history("kill-1")
    assert history is not None
    # the claim survives; re-claiming the same key+digest is a replay, a
    # different digest is a conflict — the unknown is never resent
    assert store.reserve_request(
        RequestKey(environment_namespace="env-k", principal_scope="user:local:k",
                   request_id="kill-1"), "a" * 64)
    with pytest.raises(KeyConflictError):
        store.reserve_request(
            RequestKey(environment_namespace="env-k", principal_scope="user:local:k",
                       request_id="kill-1"), "b" * 64)
    store.close()


# -- sealed legacy schema (T005-02) --------------------------------------------


def test_archived_schema_replays_readonly_and_refuses_future(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    count = replay_archived_migrations(db, ARCHIVED)
    assert count == 9
    reader = LegacyCompatReader(db)
    reader.check_supported()
    tables = reader.tables()
    assert tables, "sealed schema must have tables"
    counts = reader.neutral_counts()
    assert all(v == 0 for v in counts.values())
    # the sealed file is byte-identical after a read-only session
    before = db.read_bytes()
    reader.close()
    assert db.read_bytes() == before
    # a FUTURE version row refuses
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS agentbox_product_schema (singleton INTEGER PRIMARY KEY CHECK (singleton=1), version INTEGER NOT NULL, applied_at TEXT)")
    conn.execute("INSERT OR REPLACE INTO agentbox_product_schema VALUES (1, 99, 'future')")
    conn.commit(); conn.close()
    reader2 = LegacyCompatReader(db)
    with pytest.raises(LegacySchemaError, match="newer"):
        reader2.check_supported()


# -- fingerprint port + rotation tombstones (T005-04/07) -----------------------


def test_fingerprint_rotation_tombstone_blocks_and_comparison_goes_unavailable(tmp_path):
    store = SqliteStorePort(tmp_path / "fp.sqlite3")
    port = ProtectedFingerprintHmac(
        {"k-1": b"old-material"}, active_key_id="k-1",
        tombstone_check=store.has_key_tombstone,
    )
    assert store.reserve_request(_key("r-4"), "c" * 64)  # the request is spent
    mac = port.fingerprint(_key("r-4"), "binding", "c" * 64)
    assert port.verify("k-1", mac, _key("r-4"), "binding", "c" * 64)

    # rotation: new key mints a new id; comparing under the OLD id still works
    port.rotate("k-2", b"new-material")
    assert port.describe().key_id == "k-2"
    assert port.verify("k-1", mac, _key("r-4"), "binding", "c" * 64)

    # the old key is RETIRED (tombstoned): comparisons go unavailable while
    # the tombstone keeps the request spent
    store.record_key_tombstone("k-1")
    with pytest.raises(ComparisonUnavailableError, match="tombstone"):
        port.verify("k-1", mac, _key("r-4"), "binding", "c" * 64)
    with pytest.raises(KeyConflictError):
        store.reserve_request(_key("r-4"), "different-digest")  # never resent
    store.close()
