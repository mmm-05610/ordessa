"""G07 — only authorized projects/private skills are selectable
(verification.md G07: 授权项目/专用 Skill 可选;
反例: 客户端伪 projectId / A 专用内容给 B / 未授权跨 Server 引用).

Plus the identity-injection rules of FR09 and data-model.md §内容与版本:
公共库可用于已授权项目；项目专用仅该 projectId；Profile 专用仅该 Profile；
Profile 的 harnessId 固定，不允许跨 Harness 使用 Profile 专用项.
"""
from __future__ import annotations

import pytest

from assignments_support import (
    FakeProfileLayer,
    make_authorization,
    make_database,
    make_skill,
    make_store,
)
from ordessa_skills.assignments.authorization import AuthorizationError
from ordessa_skills.assignments.model import (
    DECISION_ENABLE,
    SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import ProfileSkillEntry
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)
from ordessa_skills.assignments.store import AssignmentScope, AssignmentStore


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    specs = {
        "skill-public": None,                      # public library
        "skill-proj-a": "project:proj-a",          # private to proj-a
        "skill-proj-b": "project:proj-b",          # private to proj-b
        "skill-prof-a": "profile:profile_a",       # private to profile_a
    }
    for asset_id, source in specs.items():
        made[asset_id] = make_skill(tmp_path, database=database,
                                    asset_id=asset_id, revision=1,
                                    source=source)
    approvals = made["skill-public"]["approvals"]
    store = make_store(database, approvals=approvals)
    return {"database": database, "assets": made, "store": store,
            "approvals": approvals,
            "revisions": made["skill-public"]["store"]}


def service_for(env, *, workspaces=("proj-a", "proj-b"), profile=None,
                server_scope="srv-test", principal="user-1"):
    store = env["store"] if server_scope == "srv-test" and principal == "user-1" \
        else make_store(env["database"], approvals=env["approvals"],
                        server_scope=server_scope, principal=principal)
    deps = ResolverDeps(
        assignments=store,
        revisions=env["revisions"],
        approvals=env["approvals"],
        authorization=make_authorization(workspaces=workspaces,
                                         server_scope=server_scope),
        profile=profile,
    )
    return SkillsResolutionService(deps)


# -- 反例 1: fabricated projectId is a typed refusal, not an empty success -------

def test_fabricated_project_id_is_refused_not_answered_empty(env):
    service = service_for(env, workspaces=("proj-a",))
    with pytest.raises(AuthorizationError) as refusal:
        service.preview_effective(ResolutionTarget(
            project_id="proj-evil", harness_id="pi", session_ref="s"))
    assert refusal.value.code == "WORKSPACE_UNKNOWN"


def test_workspace_lookup_without_registry_is_a_typed_refusal(env):
    from ordessa_skills.assignments.authorization import AssetAuthorization
    deps = ResolverDeps(
        assignments=env["store"], revisions=env["revisions"],
        approvals=env["approvals"],
        # no registry injected at all: honest refusal beats pretending a
        # project does or does not exist (the seam is disclosed, not faked)
        authorization=AssetAuthorization(workspace_lookup=None,
                                         server_scope="srv-test"),
    )
    with pytest.raises(AuthorizationError) as refusal:
        SkillsResolutionService(deps).preview_effective(ResolutionTarget(
            project_id="proj-a", harness_id="pi", session_ref="s"))
    assert refusal.value.code == "WORKSPACE_UNKNOWN"


# -- 反例 2: A-private content offered to B ---------------------------------------

def test_project_private_skill_resolved_by_its_own_project(env):
    store = env["store"]
    store.upsert(scope_kind="project", scope_id="proj-a",
                 asset_id="skill-proj-a", decision=DECISION_ENABLE, revision=1)
    view = service_for(env).preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="pi", session_ref="s"))
    assert [item["assetId"] for item in view["resolvedSkills"]] == ["skill-proj-a"]
    assert view["resolvedSkills"][0]["originScope"] == "project"


def test_project_a_private_skill_offered_to_project_b_is_refused(env):
    store = env["store"]
    # a row in proj-b's own layer naming proj-a's private content: the
    # write succeeds (the store has no origin view) — resolution is where
    # ownership bites, with a typed refusal, not a filtered-out item.
    store.upsert(scope_kind="project", scope_id="proj-b",
                 asset_id="skill-proj-a", decision=DECISION_ENABLE, revision=1)
    with pytest.raises(AuthorizationError) as refusal:
        service_for(env).preview_effective(ResolutionTarget(
            project_id="proj-b", harness_id="pi", session_ref="s"))
    assert refusal.value.code == "RESOLUTION_FOREIGN_CONTENT"


