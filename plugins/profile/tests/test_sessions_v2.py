"""Sessions v2: the application seam, journal and canonical identity.

Controlled-fixture port evidence proves Profile's journal/fence/unknown
logic; the real Harness port is a harness-api consumption (api-requests.md).
Covers G02/G08/G09(profile side)/G10/G11/G13/G16 and the test-scenarios rows
"应用拒绝 / 外部成功本地失败 / 会话身份重名 / 缺提供者".
"""
from __future__ import annotations

import pytest

from conftest import ScriptedConfigPort, ScriptedProvider, ScriptedV2Provider, make_core
from ordessa_profile import ProfileError, UNSET

MODEL = ScriptedProvider(
    "model_selection", ("model",), applies=frozenset({"pi"}),
    valid={"m1", "m2", "m3"},
)
STYLE = ScriptedProvider(
    "output_style", ("style",), applies=frozenset({"pi"}),
    valid={"terse", "verbose"},
)

V2_ITEMS = (("model", {"type": "string", "enum": ["m1", "m2"]}),)


def ab_world(tmp_path, *, config_port="default", v2_providers=()):
    kwargs = {} if config_port == "default" else {"config_port": config_port}
    core = make_core(tmp_path, providers=(MODEL, STYLE),
                     v2_providers=v2_providers, **kwargs)
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
        ])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    return core, a, b


def test_port_absent_blocks_switch_and_keeps_selection(tmp_path):
    core, a, b = ab_world(tmp_path, config_port=None)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "APPLICATION_PORT_ABSENT"
    config = core.sessions.session_config("S")
    # nothing applied, nothing cleared, selection intact (honest absence)
    assert config["switch_state"] == "pending"
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["evidence"]["journal"]["state"] == "planned"
    assert core.sessions.turns("S") == []


def test_selection_never_touches_the_port_g20(tmp_path):
    port = ScriptedConfigPort()
    core, a, b = ab_world(tmp_path, config_port=port)
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    core.sessions.select_profile("s2", session_id="S",
                                 profile_id=a["profile_id"])
    for counter in ("plan", "apply", "inspect", "abort", "restart"):
        assert port.counters[counter] == 0


def test_confirmed_switch_records_receipt_and_clears_overlays(tmp_path):
    port = ScriptedConfigPort()
    core, a, b = ab_world(tmp_path, config_port=port)
    core.sessions.set_overlay("o1", session_id="S",
                              facet_id="model_selection", item_id="model",
                              value="m3")
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    assert ticket["applied_switch"] is True
    assert ticket["receipt"]["evidence_kind"] == "controlled-fixture"
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == b["profile_id"]
    assert config["switch_state"] == "settled"
    assert config["evidence"]["receipt"] is not None
    assert config["evidence"]["journal"]["state"] == "confirmed"
    # successful switch cleared the overlay (G07)
    values = {i["item_id"]: i["value"] for i in config["items"]}
    assert values["model"] == "m2"
    assert port.counters["plan"] == 1 and port.counters["apply"] == 1


def test_commit_failure_after_external_success_is_unknown_g10_g11(tmp_path):
    def explode(operation_id):
        raise RuntimeError("db-gone")
    port = ScriptedConfigPort()
    core = make_core(tmp_path, providers=(MODEL, STYLE), config_port=port,
                     commit_injection=explode)
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
    core.sessions.set_overlay("o1", session_id="S",
                              facet_id="model_selection", item_id="model",
                              value="m3")
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SESSION_NEEDS_RECOVERY"
    config = core.sessions.session_config("S")
    # the port applied externally, but nothing is reported switched (G10)
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["switch_state"] == "needs_recovery"
    assert config["evidence"]["journal"]["state"] == "unknown"
    assert config["evidence"]["receipt"] is None
    # overlays survived (clear happens inside the failed commit)
    values = {i["item_id"]: i["value"] for i in config["items"]}
    assert values["model"] == "m3"
    # reconcile with a healthy port confirms and settles (G11)
    port_ok = ScriptedConfigPort()
    core.config_port = port_ok
    result = core.sessions.reconcile("r1", session_id="S")
    assert result["state"] == "confirmed-current"
    assert port_ok.counters["reconcile"] == 1
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "settled"
    assert config["current"]["profile_id"] == b["profile_id"]
    assert config["evidence"]["receipt"]["evidence_kind"] == \
        "controlled-fixture"
    # no user message was replayed: reconcile itself records no turn
    assert core.sessions.turns("S") == []


def test_reconcile_rejected_restores_previous_binding(tmp_path):
    port = ScriptedConfigPort(apply_verdict="unknown",
                              reconcile_verdict="rejected-unchanged")
    core, a, b = ab_world(tmp_path, config_port=port)
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    with pytest.raises(ProfileError):
        core.sessions.begin_turn("t1", session_id="S")
    result = core.sessions.reconcile("r1", session_id="S")
    assert result["state"] == "rejected-unchanged"
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "settled"
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["blockers"] == [{"reason": "switch_rejected_after_unknown"}]


