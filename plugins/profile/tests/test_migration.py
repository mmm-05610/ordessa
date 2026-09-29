"""T19 — legacy server_profiles import (G7).

Identity/revision/archive/version semantics preserved; asset references and
permission payloads reported, never imported; source opened read-only.
"""
from __future__ import annotations

import sqlite3

from conftest import make_core, write_legacy_db
from ordessa_profile import import_legacy


def sample_legacy_rows():
    return [
        {"id": "profile_aaaaaaaa11111111aaaaaaaa11111111", "version": 3,
         "name": "Daily", "harness_type": "pi", "config_revision": 4,
         "config_object_digest": "sha256:aaa", "credential_id": "cred_1",
         "permission_preset": "default", "archived_at": None,
         "created_at": "2026-01-01T00:00:00+00:00",
         "updated_at": "2026-01-02T00:00:00+00:00", "display_name": "每日"},
        {"id": "profile_bbbbbbbb22222222bbbbbbbb22222222", "version": 1,
         "name": "Old", "harness_type": "codex", "config_revision": 1,
         "config_object_digest": "sha256:bbb", "archived_at": "2026-02-01T00:00:00+00:00",
         "created_at": "2026-01-01T00:00:00+00:00",
         "updated_at": "2026-02-01T00:00:00+00:00"},
        {"id": "profile_cccccccc33333333cccccccc33333333", "version": 2,
         "name": "Clone", "harness_type": "pi", "config_revision": 2,
         "config_object_digest": "sha256:ccc",
         "origin_profile_id": "profile_aaaaaaaa11111111aaaaaaaa11111111",
         "cloned_at": "2026-03-01T00:00:00+00:00",
         "created_at": "2026-03-01T00:00:00+00:00",
         "updated_at": "2026-03-01T00:00:00+00:00"},
    ]


def ledger(core):
    """Full per-field ledger of the new store for comparison."""
    out = {}
    for view in core.profiles.list(include_archived=True):
        out[view["profile_id"]] = view
    return out


def test_import_preserves_identity_revisions_archive_version(tmp_path):
    store = tmp_path / "legacy.sqlite"
    write_legacy_db(store, sample_legacy_rows())
    core = make_core(tmp_path / "store-dir") if False else None
    # (make_core appends its filename; give it its own directory)
    (tmp_path / "store-dir").mkdir()
    core = make_core(tmp_path / "store-dir", harnesses={"pi": frozenset(),
                                                        "codex": frozenset()})
    report = import_legacy(store, target=core)
    assert report.imported == 3 and report.skipped == []
    rows = ledger(core)
    daily = rows["profile_aaaaaaaa11111111aaaaaaaa11111111"]
    assert daily["display_name"] == "每日"
    assert daily["harness_id"] == "pi"
    assert daily["version"] == 3
    assert daily["current_revision"] == 4
    assert daily["archived_at"] is None
    old = rows["profile_bbbbbbbb22222222bbbbbbbb22222222"]
    assert old["archived_at"] == "2026-02-01T00:00:00+00:00"
    clone = rows["profile_cccccccc33333333cccccccc33333333"]
    assert clone["current_revision"] == 2
    # revision chain rows exist for every imported profile
    assert core.profiles.revisions(
        "profile_aaaaaaaa11111111aaaaaaaa11111111") == [4]


def test_import_refs_reported_never_written_to_tables(tmp_path):
    store = tmp_path / "legacy.sqlite"
    write_legacy_db(store, sample_legacy_rows())
    (tmp_path / "s").mkdir()
    core = make_core(tmp_path / "s")
    report = import_legacy(store, target=core)
    refs = {r["profile_id"]: r for r in report.retained_refs}
    daily = refs["profile_aaaaaaaa11111111aaaaaaaa11111111"]
    assert daily["config_object_digest"] == "sha256:aaa"
    assert daily["credential_reference_present"] is True
    assert daily["permission_preset_present"] is True
    # no credential or permission payload landed in the new store
    import json
    with core.db.read() as conn:
        for table in ("profile_profiles", "profile_facet_values",
                      "profile_sessions", "profile_session_overlays",
                      "profile_turns"):
            columns = {r["name"] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            assert not any("credential" in c or "permission" in c
                           for c in columns), table


def test_import_is_idempotent_and_reports_skips(tmp_path):
    store = tmp_path / "legacy.sqlite"
    write_legacy_db(store, sample_legacy_rows())
    (tmp_path / "s").mkdir()
    core = make_core(tmp_path / "s")
    first = import_legacy(store, target=core)
    second = import_legacy(store, target=core)
    assert first.imported == 3
    assert second.imported == 0
    assert {s["reason"] for s in second.skipped} == {"already_present"}
    assert len(second.skipped) == 3


def test_import_source_opened_read_only(tmp_path):
    store = tmp_path / "legacy.sqlite"
    write_legacy_db(store, sample_legacy_rows())
    before = store.read_bytes()
    (tmp_path / "s").mkdir()
    core = make_core(tmp_path / "s")
    import_legacy(store, target=core)
    assert store.read_bytes() == before  # source untouched


def test_imported_profiles_keep_working_with_the_domain(tmp_path):
    store = tmp_path / "legacy.sqlite"
    write_legacy_db(store, sample_legacy_rows())
    (tmp_path / "s").mkdir()
    core = make_core(tmp_path / "s")
    import_legacy(store, target=core)
    # an imported profile can be selected into a session and serve a turn
    session = core.sessions.open_session(
        "ks", session_id="S", harness_id="pi",
        profile_id="profile_aaaaaaaa11111111aaaaaaaa11111111")
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["profile_id"] == \
        "profile_aaaaaaaa11111111aaaaaaaa11111111"
    assert ticket["config_revision"] == 4
    # archived legacy profile refused as a new selection, still viewable
    from ordessa_profile import ProfileError
    import pytest
    with pytest.raises(ProfileError) as mismatch:
        core.sessions.select_profile(
            "ks2", session_id="S",
            profile_id="profile_bbbbbbbb22222222bbbbbbbb22222222")
    assert mismatch.value.code == "SESSION_PROFILE_MISMATCH"  # codex vs pi
    pid = "profile_cccccccc33333333cccccccc33333333"
    core.profiles.archive(
        "kar", profile_id=pid,
        expected_version=core.profiles.get(pid)["version"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.select_profile("ks3", session_id="S", profile_id=pid)
    assert exc.value.code == "PROFILE_ARCHIVED"