def test_project_private_in_user_global_layer_is_refused(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-proj-a",
                 decision=DECISION_ENABLE, revision=1)
    with pytest.raises(AuthorizationError) as refusal:
        service_for(env).preview_effective(ResolutionTarget(
            project_id="proj-a", harness_id="pi", session_ref="s"))
    assert refusal.value.code == "RESOLUTION_FOREIGN_CONTENT"


# -- Profile-private content -------------------------------------------------------

def test_profile_private_only_through_its_own_profile(env):
    store = env["store"]
    # profile-private content referenced from the project layer: refused
    store.upsert(scope_kind="project", scope_id="proj-a",
                 asset_id="skill-prof-a", decision=DECISION_ENABLE, revision=1)
    with pytest.raises(AuthorizationError) as refusal:
        service_for(env).preview_effective(ResolutionTarget(
            project_id="proj-a", harness_id="pi", session_ref="s"))
    assert refusal.value.code == "RESOLUTION_FOREIGN_CONTENT"
    # through its own Profile facet it resolves
    store.remove(scope_kind="project", scope_id="proj-a",
                 asset_id="skill-prof-a")
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-prof-a", DECISION_ENABLE, 1)])
    view = service_for(env, profile=profile).preview_effective(
        ResolutionTarget(project_id="proj-a", harness_id="pi",
                         profile_id="profile_a", session_ref="s"))
    assert [item["assetId"] for item in view["resolvedSkills"]] == ["skill-prof-a"]
    assert view["resolvedSkills"][0]["originScope"] == "profile"


def test_profile_private_cannot_cross_harnesses(env):
    # profile_a lives on `pi`; targeting a session on codex with that
    # profile is a typed refusal (Profile 的 harnessId 固定), and the
    # profile-private content never rides into another harness's chain.
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-prof-a", DECISION_ENABLE, 1)])
    service = service_for(env, profile=profile)
    with pytest.raises(Exception) as refusal:
        service.preview_effective(ResolutionTarget(
            project_id="proj-a", harness_id="codex",
            profile_id="profile_a", session_ref="s"))
    assert getattr(refusal.value, "code", None) == "PROFILE_HARNESS_MISMATCH"


def test_unknown_profile_is_a_typed_refusal(env):
    profile = FakeProfileLayer(harness=None, entries=[])
    service = service_for(env, profile=profile)
    with pytest.raises(Exception) as refusal:
        service.preview_effective(ResolutionTarget(
            project_id="proj-a", harness_id="pi",
            profile_id="profile_ghost", session_ref="s"))
    assert getattr(refusal.value, "code", None) == "PROFILE_UNKNOWN"


# -- 反例 3: cross-server reference ---------------------------------------------

def test_assignments_never_cross_server_scopes(env):
    store_a = env["store"]
    store_a.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-public",
                   decision=DECISION_ENABLE, revision=1)
    # the SAME principal in ANOTHER server data domain (second injected
    # scope over the same DB file — the cross-server shape under test):
    store_b = make_store(env["database"], approvals=env["approvals"],
                         server_scope="srv-other")
    assert store_b.list() == []          # nothing leaks across scopes
    service_b = service_for(env, server_scope="srv-other")
    view_b = service_b.preview_effective(ResolutionTarget(
        project_id="proj-a", harness_id="pi", session_ref="s"))
    assert view_b["resolvedSkills"] == []
    # writing the "same" layer through srv-other creates its own row; it
    # cannot move srv-test's row (row versions prove it)
    store_b.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-public",
                   decision=DECISION_ENABLE, revision=1)
    assert [row["rowVersion"] for row in store_a.list()] == [1]
    assert [row["rowVersion"] for row in store_b.list()] == [1]
    with env["database"].read() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM skill_assignments").fetchone()["c"]
    assert total == 2


# -- FR09: identity is injected, never self-declared -------------------------------

def test_client_cannot_self_declare_owner_or_path(env):
    # upsert takes no owner/path arguments at all — the stored row carries
    # ONLY the injected server_scope/principal; an API caller has no lever
    # to claim another principal's layer.
    store = env["store"]
    row = store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-public",
                       decision=DECISION_ENABLE, revision=1)
    assert row["serverScope"] == "srv-test"
    assert row["principal"] == "user-1"
    other_principal = make_store(env["database"], approvals=env["approvals"],
                                 principal="user-2")
    assert other_principal.list() == []
    # constructor refuses empty injected identity (no anonymous scope)
    with pytest.raises(Exception) as refusal:
        AssignmentStore(env["database"], scope=AssignmentScope(
            server_scope="", principal=""))
    assert getattr(refusal.value, "code", None) == "ASSIGNMENT_INVALID"
