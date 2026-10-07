"""T09 query equivalence: for the same legacy database, the migrated
assignment view maps 1:1 onto ``AssetRecords.bindings(profile_id)`` —
field names may differ, values/ids/digests must be equal (pinned here).
"""
from __future__ import annotations

from legacy_sample import PROFILES, build_legacy_dataset

from backend.migration import (
    LEGACY_SERVER_SCOPE,
    assignment_equivalence,
    migrate,
    verify_migrated_digests,
)


def test_binding_rows_and_assignment_view_agree_field_by_field(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    target = tmp_path / "target"
    result = migrate(dataset.db_path, dataset.assets_root, target)
    assert not any(v for group in result["refusals"].values() for v in group)
    for profile_id in PROFILES:
        legacy_rows = dataset.records.bindings(profile_id)  # the REAL old query
        rows = assignment_equivalence(
            legacy_rows, target_root=target, server_scope=LEGACY_SERVER_SCOPE,
            profile_id=profile_id)
        assert len(rows) == len(legacy_rows)
        for row in rows:
            assert row["present"] is True, row
            equal = row["equal"]
            legacy_view = row["legacy"]
            migrated = row["migrated"]
            # ids
            assert equal["assetId==definition_id"] is True
            assert legacy_view["assetId"] == migrated["definition_id"]
            assert migrated["scope_id"] == profile_id
            # kind -> existence of the migrated mcp definition
            assert equal["kind==mcp-definition-exists"] is True
            # names
            assert equal["name==native_name"] is True
            assert legacy_view["name"] == migrated["native_name"]
            # enabled -> decision
            assert equal["enabled==decision"] is True
            assert migrated["decision"] == ("enable" if legacy_view["enabled"]
                                            else "disable")
            # revision / digest: equal on enabled rows; a legacy disable is a
            # mask in the new model (no revision/digest to carry, honestly
            # reported as "masked", never silently enabled)
            if legacy_view["enabled"]:
                assert equal["revision==approved_revision"] is True
                assert legacy_view["revision"] == migrated["approved_revision"]
                assert equal["digest==toolSelection.catalogDigest"] is True
                assert legacy_view["digest"] == \
                    migrated["tool_selection"]["catalog_digest"]
                assert migrated["tool_selection"]["mode"] == "allObserved"
            else:
                assert equal["revision==approved_revision"] == "masked"
                assert equal["digest==toolSelection.catalogDigest"] == "masked"
                assert migrated["tool_selection"] is None


def test_migrated_bytes_still_verify_under_the_legacy_digest_view(tmp_path):
    """Where the legacy digest column attests exactly the bound revision
    (revision == latest), the migrated file verifies against that digest;
    the known legacy view quirk (binding on an older revision joined with
    the newer row digest) is pinned as NOT verifying, so the equivalence
    table above is read for what it is and not overclaimed."""
    dataset = build_legacy_dataset(tmp_path)
    target = tmp_path / "target"
    migrate(dataset.db_path, dataset.assets_root, target)
    for profile_id in PROFILES:
        checks = verify_migrated_digests(
            dataset.records.bindings(profile_id), target_root=target,
            server_scope=LEGACY_SERVER_SCOPE, profile_id=profile_id)
        for check in checks:
            if check["asset_id"] == "fs-local":
                # legacy quirk: digest column is revision 2's, binding is on 1
                assert check["verified"] is False
            else:
                assert check["verified"] is True, check


def test_equivalence_covers_every_binding_row_of_both_profiles(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    target = tmp_path / "target"
    migrate(dataset.db_path, dataset.assets_root, target)
    total = sum(len(assignment_equivalence(
        dataset.records.bindings(profile_id), target_root=target,
        server_scope=LEGACY_SERVER_SCOPE, profile_id=profile_id))
        for profile_id in PROFILES)
    legacy_total = sum(len(dataset.records.bindings(profile_id))
                       for profile_id in PROFILES)
    assert total == legacy_total == 5
