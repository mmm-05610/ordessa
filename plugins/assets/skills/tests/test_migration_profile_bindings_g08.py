"""T07 / verification.md G08 — 老 Profile 绑定迁 enable(revision)，结果相同.

Proven at L1 (内容库+纯适配测试) on a synthetic pacthold `Database` data
root:

* positive: the migration's effective skill set — assetIds AND pinned
  revisions — equals what the legacy `server_profile_assets` bindings
  implied, checked twice (module :func:`verify` mapping check AND a real
  six-layer resolver run over the migrated Profile-layer entries);
* the three registered counter-examples of G08: 固定版变追最新 /
  已禁用项变启用 / 迁移重跑双写;
* plan is read-only; plan digest stable; the version guard detects a
  concurrent binding change at apply time;
* non-skill rows (mcp/command/plugin) are byte-identical throughout, via
  the row-byte probe pattern of test_library_kind_isolation.py;
* user-data guard: apply refuses a non-synthetic data root without the
  explicit confirmation flag (AGENTS.md rule 5).

Blocked on Z1 (docs/design/skills-v2/tasks.md T07 second half;
specs/011-q1-skills/api-requests.md §G3): writing the REAL `assets.skills`
facet and the session item-override hookup. Until then apply() is
additive/parallel — `server_profile_assets` stays authoritative history,
and the sample bytes recorded below as literals are the dry-run evidence
that the old table is never rewritten.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from assignments_support import (
    FakeProfileLayer,
    make_authorization,
    make_database,
    make_skill,
    make_store,
)
from ordessa_skills.assignments.model import LAYER_PROFILE
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)
from ordessa_skills.assignments.store import AssignmentScope, AssignmentStore
from ordessa_skills.library.records import AssetRecords
from ordessa_skills.migration import profile_bindings as mig

FOREIGN_KINDS = ("mcp", "command", "plugin")
T0 = "2026-01-01T00:00:00+00:00"

#: Byte sample IN/OUT (data-model.md §存储升级: 必须有字节/ID 样本). The
#: literal below is the exact content of `server_profile_assets` before the
#: migration surface runs; every test that writes re-asserts it unchanged,
#: because the additive migration must leave the legacy table byte-identical
#: until Z1's facet retires it (specs/011-q1-skills/api-requests.md §G3).
LEGACY_BINDING_BYTES = (
    "profile_a|foreign-command|2|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-mcp|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|foreign-plugin|3|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-alpha|1|1|" + T0 + "|" + T0 + "\n"
    "profile_a|skill-beta|1|0|" + T0 + "|" + T0 + "\n"
    "profile_b|skill-gamma|2|1|" + T0 + "|" + T0
)


def _seed_profiles_and_foreign(database):
    with database.transaction() as conn:
        for pid in ("profile_a", "profile_b"):
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


def _bind(database, profile_id, asset_id, revision, enabled):
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_profile_assets(profile_id,asset_id,revision,"
            "enabled,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (profile_id, asset_id, revision, enabled, T0, T0))


def binding_bytes(database) -> str:
    with database.read() as conn:
        rows = conn.execute(
            "SELECT profile_id,asset_id,revision,enabled,created_at,updated_at"
            " FROM server_profile_assets ORDER BY profile_id,asset_id").fetchall()
    return "\n".join("|".join(str(value) for value in tuple(row)) for row in rows)


def assignment_rows(database):
    """Full row dump of the domain table, created_at excluded but every
    CAS-relevant column (incl. row_version and operation_key) included."""
    with database.read() as conn:
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='skill_assignments'").fetchone()
        if present is None:
            return []
        return [tuple(row) for row in conn.execute(
            "SELECT assignment_id,server_scope,principal,scope_kind,scope_id,"
            "harness_key,asset_id,decision,revision,row_version,operation_key"
            " FROM skill_assignments ORDER BY assignment_id")]


def foreign_probe(database):
    with database.read() as conn:
        assets = [tuple(row) for row in conn.execute(
            "SELECT rowid,id,kind,name,description,latest_revision,digest,"
            "source,created_at,updated_at FROM server_assets"
            " WHERE kind<>'skill' ORDER BY rowid")]
        bindings = [tuple(row) for row in conn.execute(
            "SELECT b.rowid,b.profile_id,b.asset_id,b.revision,b.enabled,"
            "b.created_at,b.updated_at FROM server_profile_assets b"
            " JOIN server_assets a ON a.id=b.asset_id"
            " WHERE a.kind<>'skill' ORDER BY b.rowid")]
    return assets, bindings


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    made["skill-alpha@1"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-alpha", revision=1)
    # alpha r2 installed AND approved: latest_revision moves to 2 while the
    # legacy pin stays at 1 — the 固定版变追最新 probe needs this skew.
    made["skill-alpha@2"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-alpha", revision=2)
    made["skill-beta@1"] = make_skill(tmp_path, database=database,
                                      asset_id="skill-beta", revision=1)
    made["skill-gamma@1"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-gamma", revision=1)
    # gamma r2 installed, NEVER approved: the pin under test is r2.
    made["skill-gamma@2"] = make_skill(tmp_path, database=database,
                                       asset_id="skill-gamma", revision=2,
                                       approve=False)
    _seed_profiles_and_foreign(database)
    _bind(database, "profile_a", "skill-alpha", 1, 1)
    _bind(database, "profile_a", "skill-beta", 1, 0)
    _bind(database, "profile_b", "skill-gamma", 2, 1)
    return {
        "database": database,
        "approvals": made["skill-alpha@1"]["approvals"],
        "revisions": made["skill-alpha@1"]["store"],
    }


def entry_of(plan, profile_id, asset_id):
    matches = [e for e in plan.entries
               if e.profile_id == profile_id and e.asset_id == asset_id]
    assert len(matches) == 1, f"expected exactly one entry {profile_id}/{asset_id}"
    return matches[0]


# -- plan is a pure dry-run ------------------------------------------------------


def test_plan_is_read_only_and_classifies_every_row(env):
    database = env["database"]
    before_legacy = binding_bytes(database)
    before_foreign = foreign_probe(database)
    assert before_legacy == LEGACY_BINDING_BYTES  # byte sample IN

    p = mig.plan(database, approvals=env["approvals"])
    assert entry_of(p, "profile_a", "skill-alpha").classification == "migrate"
    assert entry_of(p, "profile_a", "skill-alpha").target_decision == "enable"
    assert entry_of(p, "profile_a", "skill-beta").target_decision == "disable"
    assert entry_of(p, "profile_b", "skill-gamma").classification == \
        mig.REFUSE_UNAPPROVED
    for kind in FOREIGN_KINDS:
        assert entry_of(p, "profile_a", f"foreign-{kind}").classification == \
            mig.SKIP_FOREIGN_KIND

    # the dry-run wrote NOTHING: legacy bytes, foreign rows, and the whole
    # domain table are untouched (byte sample OUT == IN).
    assert binding_bytes(database) == before_legacy == LEGACY_BINDING_BYTES
    assert foreign_probe(database) == before_foreign
    assert assignment_rows(database) == []


def test_plan_digest_is_stable_and_binding_sensitive(env):
    database = env["database"]
    gate = env["approvals"]
    first = mig.plan(database, profile_id="profile_a", approvals=gate)
    second = mig.plan(database, profile_id="profile_a", approvals=gate)
    assert first.digest == second.digest

    # a concurrent move of the pinned revision (a real user edit through the
    # records surface) must change the digest — this is what apply re-checks.
    AssetRecords(database).update_binding(profile_id="profile_a",
                                         asset_id="skill-alpha", revision=2)
    third = mig.plan(database, profile_id="profile_a", approvals=gate)
    assert third.digest != first.digest
    assert entry_of(third, "profile_a", "skill-alpha").source_signature == "2|1"


# -- G08 positive: 迁 enable(revision)，结果相同 ----------------------------------


def test_g08_positive_migration_resolves_to_the_legacy_effective_set(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    result = mig.apply(database, p, operation_key="op-a", approvals=gate)
    assert len(result["written"]) == 2

    # module-level forward+backward mapping check
    evidence = mig.verify(database, p)
    assert evidence["equivalent"] is True
    assert evidence["legacyEffectiveSkills"] == [["skill-alpha", 1]]
    assert evidence["migratedEffectiveSkills"] == [["skill-alpha", 1]]
    assert evidence["migratedDisabled"] == ["skill-beta"]

    # the same equivalence through the REAL six-layer resolver: the migrated
    # entries are fed as the Profile layer's skill_entries (exactly what Z1's
    # facet will supply) and must resolve to the legacy-implied set.
    legacy_implied = set()
    with database.read() as conn:
        for row in conn.execute(
                "SELECT b.asset_id,b.revision FROM server_profile_assets b"
                " JOIN server_assets a ON a.id=b.asset_id"
                " WHERE b.profile_id='profile_a' AND a.kind='skill'"
                " AND b.enabled=1"):
            legacy_implied.add((row["asset_id"], int(row["revision"])))
    entries = mig.profile_skill_entries(
        database, server_scope=p.server_scope, profile_id="profile_a")
    deps = ResolverDeps(
        assignments=make_store(database),
        revisions=env["revisions"],
        approvals=gate,
        authorization=make_authorization(workspaces=("proj-a",)),
        profile=FakeProfileLayer(harness="pi", entries=list(entries)))
    view = SkillsResolutionService(deps).preview_effective(
        ResolutionTarget(project_id="proj-a", harness_id="pi",
                         profile_id="profile_a"))
    resolved = {(item["assetId"], item["revision"])
                for item in view["resolvedSkills"]}
    assert resolved == legacy_implied == {("skill-alpha", 1)}
    beta = [item for item in view["excludedSkills"] if item["assetId"] == "skill-beta"]
    assert beta and beta[0]["excludedBy"]["layer"] == LAYER_PROFILE
    # additive/parallel: the old table remains byte-identical history
    assert binding_bytes(database) == LEGACY_BINDING_BYTES


def test_counterexample1_pinned_revision_never_becomes_latest(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    alpha = entry_of(p, "profile_a", "skill-alpha")
    # the library is at latest 2 while the legacy pin is 1: the plan must
    # carry exactly enable(1) — never "latest".
    with database.read() as conn:
        latest = int(conn.execute(
            "SELECT latest_revision FROM server_assets WHERE id='skill-alpha'"
        ).fetchone()["latest_revision"])
    assert latest == 2 and alpha.target_revision == 1
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    row = [r for r in assignment_rows(database) if r[6] == "skill-alpha"]
    assert [(r[7], r[8]) for r in row] == [("enable", 1)]

    # the unapproved pin: refuse with a type, apply refuses the plan whole,
    # and NOTHING is written for it — no upgrade to a newer revision, no
    # downgrade to the last approved one.
    pb = mig.plan(database, profile_id="profile_b", approvals=gate)
    gamma = entry_of(pb, "profile_b", "skill-gamma")
    assert gamma.classification == mig.REFUSE_UNAPPROVED
    assert gamma.target_decision is None and gamma.target_revision is None
    with pytest.raises(mig.MigrationError) as refusal:
        mig.apply(database, pb, operation_key="op-b", approvals=gate)
    assert refusal.value.code == "MIGRATION_PLAN_HAS_REFUSALS"
    assert mig.profile_skill_entries(
        database, server_scope=pb.server_scope, profile_id="profile_b") == ()


def test_counterexample2_disabled_binding_never_becomes_enabled(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    beta = entry_of(p, "profile_a", "skill-beta")
    assert (beta.classification, beta.target_decision, beta.target_revision) == \
        ("migrate", "disable", None)
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    entries = {e.asset_id: e for e in mig.profile_skill_entries(
        database, server_scope=p.server_scope, profile_id="profile_a")}
    assert entries["skill-beta"].decision == "disable"
    assert entries["skill-beta"].revision is None
    enabled = {tuple(item) for item in
               mig.verify(database, p)["migratedEffectiveSkills"]}
    assert "skill-beta" not in {asset for asset, _ in enabled}
    assert enabled == {("skill-alpha", 1)}


def test_counterexample3_rerun_never_double_writes(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    after_first = assignment_rows(database)
    assert len(after_first) == 2

    # same operation key → ledger replay, zero effect
    replayed = mig.apply(database, p, operation_key="op-a", approvals=gate)
    assert replayed["replayed"] is True
    assert assignment_rows(database) == after_first

    # a rebuilt plan reports the migrated rows as already-migrated (the
    # foreign rows on the same Profile stay skip:foreign_kind)…
    p2 = mig.plan(database, profile_id="profile_a", approvals=gate)
    assert {e.classification for e in p2.entries} == {
        mig.SKIP_ALREADY_MIGRATED, mig.SKIP_FOREIGN_KIND}
    different_key = mig.apply(database, p2, operation_key="op-b", approvals=gate)
    assert different_key["written"] == []
    assert assignment_rows(database) == after_first

    # …and re-applying the ORIGINAL plan under a *different* key must also
    # write nothing (the counter-example in its strongest form: not even a
    # row_version bump).
    third = mig.apply(database, p, operation_key="op-c", approvals=gate)
    assert third["written"] == []
    assert len(third["skippedAlreadyMigrated"]) == 2
    assert assignment_rows(database) == after_first


# -- replay identity (MAJOR-1 counter-example) ----------------------------------


def ledger_result(database, operation_key):
    """Raw JSON the operations ledger holds for one key (what replay
    would return — the stored identity is checkable by inspection)."""
    from ordessa_skills.assignments.store import OPERATIONS_TABLE
    with database.read() as conn:
        row = conn.execute(
            f"SELECT result_json FROM {OPERATIONS_TABLE} WHERE operation_key=?",
            (operation_key,)).fetchone()
    return None if row is None else json.loads(row["result_json"])


def test_replay_under_a_different_server_scope_is_refused_not_replayed(env):
    database, gate = env["database"], env["approvals"]
    plan_a = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, plan_a, operation_key="op-a", approvals=gate)

    # same operation key, a plan over the SAME rows but a different data
    # partition: this was never applied — it must not report `replayed`.
    plan_b = mig.plan(database, profile_id="profile_a",
                      server_scope="srv:second-partition", approvals=gate)
    assert plan_b.digest != plan_a.digest  # the scope is IN the identity
    with pytest.raises(mig.MigrationError) as stale:
        mig.apply(database, plan_b, operation_key="op-a", approvals=gate)
    assert stale.value.code == "MIGRATION_PLAN_STALE"

    # and nothing of B was written either way; A's rows stand untouched.
    rows = assignment_rows(database)
    assert [r for r in rows if r[1] == "srv:second-partition"] == []
    assert len(rows) == 2


def test_same_key_same_plan_still_replays_with_zero_second_write(env):
    database, gate = env["database"], env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    first = mig.apply(database, p, operation_key="op-a", approvals=gate)
    rows_after_first = assignment_rows(database)
    assert len(first["written"]) == 2

    replay = mig.apply(database, p, operation_key="op-a", approvals=gate)
    assert replay["replayed"] is True
    assert replay["planDigest"] == p.digest
    assert replay["serverScope"] == p.server_scope
    # zero second write: not even a row_version bump
    assert assignment_rows(database) == rows_after_first


def test_ledger_records_the_digest_and_scope_it_applied(env):
    database, gate = env["database"], env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    stored = ledger_result(database, "op-a")
    assert stored is not None
    assert stored["planDigest"] == p.digest
    assert stored["serverScope"] == p.server_scope == mig.DEFAULT_SERVER_SCOPE
    assert len(stored["written"]) == 2


def test_digest_binds_the_profile_partition_not_just_the_entries(env):
    database, gate = env["database"], env["approvals"]
    p_a = mig.plan(database, profile_id="profile_a", approvals=gate)
    # a document claiming p_a's digest while covering a different profile
    # partition is a tampered plan: the entries alone no longer re-hash
    lookalike = mig.MigrationPlan(server_scope=p_a.server_scope,
                                  profile_filter="profile_c",
                                  entries=p_a.entries, digest=p_a.digest)
    with pytest.raises(mig.MigrationError) as stale:
        mig.apply(database, lookalike, operation_key="op-x", approvals=gate)
    assert stale.value.code == "MIGRATION_PLAN_STALE"
    assert assignment_rows(database) == []


# -- version guard at apply time --------------------------------------------------


def test_concurrent_binding_change_is_detected_at_apply(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    # someone moves the legacy binding between plan and apply…
    AssetRecords(database).update_binding(profile_id="profile_a",
                                          asset_id="skill-alpha", revision=2)
    with pytest.raises(mig.MigrationError) as stale:
        mig.apply(database, p, operation_key="op-x", approvals=gate)
    assert stale.value.code == "MIGRATION_PLAN_STALE"
    assert assignment_rows(database) == []  # the refusal aborted the whole op


def test_concurrent_divergent_assignment_write_is_detected_at_apply(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    # an intruder writes a DIFFERENT intent at the target layer
    intruder = AssignmentStore(
        database, scope=AssignmentScope(server_scope=p.server_scope,
                                        principal=mig.profile_principal("profile_a")),
        approvals=gate)
    intruder.ensure_schema()
    intruder.upsert(scope_kind="user_global", asset_id="skill-beta",
                    decision="enable", revision=1)
    with pytest.raises(mig.MigrationError) as stale:
        mig.apply(database, p, operation_key="op-x", approvals=gate)
    assert stale.value.code == "MIGRATION_PLAN_STALE"
    # nothing of the plan was written on top of the divergent row
    rows = [(r[6], r[7], r[8]) for r in assignment_rows(database)]
    assert rows == [("skill-beta", "enable", 1)]


def test_explicit_expected_row_version_is_enforced(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    # a stale caller insisting the layers are still at version 0 is refused
    # by the explicit CAS even though the intents already match
    with pytest.raises(mig.MigrationError) as stale:
        mig.apply(database, p, operation_key="op-b", approvals=gate,
                  expected_row_version=0)
    assert stale.value.code == "MIGRATION_PLAN_STALE"


# -- isolation, guards, verification failures -------------------------------------


def test_non_skill_rows_are_never_migrated_or_touched(env):
    database = env["database"]
    gate = env["approvals"]
    before = foreign_probe(database)
    p = mig.plan(database, approvals=gate)
    assert all(entry_of(p, "profile_a", f"foreign-{k}").classification ==
               mig.SKIP_FOREIGN_KIND for k in FOREIGN_KINDS)
    mig.apply(database, mig.plan(database, profile_id="profile_a",
                                 approvals=gate),
              operation_key="op-a", approvals=gate)
    assert foreign_probe(database) == before
    migrated = [r[6] for r in assignment_rows(database)]
    assert not any(asset.startswith("foreign-") for asset in migrated)


def test_apply_refuses_a_non_synthetic_data_root_without_confirmation(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    database.data_root = Path("/home/real-user/.ordessa/data")
    with pytest.raises(mig.MigrationError) as guard:
        mig.apply(database, p, operation_key="op-a", approvals=gate)
    assert guard.value.code == "MIGRATION_USER_DATA_CONFIRMATION_REQUIRED"
    assert assignment_rows(database) == []
    # the explicit flag stands for "backup/rollback evidence + user
    # confirmation collected for THIS root" (AGENTS.md rule 5) and lets the
    # (still additive) write proceed
    result = mig.apply(database, p, operation_key="op-a", approvals=gate,
                       allow_user_data=True)
    assert len(result["written"]) == 2
    assert binding_bytes(database) == LEGACY_BINDING_BYTES


def test_verify_detects_a_diverged_migrated_row(env):
    database = env["database"]
    gate = env["approvals"]
    p = mig.plan(database, profile_id="profile_a", approvals=gate)
    mig.apply(database, p, operation_key="op-a", approvals=gate)
    diverger = AssignmentStore(
        database, scope=AssignmentScope(server_scope=p.server_scope,
                                        principal=mig.profile_principal("profile_a")),
        approvals=gate)
    diverger.upsert(scope_kind="user_global", asset_id="skill-alpha",
                    decision="disable")
    with pytest.raises(mig.MigrationError) as mismatch:
        mig.verify(database, p)
    assert mismatch.value.code == "MIGRATION_VERIFY_MISMATCH"


def test_empty_plan_applies_replayably_and_verifies(env):
    database = env["database"]
    p = mig.plan(database, profile_id="profile_nope",
                 approvals=env["approvals"])
    assert p.entries == ()
    result = mig.apply(database, p, operation_key="op-empty")
    assert result["written"] == []
    again = mig.apply(database, p, operation_key="op-empty")
    assert again["replayed"] is True
    assert mig.verify(database, p)["equivalent"] is True
