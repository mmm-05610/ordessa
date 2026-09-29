"""T06-T08 — US4 facet provider contract (G4).

FR-004 facet identity/ownership/version/validation.
FR-005 absent provider: hidden, retained, never applied.
FR-014 / SC-005 new facet with zero core changes.
US4.1-4.6 acceptance scenarios; SC-004.
"""
from __future__ import annotations

import pathlib

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileError

MODEL = ScriptedProvider(
    "model_selection", ("model",), title="Model",
    applies=frozenset({"pi", "codex"}), valid={"m1", "m2", "m3"},
)
STYLE = ScriptedProvider(
    "output_style", ("style",), title="Output style",
    applies=frozenset({"pi"}), valid={"terse", "verbose"},
)


def provisioned_core(tmp_path):
    return make_core(tmp_path, providers=(MODEL, STYLE))


def test_us4_1_applicable_facet_shows_and_provider_validates(tmp_path):
    core = provisioned_core(tmp_path)
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "k2", profile_id=profile["profile_id"], expected_version=1,
            values=[{"facet_id": "model_selection", "item_id": "model",
                     "value": "bogus"}])
    assert exc.value.code == "FACET_VALUE_INVALID" and exc.value.status == 422
    updated = core.profiles.set_facet_values(
        "k3", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    assert updated["current_revision"] == 2
    projection = core.profiles.settings_projection(profile["profile_id"])
    facet = next(f for f in projection["facets"]
                 if f["facet_id"] == "model_selection")
    assert facet["title"] == "Model"
    assert facet["items"][0]["value"] == "m1"


def test_us4_2_non_applicable_facet_hidden_and_unwritable(tmp_path):
    core = provisioned_core(tmp_path)
    codex_profile = core.profiles.create(
        "k1", harness_id="codex", display_name="C")
    projection = core.profiles.settings_projection(codex_profile["profile_id"])
    assert [f["facet_id"] for f in projection["facets"]] == ["model_selection"]
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "k2", profile_id=codex_profile["profile_id"], expected_version=1,
            values=[{"facet_id": "output_style", "item_id": "style",
                     "value": "terse"}])
    assert exc.value.code == "FACET_NOT_APPLICABLE"


def test_us4_3_duplicate_facet_declaration_rejected_not_last_wins(tmp_path):
    core = make_core(tmp_path, providers=(MODEL,))
    impostor = ScriptedProvider(
        "model_selection", ("model",), owner="other-owner", version="9.9.9")
    with pytest.raises(ProfileError) as exc:
        core.register_provider(impostor)
    assert exc.value.code == "FACET_ID_CONFLICT"
    # the first legitimate registration is untouched
    assert core.provider_lookup("model_selection").facet_version == "1.0.0"


def test_us4_4_unload_hides_items_keeps_data_others_unaffected(tmp_path):
    core = provisioned_core(tmp_path)
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    core.unregister_provider(STYLE)
    projection = core.profiles.settings_projection(profile["profile_id"])
    assert [f["facet_id"] for f in projection["facets"]] == ["model_selection"]
    stored = core.profiles.facet_values(profile["profile_id"])
    by_facet = {v["facet_id"]: v for v in stored}
    assert by_facet["output_style"]["value"] == "terse"  # retained
    # base management still works; other facet still writable
    assert core.profiles.rename(
        "k3", profile_id=profile["profile_id"],
        expected_version=2, display_name="P2")["version"] == 3
    core.profiles.set_facet_values(
        "k4", profile_id=profile["profile_id"], expected_version=3,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m2"}])
    # the retained value is not silently applied anywhere
    preview = core.profiles.resolution_preview(profile["profile_id"])
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "provider_absent"} in preview["unavailable"]
    assert all(i["facet_id"] != "output_style" for i in preview["items"])


