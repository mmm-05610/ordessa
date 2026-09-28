"""T02 — storage layer: schema ledger, transactions, idempotency account."""
from __future__ import annotations

import sqlite3

import pytest

from ordessa_profile.errors import ProfileError
from ordessa_profile.storage import ProfileDatabase
from ordessa_profile import repository as repo


def test_schema_steps_applied_once(tmp_path):
    # v2 (specs/011-z1-profile): migration is stepwise — a fresh database
    # records exactly one row per applied version; reopening adds none.
    path = tmp_path / "store.sqlite"
    db = ProfileDatabase(path)
    with db.read() as conn:
        version = conn.execute(
            "SELECT MAX(version) AS v FROM profile_schema").fetchone()["v"]
        rows = conn.execute(
            "SELECT version FROM profile_schema ORDER BY version").fetchall()
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert int(version) == 2
    assert [int(r["version"]) for r in rows] == [1, 2]
    assert {
        "profile_profiles", "profile_revisions", "profile_facet_values",
        "profile_sessions", "profile_session_overlays", "profile_turns",
        "profile_idempotency", "profile_mechanism_policy",
        "profile_application_journal", "profile_applied_receipts",
    } <= tables
    db.close()
    db2 = ProfileDatabase(path)  # reopen: no additional migration row
    with db2.read() as conn:
        rows = conn.execute("SELECT * FROM profile_schema").fetchall()
    assert len(rows) == 2
    db2.close()


def test_future_schema_refused(tmp_path):
    path = tmp_path / "store.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE profile_schema ("
                 "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO profile_schema VALUES (99, 'x')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer than supported"):
        ProfileDatabase(path)


def test_write_transaction_rolls_back(tmp_path):
    db = ProfileDatabase(tmp_path / "store.sqlite")
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO profile_profiles(profile_id, version, display_name,"
                " harness_id, current_revision, created_at, updated_at)"
                " VALUES ('p1',1,'n','pi',1,'t','t')")
            raise RuntimeError("boom")
    with db.read() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM profile_profiles").fetchone()["c"] == 0


def test_idempotency_account(tmp_path):
    db = ProfileDatabase(tmp_path / "store.sqlite")
    with db.transaction() as conn:
        assert repo.idempotency_check(conn, "scope", "k1", "d1") is None
        repo.idempotency_insert(conn, "scope", "k1", "d1", 200, {"a": 1}, "t")
        prior = repo.idempotency_check(conn, "scope", "k1", "d1")
        assert prior == {"status": 200, "response": {"a": 1}}
        with pytest.raises(ProfileError) as exc:
            repo.idempotency_check(conn, "scope", "k1", "d2")
        assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
