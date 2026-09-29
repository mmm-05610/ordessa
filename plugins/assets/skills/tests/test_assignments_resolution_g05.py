"""G05 — six-layer assignment resolution is deterministic and shows its
source (verification.md G05: 六层分配确定性解析并显示来源;
反例: 同层重复 / 项目禁用影响其他项目 / 品牌通用范围被错判).

Also FR06: 按确定顺序解析，不因 native 文件夹层级改变覆盖语义 — proven
structurally here: the resolver's only inputs are identity keys and stored
rows; two skills whose trees differ in folder depth resolve through the
identical layer chain with identical semantics.
"""
from __future__ import annotations

import sqlite3

import pytest

from assignments_support import (
    FakeProfileLayer,
    make_authorization,
    make_database,
    make_skill,
    make_store,
)
from ordessa_skills.assignments import AssignmentError

from ordessa_skills.assignments.model import (
    DECISION_DISABLE,
    DECISION_ENABLE,
    LAYER_ORDER,
    LAYER_PROJECT_ANY,
    LAYER_PROJECT_HARNESS,
    LAYER_SESSION_OVERRIDE,
    LAYER_USER_GLOBAL_ANY,
    LAYER_USER_GLOBAL_HARNESS,
    SCOPE_PROJECT,
    SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import SessionOverride
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    for asset_id in ("skill-alpha", "skill-beta", "skill-flat"):
        made[asset_id] = make_skill(tmp_path, database=database,
                                    asset_id=asset_id, revision=1)
    # the FR06 control: same domain facts, one tree level deeper
    made["skill-nested"] = make_skill(tmp_path, database=database,
                                      asset_id="skill-nested", revision=1,
                                      nested=True)
    # alpha gets a second approved revision for revision-pinning checks
    made["skill-alpha"] = make_skill(tmp_path, database=database,
                                     asset_id="skill-alpha", revision=2)
    store = make_store(database, approvals=made["skill-alpha"]["approvals"])
    return {
        "database": database,
        "assets": made,
        "store": store,
        "approvals": made["skill-alpha"]["approvals"],
        "revisions": made["skill-alpha"]["store"],
    }


def service_for(env, *, project_ids=("proj-a", "proj-b"), profile=None):
    deps = ResolverDeps(
        assignments=env["store"],
        revisions=env["revisions"],
        approvals=env["approvals"],
        authorization=make_authorization(workspaces=project_ids),
        profile=profile,
    )
    return SkillsResolutionService(deps)


def _included(service, target):
    return {item["assetId"]: item
            for item in service.preview_effective(target)["resolvedSkills"]}


# -- the layer chain, end to end ----------------------------------------------

def test_all_six_layers_applied_in_the_pinned_order(env):
    store = env["store"]
    up = dict(decision=DECISION_ENABLE)
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                 revision=1, **up)                                     # layer 1
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, harness_id="pi",
                 asset_id="skill-alpha", revision=2, **up)             # layer 2
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 asset_id="skill-alpha", revision=1, **up)             # layer 3
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 harness_id="pi", asset_id="skill-alpha", revision=2, **up)  # 4
    profile = FakeProfileLayer(
        harness="pi",
        entries=[SkillAssignmentEntry("skill-alpha", "enable", 1)])     # layer 5
    service = service_for(env, profile=profile)
    target = ResolutionTarget(project_id="proj-a", harness_id="pi",
                              profile_id="profile_a", session_ref="s1",
                              session_overrides=(                     # layer 6
                                  SessionOverride("skill-alpha",
                                                  DECISION_ENABLE, 2),))
    item = _included(service, target)["skill-alpha"]
    assert item["revision"] == 2
    assert item["selectedBy"]["layer"] == LAYER_SESSION_OVERRIDE
    # 本层设置 vs 最终结果 (ux.md §Settings): the per-layer own-values are
    # all visible, in the FR06 order, in the result that feeds the UI.
    chain_layers = [entry["layer"] for entry in item["layerDecisions"]]
    assert chain_layers == list(LAYER_ORDER)
    assert [e["decision"] for e in item["layerDecisions"]] == \
        ["enable"] * 6
    # provenance display data (G05 正例 "显示来源")
    assert item["nativeName"] == "skill-alpha"
    assert item["originScope"] == "public"
    assert item["treeDigest"].startswith("sha256:")
    assert item["capabilityEvidence"]["effect"] == "selected"
    # the row versions the decision actually used
    assert item["selectedBy"]["rowVersion"] is None  # session layer: no row
    versions = service.preview_effective(target)["assignmentRevisions"]
    assert len(versions) == 4  # the four DB layers carried rows


class SkillAssignmentEntry:
    """Tiny shim so the fake profile can speak the ProfileSkillEntry shape."""

    def __init__(self, asset_id, decision, revision=None):
        self.asset_id = asset_id
        self.decision = decision
        self.revision = revision


# -- same-layer duplicates -------------------------------------------------------

def test_duplicate_same_layer_same_asset_is_refused_in_sql(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                 decision=DECISION_ENABLE, revision=1)
    with pytest.raises(sqlite3.IntegrityError):
        with store.database.transaction() as conn:
            conn.execute(
                "INSERT INTO skill_assignments(server_scope,principal,"
                "scope_kind,scope_id,harness_key,asset_id,decision,revision,"
                "row_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("srv-test", "user-1", "user_global", "", "*", "skill-alpha",
                 "enable", 2, 9, "t", "t"))
    # the guarded API says the same thing as a typed CAS refusal, never a
    # second row: an "expectedVersion=0" (create-intent) write onto the
    # existing row is refused before insert.
    with pytest.raises(AssignmentError) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                     decision=DECISION_ENABLE, revision=2, expected_version=0)
    assert refusal.value.code == "ASSIGNMENT_VERSION_CONFLICT"