def test_apply_rejection_reports_and_keeps_everything_g07_g08(tmp_path):
    port = ScriptedConfigPort(apply_verdict="rejected")
    core, a, b = ab_world(tmp_path, config_port=port)
    core.sessions.set_overlay("o1", session_id="S",
                              facet_id="output_style", item_id="style",
                              value="verbose")
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["switch_state"] == "pending"
    values = {i["item_id"]: i["value"] for i in config["items"]}
    assert values["style"] == "verbose"  # overlay untouched
    assert port.counters["apply"] == 1


def test_v2_reset_difference_reaches_the_port_g08(tmp_path):
    v2 = ScriptedV2Provider(
        "v2_model", V2_ITEMS, capability_rule="yes")
    core = make_core(tmp_path, providers=(MODEL,),
                     v2_providers=((v2, "test-domain"),))
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"},
                {"facet_id": "v2_model", "item_id": "model", "value": "m1"}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    port = ScriptedConfigPort()
    core.config_port = port
    core.sessions.begin_turn("t1", session_id="S")
    applied = port.applied[0]
    ops = {(i.facet_id, i.item_id): i.op for i in applied}
    # A→B removal of the v2 item must appear as an explicit reset (G08)
    assert ops[("v2_model", "model")] == "reset"
    assert ops[("model_selection", "model")] == "set"


def test_missing_provider_on_either_side_blocks_never_filters_g08_g13(tmp_path):
    core, a, b = ab_world(tmp_path, config_port=ScriptedConfigPort())
    core.profiles.set_facet_values(
        "ka2", profile_id=a["profile_id"],
        expected_version=core.profiles.get(a["profile_id"])["version"],
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    # style provider vanishes after A stored a style value and B didn't
    core.unregister_provider(STYLE)
    core.profiles.archive(
        "karch", profile_id=b["profile_id"],
        expected_version=core.profiles.get(b["profile_id"])["version"])
    b2 = core.profiles.create("kb2", harness_id="pi", display_name="B2")
    core.profiles.set_facet_values(
        "kb2v", profile_id=b2["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b2["profile_id"])
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "provider_absent"} in exc.value.blockers


def test_dual_realm_same_native_key_never_collide_g02(tmp_path):
    port = ScriptedConfigPort()
    core, a, b = ab_world(tmp_path, config_port=port)
    core.sessions.open_session(
        "ks2", session_id="S-mirror", harness_id="pi",
        profile_id=a["profile_id"], realm="beta", session_uid="beta/S")
    s_alpha = core.sessions.session_config("S")
    s_beta = core.sessions.session_config("S-mirror")
    assert s_alpha["session_uid"] != s_beta["session_uid"]
    assert s_alpha["realm"] == "local" and s_beta["realm"] == "beta"
    # switching one realm's session leaves the other untouched
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    core.sessions.begin_turn("t1", session_id="S")
    beta = core.sessions.session_config("S-mirror")
    assert beta["current"]["profile_id"] == a["profile_id"]
    assert beta["switch_state"] == "settled"
    assert beta["evidence"]["journal"] is None


def test_native_key_conflict_refuses_before_plan_g16(tmp_path):
    v2 = ScriptedV2Provider(
        "clashing", V2_ITEMS, native_prefix="model_selection",
        capability_rule="yes")
    core = make_core(tmp_path, providers=(MODEL,),
                     v2_providers=((v2, "clash-domain"),),
                     config_port=ScriptedConfigPort())
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": "clashing", "item_id": "model",
                 "value": "m2"}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    port = core.config_port
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "NATIVE_KEY_CONFLICT"
    named = {(b_["facet_id"], b_["item_id"])
             for b_ in exc.value.blockers}
    assert named == {("model_selection", "model"), ("clashing", "model")}
    assert port.counters["plan"] == 0  # refused before any native plan


def test_generation_staleness_blocks_late_flow_g13(tmp_path):
    core, a, b = ab_world(tmp_path, config_port=ScriptedConfigPort())
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=b["profile_id"])
    core.registry.unregister(MODEL)
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t1", session_id="S")
    assert exc.value.code == "SWITCH_BLOCKED"
    assert {"facet_id": "model_selection", "item_id": "model",
            "reason": "provider_absent"} in exc.value.blockers


def test_same_profile_reselect_never_clears_overlays_g07(tmp_path):
    core, a, b = ab_world(tmp_path, config_port=ScriptedConfigPort())
    core.sessions.set_overlay("o1", session_id="S",
                              facet_id="model_selection", item_id="model",
                              value="m3")
    core.sessions.select_profile("s1", session_id="S",
                                 profile_id=a["profile_id"])
    config = core.sessions.session_config("S")
    values = {i["item_id"]: i["value"] for i in config["items"]}
    assert values["model"] == "m3"
    assert config["pending"] is None or \
        config["pending"]["profile_id"] == a["profile_id"]
