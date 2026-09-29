"""V02 gate: scope resolution order, approvals, tool subsets, principal
isolation, catalog drift and snapshot determinism."""
import json

import pytest

from backend.assignment import McpAssignmentStore
from backend.definition_store import McpDefinitionStore
from backend.errors import (
    MCP_CAS_CONFLICT,
    MCP_CATALOG_MISSING,
    MCP_DEFINITION_ARCHIVED,
    MCP_OPERATION_CONFLICT,
    MCP_OWNER_CONFLICT,
    MCP_REVISION_NOT_APPROVED,
    MCP_TOOL_NOT_OBSERVED,
    McpError,
)
from backend.resolve import resolve_preview

SCOPE = "scope-a"
PROJECT = "project-1"
PROFILE = "profile-rev-3"
CATALOG_1 = {"catalogDigest": "sha256:cat-1", "toolNames": ["fetch", "search"]}
CATALOG_DRIFT = {"catalogDigest": "sha256:cat-2", "toolNames": ["fetch", "search", "newtool"]}


@pytest.fixture
def stores(tmp_path):
    definitions = McpDefinitionStore(tmp_path / "defs")
    assignments = McpAssignmentStore(tmp_path / "assignments", definitions)
    return definitions, assignments


def _definition(def_id):
    return {"name": def_id, "transport": {"stdio": {
        "command": f"/bin/{def_id}", "args": [],
        "env": {"API_KEY": {"secretRef": "credential_1"}, "MODE": {"literal": "fast"}}}}}


def publish(definitions, def_id, *, revisions=1, approve_to=None, scope=SCOPE):
    try:
        current = definitions.get_definition(
            server_scope=scope, definition_id=def_id).latest_revision
    except McpError:
        current = 0
    for number in range(current + 1, revisions + 1):
        definitions.save_revision(
            server_scope=scope, definition_id=def_id, definition=_definition(def_id),
            expected_version=number - 1, operation_key=f"save-{scope}-{def_id}-{number}")
    for number in range(1, (approve_to if approve_to is not None else revisions) + 1):
        definitions.approve_revision(
            server_scope=scope, definition_id=def_id, revision=number, actor="admin-1")


def enable(store, def_id, *, principal="alice", scope_kind="user-default", scope_id=None,
           harness=None, revision=1, selection=None, catalog=CATALOG_1,
           expected_row_version=0, key=None):
    return store.assign(
        server_scope=SCOPE, principal=principal, scope_kind=scope_kind,
        scope_id=scope_id if scope_id is not None else principal,
        harness=harness, definition_id=def_id, decision="enable",
        approved_revision=revision,
        tool_selection=selection if selection is not None else {
            "mode": "allowNames", "names": ["search"], "catalogDigest": "sha256:cat-1"},
        observed_catalog=catalog, expected_row_version=expected_row_version,
        operation_key=key or f"enable-{scope_kind}-{scope_id}-{harness}-{def_id}")


def decide_off(store, def_id, *, principal="alice", scope_kind="user-default",
               scope_id=None, harness=None, decision="disable", expected_row_version=0,
               key=None):
    return store.assign(
        server_scope=SCOPE, principal=principal, scope_kind=scope_kind,
        scope_id=scope_id if scope_id is not None else principal,
        harness=harness, definition_id=def_id, decision=decision,
        expected_row_version=expected_row_version,
        operation_key=key or f"{decision}-{scope_kind}-{scope_id}-{harness}-{def_id}")


def enabled_ids(snapshot):
    return [entry["definition_id"] for entry in snapshot.definition_revisions]


# -- resolution order ----------------------------------------------------------------


