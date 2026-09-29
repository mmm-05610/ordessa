"""T09-T11 — US3 session overlays vs profile-global revisions (G3).

FR-015 next-turn pickup of global revisions; FR-016 session-only writes;
FR-017 per-item granularity; FR-018 per-item source facts; FR-019 per-item
restore-follow with persistence; FR-021 merged-config conflict refusal.
US3.1-3.7; SC-006/SC-007.
"""
from __future__ import annotations

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileError

MODEL = ScriptedProvider(
    "model_selection", ("model", "reasoning"),
    applies=frozenset({"pi", "codex"}),
    valid={"m1", "m2", "m3", "low", "high"},
)


def set_profile_values(core, pid, values, key="kpx"):
    version = core.profiles.get(pid)["version"]
    return core.profiles.set_facet_values(
        key, profile_id=pid, expected_version=version, values=values)


def two_session_world(tmp_path, *, store_name="profile-store.sqlite"):
    core = make_core(tmp_path, providers=(MODEL,))
    profile = core.profiles.create("kp", harness_id="pi", display_name="P")
    pid = profile["profile_id"]
    core.profiles.set_facet_values(
        "kp1", profile_id=pid, expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "model_selection", "item_id": "reasoning",
             "value": "low"},
        ])
    core.sessions.open_session("ka", session_id="A", harness_id="pi",
                               profile_id=pid)
    core.sessions.open_session("kb", session_id="B", harness_id="pi",
                               profile_id=pid)
    return core, pid


def effective_model_and_reasoning(core, session_id):
    items = {(i["facet_id"], i["item_id"]): i
             for i in core.sessions.session_config(session_id)["items"]}
    return (items.get(("model_selection", "model"), {}).get("value"),
            items.get(("model_selection", "reasoning"), {}).get("value"))


def test_us3_1_overlay_is_session_local_and_midturn_safe(tmp_path):
    core, pid = two_session_world(tmp_path)
    # a turn is already executing under M1 (recorded at its begin)
    running = core.sessions.begin_turn("t0", session_id="A")
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    # the running turn keeps M1 (FR-007; its record is immutable)
    assert running["effective"][0]["value"] == "m1"
    # P and B unchanged; A resolves M2 next turn
    assert effective_model_and_reasoning(core, "B") == ("m1", "low")
    values = {v["item_id"]: v["value"]
              for v in core.profiles.facet_values(pid)}
    assert values == {"model": "m1", "reasoning": "low"}
    assert effective_model_and_reasoning(core, "A") == ("m2", "low")


def test_us3_2_global_update_enters_unoverlaid_items_only(tmp_path):
    core, pid = two_session_world(tmp_path)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning",
         "value": "high"},
    ])
    assert effective_model_and_reasoning(core, "A") == ("m2", "high")
    assert effective_model_and_reasoning(core, "B") == ("m3", "high")
    values = {v["item_id"]: v["value"]
              for v in core.profiles.facet_values(pid)}
    assert values == {"model": "m3", "reasoning": "high"}


def test_us3_3_per_item_restore_follow_uses_current_profile_value(tmp_path):
    core, pid = two_session_world(tmp_path)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"}])
    core.sessions.clear_overlay(
        "ca", session_id="A", facet_id="model_selection", item_id="model")
    assert effective_model_and_reasoning(core, "A") == ("m3", "low")
    # P itself unchanged by the clear
    values = {v["item_id"]: v["value"]
              for v in core.profiles.facet_values(pid)}
    assert values["model"] == "m3"


def test_us3_4_overlay_survives_restart_and_stays_session_local(tmp_path):
    first = make_core(tmp_path, providers=(MODEL,))
    profile = first.profiles.create("kp", harness_id="pi", display_name="P")
    first.sessions.open_session("ka", session_id="A", harness_id="pi",
                                profile_id=profile["profile_id"])
    first.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    # "restart": a fresh core on the same store (same tmp store file)
    second = make_core(tmp_path, providers=(MODEL,))
    assert effective_model_and_reasoning(second, "A") == ("m2", None)
    profile_b = second.profiles.create("kb", harness_id="pi", display_name="PB")
    second.sessions.open_session(
        "kb2", session_id="B", harness_id="pi",
        profile_id=profile_b["profile_id"])
    assert effective_model_and_reasoning(second, "B") == (None, None)


