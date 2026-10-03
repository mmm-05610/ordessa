"""T07 rollback evidence (verification.md G09 half of the dry-run/回退 pair;
data-model.md §存储升级: 迁移必须有字节/ID 样本和回滚验证).

G09's own cell — Profile 会话覆盖下一次提交生效 — stays BLOCKED on Z1's
session item-override mechanism (specs/011-q1-skills/api-requests.md §G3(b));
what this file proves at L1 is the rollback contract of the migration
engine:

* :func:`rollback` removes exactly the rows one settled operation applied
  and nothing else (a second operation's rows, foreign-kind rows, and the
  `server_profile_assets` history all survive byte-identical);
* the drift half of the contract: if any written row moved (decision,
  revision or row_version diverged from the ledger's ``written`` views)
  between apply and rollback, the rollback REFUSES with the typed
  ``MIGRATION_ROLLBACK_ROW_DRIFT`` and removes NOTHING — the probe runs
  to completion before the first delete, so one drifted row in a 3-row
  operation costs zero rows, not two, and the edited assignment survives;
* the legacy table sample bytes recorded as literals below are the same
  before and after a full plan → apply → rollback cycle;
* an unknown or already-rolled-back key refuses with a type;
* after rollback the operation key is cleared, so a rebuilt plan can
  legitimately re-apply;
* rolling back an operation that applied zero rows (a different-key
  re-run, G08 counter-example 3) removes zero rows.

User-data guard applies to rollback too: destructive writes against a
non-synthetic root need the explicit confirmation flag (AGENTS.md rule 5).
The path-shape rule is all that is enforced; ``allow_user_data=True`` is
an unverified caller assertion, not evidence validation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assignments_support import make_database, make_skill
from ordessa_skills.assignments.store import AssignmentScope, AssignmentStore
from ordessa_skills.migration import profile_bindings as mig

FOREIGN_KINDS = ("mcp", "command", "plugin")
T0 = "2026-01-01T00:00:00+00:00"

#: Byte sample IN/OUT for the whole apply→rollback cycle (see the module
#: docstring of profile_bindings: the migration is additive; the legacy
#: table is authoritative history until Z1's facet retires it, §G3).
LEGACY_BINDING_BYTES = (
    "profile_a|foreign-command|2|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-mcp|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-plugin|3|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-alpha|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-beta|1|0|" + T0 + "|" + T0 + "\n"
    "profile_c|skill-alpha|2|1|" + T0 + "|" + T0
)


def _seed(database):
    with database.transaction() as conn:
        for pid in ("profile_a", "profile_c"):
            conn.execute(
                "INSERT INTO server_profiles(id,version,name,harness_type,"
                "config_revision,native_generation,config_object_digest,"
                "created_at,updated_at) VALUES (?,1,'role','pi',1,0,'sha256:x',?,?)",
                (pid, T0, T0))
        for index, kind in enumerate(FOREIGN_KINDS):
            conn.execute(
                "INSERT INTO server_assets(id,kind,name,description,"
                "latest_revision,digest,source,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"foreign-{kind}", kind, f"name-{kind}", "not a skill",
                 index + 1, "sha256:" + "f" * 64, "legacy:server-compat",
                 T0, T0))
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,"
                "revision,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ("profile_a", f"foreign-{kind}", index + 1, 1, T0, T0))
        for pid, asset, revision, enabled in (
                ("profile_a", "skill-alpha", 1, 1),
                ("profile_a", "skill-beta", 1, 0),
                ("profile_c", "skill-alpha", 2, 1)):
            conn.execute(
                "INSERT INTO server_profile_assets(profile_id,asset_id,"
                "revision,enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (pid, asset, revision, enabled, T0, T0))


def binding_bytes(database) -> str:
    with database.read() as conn:
        rows = conn.execute(
            "SELECT profile_id,asset_id,revision,enabled,created_at,updated_at"
            " FROM server_profile_assets ORDER BY profile_id,asset_id").fetchall()
    return "\n".join("|".join(str(value) for value in tuple(row)) for row in rows)


def assignment_rows(database):
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='skill_assignments'").fetchone()
        if present is None:
            return []
        return [tuple(row) for row in conn.execute(
            "SELECT principal,asset_id,decision,revision,row_version"
            " FROM skill_assignments ORDER BY assignment_id")]


def ledger_keys(database):
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='skill_assignment_operations'").fetchone()
        if present is None:
            return set()
        return {row["operation_key"] for row in conn.execute(
            "SELECT operation_key FROM skill_assignment_operations")}


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    made["skill-alpha@1"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-alpha", revision=1)
    made["skill-alpha@2"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-alpha", revision=2)
    made["skill-beta@1"] = make_skill(tmp_path, database=database,
                                      asset_id="skill-beta", revision=1)
    _seed(database)
    return {"database": database,
            "approvals": made["skill-alpha@1"]["approvals"]}


def apply_two_operations(env):
    """op-a migrates profile_a (2 rows), op-c migrates profile_c (1 row)."""
    database, gate = env["database"], env["approvals"]
    pa = mig.plan(database, profile_id="profile_a", approvals=gate)
    pc = mig.plan(database, profile_id="profile_c", approvals=gate)
    ra = mig.apply(database, pa, operation_key="op-a", approvals=gate)
    rc = mig.apply(database, pc, operation_key="op-c", approvals=gate)
    assert (len(ra["written"]), len(rc["written"])) == (2, 1)
    return pa, pc


def test_rollback_removes_exactly_the_operations_rows(env):
    database = env["database"]
    before_legacy = binding_bytes(database)
    assert before_legacy == LEGACY_BINDING_BYTES  # byte sample IN
    apply_two_operations(env)
    after_apply = assignment_rows(database)
    assert len(after_apply) == 3

    result = mig.rollback(database, "op-a")
    assert result["removedRows"] == 2

    # only op-c's row survives — exact-set removal, nothing broader
    survivors = [row for row in assignment_rows(database)
                 if row[0] == mig.profile_principal("profile_a")]
    assert survivors == []
    assert assignment_rows(database) == [
        row for row in after_apply
        if row[0] == mig.profile_principal("profile_c")]
    assert mig.profile_skill_entries(
        database, server_scope=mig.DEFAULT_SERVER_SCOPE,
        profile_id="profile_a") == ()

    # the legacy history and foreign rows are byte-identical (sample OUT)
    assert binding_bytes(database) == before_legacy == LEGACY_BINDING_BYTES

    # ledger: op-a's master and both sub keys cleared; op-c's keys stand
    keys = ledger_keys(database)
    assert not {k for k in keys if k == "op-a" or k.startswith("op-a:")}
    assert "op-c" in keys and any(k.startswith("op-c:") for k in keys)


def test_rollback_of_a_zero_write_operation_removes_nothing(env):
    database, gate = env["database"], env["approvals"]
    pa = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, pa, operation_key="op-a", approvals=gate)
    rows_after_first = assignment_rows(database)
    # a different-key re-run writes nothing (G08 counter-example 3)…
    rerun = mig.apply(database, pa, operation_key="op-rerun", approvals=gate)
    assert rerun["written"] == []
    # …so rolling IT back must remove nothing, not the original rows.
    result = mig.rollback(database, "op-rerun")
    assert result["removedRows"] == 0
    assert assignment_rows(database) == rows_after_first


def test_rollback_without_drift_still_reverts_every_written_row(env):
    database, gate = env["database"], env["approvals"]
    apply_two_operations(env)
    result = mig.rollback(database, "op-a")
    assert result["removedRows"] == 2
    # every row op-a wrote is gone…
    assert [row for row in assignment_rows(database)
            if row[0] == mig.profile_principal("profile_a")] == []
    # …and its ledger keys (master + both subs) are cleaned with it
    keys = ledger_keys(database)
    assert not {k for k in keys if k == "op-a" or k.startswith("op-a:")}
    # the untouched op-c keeps its rows and its ledger
    assert len([row for row in assignment_rows(database)
                if row[0] == mig.profile_principal("profile_c")]) == 1
    assert "op-c" in keys


def test_rollback_refuses_when_a_written_row_drifted_after_apply(env):
    database, gate = env["database"], env["approvals"]
    apply_two_operations(env)
    # the user edits one migrated assignment between apply and rollback:
    # disable is exactly the edit the drift probe must not delete past
    editor = AssignmentStore(database, scope=AssignmentScope(
        server_scope=mig.DEFAULT_SERVER_SCOPE,
        principal=mig.profile_principal("profile_a")))
    editor.upsert(scope_kind="user_global", asset_id="skill-alpha",
                  decision="disable")

    with pytest.raises(mig.MigrationError) as drift:
        mig.rollback(database, "op-a")
    assert drift.value.code == "MIGRATION_ROLLBACK_ROW_DRIFT"

    # the edited row stands exactly as the user left it — not reverted
    rows = assignment_rows(database)
    assert len(rows) == 3  # nothing at all was removed
    edited = [row for row in rows if row[1] == "skill-alpha"
              and row[0] == mig.profile_principal("profile_a")]
    assert edited == [(mig.profile_principal("profile_a"), "skill-alpha",
                       "disable", None, 2)]
    # the ledger still describes the operation (retry after resolving)
    keys = ledger_keys(database)
    assert "op-a" in keys and any(k.startswith("op-a:") for k in keys)


def test_rollback_refusal_is_atomic_when_only_the_middle_row_drifted(env):
    database, gate = env["database"], env["approvals"]
    whole = mig.plan(database, approvals=gate)  # profile_a ×2 + profile_c ×1
    result = mig.apply(database, whole, operation_key="op-all",
                       approvals=gate)
    assert len(result["written"]) == 3
    assert [(t["principal"], t["assetId"]) for t in result["targets"]] == [
        (mig.profile_principal("profile_a"), "skill-alpha"),
        (mig.profile_principal("profile_a"), "skill-beta"),
        (mig.profile_principal("profile_c"), "skill-alpha")]

    # drift ONLY the middle row: the disable intent becomes an enable(1)
    editor = AssignmentStore(
        database, scope=AssignmentScope(
            server_scope=mig.DEFAULT_SERVER_SCOPE,
            principal=mig.profile_principal("profile_a")), approvals=gate)
    editor.upsert(scope_kind="user_global", asset_id="skill-beta",
                  decision="enable", revision=1)

    with pytest.raises(mig.MigrationError) as drift:
        mig.rollback(database, "op-all")
    assert drift.value.code == "MIGRATION_ROLLBACK_ROW_DRIFT"

    # atomic refusal: the two undrifted rows survive too, and the whole
    # ledger entry stands — zero deletes, not two.
    assert len(assignment_rows(database)) == 3
    keys = ledger_keys(database)
    assert "op-all" in keys
    assert sum(1 for k in keys if k.startswith("op-all:")) == 3


def test_rollback_refuses_unknown_and_already_rolled_back_keys(env):
    database = env["database"]
    with pytest.raises(mig.MigrationError) as unknown:
        mig.rollback(database, "op-never")
    assert unknown.value.code == "MIGRATION_OPERATION_UNKNOWN"

    apply_two_operations(env)
    mig.rollback(database, "op-a")
    with pytest.raises(mig.MigrationError) as second:
        mig.rollback(database, "op-a")
    assert second.value.code == "MIGRATION_OPERATION_UNKNOWN"


def test_reapply_after_rollback_is_clean_and_verifies(env):
    database, gate = env["database"], env["approvals"]
    pa, _ = apply_two_operations(env)
    mig.rollback(database, "op-a")
    # the freed key replays nothing stale: it applies fresh (the rolled-back
    # rows were removed, so the ledger was cleared with them)
    again = mig.apply(database, pa, operation_key="op-a", approvals=gate)
    assert len(again["written"]) == 2
    assert mig.verify(database, pa)["equivalent"] is True
    assert binding_bytes(database) == LEGACY_BINDING_BYTES


def test_rollback_refuses_a_non_synthetic_root_without_confirmation(env):
    database = env["database"]
    apply_two_operations(env)
    database.data_root = Path("/home/real-user/.ordessa/data")
    with pytest.raises(mig.MigrationError) as guard:
        mig.rollback(database, "op-a")
    assert guard.value.code == "MIGRATION_USER_DATA_CONFIRMATION_REQUIRED"
    assert len(assignment_rows(database)) == 3  # nothing removed
    result = mig.rollback(database, "op-a", allow_user_data=True)
    assert result["removedRows"] == 2
