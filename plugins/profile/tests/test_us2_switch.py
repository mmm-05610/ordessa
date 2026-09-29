"""T12-T15 — US2 same-session Profile switching (G2).

FR-006 selection gates; FR-007 running turn untouched; FR-008 all-or-nothing;
FR-009 immutable per-turn facts; FR-010 absence/failure never "switched";
FR-013 honest backend state; FR-022 atomic overlay purge on success only.
US2.1-2.8; SC-002/SC-003/SC-008; edge cases 1-3.
"""
from __future__ import annotations

import inspect

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileError

MODEL = ScriptedProvider(
    "model_selection", ("model",), applies=frozenset({"pi"}),
    valid={"m1", "m2", "m3"},
)
STYLE = ScriptedProvider(
    "output_style", ("style",), applies=frozenset({"pi"}),
    valid={"terse", "verbose"},
)


def ab_world(tmp_path, *, config_port=None):
    core = make_core(tmp_path, providers=(MODEL, STYLE),
                     **({"config_port": config_port}
                        if config_port is not None else {}))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m2"},
            {"facet_id": "output_style", "item_id": "style", "value": "verbose"},
        ])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    return core, a, b


def snapshot(core):
    return {
        "profiles": [core.profiles.list(include_archived=True)],
        "sessions": core.sessions.session_config("S"),
    }


def test_us2_1_running_turn_keeps_a_pending_shown_separately(tmp_path):
    core, a, b = ab_world(tmp_path)
    running = core.sessions.begin_turn("t0", session_id="S")
    assert running["profile_id"] == a["profile_id"]
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["pending"]["profile_id"] == b["profile_id"]
    assert config["switch_state"] == "pending"
    # the in-flight turn record still says A
    turns = core.sessions.turns("S")
    assert [t["profile_id"] for t in turns] == [a["profile_id"]]


def test_us2_2_switch_applies_before_next_turn_session_history_intact(tmp_path):
    core, a, b = ab_world(tmp_path)
    first = core.sessions.begin_turn("t0", session_id="S")
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    second = core.sessions.begin_turn("t1", session_id="S")
    assert second["applied_switch"] is True
    assert second["profile_id"] == b["profile_id"]
    assert second["session_id"] == "S"  # same session, history not abandoned
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == b["profile_id"]
    assert config["pending"] is None
    assert config["switch_state"] == "settled"
    turns = core.sessions.turns("S")
    assert [t["profile_id"] for t in turns] == [
        a["profile_id"], b["profile_id"]]
    assert turns[0]["turn_id"] == first["turn_id"]
    assert turns[0]["effective"] == first["effective"]


def test_us2_3_blocked_difference_refuses_turn_names_items(tmp_path):
    blocked_style = ScriptedProvider(
        "output_style", ("style",), applies=frozenset({"pi"}),
        valid={"terse", "verbose"}, session_apply_verdict="blocked")
    core = make_core(tmp_path, providers=(MODEL, blocked_style))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m2"},
            {"facet_id": "output_style", "item_id": "style",
             "value": "verbose"},
        ])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "session_apply_blocked"} in exc.value.blockers
    # nothing was applied; never displayed as switched; no new turn
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["switch_state"] == "pending"
    assert core.sessions.turns("S") == []


def test_us2_4_unprovable_application_marks_needs_recovery(tmp_path):
    # v2 (specs/011-z1-profile): the proof comes from the application port.
    # A port answering "unknown" blocks sending and marks the session; the
    # DB alone can never upgrade the outcome (PV-04/PV-07).
    from conftest import ScriptedConfigPort
    core, a, b = ab_world(
        tmp_path, config_port=ScriptedConfigPort(apply_verdict="unknown"))
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SESSION_NEEDS_RECOVERY"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "needs_recovery"
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["evidence"]["journal"]["state"] == "unknown"
    # sending stays blocked; the backend never pretends a safe state
    with pytest.raises(ProfileError) as exc2:
        core.sessions.begin_turn("t2", session_id="S")
    assert exc2.value.code == "SESSION_NEEDS_RECOVERY"
    assert core.sessions.turns("S") == []
    # the previous configuration was never reported as replaced
    assert config["current"]["profile_id"] == a["profile_id"]


def test_us2_5_cross_harness_or_archived_refused_before_any_change(tmp_path):
    core, a, b = ab_world(tmp_path)
    other = core.profiles.create("kx", harness_id="codex", display_name="X")
    before = snapshot(core)
    with pytest.raises(ProfileError) as exc:
        core.sessions.select_profile(
            "selx", session_id="S", profile_id=other["profile_id"])
    assert exc.value.code == "SESSION_PROFILE_MISMATCH"
    assert snapshot(core) == before
    core.profiles.archive(
        "karch", profile_id=b["profile_id"],
        expected_version=core.profiles.get(b["profile_id"])["version"])
    before2 = snapshot(core)
    with pytest.raises(ProfileError) as exc2:
        core.sessions.select_profile(
            "sely", session_id="S", profile_id=b["profile_id"])
    assert exc2.value.code == "PROFILE_ARCHIVED"
    assert snapshot(core) == before2


