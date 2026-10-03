"""Snapshot freeze tests (FR08, G18 pure-decision side; data-model.md
§解析顺序 last paragraph).

Covered here:
* digest stability — the same resolution content with shuffled collection
  orders digests to the same snapshotDigest (stable ordering + canonical
  JSON), and a content change moves it (not a constant);
* moved-revision refusal — any assignment row version, Profile identity or
  resolved-pin shift after the freeze makes ``matches_frozen`` False and
  ``assert_apply_eligible`` refuse with SNAPSHOT_STALE (在任何原生写入前拒绝);
* retry idempotency through the freeze — replaying a settled operationKey
  leaves the digest untouched, while a real second write moves it;
* the contracts.md sharing rule — 查询与每次提交的 plan 共享同一解析算法 —
  proven by call-counting the ONE shared method both entry points go
  through, plus output equality for identical inputs.

The apply itself (native writes + one prompt send) is owned by C0's
harness-api (api-requests.md §G2) and deliberately absent — nothing here
fakes the other half of G18.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from assignments_support import (
    FakeProfileLayer,
    make_authorization,
    make_database,
    make_skill,
    make_store,
)
from ordessa_skills.assignments.model import (
    DECISION_DISABLE,
    DECISION_ENABLE,
    SCOPE_PROJECT,
    SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import ProfileSkillEntry
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)
from ordessa_skills.assignments.snapshot import (
    SkillSnapshot,
    SnapshotError,
    assert_apply_eligible,
    build_snapshot,
    canonical_digest,
    matches_frozen,
)


@pytest.fixture()
def env(tmp_path):
    database = make_database(tmp_path)
    made = {}
    for asset in ("snap-one", "snap-two"):
        made[asset] = make_skill(tmp_path, database=database,
                                 asset_id=asset, revision=1)
        made[asset] = make_skill(tmp_path, database=database,
                                 asset_id=asset, revision=2)
    approvals = made["snap-one"]["approvals"]
    store = make_store(database, approvals=approvals)
    return {"database": database, "store": store, "assets": made,
            "approvals": approvals, "revisions": made["snap-one"]["store"]}


def service_for(env, profile=None):
    deps = ResolverDeps(
        assignments=env["store"], revisions=env["revisions"],
        approvals=env["approvals"],
        authorization=make_authorization(workspaces=("proj-a",)),
        profile=profile,
    )
    return SkillsResolutionService(deps)


TARGET = ResolutionTarget(project_id="proj-a", harness_id="pi",
                          profile_id=None, session_ref="session-9",
                          runtime_generation=7)


def seed(store):
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="snap-one",
                 decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 asset_id="snap-two", decision=DECISION_ENABLE, revision=2)


def _rehydrate(view):
    """Build a SkillSnapshot back from its frozen wire view — what a later
    apply request would hold (the freeze travels as data, not as an
    object identity)."""
    return SkillSnapshot(
        target_session=view["targetSession"],
        runtime_generation=view["runtimeGeneration"],
        project_id=view["projectId"],
        profile_revision=view["profileRevision"],
        assignment_revisions=view["assignmentRevisions"],
        resolved_skills=tuple(view["resolvedSkills"]),
        snapshot_digest=view["snapshotDigest"],
    )


# -- digest stability ---------------------------------------------------------------

def test_digest_is_independent_of_collection_order_but_not_a_constant(env):
    seed(env["store"])
    service = service_for(env)
    resolution = service.effective(TARGET)
    shuffled = replace(
        resolution,
        included=tuple(reversed(resolution.included)),
        assignment_revisions=dict(
            reversed(list(resolution.assignment_revisions.items()))),
    )
    frozen = build_snapshot(resolution)
    reshuffled = build_snapshot(shuffled)
    assert frozen.snapshot_digest == reshuffled.snapshot_digest
    assert frozen.snapshot_digest.startswith("sha256:")
    # the view's pin list is stably ordered by assetId regardless
    assert [item["assetId"] for item in frozen.view()["resolvedSkills"]] == \
        ["snap-one", "snap-two"]
    # a content change DOES move the digest (the equality above is not
    # an artifact of a constant function)
    env["store"].upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="snap-one",
                        decision=DECISION_DISABLE)
    changed = build_snapshot(service.effective(TARGET))
    assert changed.snapshot_digest != frozen.snapshot_digest
    # canonical JSON: key order inside the pre-image is irrelevant
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})


# -- moved revisions are refused ------------------------------------------------------

def test_moved_assignment_version_refuses_the_freeze(env):
    seed(env["store"])
    service = service_for(env)
    snapshot = _rehydrate(service.commit_plan(TARGET)["snapshot"])
    assert matches_frozen(snapshot, service, TARGET) is True
    # the user changes their mind on one layer: row_version moves
    env["store"].upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="snap-one",
                        decision=DECISION_DISABLE)
    assert matches_frozen(snapshot, service, TARGET) is False
    with pytest.raises(SnapshotError) as refusal:
        assert_apply_eligible(snapshot, service, TARGET)
    assert refusal.value.code == "SNAPSHOT_STALE"


def test_moved_profile_identity_refuses_the_freeze(env):
    seed(env["store"])
    profile = FakeProfileLayer(
        harness="pi",
        entries=[ProfileSkillEntry("snap-one", "inherit")],
        revision_identity={"configRevision": 3,
                           "configObjectDigest": "sha256:" + "3" * 64})
    service = service_for(env, profile=profile)
    target = ResolutionTarget(project_id="proj-a", harness_id="pi",
                              profile_id="profile_a", session_ref="s",
                              runtime_generation=1)
    snapshot = _rehydrate(service.commit_plan(target)["snapshot"])
    assert matches_frozen(snapshot, service, target) is True
    # Z1 bumps the profile config revision (nothing in Skills moved):
    profile._revision_identity["configRevision"] = 4
    assert matches_frozen(snapshot, service, target) is False
    with pytest.raises(SnapshotError) as refusal:
        assert_apply_eligible(snapshot, service, target)
    assert refusal.value.code == "SNAPSHOT_STALE"


def test_target_mismatch_is_a_typed_refusal_not_a_silent_false(env):
    seed(env["store"])
    service = service_for(env)
    snapshot = _rehydrate(service.commit_plan(TARGET)["snapshot"])
    with pytest.raises(SnapshotError) as refusal:
        matches_frozen(snapshot, service, ResolutionTarget(
            project_id="proj-a", harness_id="codex", session_ref="other",
            runtime_generation=7))
    assert refusal.value.code == "SNAPSHOT_TARGET_MISMATCH"


# -- retry idempotency through the freeze ---------------------------------------------

def test_operation_key_retry_leaves_the_digest_untouched(env):
    seed(env["store"])
    store = env["store"]
    service = service_for(env)
    # one guarded write (row version 1 -> 2)…
    moved = store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                         asset_id="snap-two", decision=DECISION_ENABLE,
                         revision=2, expected_version=1, operation_key="k1")
    assert moved["rowVersion"] == 2
    digest = service.commit_plan(TARGET)["snapshot"]["snapshotDigest"]
    # …replayed with the same key: byte-identical result, no second bump,
    # the frozen digest still describes the present state
    again = store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                         asset_id="snap-two", decision=DECISION_ENABLE,
                         revision=2, expected_version=1, operation_key="k1")
    assert again == moved
    assert service.commit_plan(TARGET)["snapshot"]["snapshotDigest"] == digest
    # a REAL second write moves the version and the digest — the freeze
    # notices (the retry guard is not an accident of nothing changing)
    store.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                 asset_id="snap-two", decision=DECISION_ENABLE,
                 revision=1, expected_version=moved["rowVersion"])
    assert service.commit_plan(TARGET)["snapshot"]["snapshotDigest"] != digest


# -- the ONE shared algorithm: preview == commit plan ---------------------------------

def test_preview_and_plan_run_the_same_resolution_instance(env):
    seed(env["store"])
    profile = FakeProfileLayer(harness="pi", entries=[])
    service = service_for(env, profile=profile)
    target = ResolutionTarget(project_id="proj-a", harness_id="pi",
                              profile_id="profile_a", session_ref="s1",
                              runtime_generation=2)
    calls: list[ResolutionTarget] = []
    original = service.effective

    def spy(t):
        calls.append(t)
        return original(t)

    service.effective = spy  # instance-level: intercepts BOTH entry points
    preview = service.preview_effective(target)
    plan = service.commit_plan(target)
    assert len(calls) == 2, "preview and plan must share ONE algorithm"
    # identical output for identical inputs: the plan's skills are exactly
    # the preview's resolvedSkills (assetId/revision/digest/selectedBy)
    assert plan["plan"] == [
        {"assetId": item["assetId"], "revision": item["revision"],
         "treeDigest": item["treeDigest"], "selectedBy": item["selectedBy"]}
        for item in preview["resolvedSkills"]]
    assert plan["assignmentRevisions"] == preview["assignmentRevisions"]
    # and the plan carries the data-model snapshot identity fields
    assert plan["snapshot"]["targetSession"] == "s1"
    assert plan["snapshot"]["runtimeGeneration"] == 2
    assert plan["snapshot"]["projectId"] == "proj-a"
    assert plan["snapshot"]["profileRevision"]["profileId"] == "profile_a"
