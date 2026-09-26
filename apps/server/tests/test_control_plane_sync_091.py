"""Order 091 control-plane sync gates: first deploy, incremental, authority, secrets.

Everything here is transport-independent (the engine, not a live worker): a
control-plane snapshot -> manifest -> an execution-side projection, exercised
in-process. The gates mirror the order's G1-G4 and each carries the counter-case
that makes it bite.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server_compat.execution.control_plane_sync import (
    ControlPlaneSyncError, ExecutionSideProjection, SYNC_SET,
    collect_sync_snapshot, plan_deployment, verify_parity,
    SyncItem,
)


def _snapshot():
    return [
        SyncItem("profile", "profile_a", 1, {"harness_type": "pi", "name": "Alpha",
                                             "credential_id": "cred_a", "permission_preset": "default"}),
        SyncItem("provider-model", "pm_a", 1, {"harness": "pi", "provider": "deepseek"}),
        SyncItem("workspace", "ws_a", 1, {"path": "/workspace", "env_kind": "wsl"}),
    ]


def test_first_deploy_makes_the_execution_side_item_by_item_identical():
    """G1: an empty execution side, deployed once, matches the manifest exactly
    (per-item version + digest)."""
    items = _snapshot()
    manifest = plan_deployment(items)
    projection = ExecutionSideProjection()
    report = projection.apply(manifest, items)

    assert sorted(report.applied) == ["profile:profile_a", "provider-model:pm_a", "workspace:ws_a"]
    assert verify_parity(projection, manifest) == []
    # the deployment ledger names every record it carried
    assert manifest.as_dict()["manifestDigest"].startswith("sha256:")
    assert [e.kind for e in manifest.entries] == sorted(
        [e.kind for e in manifest.entries])  # deterministic order


def test_only_half_synced_is_caught():
    """G1 counter-case: a deploy that carried only part of the set leaves a full
    manifest line missing, so the completeness check fails rather than reading as
    'synced'."""
    items = _snapshot()
    full_manifest = plan_deployment(items)
    projection = ExecutionSideProjection()
    projection.apply(plan_deployment(items[:2]), items[:2])  # workspace never delivered
    problems = verify_parity(projection, full_manifest)
    assert problems == ["workspace:ws_a=missing"], problems


def test_redeploy_of_the_same_version_is_idempotent_and_a_change_lands():
    """G2: re-delivery of the same version does not re-apply; a version bump does.
    apply_count proves the replay did nothing."""
    items = _snapshot()
    manifest = plan_deployment(items)
    projection = ExecutionSideProjection()
    first = projection.apply(manifest, items)
    assert first.apply_count == {"profile:profile_a": 1, "provider-model:pm_a": 1,
                                 "workspace:ws_a": 1}

    replay = projection.apply(manifest, items)
    assert replay.applied == [], replay.applied          # nothing re-applied
    assert set(replay.unchanged) == {"profile:profile_a", "provider-model:pm_a", "workspace:ws_a"}
    assert replay.apply_count["profile:profile_a"] == 0  # this call applied it zero times

    changed = list(items)
    changed[0] = SyncItem("profile", "profile_a", 2, {**dict(items[0].body), "name": "Alpha2"})
    bumped = plan_deployment(changed)
    third = projection.apply(bumped, changed)
    assert third.applied == ["profile:profile_a"], third.applied
    assert third.apply_count["profile:profile_a"] == 1   # landed exactly once more
    assert verify_parity(projection, bumped) == []


def test_incremental_single_record_delivery_is_idempotent():
    """G2: apply_incremental on an unchanged record is a no-op; on a change it lands."""
    projection = ExecutionSideProjection()
    item = SyncItem("provider-model", "pm_b", 1, {"provider": "deepseek"})
    assert projection.apply_incremental(item) == "applied"
    assert projection.apply_incremental(item) == "unchanged"
    assert projection.apply_incremental(
        SyncItem("provider-model", "pm_b", 2, {"provider": "moonshot"})) == "applied"


def test_execution_side_local_edit_is_refused_windows_wins():
    """G4: the execution side cannot author an edit to a synced record."""
    items = _snapshot()
    projection = ExecutionSideProjection()
    projection.apply(plan_deployment(items), items)
    with pytest.raises(ControlPlaneSyncError) as refused:
        projection.local_edit("profile", "profile_a", {"name": "hijacked"})
    assert refused.value.code == "CONTROL_PLANE_AUTHORITY"
    # the authoritative body is untouched - the edit was refused, not applied
    assert projection.get("profile", "profile_a").body["name"] == "Alpha"


def test_credential_content_cannot_enter_the_sync_set():
    """G3: a secret-shaped field is refused by the planner and never reaches the
    projection; a synced body keeps only id/kind references, no secret value."""
    secret = SyncItem("profile", "p", 1, {"name": "ok", "api_key": "sk-live-secret"})
    with pytest.raises(ServerError) as refused:
        plan_deployment([secret])
    assert refused.value.code == "SECRET_FIELD_FORBIDDEN"

    projection = ExecutionSideProjection()
    projection.apply(plan_deployment(_snapshot()), _snapshot())
    dumped = repr([r.body for r in projection._records.values()])
    assert "sk-live-secret" not in dumped
    # the synced profile references the credential by id only, never by content
    assert projection.get("profile", "profile_a").body["credential_id"] == "cred_a"


@pytest.mark.parametrize("kind", ["session", "native-home", "transcript", "hook", "asset-binding"])
def test_only_the_declared_sync_set_is_accepted(kind):
    """The set is closed: an out-of-set kind is refused by name, not silently
    synced (sessions/home/transcripts) or quietly stretched (hook/binding)."""
    assert kind not in SYNC_SET
    with pytest.raises(ControlPlaneSyncError) as refused:
        plan_deployment([SyncItem(kind, "x", 1, {"any": "thing"})])
    assert refused.value.code == "SYNC_KIND_UNSUPPORTED"


def test_collect_snapshot_maps_real_rows_to_secret_free_items():
    """The real-record adapter: identity + version + public body; a locator or
    secret value on the row would be refused by the same validation."""
    profiles = [{"profile_id": "p1", "version": 3, "harness_type": "pi",
                 "config_object_digest": "sha256:abc", "credential_id": "c1"}]
    provider_models = [{"id": "pm1", "version": 1, "provider": "deepseek"}]
    workspaces = [{"id": "w1", "version": 2, "path": "/workspace", "env_kind": "wsl"}]
    items = collect_sync_snapshot(profiles=profiles, provider_models=provider_models,
                                  workspaces=workspaces)
    assert {i.kind for i in items} == {"profile", "provider-model", "workspace"}
    profile = next(i for i in items if i.kind == "profile")
    assert profile.version == 3
    assert profile.body["credential_id"] == "c1"          # reference travels
    assert "secret_locator" not in profile.body           # locator/content do not
    plan_deployment(items)  # would raise SECRET_FIELD_FORBIDDEN if a secret leaked in
