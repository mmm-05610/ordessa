"""Storage migration v2 (PV-04, G17): incremental, idempotent, honest.

Old databases upgrade in place with ids/revisions preserved; canonical
session identity is backfilled deterministically; legacy "settled" history
is projected as legacy-unverified and can never become a receipt; collisions
refuse instead of merging.
"""
from __future__ import annotations

import sqlite3

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileCore, ProfileError, StaticHarnessCatalog
from ordessa_profile.storage import ProfileDatabase, _SCHEMA_V1

MODEL = ScriptedProvider("model_selection", ("model",))


def build_v1_store(path, *, sessions=()):
    """A genuine v1-shaped database (the pre-v2 schema, populated)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE profile_schema ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executescript(_SCHEMA_V1)
    conn.execute(
        "INSERT INTO profile_profiles(profile_id, version, display_name,"
        " harness_id, current_revision, archived_at, created_at, updated_at)"
        " VALUES ('profile_old1', 3, '旧配置', 'pi', 2, NULL,"
        " '2026-01-01T00:00:00+00:00', '2026-01-02T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO profile_revisions(profile_id, config_revision, created_at)"
        " VALUES ('profile_old1', 1, '2026-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO profile_revisions(profile_id, config_revision, created_at)"
        " VALUES ('profile_old1', 2, '2026-01-01T12:00:00+00:00')")
    conn.execute(
        "INSERT INTO profile_facet_values(profile_id, config_revision,"
        " facet_id, item_id, value_json, facet_version, quarantined,"
        " updated_at) VALUES ('profile_old1', 2, 'model_selection', 'model',"
        " '\"m1\"', '1.0.0', 0, '2026-01-01T12:00:00+00:00')")
    for sid, state, pending in sessions:
        conn.execute(
            "INSERT INTO profile_sessions(session_id, harness_id,"
            " current_profile_id, current_revision, pending_profile_id,"
            " pending_seq, switch_state, blockers_json, created_at,"
            " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "pi", "profile_old1", 2, pending, 1 if pending else None,
             state, None, '2026-01-01T00:00:00+00:00',
             '2026-01-01T00:00:00+00:00'))
    conn.execute(
        "INSERT INTO profile_schema(version, applied_at) VALUES (1, 'x')")
    conn.commit()
    conn.close()


def test_v1_store_upgrades_in_place_with_ids_preserved(tmp_path):
    path = tmp_path / "store.sqlite"
    build_v1_store(path, sessions=[("S-old", "settled", None)])
    db = ProfileDatabase(path)
    with db.read() as conn:
        versions = [int(r["version"]) for r in conn.execute(
            "SELECT version FROM profile_schema ORDER BY version")]
        profile = conn.execute(
            "SELECT * FROM profile_profiles WHERE profile_id='profile_old1'"
        ).fetchone()
        session = conn.execute(
            "SELECT * FROM profile_sessions WHERE session_id='S-old'"
        ).fetchone()
        value = conn.execute(
            "SELECT value_json FROM profile_facet_values WHERE"
            " profile_id='profile_old1' AND config_revision=2"
        ).fetchone()
    assert versions == [1, 2]  # only the missing step ran
    assert profile["version"] == 3 and profile["current_revision"] == 2
    assert profile["realm"] == "local"
    assert session["session_uid"] == "legacy:S-old"
    assert session["native_session_key"] == "S-old"
    assert value["value_json"] == '"m1"'  # stored values untouched
    db.close()


def test_upgrade_is_idempotent_when_run_twice(tmp_path):
    path = tmp_path / "store.sqlite"
    build_v1_store(path)
    db1 = ProfileDatabase(path)
    db1.close()
    db2 = ProfileDatabase(path)  # second run: no extra rows, no error
    with db2.read() as conn:
        rows = conn.execute(
            "SELECT version FROM profile_schema ORDER BY version").fetchall()
        assert [int(r["version"]) for r in rows] == [1, 2]
    db2.close()


def test_legacy_settled_projected_as_unverified_never_confirmed(tmp_path):
    path = tmp_path / "store.sqlite"
    build_v1_store(path, sessions=[("S-old", "settled", None)])
    core = ProfileCore(path, harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    config = core.sessions.session_config("S-old")
    assert config["switch_state"] == "settled"
    assert config["evidence"]["receipt"] is None
    assert config["evidence"]["evidence_kind"] == "legacy-unverified"
    # the v2 service layer can address the legacy row by uid and by old id
    assert core.sessions.session_config("legacy:S-old")["session_uid"] == \
        "legacy:S-old"


def test_legacy_pending_survives_migration_and_stays_pending(tmp_path):
    path = tmp_path / "store.sqlite"
    build_v1_store(path, sessions=[("S-old", "pending", "profile_old1")])
    core = ProfileCore(path, harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    config = core.sessions.session_config("S-old")
    assert config["switch_state"] == "pending"
    assert config["pending"]["profile_id"] == "profile_old1"


def test_collision_on_uid_refuses_instead_of_merging(tmp_path):
    path = tmp_path / "store.sqlite"
    build_v1_store(path, sessions=[("S-old", "settled", None)])
    core = ProfileCore(
        path, harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    # a new session claiming the migrated uid is refused, never merged
    with pytest.raises(ProfileError) as exc:
        core.sessions.open_session(
            "k1", session_id="S-new", harness_id="pi",
            profile_id="profile_old1", session_uid="legacy:S-old")
    assert exc.value.code == "PROFILE_VALUE_INVALID"
    # the migrated row keeps its identity
    assert core.sessions.session_config("S-old")["session_uid"] == \
        "legacy:S-old"


def test_v2_fresh_database_reaches_version_two(tmp_path):
    db = ProfileDatabase(tmp_path / "fresh.sqlite")
    with db.read() as conn:
        rows = conn.execute(
            "SELECT version FROM profile_schema ORDER BY version").fetchall()
    assert [int(r["version"]) for r in rows] == [1, 2]
    db.close()


def test_legacy_import_still_works_on_v2_store(tmp_path):
    """The v21 ``server_profiles`` import path keeps its semantics."""
    from conftest import write_legacy_db
    legacy = tmp_path / "legacy.sqlite"
    write_legacy_db(legacy, [{
        "id": "profile_from_v21", "version": 2, "name": "imported",
        "harness_type": "pi", "config_revision": 4,
        "config_object_digest": "sha256:legacy",
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }])
    core = ProfileCore(
        tmp_path / "store.sqlite",
        harnesses=StaticHarnessCatalog({"pi": frozenset()}),
        new_id=lambda prefix: f"{prefix}_x",
    )
    report = __import__("ordessa_profile.migration", fromlist=["import_legacy"]) \
        .import_legacy(legacy, target=core)
    assert report.imported == 1
    view = core.profiles.get("profile_from_v21")
    assert view["current_revision"] == 4  # revisions never collapse
    assert view["realm"] == "local"
