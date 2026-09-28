"""Mechanism policy service (US1, PV-06/PV-08 backend half).

G03: enabling/disabling never grants or revokes execution permission and
never deletes data.  G04: forbidden override *writes* still allow reads and
clears.  CAS + idempotency + impact preview.
"""
from __future__ import annotations

import pytest

from conftest import make_core
from ordessa_profile import ProfileError

MODEL = None  # providers defined per-test where needed


def test_policy_defaults_enable_and_allow(tmp_path):
    core = make_core(tmp_path)
    policy = core.policy.get_public("local")
    assert policy["revision"] == 1
    assert policy["allow_user_override_writes_global"] is True
    assert policy["facet_enabled"] == {}


def test_update_is_cas_and_idempotent(tmp_path):
    core = make_core(tmp_path)
    first = core.policy.update("k1", realm="local", expected_revision=1,
                               patch={"allow_user_override_writes_global": False},
                               caller="settings-ui")
    assert first["policy"]["revision"] == 2
    assert first["policy"]["allow_user_override_writes_global"] is False
    with pytest.raises(ProfileError) as exc:
        core.policy.update("k2", realm="local", expected_revision=1,
                           patch={}, caller="settings-ui")
    assert exc.value.code == "POLICY_REVISION_CONFLICT"
    replay = core.policy.update("k1", realm="local", expected_revision=1,
                                patch={"allow_user_override_writes_global": False},
                                caller="settings-ui")
    assert replay["policy"]["revision"] == 2  # idempotent replay
    assert core.policy.get_public("local")["revision"] == 2


def test_same_key_different_payload_refused(tmp_path):
    core = make_core(tmp_path)
    core.policy.update("k1", realm="local", expected_revision=1,
                       patch={"allow_user_override_writes_global": False},
                       caller="ui")
    with pytest.raises(ProfileError) as exc:
        core.policy.update("k1", realm="local", expected_revision=2,
                           patch={}, caller="ui")
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_forbidden_override_write_blocks_but_reads_and_clears_survive(tmp_path):
    from conftest import ScriptedProvider
    model = ScriptedProvider("model_selection", ("model",))
    core = make_core(tmp_path, providers=(model,))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    core.profiles.set_facet_values(
        "f1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.set_overlay("o1", session_id="S",
                              facet_id="model_selection", item_id="model",
                              value="m2")
    core.policy.update("p1", realm="local", expected_revision=1,
                       patch={"allow_user_override_writes": {
                           "model_selection": False}},
                       caller="ui")
    with pytest.raises(ProfileError) as exc:
        core.sessions.set_overlay("o2", session_id="S",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
    assert exc.value.code == "OVERRIDE_WRITES_FORBIDDEN"
    # G04: the existing override is still visible and can still be cleared
    items = {i["item_id"]: i for i in core.sessions.session_config("S")["items"]}
    assert items["model"]["value"] == "m2"
    assert items["model"]["source"] == "session_only"
    core.sessions.clear_overlay("c1", session_id="S",
                                facet_id="model_selection", item_id="model")
    items = {i["item_id"]: i for i in core.sessions.session_config("S")["items"]}
    assert items["model"]["source"] == "profile"


def test_disabled_facet_blocks_overlay_writes_and_keeps_data(tmp_path):
    from conftest import ScriptedProvider
    model = ScriptedProvider("model_selection", ("model",))
    core = make_core(tmp_path, providers=(model,))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    core.profiles.set_facet_values(
        "f1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.policy.update("p1", realm="local", expected_revision=1,
                       patch={"facet_enabled": {"model_selection": False}},
                       caller="ui")
    # stored data survives the disable (G03/G13)
    assert core.profiles.facet_values(a["profile_id"])[0]["value"] == "m1"
    # new surface writes are refused with the typed disabled code
    with pytest.raises(ProfileError) as exc:
        core.sessions.set_overlay(
            "o1", session_id="S", facet_id="model_selection",
            item_id="model", value="m2")
    assert exc.value.code == "FACET_DISABLED"
    # re-enable, write an overlay, disable again: clearing stays available
    core.policy.update("p2", realm="local",
                       expected_revision=core.policy.get_public("local")[
                           "revision"],
                       patch={"facet_enabled": {"model_selection": True}},
                       caller="ui")
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m2")
    core.policy.update("p3", realm="local",
                       expected_revision=core.policy.get_public("local")[
                           "revision"],
                       patch={"facet_enabled": {"model_selection": False}},
                       caller="ui")
    core.sessions.clear_overlay(
        "c1", session_id="S", facet_id="model_selection", item_id="model")
    items = {i["item_id"]: i for i in core.sessions.session_config("S")["items"]}
    assert items["model"]["source"] == "profile"


def test_impact_preview_counts_affected_profiles(tmp_path):
    from conftest import ScriptedProvider
    model = ScriptedProvider("model_selection", ("model",))
    core = make_core(tmp_path, providers=(model,))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    for pid, key in ((a["profile_id"], "f1"), (b["profile_id"], "f2")):
        core.profiles.set_facet_values(
            key, profile_id=pid, expected_version=1,
            values=[{"facet_id": "model_selection", "item_id": "model",
                     "value": "m1"}])
    result = core.policy.update(
        "p1", realm="local", expected_revision=1,
        patch={"facet_enabled": {"model_selection": False}}, caller="ui")
    assert result["impact"]["disabling"]["model_selection"][
        "profiles_with_values"] == 2


def test_realms_are_isolated(tmp_path):
    core = make_core(tmp_path)
    core.policy.update("k1", realm="alpha", expected_revision=1,
                       patch={"allow_user_override_writes_global": False},
                       caller="ui")
    assert core.policy.get_public("beta")[
        "allow_user_override_writes_global"] is True
    assert core.policy.get_public("alpha")[
        "allow_user_override_writes_global"] is False
