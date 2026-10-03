"""D1 / AC-3 / AC-7: bindings pin revisions and never move by themselves.
Ported from `plugins/assets/tests/test_records_pinning.py` @ 752f148b1b with
every assertion intact (G04/G08: bind pins latest-at-bind-time, a new
revision never moves a binding, explicit updates move only the target).
"""
from __future__ import annotations

import pytest

from ordessa_skills.api.errors import BindingError
from ordessa_skills.library.records import AssetRecords
from pacthold_runtime_compat.storage import Database


@pytest.fixture()
def records(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    with database.transaction() as conn:
        for profile_id in ("profile_a", "profile_b"):
            conn.execute(
                "INSERT INTO server_profiles(id,version,name,harness_type,config_revision,"
                "native_generation,config_object_digest,created_at,updated_at) "
                "VALUES (?,1,'role','pi',1,0,'sha256:x','t','t')", (profile_id,))
    return AssetRecords(database)


def _publish(records, revision, digest_suffix, asset_id="demo-skill"):
    kind, body = records.publish(
        kind="skill", name="demo-skill", revision=revision,
        digest="sha256:" + digest_suffix * 64, asset_id=asset_id,
        description="A demo.", source="local:test")
    return body


def test_publish_then_bind_without_revision_pins_the_latest_at_bind_time(records):
    _publish(records, 1, "1")
    binding = records.bind(profile_id="profile_a", asset_id="demo-skill")
    assert binding["revision"] == 1 and binding["enabled"] is True


def test_a_new_revision_never_moves_any_binding(records):
    _publish(records, 1, "1")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    _publish(records, 2, "2")
    assert records.bindings("profile_a")[0]["revision"] == 1


def test_explicit_update_binding_moves_only_the_target_profile(records):
    _publish(records, 1, "1")
    _publish(records, 2, "2")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    records.bind(profile_id="profile_b", asset_id="demo-skill", revision=2)
    moved = records.update_binding(profile_id="profile_a", asset_id="demo-skill", revision=2)
    assert moved["revision"] == 2
    assert records.bindings("profile_b")[0]["revision"] == 2
    assert records.bindings("profile_a")[0]["revision"] == 2
    # …and only the targeted pair: profile_b stays on its own pin (AC-7)
    records.update_binding(profile_id="profile_b", asset_id="demo-skill", revision=1)
    assert records.bindings("profile_a")[0]["revision"] == 2


def test_two_profiles_pin_opposite_revisions_without_overwriting(records):
    _publish(records, 1, "1")
    _publish(records, 2, "2")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1, enabled=False)
    records.bind(profile_id="profile_b", asset_id="demo-skill", revision=2)
    a, b = records.bindings("profile_a")[0], records.bindings("profile_b")[0]
    assert (a["revision"], a["enabled"]) == (1, False)
    assert (b["revision"], b["enabled"]) == (2, True)


def test_unknown_revision_and_unknown_asset_are_typed_refusals(records):
    _publish(records, 1, "1")
    with pytest.raises(BindingError) as refusal:
        records.bind(profile_id="profile_a", asset_id="demo-skill", revision=9)
    assert refusal.value.code == "ASSET_REVISION_UNKNOWN"
    with pytest.raises(BindingError) as refusal:
        records.bind(profile_id="profile_a", asset_id="ghost", revision=1)
    assert refusal.value.code == "ASSET_NOT_FOUND"


def test_unbind_removes_exactly_one_pair(records):
    _publish(records, 1, "1")
    records.bind(profile_id="profile_a", asset_id="demo-skill", revision=1)
    records.unbind(profile_id="profile_a", asset_id="demo-skill")
    assert records.bindings("profile_a") == []
    with pytest.raises(BindingError) as refusal:
        records.unbind(profile_id="profile_a", asset_id="demo-skill")
    assert refusal.value.code == "BINDING_NOT_FOUND"


def test_asset_view_carries_no_content_and_keeps_the_source(records):
    body = _publish(records, 1, "1")
    updated = records.publish(kind="skill", name="demo-skill", revision=2,
                              digest="sha256:" + "2" * 64,
                              asset_id=body["asset_id"])[1]
    assert updated["latest_revision"] == 2 and updated["source"] == "local:test"
    assert updated["asset_id"] == "demo-skill"
    assert "content" not in str(updated)