# -- project isolation (反例: 项目禁用影响其他项目) ---------------------------------

def test_project_disable_does_not_leak_to_another_project(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                 decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 asset_id="skill-alpha", decision=DECISION_DISABLE)
    service = service_for(env)
    a = service.preview_effective(
        ResolutionTarget(project_id="proj-a", harness_id="pi", session_ref="s"))
    b = service.preview_effective(
        ResolutionTarget(project_id="proj-b", harness_id="pi", session_ref="s"))
    assert [item["assetId"] for item in a["resolvedSkills"]] == []
    disabled = next(item for item in a["excludedSkills"]
                    if item["assetId"] == "skill-alpha")
    assert disabled["excludedBy"]["layer"] == LAYER_PROJECT_ANY
    assert [item["assetId"] for item in b["resolvedSkills"]] == ["skill-alpha"]
    # and proj-a's own decision came from ITS row, not from anywhere global
    assert b["resolvedSkills"][0]["selectedBy"]["layer"] == LAYER_USER_GLOBAL_ANY


# -- any-harness vs brand scope (反例: 品牌通用范围被错判) ---------------------------

def test_any_harness_and_brand_harness_are_different_layers(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                 decision=DECISION_ENABLE, revision=1)          # any
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, harness_id="codex",
                 asset_id="skill-alpha", decision=DECISION_DISABLE)  # brand
    service = service_for(env)
    pi = _included(service, ResolutionTarget(project_id="proj-a",
                                             harness_id="pi", session_ref="s"))
    assert pi["skill-alpha"]["revision"] == 1
    assert pi["skill-alpha"]["selectedBy"]["layer"] == LAYER_USER_GLOBAL_ANY
    codex = service.preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="codex", session_ref="s"))
    assert codex["resolvedSkills"] == []
    excluded = codex["excludedSkills"][0]
    assert excluded["excludedBy"]["layer"] == LAYER_USER_GLOBAL_HARNESS
    # the pi run records the codex-scoped row as a visible absence
    # diagnostic instead of silently dropping it
    full = service.preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="pi", session_ref="s"))
    assert any(d["kind"] == "other_harness_scope" and d["assetId"] == "skill-alpha"
               for d in full["diagnostics"])


def test_project_harness_specific_beats_project_any(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-alpha",
                 decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 asset_id="skill-beta", decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a", harness_id="pi",
                 asset_id="skill-beta", decision=DECISION_DISABLE)
    service = service_for(env)
    view = service.preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="pi", session_ref="s"))
    excluded = next(item for item in view["excludedSkills"]
                    if item["assetId"] == "skill-beta")
    assert excluded["excludedBy"]["layer"] == LAYER_PROJECT_HARNESS


# -- FR06: native folder depth cannot move the order -------------------------------

def test_resolution_semantics_are_independent_of_folder_depth(env):
    """A skill whose tree nests payloads a level deeper and a flat one,
    under identical assignment rows, resolve through identical chains
    (FR06: 不因 native 文件夹层级改变 Ordessa 的覆盖语义).

    The structural reason is pinned too: the resolver takes no file path
    input at all — folder depth is not even in its type.
    """
    store = env["store"]
    for asset in ("skill-flat", "skill-nested"):
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id=asset,
                     decision=DECISION_ENABLE, revision=1)
        store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a", asset_id=asset,
                     decision=DECISION_DISABLE)
    service = service_for(env)
    view = service.preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="pi", session_ref="s"))
    by_asset = {item["assetId"]: item for item in view["excludedSkills"]}
    flat_chain = [(e["layer"], e["decision"])
                  for e in by_asset["skill-flat"]["layerDecisions"]]
    nested_chain = [(e["layer"], e["decision"])
                    for e in by_asset["skill-nested"]["layerDecisions"]]
    assert flat_chain == nested_chain
    assert [layer for layer, _ in flat_chain] == list(LAYER_ORDER)
    assert by_asset["skill-flat"]["excludedBy"]["layer"] == \
        by_asset["skill-nested"]["excludedBy"]["layer"] == LAYER_PROJECT_ANY
    # no resolver input is a path: the target only carries identity tokens
    fields = set(ResolutionTarget.__dataclass_fields__)
    assert fields == {"project_id", "harness_id", "profile_id", "session_ref",
                      "session_overrides", "runtime_generation"}


# -- determinism of the projection itself ------------------------------------------

def test_two_runs_over_the_same_rows_are_identical(env):
    store = env["store"]
    for asset in ("skill-alpha", "skill-beta"):
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id=asset,
                     decision=DECISION_ENABLE, revision=1)
    service = service_for(env)
    target = ResolutionTarget(project_id="proj-a", harness_id="pi",
                              session_ref="s1")
    first = service.preview_effective(target)
    second = service.preview_effective(target)
    assert first == second
    # stable ordering: projection is sorted by assetId, not by insert order
    assert [item["assetId"] for item in first["resolvedSkills"]] == \
        ["skill-alpha", "skill-beta"]