def test_us2_6_every_turn_identifies_its_profile_revision_config(tmp_path):
    core, a, b = ab_world(tmp_path)
    first = core.sessions.begin_turn("t0", session_id="S")
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    second = core.sessions.begin_turn("t1", session_id="S")
    # mutate B afterwards: history must not change
    core.profiles.set_facet_values(
        "kb2", profile_id=b["profile_id"], expected_version=2,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m3"}])
    turns = core.sessions.turns("S")
    by_id = {t["turn_id"]: t for t in turns}
    assert by_id[first["turn_id"]]["profile_id"] == a["profile_id"]
    assert by_id[first["turn_id"]]["config_revision"] == 2
    assert {i["value"] for i in by_id[first["turn_id"]]["effective"]} == \
        {"m1", "terse"}
    assert by_id[second["turn_id"]]["profile_id"] == b["profile_id"]
    assert by_id[second["turn_id"]]["config_revision"] == 2
    assert by_id[second["turn_id"]]["effective"] == second["effective"]
    assert all(t["effective_digest"].startswith("sha256:")
               for t in turns)


def test_us2_7_successful_switch_atomically_clears_all_overlays(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m3")
    core.sessions.set_overlay(
        "o2", session_id="S", facet_id="output_style", item_id="style",
        value="verbose")
    assert core.sessions.session_config("S")["items"][0]["source"] == \
        "session_only"
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    items = {(i["facet_id"], i["item_id"]): i
             for i in ticket["effective"]}
    assert items[("model_selection", "model")]["source"] == "profile"
    assert items[("model_selection", "model")]["value"] == "m2"
    assert items[("output_style", "style")]["value"] == "verbose"
    assert core.sessions.session_config("S")["items"] == ticket["effective"]
    # no confirmation / extra prompt step exists in the switching API
    params = inspect.signature(core.sessions.select_profile).parameters
    assert "confirm" not in params and "prompt" not in params
    # A, B and history untouched by the purge
    assert {v["item_id"]: v["value"]
            for v in core.profiles.facet_values(a["profile_id"])} == \
        {"model": "m1", "style": "terse"}
    assert {v["item_id"]: v["value"]
            for v in core.profiles.facet_values(b["profile_id"])} == \
        {"model": "m2", "style": "verbose"}


def test_us2_8_refused_switch_keeps_overlays_and_honesty(tmp_path):
    blocked_style = ScriptedProvider(
        "output_style", ("style",), applies=frozenset({"pi"}),
        valid={"terse", "verbose"}, session_apply_verdict="blocked")
    core = make_core(tmp_path, providers=(MODEL, blocked_style))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m2"},
            {"facet_id": "output_style", "item_id": "style",
             "value": "verbose"},
        ])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m3")
    before_overlays = core.sessions.session_config("S")["items"]
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError):
        core.sessions.begin_turn("t1", session_id="S")
    assert core.sessions.session_config("S")["items"] == before_overlays
    assert core.sessions.turns("S") == []


def test_edge3_rapid_bc_selection_only_highest_seq_applies(tmp_path):
    core, a, b = ab_world(tmp_path)
    c = core.profiles.create("kc", harness_id="pi", display_name="C")
    core.profiles.set_facet_values(
        "kc1", profile_id=c["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m3"}])
    first = core.sessions.select_profile(
        "selB", session_id="S", profile_id=b["profile_id"])
    second = core.sessions.select_profile(
        "selC", session_id="S", profile_id=c["profile_id"])
    assert first["pending_seq"] == 1
    assert second["pending_profile_id"] == c["profile_id"]
    assert second["pending_seq"] == 2
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["profile_id"] == c["profile_id"]
    assert ticket["applied_switch"] is True


def test_sc002_switch_session_identity_and_revision_ledger(tmp_path):
    core, a, b = ab_world(tmp_path)
    first = core.sessions.begin_turn("t0", session_id="S")
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    second = core.sessions.begin_turn("t1", session_id="S")
    turns = core.sessions.turns("S")
    assert [t["session_id"] for t in turns] == ["S", "S"]
    assert turns[0]["profile_id"] == a["profile_id"] and \
        turns[0]["config_revision"] == 2
    assert turns[1]["profile_id"] == b["profile_id"] and \
        turns[1]["config_revision"] == 2
    assert turns[0]["turn_id"] == first["turn_id"]
    assert turns[0]["effective"] == first["effective"]  # current turn never rewritten