def test_us3_5_incompatible_merge_refuses_turn_without_rewriting(tmp_path):
    conflict_provider = ScriptedProvider(
        "model_selection", ("model", "reasoning"),
        applies=frozenset({"pi"}),
        valid={"m1", "m2", "m3", "low", "high"},
        resolved_conflicts=["model"],
    )
    core = make_core(tmp_path, providers=(conflict_provider,))
    profile = core.profiles.create("kp", harness_id="pi", display_name="P")
    pid = profile["profile_id"]
    core.profiles.set_facet_values(
        "kp1", profile_id=pid, expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.sessions.open_session("ka", session_id="A", harness_id="pi",
                               profile_id=pid)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    # a global revision that merges badly with the overlay
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "reasoning",
         "value": "high"}])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="A")
    assert exc.value.code == "CONFIG_CONFLICT"
    assert exc.value.conflicts == [
        {"facet_id": "model_selection", "item_id": "model"}]
    # no partial application, no rewrite of overlay or profile
    assert effective_model_and_reasoning(core, "A") == ("m2", "high")
    assert core.sessions.turns("A") == []
    values = {v["item_id"]: v["value"]
              for v in core.profiles.facet_values(pid)}
    assert values == {"model": "m1", "reasoning": "high"}


def test_fr017_overlay_never_masks_facet_siblings(tmp_path):
    core, pid = two_session_world(tmp_path)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "reasoning",
         "value": "high"}])
    items = {(i["item_id"]): i["source"]
             for i in core.sessions.session_config("A")["items"]}
    assert items == {"model": "session_only", "reasoning": "profile"}


def test_us3_7_midturn_global_edit_leaves_running_turn_intact(tmp_path):
    core, pid = two_session_world(tmp_path)
    running = core.sessions.begin_turn("t0", session_id="A")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"}])
    stored = {t["turn_id"]: t for t in core.sessions.turns("A")}
    assert stored[running["turn_id"]]["effective"][0]["value"] == "m1"
    assert stored[running["turn_id"]]["config_revision"] == 2
    # next turn resolves the new revision (FR-015)
    nxt = core.sessions.begin_turn("t1", session_id="A")
    assert nxt["effective"][0]["value"] == "m3"
    assert nxt["config_revision"] == 3


def test_fr018_sources_record_per_item_with_revision(tmp_path):
    core, pid = two_session_world(tmp_path)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "reasoning",
         "value": "high"}])
    ticket = core.sessions.begin_turn("t1", session_id="A")
    sources = {(i["item_id"]): i for i in ticket["effective"]}
    assert sources["model"]["source"] == "session_only"
    assert sources["model"]["revision"] == 3
    assert sources["reasoning"]["source"] == "profile"
    assert sources["reasoning"]["revision"] == 3
    assert ticket["effective_digest"].startswith("sha256:")


def test_sc006_two_sessions_divergence_and_history_immutability(tmp_path):
    core, pid = two_session_world(tmp_path)
    first_a = core.sessions.begin_turn("t0a", session_id="A")
    first_b = core.sessions.begin_turn("t0b", session_id="B")
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    set_profile_values(core, pid, [
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning",
         "value": "high"},
    ])
    next_a = core.sessions.begin_turn("t1a", session_id="A")
    next_b = core.sessions.begin_turn("t1b", session_id="B")
    by_item = lambda t: {i["item_id"]: i["value"] for i in t["effective"]}
    assert by_item(next_a) == {"model": "m2", "reasoning": "high"}
    assert by_item(next_b) == {"model": "m3", "reasoning": "high"}
    # history of both sessions is never rewritten
    turns_a = {t["turn_id"]: t for t in core.sessions.turns("A")}
    turns_b = {t["turn_id"]: t for t in core.sessions.turns("B")}
    assert by_item(turns_a[first_a["turn_id"]]) == \
        by_item(first_a)
    assert by_item(turns_b[first_b["turn_id"]]) == {"model": "m1",
                                                    "reasoning": "low"}


def test_sc007_clearing_overlay_touches_only_that_session(tmp_path):
    core, pid = two_session_world(tmp_path)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    before_b = core.sessions.session_config("B")
    before_profile = core.profiles.facet_values(pid)
    before_turns = core.sessions.turns("A")
    core.sessions.clear_overlay(
        "ca", session_id="A", facet_id="model_selection", item_id="model")
    assert effective_model_and_reasoning(core, "A") == ("m1", "low")
    assert core.sessions.session_config("B") == before_b
    assert core.profiles.facet_values(pid) == before_profile
    assert core.sessions.turns("A") == before_turns


def test_fr016_overlay_write_never_leaks_to_profile_or_other_sessions(tmp_path):
    core, pid = two_session_world(tmp_path)
    profile_before = core.profiles.facet_values(pid)
    revisions_before = core.profiles.revisions(pid)
    core.sessions.set_overlay(
        "oa", session_id="A", facet_id="model_selection", item_id="model",
        value="m2")
    assert core.profiles.facet_values(pid) == profile_before
    assert core.profiles.revisions(pid) == revisions_before
    assert effective_model_and_reasoning(core, "B") == ("m1", "low")
