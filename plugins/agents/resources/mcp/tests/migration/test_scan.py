"""T09 scan inventory: the legacy truth is reported as found, nothing fixed.

The sample is rebuilt with raw SQL and the live definition digest (see
``legacy_sample.py``) because the retired ``ordessa_server_compat`` pieces that
used to produce it are gone; the expectations below are still byte-level facts
of the legacy layout the tool reads.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from legacy_sample import (
    PROFILES,
    SKILL_ASSET_ID,
    build_digest_mismatch_dataset,
    build_legacy_dataset,
    build_name_mismatch_dataset,
)

from backend.definition import canonical_definition, definition_digest
from backend.migration import scan_legacy


def _assets_by_id(scan):
    return {asset["asset_id"]: asset for asset in scan["assets"]}


def test_scan_lists_every_mcp_asset_row_and_skips_other_kinds(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    assert sorted(_assets_by_id(scan)) == ["env-ref-srv", "fs-local", "remote-weather"]
    assert scan["profiles"] == ["p-alpha", "p-beta"]
    # the fixture really carries a non-mcp catalogue row and a live binding on
    # it (p-alpha then has three legacy bindings) - the scan reports mcp only
    assert len(dataset.bindings("p-alpha")) == 3
    assert {row["kind"] for row in dataset.bindings("p-alpha")} == {"mcp", "skill"}
    assert {asset["kind"] for asset in scan["assets"]} == {"mcp"}
    assert [b for b in scan["bindings"] if b["asset_id"] == SKILL_ASSET_ID] == []
    # every mcp binding is reported with its joined digest: 5 rows
    assert len(scan["bindings"]) == 5
    assert len(scan["bindings"]) == sum(
        len(dataset.mcp_bindings(profile_id)) for profile_id in PROFILES)
    assert scan["refusals"]["digest-mismatch"] == []
    assert scan["refusals"]["dangling-binding"] == []


def test_legacy_binding_view_is_the_raw_join_the_tool_reads(tmp_path):
    """Fixture fidelity: the quarantine fixture's ``bindings()`` is re-derived
    here straight from SQLite with the tool's own join, so the equivalence
    tests below really compare against legacy rows, not fixture opinions."""
    dataset = build_legacy_dataset(tmp_path)
    conn = sqlite3.connect(str(dataset.db_path))
    conn.row_factory = sqlite3.Row
    try:
        raw = conn.execute(
            "SELECT b.profile_id, b.asset_id, b.revision, b.enabled, a.kind,"
            " a.name, a.digest FROM server_profile_assets b"
            " JOIN server_assets a ON a.id=b.asset_id WHERE a.kind='mcp'"
            " ORDER BY b.profile_id, b.asset_id").fetchall()
    finally:
        conn.close()
    assert len(raw) == 5
    for profile_id in PROFILES:
        profile_raw = [row for row in raw if row["profile_id"] == profile_id]
        view = {row["assetId"]: row for row in dataset.mcp_bindings(profile_id)}
        assert sorted(view) == sorted(row["asset_id"] for row in profile_raw)
        for row in profile_raw:
            fixture_row = view[row["asset_id"]]
            assert (fixture_row["name"], fixture_row["revision"], fixture_row["enabled"],
                    fixture_row["digest"]) == (
                row["name"], int(row["revision"]), bool(row["enabled"]), row["digest"])
    # the quirk is in the raw data itself: fs-local bindings sit on revision 1
    # while the joined digest column is revision 2's
    old = [row for row in raw if row["asset_id"] == "fs-local"]
    assert old and all(int(row["revision"]) == 1 for row in old)
    assert old[0]["digest"] == dataset.facts["fs-local@2"]["digest"]


def test_digest_column_is_cross_checked_against_legacy_definition_digest(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    fs_local = _assets_by_id(scan)["fs-local"]
    rev1, rev2 = fs_local["revisions"]
    assert (rev1["revision"], rev1["status"]) == (1, "unattested")
    assert (rev2["revision"], rev2["status"]) == (2, "attested")
    assert rev1["file_digest"] == dataset.facts["fs-local@1"]["digest"]
    assert rev2["file_digest"] == dataset.facts["fs-local@2"]["digest"]
    # the live definition module recomputes the attested file's digest exactly
    # (successor of the retired McpAssetStore.verify pin: same bytes, same rule)
    on_disk = json.loads(Path(rev2["path"]).read_text(encoding="utf-8"))
    assert definition_digest(canonical_definition(on_disk)) == fs_local["digest"]
    assert rev2["name"] == fs_local["name"]
    assert fs_local["status"] == "attested"


def test_binding_rows_carry_the_legacy_view_quirk_verbatim(tmp_path):
    """bindings to fs-local@1 JOIN the row digest of revision 2 - the old
    ``AssetRecords.bindings`` output did that, and the scan mirrors it."""
    dataset = build_legacy_dataset(tmp_path)
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    legacy_rows = {profile_id: dataset.mcp_bindings(profile_id) for profile_id in PROFILES}
    for binding in scan["bindings"]:
        legacy_row = next(
            row for row in legacy_rows[binding["profile_id"]]
            if row["assetId"] == binding["asset_id"])
        assert (binding["digest"], binding["revision"], binding["enabled"],
                binding["name"]) == (legacy_row["digest"], legacy_row["revision"],
                                     legacy_row["enabled"], legacy_row["name"])
        assert binding["file_status"] == "present"
    old = [b for b in scan["bindings"] if b["asset_id"] == "fs-local"]
    assert old and all(b["revision"] == 1 and b["file_status"] == "present" for b in old)
    assert old[0]["digest"] == dataset.facts["fs-local@2"]["digest"]


def test_digest_column_mismatch_is_listed_not_repaired(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    before = (dataset.assets_root / "mcp" / "remote-weather" / "1" / "server.json"
              ).read_bytes()
    dataset.mutate_rows("UPDATE server_assets SET digest=? WHERE id=?",
                        ("sha256:" + "0" * 64, "remote-weather"))
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    mismatch = scan["refusals"]["digest-mismatch"]
    assert [item["asset_id"] for item in mismatch] == ["remote-weather"]
    assert mismatch[0]["reason"] == "digest-column-differs-from-file"
    assert mismatch[0]["column_digest"] == "sha256:" + "0" * 64
    assert mismatch[0]["file_digest"] == dataset.facts["remote-weather@1"]["digest"]
    assert _assets_by_id(scan)["remote-weather"]["status"] == "digest-mismatch"
    # the scan reads only: the revision file is byte-unchanged afterwards
    assert (dataset.assets_root / "mcp" / "remote-weather" / "1" / "server.json"
            ).read_bytes() == before


def test_name_column_mismatch_is_listed_not_repaired(tmp_path):
    dataset = build_name_mismatch_dataset(tmp_path)
    before = (dataset.assets_root / "mcp" / "remote-weather" / "1" / "server.json"
              ).read_bytes()
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    asset = _assets_by_id(scan)["remote-weather"]
    assert (asset["status"], asset["refusal_reason"]) == \
        ("name-mismatch", "asset-name-differs-from-file")
    assert asset["name"] == "renamed-weather"
    assert asset["revisions"][0]["file_digest"] == \
        dataset.facts["remote-weather@1"]["digest"]  # the digest still matches
    # the scan groups every non-attested asset under the same refusal bucket,
    # but names the real reason and reports equal column/file digests
    listed = scan["refusals"]["digest-mismatch"]
    assert [item["asset_id"] for item in listed] == ["remote-weather"]
    assert listed[0]["reason"] == "asset-name-differs-from-file"
    assert listed[0]["column_digest"] == listed[0]["file_digest"]
    assert (dataset.assets_root / "mcp" / "remote-weather" / "1" / "server.json"
            ).read_bytes() == before


def test_missing_bound_revision_file_is_listed_as_dangling(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    (dataset.assets_root / "mcp" / "fs-local" / "1" / "server.json").unlink()
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    assert [item["asset_id"] for item in scan["refusals"]["dangling-binding"]] \
        == ["fs-local", "fs-local"]  # p-alpha and p-beta both reference rev1
    assert all(item["reason"] == "revision-file-missing-or-unreadable"
               for item in scan["refusals"]["dangling-binding"])
    # asset itself still attested through revision 2 (digest check is per row)
    assert _assets_by_id(scan)["fs-local"]["status"] == "attested"


def test_non_revision_entries_are_inventory_only(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    (dataset.assets_root / "mcp" / "fs-local" / "notes.txt").write_text(
        "not a revision", encoding="utf-8")
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    fs_local = _assets_by_id(scan)["fs-local"]
    assert fs_local["unexpected_entries"] == ["notes.txt"]
    assert [entry["revision"] for entry in fs_local["revisions"]] == [1, 2]
    assert fs_local["status"] == "attested"
    assert scan["refusals"]["digest-mismatch"] == []


def test_digest_mismatch_dataset_helper_matches_manual_surgery(tmp_path):
    dataset = build_digest_mismatch_dataset(tmp_path)
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    assert [item["asset_id"] for item in scan["refusals"]["digest-mismatch"]] \
        == ["remote-weather"]