def test_the_six_layers_resolve_in_documented_order(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions, harness="h1", project_id=PROJECT,
                profile_revision=PROFILE, session_ref="session-A")

    enable(assignments, "web-tools")
    assert enabled_ids(resolve_preview(**base)) == ["web-tools"]

    decide_off(assignments, "web-tools", scope_kind="user-default", harness="h1", key="off-duh")
    assert enabled_ids(resolve_preview(**base)) == []
    assert enabled_ids(resolve_preview(**{**base, "harness": "h2"})) == ["web-tools"]

    enable(assignments, "web-tools", scope_kind="project", scope_id=PROJECT,
           expected_row_version=0, key="on-proj")
    assert enabled_ids(resolve_preview(**base)) == ["web-tools"]

    decide_off(assignments, "web-tools", scope_kind="project", harness="h1",
               scope_id=PROJECT, key="off-projh")
    assert enabled_ids(resolve_preview(**base)) == []

    enable(assignments, "web-tools", scope_kind="profile", scope_id=PROFILE, key="on-prof")
    assert enabled_ids(resolve_preview(**base)) == ["web-tools"]

    decide_off(assignments, "web-tools", scope_kind="session", scope_id="session-A",
               key="off-sess")
    assert enabled_ids(resolve_preview(**base)) == []
    # a session without an override still sees the profile enable
    assert enabled_ids(resolve_preview(**{**base, "session_ref": "session-B"})) == ["web-tools"]


def test_disable_then_reenable_by_explicit_profile_approval(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    publish(definitions, "web-tools", revisions=2, approve_to=1)  # rev2 unapproved
    enable(assignments, "web-tools")
    decide_off(assignments, "web-tools", scope_kind="project", scope_id=PROJECT, key="off-p")
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions, project_id=PROJECT)
    assert enabled_ids(resolve_preview(**base)) == []
    enable(assignments, "web-tools", scope_kind="profile", scope_id=PROFILE, key="on-pf")
    snapshot = resolve_preview(**{**base, "profile_revision": PROFILE})
    assert snapshot.definition_revisions[0]["revision"] == 1


# -- approvals and upgrades -----------------------------------------------------------


def test_unapproved_revision_never_reaches_the_effective_snapshot(stores, tmp_path):
    definitions, assignments = stores
    publish(definitions, "web-tools", revisions=1)
    publish(definitions, "web-tools", revisions=2, approve_to=1)  # rev2 saved, unapproved
    with pytest.raises(McpError) as refused:
        enable(assignments, "web-tools", revision=2, key="bad")
    assert refused.value.code == MCP_REVISION_NOT_APPROVED

    enable(assignments, "web-tools", revision=1, key="good")
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions)
    snapshot = resolve_preview(**base)
    assert (snapshot.definition_revisions[0]["revision"],
            snapshot.definition_revisions[0]["canonical_digest"]) == (1, _digest_at(definitions, 1))
    # saving a newer revision does not move the assignment pointer
    publish(definitions, "web-tools", revisions=3, approve_to=2)
    assert resolve_preview(**base).definition_revisions[0]["revision"] == 1
    # a tampered row pointing at an unapproved revision is excluded, not trusted
    table_path = tmp_path / "assignments" / "assignments" / "assignments.json"
    table = json.loads(table_path.read_text(encoding="utf-8"))
    for row in table["rows"].values():
        row["approved_revision"] = 99
    table_path.write_text(json.dumps(table), encoding="utf-8")
    assert enabled_ids(resolve_preview(**base)) == []
    # only the explicit approve + re-assign upgrades the binding
    definitions.approve_revision(server_scope=SCOPE, definition_id="web-tools",
                                 revision=3, actor="admin-1")
    enable(assignments, "web-tools", revision=3, expected_row_version=1, key="upgrade")
    assert resolve_preview(**base).definition_revisions[0]["revision"] == 3


def _digest_at(definitions, revision):
    return definitions.read_revision(
        server_scope=SCOPE, definition_id="web-tools", revision=revision).canonical_digest


# -- principal / serverScope isolation ---------------------------------------------------


