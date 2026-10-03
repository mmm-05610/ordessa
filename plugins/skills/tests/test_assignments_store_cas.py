"""Assignment store: durable writes with CAS + operationKey, the
schema-ownership pattern, and the BindingCasPort contract
(data-model.md §内容与版本: 更新已启用范围时明确挑选目标修订并写 CAS/操作键；
重试不能重复升级; library/records.py hands this table's ownership here).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assignments_support import make_database, make_skill, make_store
from ordessa_skills.assignments import AssignmentError
from ordessa_skills.assignments.model import (
    DECISION_DISABLE,
    DECISION_ENABLE,
    SCOPE_PROJECT,
    SCOPE_USER_GLOBAL,
    SkillAssignment,
)
from ordessa_skills.assignments.store import (
    ASSIGNMENTS_TABLE,
    BINDING_CAS_TABLE,
    OPERATIONS_TABLE,
    AssignmentBindingCas,
    AssignmentScope,
    AssignmentStore,
)
from ordessa_skills.library.records import AssetRecords, BindingCasPort


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = make_skill(tmp_path, database=database, asset_id="skill-one",
                      revision=1)
    made2 = make_skill(tmp_path, database=database, asset_id="skill-one",
                       revision=2)
    store = make_store(database, approvals=made["approvals"])
    return {"database": database, "store": store,
            "approvals": made["approvals"], "facts": made2}


def _rows(database, table):
    with database.read() as conn:
        return [tuple(row) for row in conn.execute(
            f"SELECT * FROM {table} ORDER BY 1").fetchall()]


# -- model rules, enforced at the store boundary ---------------------------------

def test_enable_requires_revision_disable_forbids_it(env):
    store = env["store"]
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                     decision=DECISION_ENABLE)
    assert refusal.value.code == "ASSIGNMENT_INVALID"
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                     decision=DECISION_DISABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_INVALID"


def test_assignments_reference_only_skill_assets(env):
    store = env["store"]
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="ghost-asset",
                     decision=DECISION_ENABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_ASSET_UNKNOWN"
    # a foreign kind planted straight into server_assets (the mcp/plugin
    # rows server-compat owns) is equally unassignable — the new table
    # inherits the G01 kind isolation.
    with store.database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_assets(id,kind,name,description,latest_revision,"
            "digest,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("foreign-mcp", "mcp", "m", None, 1, "sha256:" + "f" * 64,
             "legacy", "t", "t"))
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="foreign-mcp",
                     decision=DECISION_ENABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_ASSET_UNKNOWN"


# -- schema ownership: idempotent, additive, never touching shared tables --------

def test_ensure_schema_is_idempotent_and_registers_new_tables_only(env):
    store = env["store"]
    before = _rows(store.database, ASSIGNMENTS_TABLE)
    store.ensure_schema()      # second call on a live data root
    store.ensure_schema()
    assert _rows(store.database, ASSIGNMENTS_TABLE) == before == []
    with store.database.read() as conn:
        names = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {ASSIGNMENTS_TABLE, OPERATIONS_TABLE,
            BINDING_CAS_TABLE} <= names
    assert "server_assets" in names  # the shared tables stay shared
    # a store on a data root without the helper's tables refuses to read
    # instead of silently answering empty (the seam is disclosed)
    fresh = make_database(Path(store.database.data_root).parent / "data2")
    lazy = AssignmentStore(fresh, scope=AssignmentScope(
        server_scope="srv-lazy", principal="user-9"),
        approvals=env["approvals"])
    with pytest.raises(AssignmentError) as refusal:
        lazy.list()
    assert refusal.value.code == "ASSIGNMENT_SCHEMA_UNAVAILABLE"
    lazy.ensure_schema()
    assert lazy.list() == []


# -- CAS + operation key -----------------------------------------------------------

def test_row_version_moves_only_on_real_writes(env):
    store = env["store"]
    first = store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                         decision=DECISION_ENABLE, revision=1,
                         expected_version=0, operation_key="op-a")
    assert first["rowVersion"] == 1
    # same operation key, replayed: exact same result, no double apply
    replay = store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                          decision=DECISION_ENABLE, revision=2,
                          expected_version=0, operation_key="op-a")
    assert replay == first
    # a second, new operation succeeds and bumps exactly one version
    second = store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                          decision=DECISION_ENABLE, revision=2,
                          expected_version=1, operation_key="op-b")
    assert second["rowVersion"] == 2
    # stale expectation is refused with the version actually on the row
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                     decision=DECISION_DISABLE, expected_version=1)
    assert refusal.value.code == "ASSIGNMENT_VERSION_CONFLICT"


def test_remove_is_versioned_and_idempotent(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                 decision=DECISION_ENABLE, revision=1)
    result = store.remove(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                          expected_version=1, operation_key="op-r")
    assert result["removed"] is True
    assert result["previousRowVersion"] == 1
    # retry of the settled key replays the same answer…
    assert store.remove(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one",
                        operation_key="op-r") == result
    # …and a fresh attempt on the gone row is a typed not-found, not
    # silent success.
    with pytest.raises(AssignmentError) as refusal:
        store.remove(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-one")
    assert refusal.value.code == "ASSIGNMENT_NOT_FOUND"


def test_project_layer_needs_a_bounded_scope_id(env):
    store = env["store"]
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_PROJECT, scope_id="",
                     asset_id="skill-one", decision=DECISION_ENABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_INVALID"
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_PROJECT,
                     scope_id="../../etc/passwd", asset_id="skill-one",
                     decision=DECISION_ENABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_INVALID"


# -- the BindingCasPort contract (records.py T05 seam) ------------------------------

def test_store_satisfies_the_binding_cas_port_protocol(env):
    cas = env["store"].binding_cas()
    assert isinstance(cas, BindingCasPort)
    assert cas.current_version("profile_a", "skill-one") == 0
    assert cas.replay("never-seen") is None


def test_guarded_profile_binding_writes_upgrade_exactly_once(env):
    database = env["database"]
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profiles(id,version,name,harness_type,"
            "config_revision,native_generation,config_object_digest,"
            "created_at,updated_at) VALUES ('profile_b',1,'r','pi',1,0,"
            "'sha256:x','t','t')")
    records = AssetRecords(database, cas=env["store"].binding_cas())
    first = records.bind(profile_id="profile_b", asset_id="skill-one",
                         revision=1, expected_version=0,
                         operation_key="bind-1")
    assert first["revision"] == 1
    # retry of the same operation key returns the settled view and does
    # NOT bump the CAS ledger (重试不能重复升级)
    replay = records.bind(profile_id="profile_b", asset_id="skill-one",
                          revision=2, expected_version=0,
                          operation_key="bind-1")
    assert replay == first
    assert records.bindings("profile_b")[0]["revision"] == 1
    # a NEW expectation against the settled version proceeds: 1 → 2
    moved = records.update_binding(profile_id="profile_b", asset_id="skill-one",
                                   revision=2, expected_version=1,
                                   operation_key="bind-2")
    assert moved["revision"] == 2
    assert env["store"].binding_cas().current_version("profile_b",
                                                      "skill-one") == 2
    with pytest.raises(Exception) as refusal:
        records.update_binding(profile_id="profile_b", asset_id="skill-one",
                               revision=1, expected_version=1)
    assert getattr(refusal.value, "code", None) == "BINDING_VERSION_CONFLICT"


def test_legacy_shape_without_cas_is_unchanged(env):
    # records.py's documented behaviour: expectedVersion without an
    # injected port is a typed refusal, never a silent downgrade — and
    # plain legacy writes (no CAS args) still work next to the new table.
    records = AssetRecords(env["database"])
    with pytest.raises(Exception) as refusal:
        records.bind(profile_id="profile_x", asset_id="skill-one",
                     expected_version=0)
    assert getattr(refusal.value, "code", None) == "BINDING_CAS_UNAVAILABLE"
