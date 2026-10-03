"""Directory snapshots: list first, install later, never touch bindings (AC-3).
Ported from `plugins/assets/tests/test_catalog_snapshot.py` @ 752f148b1b
with every assertion intact (G04: an install from a snapshot never moves a
binding; G03-adjacent: snapshot atomicity and pinned provenance).
"""
from __future__ import annotations

import json

import pytest

from ordessa_skills.api.errors import CatalogError
from ordessa_skills.library.catalog import CatalogStore, parse_index


def _make_source(root, origin="git:example.test/skills@main"):
    (root / "demo-skill").mkdir(parents=True)
    (root / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: A demo.\n---\nbody\n")
    index = {
        "schema_version": 1,
        "entries": [{"kind": "skill", "name": "demo-skill",
                     "path": "demo-skill", "origin": origin,
                     "description": "A demo."}],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return root


def _make_store(tmp_path):
    from pacthold_runtime_compat.storage import Database

    from ordessa_skills.library.records import AssetRecords
    database = Database(tmp_path / "data")
    database.initialize()
    return CatalogStore(tmp_path / "assets" / "catalogs"), AssetRecords(database)


def test_sync_writes_a_snapshot_with_a_canonical_digest(tmp_path):
    store, _records = _make_store(tmp_path)
    _make_source(tmp_path / "source")
    snapshot = store.sync(source_id="main", source_path=tmp_path / "source")
    assert snapshot["digest"].startswith("sha256:")
    assert snapshot["entries"][0]["name"] == "demo-skill"


def test_a_failed_sync_leaves_the_previous_snapshot_untouched(tmp_path):
    store, _records = _make_store(tmp_path)
    _make_source(tmp_path / "source")
    good = store.sync(source_id="main", source_path=tmp_path / "source")

    (tmp_path / "next").mkdir()
    (tmp_path / "next" / "index.json").write_text("{not json")
    with pytest.raises(CatalogError):
        store.sync(source_id="main", source_path=tmp_path / "next")
    assert store.snapshot("main") == good


def test_escaping_or_unknown_entries_are_refused(tmp_path):
    bad_index = {
        "schema_version": 1,
        "entries": [{"kind": "skill", "name": "esc", "path": "../outside",
                     "origin": "x"}],
    }
    with pytest.raises(CatalogError):
        parse_index(json.dumps(bad_index).encode())
    dup = {
        "schema_version": 1,
        "entries": [
            {"kind": "skill", "name": "a", "path": "a", "origin": "x"},
            {"kind": "skill", "name": "a", "path": "b", "origin": "x"},
        ],
    }
    with pytest.raises(CatalogError):
        parse_index(json.dumps(dup).encode())


def test_install_entry_pins_provenance_and_touches_no_binding(tmp_path):
    store, records = _make_store(tmp_path)
    _make_source(tmp_path / "source")
    snapshot = store.sync(source_id="main", source_path=tmp_path / "source")

    from pacthold_runtime_compat.storage import Database as DB
    database = DB(tmp_path / "data")
    records.publish(kind="skill", name="demo-skill", revision=1,
                    digest="sha256:" + "1" * 64, asset_id="demo-skill")
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
            "native_generation,config_object_digest,created_at,updated_at) "
            "VALUES ('profile_a',1,'role','pi',1,0,'sha256:x','t','t')")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)

    installed = store.install_entry(
        snapshot=snapshot, entry_name="demo-skill", revision=2, records=records)
    assert installed["source"].startswith(snapshot["digest"] + ":")
    assert installed["revision"] == 2
    # The install changed no binding row: profile_a stays pinned at revision 1.
    assert records.bindings("profile_a")[0]["revision"] == 1


def test_payload_must_stay_inside_the_snapshot_source(tmp_path):
    store, records = _make_store(tmp_path)
    _make_source(tmp_path / "source")
    snapshot = store.sync(source_id="main", source_path=tmp_path / "source")
    (tmp_path / "source" / "demo-skill" / "SKILL.md").unlink()
    with pytest.raises(CatalogError) as refusal:
        store.install_entry(snapshot=snapshot, entry_name="demo-skill",
                            revision=1, records=records)
    assert refusal.value.code == "CATALOG_SOURCE_MISSING"
