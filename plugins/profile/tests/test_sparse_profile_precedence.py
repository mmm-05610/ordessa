"""User-ruling counterexamples: Profile patches only its explicit item mask.

Controlled port evidence only; these tests intentionally expose the previous
replace/reset semantics until the separately approved implementation lands.
"""
import pytest

from ordessa_profile.errors import ProfileError
from profile_harness_doubles import ScriptedConfigPort, ScriptedProvider, make_core


def world(tmp_path):
    port = ScriptedConfigPort()
    port.native_turn_application = True
    core = make_core(tmp_path, config_port=port, providers=(
        ScriptedProvider("model", ("choice",), valid={"a", "b", "override"}),
        ScriptedProvider("style", ("choice", "detail"), valid={"terse", "verbose"}),
    ))
    profiles = {}
    for name, values in (
        ("base", [("model", "choice", "a"), ("style", "choice", "terse"), ("style", "detail", "terse")]),
        ("model-only", [("model", "choice", "b")]),
        ("style-only", [("style", "choice", "verbose")]),
    ):
        created = core.profiles.create(f"create:{name}", harness_id="pi", display_name=name)
        profiles[name] = core.profiles.set_facet_values(f"values:{name}", profile_id=created["profile_id"],
            expected_version=1, values=[{"facet_id": f, "item_id": i, "value": v} for f, i, v in values])
    core.sessions.open_session("open", session_id="s", harness_id="pi", profile_id=profiles["base"]["profile_id"])
    core.sessions.begin_turn("first", session_id="s")
    return core, profiles, port


def values(core):
    return {(i["facet_id"], i["item_id"]): i["value"] for i in core.sessions.session_config("s")["items"]}


def pick(core, profiles, name, key="pick"):
    core.sessions.select_profile(key, session_id="s", profile_id=profiles[name]["profile_id"])


@pytest.mark.parametrize("target,untouched", [("style-only", ("model", "choice")), ("model-only", ("style", "choice"))])
def test_omitted_item_never_compiles_to_reset_and_stays_effective_next_turn(tmp_path, target, untouched):
    core, profiles, port = world(tmp_path)
    try:
        before = values(core)[untouched]
        pick(core, profiles, target)
        core.sessions.begin_turn("switch", session_id="s")
        assert all(i.op != "reset" for i in port.applied[-1])
        assert values(core)[untouched] == before
        core.sessions.begin_turn("ordinary", session_id="s")
        assert values(core)[untouched] == before
        assert all(i.op != "reset" for i in port.applied[-1])
    finally:
        core.db.close()


def test_profile_overwrites_only_matching_overlay_item_not_facet_sibling(tmp_path):
    core, profiles, _ = world(tmp_path)
    try:
        for facet, item, value in [("model", "choice", "override"), ("style", "choice", "terse"), ("style", "detail", "verbose")]:
            core.sessions.set_overlay(f"overlay:{facet}:{item}", session_id="s", facet_id=facet, item_id=item, value=value)
        pick(core, profiles, "style-only")
        core.sessions.begin_turn("switch", session_id="s")
        assert values(core) == {("model", "choice"): "override", ("style", "choice"): "verbose", ("style", "detail"): "verbose"}
    finally:
        core.db.close()


@pytest.mark.parametrize("verdict", ["rejected", "unknown", "commit-failed"])
def test_unconfirmed_patch_retains_all_effective_values_and_pending_choice(tmp_path, verdict):
    core, profiles, port = world(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model", item_id="choice", value="override")
        before = values(core)
        pick(core, profiles, "style-only")
        if verdict == "commit-failed":
            def fail_commit(_operation):
                raise RuntimeError("controlled-commit-failure")
            core.commit_injection = fail_commit
        else:
            port.apply_verdict = verdict
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("failed", session_id="s")
        config = core.sessions.session_config("s")
        assert values(core) == before
        assert config["pending"]["profile_id"] == profiles["style-only"]["profile_id"]
        assert len(core.sessions.turns("s")) == 1
    finally:
        core.db.close()


def test_confirmed_reconciliation_preserves_omitted_overlay_and_uses_admitted_item_mask(tmp_path):
    core, profiles, port = world(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="style", item_id="detail", value="verbose")
        pick(core, profiles, "model-only")
        port.apply_verdict = "unknown"
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("unknown", session_id="s")
        target = profiles["model-only"]
        # This later global edit was not part of the unknown native operation.
        core.profiles.set_facet_values("late-global", profile_id=target["profile_id"], expected_version=target["version"],
            values=[{"facet_id": "style", "item_id": "detail", "value": "terse"}])
        core.sessions.reconcile("reconcile", session_id="s")
        assert values(core)[("style", "detail")] == "verbose"
        assert len(core.sessions.turns("s")) == 1
    finally:
        core.db.close()


@pytest.mark.parametrize("verdict", ["confirmed", "rejected", "unknown", "commit-failed"])
def test_new_pick_during_apply_remains_pending_for_next_turn(tmp_path, verdict):
    core, profiles, port = world(tmp_path)
    original = port.apply
    def apply_then_pick(plan, desired):
        result = original(plan, desired)
        pick(core, profiles, "style-only", "late-pick")
        return result
    try:
        pick(core, profiles, "model-only")
        if verdict == "commit-failed":
            def fail_commit(_operation):
                raise RuntimeError("controlled-commit-failure")
            core.commit_injection = fail_commit
        else:
            port.apply_verdict = verdict
        port.apply = apply_then_pick
        if verdict == "confirmed":
            core.sessions.begin_turn("apply", session_id="s")
        else:
            with pytest.raises(ProfileError):
                core.sessions.begin_turn("apply", session_id="s")
        config = core.sessions.session_config("s")
        assert config["current"]["profile_id"] == profiles["model-only" if verdict == "confirmed" else "base"]["profile_id"]
        assert config["pending"]["profile_id"] == profiles["style-only"]["profile_id"]
    finally:
        core.db.close()


def test_later_model_override_during_apply_is_not_consumed_by_earlier_profile_patch(tmp_path):
    core, profiles, port = world(tmp_path)
    original = port.apply
    def apply_then_override(plan, desired):
        result = original(plan, desired)
        core.sessions.set_overlay("late-overlay", session_id="s", facet_id="model", item_id="choice", value="override")
        return result
    try:
        pick(core, profiles, "model-only")
        port.apply = apply_then_override
        core.sessions.begin_turn("apply", session_id="s")
        assert values(core)[("model", "choice")] == "override"
    finally:
        core.db.close()


def test_ordinary_submit_and_global_profile_edits_still_respect_session_override(tmp_path):
    core, profiles, port = world(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model", item_id="choice", value="override")
        profile = profiles["base"]
        core.profiles.set_facet_values("global-edit", profile_id=profile["profile_id"], expected_version=profile["version"],
            values=[{"facet_id": "model", "item_id": "choice", "value": "b"}, {"facet_id": "style", "item_id": "choice", "value": "verbose"}])
        core.sessions.begin_turn("ordinary", session_id="s")
        assert values(core)[("model", "choice")] == "override"
        assert {i.value for i in port.applied[-1]} == {"override", "verbose", "terse"}
    finally:
        core.db.close()