def test_sc003_zero_false_success_and_zero_partial_turns(tmp_path):
    # counterexample 1: blocked difference
    blocked_style = ScriptedProvider(
        "output_style", ("style",), applies=frozenset({"pi"}),
        valid={"terse", "verbose"}, session_apply_verdict="blocked")
    ce1 = tmp_path / "ce1"; ce1.mkdir()
    core1 = make_core(ce1, providers=(MODEL, blocked_style))
    a = core1.profiles.create("ka", harness_id="pi", display_name="A")
    b = core1.profiles.create("kb", harness_id="pi", display_name="B")
    core1.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core1.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m2"},
            {"facet_id": "output_style", "item_id": "style",
             "value": "verbose"},
        ])
    core1.sessions.open_session("ks", session_id="S", harness_id="pi",
                                profile_id=a["profile_id"])
    core1.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError):
        core1.sessions.begin_turn("t1", session_id="S")
    assert core1.sessions.turns("S") == []
    assert core1.sessions.session_config("S")["switch_state"] == "pending"

    # counterexample 2: absent provider for a required item
    from conftest import StaticHarnessCatalog
    catalog = StaticHarnessCatalog({"pi": frozenset({"output_style/style"})})
    ce2 = tmp_path / "ce2"; ce2.mkdir()
    core2 = make_core(ce2, harnesses=catalog,
                      providers=(MODEL,))  # style provider absent
    a2 = core2.profiles.create("ka", harness_id="pi", display_name="A")
    b2 = core2.profiles.create("kb", harness_id="pi", display_name="B")
    core2.profiles.set_facet_values(
        "ka1", profile_id=a2["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core2.profiles.set_facet_values(
        "kb1", profile_id=b2["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    core2.sessions.open_session("ks", session_id="S", harness_id="pi",
                                profile_id=a2["profile_id"])
    core2.sessions.select_profile(
        "sel1", session_id="S", profile_id=b2["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core2.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "FACET_PROVIDER_UNAVAILABLE"
    assert core2.sessions.turns("S") == []

    # counterexample 3: application cannot be proven (port answers unknown;
    # controlled fixture — the real Harness port is consumed via harness-api)
    from conftest import ScriptedConfigPort
    ce3 = tmp_path / "ce3"; ce3.mkdir()
    core3, a3, b3 = ab_world(
        ce3, config_port=ScriptedConfigPort(apply_verdict="unknown"))
    core3.sessions.select_profile(
        "sel1", session_id="S", profile_id=b3["profile_id"])
    with pytest.raises(ProfileError) as exc3:
        core3.sessions.begin_turn("t1", session_id="S")
    assert exc3.value.code == "SESSION_NEEDS_RECOVERY"
    assert core3.sessions.turns("S") == []
    assert core3.sessions.session_config("S")["switch_state"] == \
        "needs_recovery"


def test_sc008_overlay_fate_on_both_switch_paths_no_confirmation(tmp_path):
    # success path clears both overlays (see us2_7); here the refusal path
    core, a, b = ab_world(tmp_path)
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m3")
    core.sessions.set_overlay(
        "o2", session_id="S", facet_id="output_style", item_id="style",
        value="verbose")
    archived_snapshot = dict(b)
    core.profiles.archive(
        "karch", profile_id=b["profile_id"],
        expected_version=core.profiles.get(b["profile_id"])["version"])
    with pytest.raises(ProfileError):
        core.sessions.select_profile(
            "sel1", session_id="S", profile_id=b["profile_id"])
    items = {(i["facet_id"], i["item_id"]): i["value"]
             for i in core.sessions.session_config("S")["items"]}
    assert items == {("model_selection", "model"): "m3",
                     ("output_style", "style"): "verbose"}
    params = inspect.signature(core.sessions.select_profile).parameters
    assert "confirm" not in params


def test_edge1_restart_verifies_pending_honestly(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    restarted = make_core(tmp_path, providers=(MODEL, STYLE))
    report = restarted.sessions.verify_recovery("v1", session_id="S")
    assert report["verification"] == "pending_intact_not_applied"
    assert report["switch_state"] == "pending"
    assert report["pending_profile_id"] == b["profile_id"]
    # and the pending still applies on the next turn after the restart
    ticket = restarted.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    assert ticket["profile_id"] == b["profile_id"]


def test_edge5_recovery_path_never_claims_in_place_success(tmp_path):
    """A facet that cannot apply in-session must not be reported as switched
    just because a reload would eventually restore the session."""
    blocked_model = ScriptedProvider(
        "model_selection", ("model",), applies=frozenset({"pi"}),
        valid={"m1", "m2"}, session_apply_verdict="blocked")
    core = make_core(tmp_path, providers=(blocked_model,))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert core.sessions.session_config("S")["current"]["profile_id"] == \
        a["profile_id"]


def test_edge6_selection_never_edits_the_profile(tmp_path):
    core, a, b = ab_world(tmp_path)
    before_a = core.profiles.facet_values(a["profile_id"])
    before_b = core.profiles.facet_values(b["profile_id"])
    before_version_a = core.profiles.get(a["profile_id"])["version"]
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    core.sessions.begin_turn("t1", session_id="S")
    assert core.profiles.facet_values(a["profile_id"]) == before_a
    assert core.profiles.facet_values(b["profile_id"]) == before_b
    assert core.profiles.get(a["profile_id"])["version"] == before_version_a
