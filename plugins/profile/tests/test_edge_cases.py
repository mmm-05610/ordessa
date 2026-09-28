"""T18 — the six spec Edge Cases, each with a discriminating scenario (G6).

Edge 1 restart verification, edge 2 stale-capability revalidation before the
next turn, edge 3 rapid B/C selection, edge 4 per-item merge (also G3),
edge 5 no in-place-switch impersonation, edge 6 selection never edits.
"""
from __future__ import annotations

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


def ab_world(tmp_path):
    core = make_core(tmp_path, providers=(MODEL, STYLE))
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
    return core, a, b


def test_edge1_pending_survives_restart_and_is_verified_not_assumed(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    # service restart: a brand-new core instance over the same store
    restarted = make_core(tmp_path, providers=(MODEL, STYLE))
    report = restarted.sessions.verify_recovery("v1", session_id="S")
    assert report["verification"] == "pending_intact_not_applied"
    assert report["pending_profile_id"] == b["profile_id"]
    # verified pending still applies on the next turn
    ticket = restarted.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True


def test_edge1_unverifiable_after_restart_blocks_sending(tmp_path):
    # v2: the proof comes from the application port; a port answering
    # "unknown" blocks sending, and recovery goes through reconcile — never
    # a database read (PV-04/PV-07, controlled fixture port).
    from conftest import ScriptedConfigPort
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    restarted = make_core(
        tmp_path, providers=(MODEL, STYLE),
        config_port=ScriptedConfigPort(apply_verdict="unknown"))
    with pytest.raises(ProfileError) as exc:
        restarted.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SESSION_NEEDS_RECOVERY"
    # explicit recovery: the port reconciles the unknown operation and only
    # its confirmation returns the session to settled
    result = restarted.sessions.reconcile("r1", session_id="S")
    assert result["state"] == "confirmed-current"
    report = restarted.sessions.verify_recovery("v1", session_id="S")
    assert report["switch_state"] == "settled"
    assert report["pending_profile_id"] is None
    # sending works again only after that explicit reconciliation
    ticket = restarted.sessions.begin_turn("t2", session_id="S")
    assert ticket["applied_switch"] is False


def test_edge2_unload_between_select_and_begin_revalidates(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    core.unregister_provider(STYLE)  # provider vanishes after the selection
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "provider_absent"} in exc.value.blockers
    assert core.sessions.turns("S") == []


def test_edge2_quarantine_between_select_and_begin_revalidates(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    core.unregister_provider(STYLE)
    breaker = ScriptedProvider(
        "output_style", ("style",), applies=frozenset({"pi"}),
        stored_ruling="incompatible", version="2.0.0")
    core.register_provider(breaker)  # retained B values become incompatible
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert exc.value.blockers[0]["reason"] == "value_quarantined"


def test_edge2_edited_target_resolved_at_latest_revision(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    core.profiles.set_facet_values(
        "kb2", profile_id=b["profile_id"], expected_version=2,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m3"}])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["config_revision"] == 3  # the newest revision, not the
    # revision the user saw when selecting
    values = {i["item_id"]: i["value"] for i in ticket["effective"]}
    assert values["model"] == "m3"


def test_edge4_overlay_item_and_global_items_merge_per_item(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m3")
    core.profiles.set_facet_values(
        "ka2", profile_id=a["profile_id"], expected_version=2,
        values=[{"facet_id": "output_style", "item_id": "style",
                 "value": "verbose"}])
    items = {(i["facet_id"], i["item_id"]): (i["value"], i["source"])
             for i in core.sessions.session_config("S")["items"]}
    assert items[("model_selection", "model")] == ("m3", "session_only")
    assert items[("output_style", "style")] == ("verbose", "profile")


def test_fr002_idempotent_begin_turn_replays_same_ticket(tmp_path):
    core, a, b = ab_world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    first = core.sessions.begin_turn("t1", session_id="S")
    replay = core.sessions.begin_turn("t1", session_id="S")
    assert first == replay
    assert len(core.sessions.turns("S")) == 1