def test_same_layer_other_principal_conflicts_and_cannot_read_or_preview(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", scope_kind="project", scope_id=PROJECT, key="a-on")
    with pytest.raises(McpError) as clash:
        enable(assignments, "web-tools", principal="mallory", scope_kind="project",
               scope_id=PROJECT, key="m-on")
    assert clash.value.code == MCP_OWNER_CONFLICT
    with pytest.raises(McpError) as peek:
        assignments.get(server_scope=SCOPE, principal="mallory", scope_kind="project",
                        scope_id=PROJECT, harness=None, definition_id="web-tools")
    assert peek.value.code == MCP_OWNER_CONFLICT
    stolen = resolve_preview(server_scope=SCOPE, principal="mallory",
                             assignments=assignments, definitions=definitions,
                             project_id=PROJECT)
    assert enabled_ids(stolen) == []


MCP_ASSET_MISSING_ERROR = "MCP_ASSET_MISSING"


def test_cross_server_scope_assignment_is_refused(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    with pytest.raises(McpError) as refused:
        assignments.assign(
            server_scope="scope-b", principal="alice", scope_kind="user-default",
            scope_id="alice", harness=None, definition_id="web-tools", decision="enable",
            approved_revision=1, tool_selection={"mode": "allowNames", "names": ["search"],
                                                 "catalogDigest": "sha256:cat-1"},
            observed_catalog=CATALOG_1, expected_row_version=0, operation_key="b-steal")
    assert refused.value.code == MCP_ASSET_MISSING_ERROR


def test_session_override_never_writes_back_to_profile(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", scope_kind="profile", scope_id=PROFILE, key="on-prof")
    decide_off(assignments, "web-tools", scope_kind="session", scope_id="session-A",
               key="off-sa")
    row = assignments.get(server_scope=SCOPE, principal="alice", scope_kind="profile",
                         scope_id=PROFILE, harness=None, definition_id="web-tools")
    assert row.decision == "enable" and row.row_version == 1
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions, profile_revision=PROFILE)
    assert enabled_ids(resolve_preview(**base, session_ref="session-B")) == ["web-tools"]
    assert enabled_ids(resolve_preview(**base, session_ref="session-A")) == []


# -- tool subsets and catalog drift ---------------------------------------------------------


def test_allownames_must_come_from_the_observed_catalog(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    with pytest.raises(McpError) as refused:
        enable(assignments, "web-tools", selection={"mode": "allowNames",
                                                    "names": ["search", "not-observed"],
                                                    "catalogDigest": "sha256:cat-1"},
               key="bad-names")
    assert refused.value.code == MCP_TOOL_NOT_OBSERVED
    with pytest.raises(McpError) as nocat:
        enable(assignments, "web-tools", catalog=None, key="nocat")
    assert nocat.value.code == MCP_CATALOG_MISSING


def test_all_observed_binds_current_digest_and_drift_only_flags_revalidation(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    with pytest.raises(McpError) as stale_bind:
        enable(assignments, "web-tools", selection={"mode": "allObserved",
                                                    "names": ["fetch", "search"],
                                                    "catalogDigest": "sha256:old"},
               key="stale")
    assert stale_bind.value.code == MCP_CATALOG_MISSING
    enable(assignments, "web-tools", selection={"mode": "allObserved",
                                                "names": ["fetch", "search"],
                                                "catalogDigest": "sha256:cat-1"},
           key="bound")
    drifting = dict(
        server_scope=SCOPE, principal="alice", assignments=assignments,
        definitions=definitions,
        catalog_provider=lambda did, rev: CATALOG_DRIFT)
    snapshot = resolve_preview(**drifting)
    assert snapshot.needs_revalidation == ("web-tools",)
    assert set(snapshot.allowed_tool_names) == {"fetch", "search"}  # no newtool
    stable = resolve_preview(**{**drifting,
                                "catalog_provider": lambda did, rev: CATALOG_1})
    assert stable.needs_revalidation == ()


# -- snapshot shape and purity ----------------------------------------------------------------


def test_snapshot_is_read_only_deterministic_and_unsubmitted(stores, tmp_path):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", key="ro-on")
    roots = [tmp_path / "defs", tmp_path / "assignments"]

    def listing():
        return sorted(str(p.relative_to(r)) for r in roots for p in r.rglob("*"))

    args = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions, project_id=PROJECT, session_ref="session-A",
                target_session="session-A", runtime_generation=4)
    before = listing()
    first = resolve_preview(**args)
    second = resolve_preview(**args)
    third = resolve_preview(
        server_scope=SCOPE, principal="alice", assignments=assignments,
        definitions=McpDefinitionStore(roots[0]),  # fresh instance, same bytes on disk
        project_id=PROJECT, session_ref="session-A",
        target_session="session-A", runtime_generation=4)
    after = listing()
    assert before == after
    assert first.snapshot_digest == second.snapshot_digest == third.snapshot_digest
    assert first.snapshot_digest.startswith("sha256:")
    assert first.submission_id is None
    moved = resolve_preview(**{**args, "session_ref": "session-Z",
                               "target_session": "session-Z"})
    assert moved.snapshot_digest != first.snapshot_digest


def test_snapshot_carries_lanes_enforcement_credentials_and_row_versions(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", key="snap-on")
    snapshot = resolve_preview(
        server_scope=SCOPE, principal="alice", assignments=assignments,
        definitions=definitions, lane_by_definition={"web-tools": "native"},
        native_enforcement_proven=["web-tools"], target_session="s", runtime_generation=1)
    assert snapshot.lane_by_definition["web-tools"] == {"lane": "native",
                                                        "enforcement": "proven"}
    unproven = resolve_preview(
        server_scope=SCOPE, principal="alice", assignments=assignments,
        definitions=definitions, lane_by_definition={"web-tools": "native"},
        target_session="s", runtime_generation=1)
    assert unproven.lane_by_definition["web-tools"]["enforcement"] == "unproven"
    assert list(unproven.lane_by_definition["web-tools"]) == ["lane", "enforcement"]
    managed = resolve_preview(
        server_scope=SCOPE, principal="alice", assignments=assignments,
        definitions=definitions, target_session="s", runtime_generation=1)
    assert managed.lane_by_definition["web-tools"] == {"lane": "managed",
                                                       "enforcement": "proven"}
    assert list(snapshot.credential_ref_revisions) == [{
        "definition_id": "web-tools", "revision": 1, "slot": "API_KEY",
        "credential_id": "credential_1"}]
    assert snapshot.assignment_revisions[0]["row_version"] == 1
    assert snapshot.allowed_tool_names == ("search",)
    blob = json.dumps([dict(e) for e in snapshot.definition_revisions]
                      + [dict(e) for e in snapshot.credential_ref_revisions])
    assert "fast" not in blob  # literal values never enter the snapshot


# -- higher-admin prohibition and archive ---------------------------------------------------------


def test_policy_denied_blocks_any_layer_reenable(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", scope_kind="project", scope_id=PROJECT, key="deny-on")
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions, project_id=PROJECT, policy_denied=("web-tools",))
    assert enabled_ids(resolve_preview(**base)) == []
    enable(assignments, "web-tools", scope_kind="profile", scope_id=PROFILE, key="deny-prof")
    assert enabled_ids(resolve_preview(**{**base, "profile_revision": PROFILE})) == []


def test_archived_definition_blocks_new_assignments_but_keeps_existing_snapshot(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    enable(assignments, "web-tools", key="arch-on")
    definitions.archive_definition(server_scope=SCOPE, definition_id="web-tools")
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions)
    assert enabled_ids(resolve_preview(**base)) == ["web-tools"]
    with pytest.raises(McpError) as refused:
        enable(assignments, "web-tools", scope_kind="project", scope_id="project-2",
               key="arch-new")
    assert refused.value.code == MCP_DEFINITION_ARCHIVED


# -- assignment CAS -------------------------------------------------------------------------------


def test_assignment_cas_replay_and_inherit_delete(stores):
    definitions, assignments = stores
    publish(definitions, "web-tools")
    first = enable(assignments, "web-tools", key="cas-1")
    assert first["assignment"]["row_version"] == 1
    replay = enable(assignments, "web-tools", key="cas-1")
    assert replay["replayed"] is True and replay["assignment"]["row_version"] == 1
    with pytest.raises(McpError) as clash:
        enable(assignments, "web-tools", expected_row_version=0, key="cas-2")
    assert clash.value.code == MCP_CAS_CONFLICT
    with pytest.raises(McpError) as opconflict:
        enable(assignments, "web-tools", revision=1, expected_row_version=1, key="cas-1")
    assert opconflict.value.code == MCP_OPERATION_CONFLICT
    gone = decide_off(assignments, "web-tools", decision="inherit",
                      expected_row_version=1, key="inherit-1")
    assert gone["removed"] is True
    base = dict(server_scope=SCOPE, principal="alice", assignments=assignments,
                definitions=definitions)
    assert enabled_ids(resolve_preview(**base)) == []
    # after inherit the slot is free again for a fresh enable
    again = enable(assignments, "web-tools", expected_row_version=0, key="cas-3")
    assert again["assignment"]["row_version"] == 1
