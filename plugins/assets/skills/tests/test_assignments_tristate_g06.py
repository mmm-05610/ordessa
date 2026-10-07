"""G06 — later layers override the tri-state correctly and pin the revision
(verification.md G06: 后层三态正确覆盖并固定 revision;
反例: inherit 被当 disable / 启用未批准版 / 管理员强制规则被覆盖).

Includes the data-model.md §解析顺序 flagship chain: 一份 Skill 在全局启用、
项目禁用后，Profile 可再次显式启用，但必须指向获准修订 — and the seam that
keeps the admin policy layer outside the overridable six (its real
permissions-api is pending; the in-test fake proves the seam).
"""
from __future__ import annotations

import pytest

from assignments_support import (
    FakeMandatoryPolicy,
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
    LAYER_MANDATORY,
    LAYER_PROFILE,
    LAYER_PROJECT_ANY,
    LAYER_USER_GLOBAL_ANY,
    SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import (
    MandatoryRule,
    ProfileSkillEntry,
    SessionOverride,
)
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    for asset_id in ("skill-gamma", "skill-delta"):
        made[asset_id] = make_skill(tmp_path, database=database,
                                    asset_id=asset_id, revision=1)
        made[asset_id] = make_skill(tmp_path, database=database,
                                    asset_id=asset_id, revision=2)
    # r3 installed but NEVER approved — the G06 「启用未批准版」 probe
    staging = tmp_path / "src" / "skill-gamma" / "3"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "SKILL.md").write_text(
        "---\nname: skill-gamma\ndescription: A demo skill.\n---\n\nBody r3.\n",
        encoding="utf-8")
    made["skill-gamma"]["store"].install(staging, asset_id="skill-gamma",
                                         revision=3)
    made["skill-gamma"]["records"].publish(
        kind="skill", name="skill-gamma", revision=3,
        digest="sha256:" + "9" * 64, asset_id="skill-gamma")
    store = make_store(database, approvals=made["skill-gamma"]["approvals"])
    return {
        "database": database,
        "assets": made,
        "store": store,
        "approvals": made["skill-gamma"]["approvals"],
        "revisions": made["skill-gamma"]["store"],
    }


def service_for(env, *, profile=None, mandatory=None):
    deps = ResolverDeps(
        assignments=env["store"],
        revisions=env["revisions"],
        approvals=env["approvals"],
        authorization=make_authorization(workspaces=("proj-a",)),
        profile=profile,
        mandatory=mandatory,
    )
    return SkillsResolutionService(deps)


def target(**kwargs):
    base = dict(project_id="proj-a", harness_id="pi", session_ref="s1")
    base.update(kwargs)
    return ResolutionTarget(**base)


def by_asset(view):
    merged = {item["assetId"]: ("included", item)
              for item in view["resolvedSkills"]}
    merged.update({item["assetId"]: ("excluded", item)
                   for item in view["excludedSkills"]})
    return merged


# -- the flagship override chain --------------------------------------------------

def test_global_enable_project_disable_profile_reenable_at_approved_revision(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                 decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-delta",
                 decision=DECISION_ENABLE, revision=1)
    for asset in ("skill-gamma", "skill-delta"):
        store.upsert(scope_kind="project", scope_id="proj-a", asset_id=asset,
                     decision=DECISION_DISABLE)
    # Profile re-enables gamma at the approved revision 2; leaves delta out
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-gamma", "enable", 2)])
    service = service_for(env, profile=profile)
    view = service.preview_effective(target(profile_id="profile_a"))
    state = by_asset(view)
    kind, gamma = state["skill-gamma"]
    assert kind == "included"
    assert gamma["revision"] == 2                       # 固定 revision
    assert gamma["selectedBy"]["layer"] == LAYER_PROFILE
    kind, delta = state["skill-delta"]
    assert kind == "excluded"
    assert delta["excludedBy"]["layer"] == LAYER_PROJECT_ANY
    # the session layer can still out-rank the profile for one commit…
    service2 = service_for(env, profile=profile)
    view2 = service2.preview_effective(target(
        profile_id="profile_a",
        session_overrides=(SessionOverride("skill-gamma", DECISION_DISABLE),)))
    assert by_asset(view2)["skill-gamma"][0] == "excluded"
    assert by_asset(view2)["skill-gamma"][1]["excludedBy"]["layer"] == \
        "session_override"


# -- inherit is not disable (反例: inherit 被当 disable) --------------------------------