def test_us4_5_reload_compatible_restores_incompatible_quarantines(tmp_path):
    core = provisioned_core(tmp_path)
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    current = STYLE
    core.unregister_provider(current)

    reloaded = ScriptedProvider(
        "output_style", ("style",), title="Output style",
        applies=frozenset({"pi"}), valid={"terse", "verbose"},
        stored_ruling="accepted", version="1.1.0")
    report = core.register_provider(reloaded)
    assert report.accepted == 1 and report.quarantined == 0
    assert core.profiles.facet_values(
        profile["profile_id"])[1]["value"] == "terse"

    core.unregister_provider(reloaded)
    breaker = ScriptedProvider(
        "output_style", ("style",), title="Output style",
        applies=frozenset({"pi"}), stored_ruling="incompatible",
        version="2.0.0")
    report = core.register_provider(breaker)
    assert report.quarantined == 1
    stored = {v["facet_id"]: v for v in
              core.profiles.facet_values(profile["profile_id"])}
    assert stored["output_style"]["quarantined"] is True  # retained, flagged
    projection = core.profiles.settings_projection(profile["profile_id"])
    style = next(f for f in projection["facets"]
                 if f["facet_id"] == "output_style")
    assert style["items"][0]["needs_migration"] is True
    preview = core.profiles.resolution_preview(profile["profile_id"])
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "value_quarantined"} in preview["unavailable"]

    core.unregister_provider(breaker)
    migration = ScriptedProvider(
        "output_style", ("style",), title="Output style",
        applies=frozenset({"pi"}), stored_ruling="migrated",
        migrated_value="verbose", version="3.0.0")
    report = core.register_provider(migration)
    assert report.migrated == 1
    stored = {v["facet_id"]: v for v in
              core.profiles.facet_values(profile["profile_id"])}
    assert stored["output_style"]["value"] == "verbose"
    assert stored["output_style"]["quarantined"] is False


def test_us4_6_required_item_with_absent_provider_refuses_turn(tmp_path):
    from conftest import StaticHarnessCatalog
    catalog = StaticHarnessCatalog({
        "pi": frozenset({"model_selection/model"}),
        "codex": frozenset(),
    })
    core = make_core(tmp_path, harnesses=catalog, providers=(MODEL,))
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": "model_selection", "item_id": "model",
                 "value": "m1"}])
    session = core.sessions.open_session(
        "ks", session_id="s1", harness_id="pi",
        profile_id=profile["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="s1")
    assert ticket["effective"][0]["value"] == "m1"
    core.unregister_provider(MODEL)
    with pytest.raises(ProfileError) as exc:
        core.sessions.begin_turn("t2", session_id="s1")
    assert exc.value.code == "FACET_PROVIDER_UNAVAILABLE"
    assert exc.value.item == "model_selection/model"
    # profiles/harnesses that do not require the value are unaffected
    other = core.profiles.create("k3", harness_id="codex", display_name="O")
    assert other["profile_id"]
    session2 = core.sessions.open_session(
        "ks2", session_id="s2", harness_id="codex",
        profile_id=other["profile_id"])
    assert core.sessions.begin_turn("t3", session_id="s2")["applied_switch"] \
        is False


def test_sc004_unload_reload_preserves_every_value(tmp_path):
    core = provisioned_core(tmp_path)
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    before = core.profiles.facet_values(profile["profile_id"])
    core.unregister_provider(MODEL)
    core.unregister_provider(STYLE)
    during = core.profiles.facet_values(profile["profile_id"])
    assert during == before  # absent providers never mutate stored data
    core.register_provider(MODEL)
    core.register_provider(STYLE)
    after = core.profiles.facet_values(profile["profile_id"])
    assert [(v["facet_id"], v["item_id"], v["value"]) for v in after] == \
        [(v["facet_id"], v["item_id"], v["value"]) for v in before]


def test_sc005_brand_new_facet_needs_no_core_change(tmp_path):
    """A facet unknown to the core at authoring time joins the full flow."""
    brand_new = ScriptedProvider("echo_volume", ("volume",), valid={"low"})
    core = make_core(tmp_path, providers=(brand_new,))
    profile = core.profiles.create("k1", harness_id="pi", display_name="P")
    core.profiles.set_facet_values(
        "k2", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": "echo_volume", "item_id": "volume",
                 "value": "low"}])
    session = core.sessions.open_session(
        "ks", session_id="s1", harness_id="pi",
        profile_id=profile["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="s1")
    assert ticket["effective"][0] == {
        "facet_id": "echo_volume", "item_id": "volume", "value": "low",
        "source": "profile", "revision": 2,
    }
    assert core.sessions.session_config("s1")["items"][0]["value"] == "low"

    # structural proof: no ordessa_profile source file mentions any facet id
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_profile"
    facet_ids = ("model_selection", "output_style", "echo_volume")
    for path in src.glob("*.py"):
        text = path.read_text()
        for facet_id in facet_ids:
            assert facet_id not in text, f"{path.name} hardcodes {facet_id}"
