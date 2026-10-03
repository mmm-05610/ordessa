"""T09 refusal counterexamples: mismatched digests, dangling bindings,
colliding target revision directories and foreign assignment rows are
listed and LEFT ALONE - the migration never repairs or invents.
"""
from __future__ import annotations

from legacy_sample import (
    build_digest_mismatch_dataset,
    build_dangling_binding_dataset,
    build_legacy_dataset,
)
from ordessa_server_compat.assets import mcp as legacy  # noqa: F401 (boundary pin)

from backend.assignment import McpAssignmentStore
from backend.definition_store import McpDefinitionStore
from backend.migration import LEGACY_SERVER_SCOPE, migrate, profile_principal


def test_digest_mismatch_asset_is_refused_and_never_adopted(tmp_path):
    dataset = build_digest_mismatch_dataset(tmp_path)
    target = tmp_path / "target"
    result = migrate(dataset.db_path, dataset.assets_root, target)
    refused = result["refusals"]["digest-mismatch"]
    assert [item["asset_id"] for item in refused] == ["remote-weather"]
    assert refused[0]["reason"] == "digest-column-differs-from-file"
    assert any(a["op"] == "skip-asset" and a["asset_id"] == "remote-weather"
               and a["status"] == "refused" for a in result["actions"])
    definitions = McpDefinitionStore(target)
    # nothing was copied or registered for the refused asset...
    assert not (target / "mcp" / "remote-weather").exists()
    # ...while the healthy siblings still migrated.
    assert definitions.get_definition(
        server_scope=LEGACY_SERVER_SCOPE, definition_id="fs-local")
    # the binding on it is refused as blocked, NOT turned into an assignment
    assert [item["asset_id"] for item in result["refusals"]["blocked-asset"]] \
        == ["remote-weather"]
    assignments = McpAssignmentStore(target, definitions)
    rows = assignments.list_for(server_scope=LEGACY_SERVER_SCOPE,
                                principal=profile_principal("p-beta"))
    assert "remote-weather" not in {r.definition_id for r in rows}


def test_dangling_binding_is_refused_without_fabricated_content(tmp_path):
    dataset = build_dangling_binding_dataset(tmp_path)
    target = tmp_path / "target"
    result = migrate(dataset.db_path, dataset.assets_root, target)
    dangling = result["refusals"]["dangling-binding"]
    assert {(d["profile_id"], d["asset_id"], d["revision"]) for d in dangling} \
        == {("p-alpha", "fs-local", 1), ("p-beta", "fs-local", 1)}
    # the dangled revision was neither copied nor adopted; rev2 still was
    assert not (target / "mcp" / "fs-local" / "1").exists()
    assert (target / "mcp" / "fs-local" / "2" / "server.json").is_file()
    definitions = McpDefinitionStore(target)
    adopted = definitions._load_index()["definitions"]["fs-local"]["revisions"]
    assert list(adopted) == ["2"]
    # and the two dangling bindings produce no assignment rows (p-alpha's
    # only other binding, env-ref-srv, stays healthy and does migrate)
    assignments = McpAssignmentStore(target, definitions)
    alpha = assignments.list_for(server_scope=LEGACY_SERVER_SCOPE,
                                 principal=profile_principal("p-alpha"))
    assert {r.definition_id for r in alpha} == {"env-ref-srv"}
    beta = assignments.list_for(server_scope=LEGACY_SERVER_SCOPE,
                                principal=profile_principal("p-beta"))
    assert {r.definition_id for r in beta} == {"remote-weather", "env-ref-srv"}


def test_conflicting_target_revision_is_reported_unknown_and_not_overwritten(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    target = tmp_path / "target"
    clash = target / "mcp" / "remote-weather" / "1"
    clash.mkdir(parents=True)
    (clash / "server.json").write_bytes(b'{"not":"the legacy bytes"}')
    before = (clash / "server.json").read_bytes()
    result = migrate(dataset.db_path, dataset.assets_root, target)
    unknown = result["refusals"]["unknown"]
    assert any(item["reason"] == "target-revision-directory-conflict"
               and item["asset_id"] == "remote-weather" and item["overwritten"] is False
               for item in unknown)
    assert (clash / "server.json").read_bytes() == before  # never overwritten
    index = McpDefinitionStore(target)._load_index()
    assert "remote-weather" not in index["definitions"]  # refused adoption
    # the bound assignment must not be invented over an unadopted revision
    assert any(item["asset_id"] == "remote-weather" for item in unknown
               if item["reason"] == "revision-not-adopted")
    # the healthy assets are untouched by the clash and still migrate
    assert (target / "mcp" / "fs-local" / "2" / "server.json").is_file()


def test_existing_foreign_assignment_row_conflicts_without_clobber(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    target = tmp_path / "target"
    definitions = McpDefinitionStore(target)
    # seed: a foreign principal already owns p-beta/env-ref-srv via the real
    # assignment store (disable needs no approval surface)
    assignments = McpAssignmentStore(target, definitions)
    assignments.assign(
        server_scope=LEGACY_SERVER_SCOPE, principal="intruder", scope_kind="profile",
        scope_id="p-beta", harness=None, definition_id="env-ref-srv",
        decision="disable", expected_row_version=0, operation_key="seed-intruder")
    result = migrate(dataset.db_path, dataset.assets_root, target)
    conflicts = result["refusals"]["assignment-conflict"]
    assert [c["asset_id"] for c in conflicts] == ["env-ref-srv"]
    assert conflicts[0]["owner"] == "intruder"
    row = assignments.get(server_scope=LEGACY_SERVER_SCOPE, principal="intruder",
                          scope_kind="profile", scope_id="p-beta", harness="any",
                          definition_id="env-ref-srv")
    assert (row.principal, row.decision, row.row_version) == ("intruder", "disable", 1)
