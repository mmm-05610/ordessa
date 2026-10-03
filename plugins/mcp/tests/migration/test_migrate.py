"""T09 migrate: adopt under the OLD digest, byte-faithful copies, binding →
McpAssignment, idempotent re-run, honest dry-run plan, legacy byte-frozen.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from legacy_sample import build_legacy_dataset
from ordessa_server_compat.assets import mcp as legacy

from backend.assignment import McpAssignmentStore
from backend.definition_store import McpDefinitionStore
from backend.migration import (
    LEGACY_SERVER_SCOPE,
    MIGRATION_SOURCE,
    migrate,
    profile_principal,
    snapshot_tree,
)


@pytest.fixture
def stack(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    return {
        "dataset": dataset,
        "db_path": dataset.db_path,
        "assets_root": dataset.assets_root,
        "target_root": tmp_path / "new-mcp-root",
    }


def _op(result, op):
    return [a for a in result["actions"] if a["op"] == op]


def test_migrate_copies_bytes_verbatim_and_adopts_under_the_old_digest(stack):
    result = migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    assert result["dry_run"] is False
    assert result["changed"] > 0
    assert not any(a["status"] == "refused" for a in result["actions"])
    definitions = McpDefinitionStore(stack["target_root"])
    fs_local = definitions.get_definition(
        server_scope=LEGACY_SERVER_SCOPE, definition_id="fs-local")
    assert (fs_local.transport, fs_local.native_name, fs_local.latest_revision) \
        == ("stdio", "fs-local", 2)
    for asset_id, revision in [("fs-local", 1), ("fs-local", 2),
                               ("env-ref-srv", 1), ("remote-weather", 1)]:
        target = definitions.revision_dir(asset_id, revision) / "server.json"
        source = stack["assets_root"] / "mcp" / asset_id / str(revision) / "server.json"
        # same relative path, byte-for-byte, never re-serialised
        assert target.read_bytes() == source.read_bytes()
        revision_view = definitions.read_revision(
            server_scope=LEGACY_SERVER_SCOPE, definition_id=asset_id, revision=revision)
        assert revision_view.canonical_shape == "legacy"
        assert revision_view.source == MIGRATION_SOURCE
        # the registered digest IS the legacy digest column / file digest
        assert revision_view.canonical_digest == \
            stack["dataset"].facts[f"{asset_id}@{revision}"]["digest"]
    # the copied files still verify under the OLD legacy store's rules
    legacy_store = legacy.McpAssetStore(stack["target_root"])
    assert legacy_store.verify(asset_id="remote-weather", revision=1,
                               expected_digest=stack["dataset"].facts["remote-weather@1"]["digest"])


def test_bindings_become_profile_assignments(stack):
    migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    assignments = McpAssignmentStore(stack["target_root"],
                                     McpDefinitionStore(stack["target_root"]))
    alpha = assignments.list_for(server_scope=LEGACY_SERVER_SCOPE,
                                 principal=profile_principal("p-alpha"))
    by_id = {a.definition_id: a for a in alpha}
    fs = by_id["fs-local"]
    assert (fs.decision, fs.approved_revision, fs.scope_kind, fs.scope_id) \
        == ("enable", 1, "profile", "p-alpha")
    # allObserved frozen on the legacy joined digest (the rev-2 row digest,
    # exactly what AssetRecords.bindings reports for this binding)
    assert fs.tool_selection.mode == "allObserved"
    assert fs.tool_selection.catalog_digest == stack["dataset"].facts["fs-local@2"]["digest"]
    # the adopted revision carries an approval (enable needs one; the legacy
    # binding is the approval evidence, so the migration records it)
    definitions = McpDefinitionStore(stack["target_root"])
    assert definitions.read_revision(
        server_scope=LEGACY_SERVER_SCOPE, definition_id="fs-local",
        revision=1).approval is not None
    beta = {a.definition_id: a for a in assignments.list_for(
        server_scope=LEGACY_SERVER_SCOPE, principal=profile_principal("p-beta"))}
    # legacy binding with enabled=0 must NOT be invented into an enable
    disabled = beta["env-ref-srv"]
    assert disabled.decision == "disable"
    assert disabled.approved_revision is None
    assert disabled.tool_selection is None
    assert beta["remote-weather"].decision == "enable"


def test_rerun_is_a_zero_change_replay(stack):
    first = migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    target_after_first = snapshot_tree(stack["target_root"])
    second = migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    assert second["changed"] == 0
    assert all(a["status"] in ("unchanged", "refused") for a in second["actions"])
    assert {a["op"] for a in second["actions"]} >= {"copy-revision", "adopt", "assign"}
    assert snapshot_tree(stack["target_root"]) == target_after_first
    assert first["changed"] > 0


def test_dry_run_plans_everything_and_writes_nothing(stack):
    result = migrate(stack["db_path"], stack["assets_root"], stack["target_root"],
                     dry_run=True)
    assert result["dry_run"] is True
    assert result["changed"] > 0
    assert all(a["status"] in ("planned", "refused") for a in result["actions"])
    ops = sorted((a["op"], str(a.get("asset_id", "")), str(a.get("profile_id", "")))
                 for a in result["actions"] if a["status"] == "planned")
    assert not Path(stack["target_root"]).exists()
    real = migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    applied = sorted((a["op"], str(a.get("asset_id", "")), str(a.get("profile_id", "")))
                     for a in real["actions"] if a["status"] == "applied")
    assert ops == applied  # the plan was exactly what the real run did


def test_legacy_side_is_byte_frozen_through_full_migration_and_scans(stack):
    from backend.migration import scan_legacy

    def legacy_state():
        return {"data_root": snapshot_tree(stack["dataset"].data_root),
                "assets_root": snapshot_tree(stack["assets_root"])}

    before = legacy_state()
    migrate(stack["db_path"], stack["assets_root"], stack["target_root"], dry_run=True)
    migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    scan_legacy(stack["db_path"], stack["assets_root"])
    migrate(stack["db_path"], stack["assets_root"], stack["target_root"])
    assert legacy_state() == before


def test_target_root_must_be_independent_of_legacy_root(stack):
    with pytest.raises(ValueError):
        migrate(stack["db_path"], stack["assets_root"], stack["assets_root"])