def test_inherit_layers_keep_the_lower_decision_and_are_marked_inherit(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                 decision=DECISION_ENABLE, revision=1)
    service = service_for(env)
    view = service.preview_effective(target())
    gamma = view["resolvedSkills"][0]
    assert gamma["revision"] == 1
    assert gamma["selectedBy"]["layer"] == LAYER_USER_GLOBAL_ANY
    # the five layers above it are recorded as *inherit*, not as disables:
    rest = [entry for entry in gamma["layerDecisions"]
            if entry["layer"] != LAYER_USER_GLOBAL_ANY]
    assert [entry["decision"] for entry in rest] == ["inherit"] * 5
    # An asset only ever *mentioned* with an explicit inherit on the Profile
    # layer, and enabled nowhere, is absent with a reason — a shape the
    # resolver keeps deliberately distinct from a disable (which carries
    # excludedBy). 反例: inherit 被当 disable.
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-delta", "inherit")])
    service2 = service_for(env, profile=profile)
    view2 = service2.preview_effective(target(profile_id="profile_a"))
    delta = by_asset(view2)["skill-delta"]
    assert delta[0] == "excluded"
    assert delta[1]["excludedBy"] is None
    assert delta[1]["absentReason"] == "not_enabled"
    # the same asset, once actually disabled at a layer, is excluded *by*
    # that layer — the two shapes stay distinguishable in the view
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-delta",
                 decision=DECISION_DISABLE)
    state = by_asset(service2.preview_effective(target(profile_id="profile_a")))
    assert state["skill-delta"][1]["excludedBy"] is not None
    assert state["skill-delta"][1]["excludedBy"]["layer"] == LAYER_USER_GLOBAL_ANY


# -- enabling an unapproved revision is a typed refusal (启用未批准版) ------------------

def test_assignment_enable_of_unapproved_revision_is_refused(env):
    store = env["store"]
    with pytest.raises(Exception) as refusal:
        store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                     decision=DECISION_ENABLE, revision=3)
    assert getattr(refusal.value, "code", None) == "SKILL_APPROVAL_MISSING"
    # and the row was not half-written: the layer is still empty
    assert store.list(asset_id="skill-gamma") == []


def test_profile_enable_of_unapproved_revision_is_refused_at_resolve(env):
    # a Profile facet entry (Z1 shape) naming r3 (installed, unapproved):
    # the WRITE-side gate cannot run here, so the RESOLVE-side gate must —
    # typed refusal, never a silently filtered list (G06 + contracts.md).
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                 decision=DECISION_ENABLE, revision=1)
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-gamma", "enable", 3)])
    service = service_for(env, profile=profile)
    with pytest.raises(Exception) as refusal:
        service.preview_effective(target(profile_id="profile_a"))
    assert getattr(refusal.value, "code", None) == "SKILL_APPROVAL_MISSING"


def test_enable_gate_is_required_not_optional(env):
    from ordessa_skills.assignments.store import AssignmentScope, AssignmentStore
    bare = AssignmentStore(env["database"], scope=AssignmentScope(
        server_scope="srv-test", principal="user-1"))
    bare.ensure_schema()
    with pytest.raises(AssignmentError) as refusal:
        bare.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                    decision=DECISION_ENABLE, revision=1)
    assert refusal.value.code == "ASSIGNMENT_SCHEMA_UNAVAILABLE"


# -- the mandatory policy layer cannot be overridden (管理员强制规则被覆盖) ---------------

def test_mandatory_enable_survives_profile_and_session_disable(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-delta",
                 decision=DECISION_ENABLE, revision=1)
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-delta", "disable")])
    mandatory = FakeMandatoryPolicy([
        MandatoryRule("skill-delta", DECISION_ENABLE, 2)])
    service = service_for(env, profile=profile, mandatory=mandatory)
    view = service.preview_effective(target(
        profile_id="profile_a",
        session_overrides=(SessionOverride("skill-delta", DECISION_DISABLE),)))
    delta = by_asset(view)["skill-delta"]
    assert delta[0] == "included"
    assert delta[1]["revision"] == 2                    # pinned by the policy
    assert delta[1]["selectedBy"]["layer"] == LAYER_MANDATORY
    assert any(d["kind"] == "mandatory_policy_applied"
               for d in view["diagnostics"])


def test_mandatory_disable_survives_every_lower_enable(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                 decision=DECISION_ENABLE, revision=1)
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-gamma", "enable", 2)])
    mandatory = FakeMandatoryPolicy([MandatoryRule("skill-gamma", DECISION_DISABLE)])
    service = service_for(env, profile=profile, mandatory=mandatory)
    view = service.preview_effective(target(
        profile_id="profile_a",
        session_overrides=(SessionOverride("skill-gamma", DECISION_ENABLE, 1),)))
    gamma = by_asset(view)["skill-gamma"]
    assert gamma[0] == "excluded"
    assert gamma[1]["excludedBy"]["layer"] == LAYER_MANDATORY


def test_mandatory_enable_without_revision_keeps_the_lower_pin(env):
    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-gamma",
                 decision=DECISION_ENABLE, revision=2)
    mandatory = FakeMandatoryPolicy([MandatoryRule("skill-gamma", DECISION_ENABLE)])
    service = service_for(env, mandatory=mandatory)
    view = service.preview_effective(target(
        session_overrides=(SessionOverride("skill-gamma", DECISION_DISABLE),)))
    gamma = by_asset(view)["skill-gamma"]
    assert gamma[0] == "included"          # forced back in by the policy
    assert gamma[1]["revision"] == 2       # revision stays the selected pin
    assert gamma[1]["selectedBy"]["forcedBy"] == LAYER_MANDATORY
