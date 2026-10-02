"""Opt-in native port applies effective configuration at every submit boundary."""
from profile_harness_doubles import ScriptedConfigPort, ScriptedProvider, make_core
import pytest
from ordessa_profile.errors import ProfileError


def world(tmp_path):
    port = ScriptedConfigPort()
    port.native_turn_application = True
    core = make_core(tmp_path, config_port=port, providers=(ScriptedProvider(
        "model", ("choice",), valid={"a", "b", "override"}), ScriptedProvider(
        "style", ("choice",), valid={"terse", "verbose"})))
    profile = core.profiles.create("create", harness_id="pi", display_name="A")
    profile = core.profiles.set_facet_values("values", profile_id=profile["profile_id"], expected_version=1,
        values=[{"facet_id": "model", "item_id": "choice", "value": "a"},
                {"facet_id": "style", "item_id": "choice", "value": "terse"}])
    core.sessions.open_session("open", session_id="s", harness_id="pi", profile_id=profile["profile_id"])
    return core, profile, port


def test_first_submit_requires_application_not_just_configuration_resolution(tmp_path):
    core, _, port = world(tmp_path)
    try:
        result = core.sessions.begin_turn("first", session_id="s")
        assert result["applied"] is True
        assert {i.value for i in port.applied[-1]} == {"a", "terse"}
        assert core.sessions.begin_turn("first", session_id="s") == result
        assert len(port.applied) == 1
    finally:
        core.db.close()


def test_next_submit_preserves_override_while_other_global_changes_apply(tmp_path):
    core, profile, port = world(tmp_path)
    try:
        core.sessions.begin_turn("first", session_id="s")
        core.sessions.set_overlay("override", session_id="s", facet_id="model", item_id="choice", value="override")
        core.profiles.set_facet_values("globals", profile_id=profile["profile_id"], expected_version=profile["version"],
            values=[{"facet_id": "model", "item_id": "choice", "value": "b"},
                    {"facet_id": "style", "item_id": "choice", "value": "verbose"}])
        core.sessions.begin_turn("next", session_id="s")
        assert {i.value for i in port.applied[-1]} == {"override", "verbose"}
        core.sessions.begin_turn("third", session_id="s")
        assert {i.value for i in port.applied[-1]} == {"override", "verbose"}
        assert core.profiles.get(profile["profile_id"])["version"] == profile["version"] + 1
    finally:
        core.db.close()


def test_confirmed_reconciliation_of_same_profile_preserves_session_override(tmp_path):
    core, _, port = world(tmp_path)
    try:
        core.sessions.set_overlay("override", session_id="s", facet_id="model", item_id="choice", value="override")
        port.apply_verdict = "unknown"
        with pytest.raises(ProfileError): core.sessions.begin_turn("unknown", session_id="s")
        assert core.sessions.reconcile("recover", session_id="s")["state"] == "confirmed-current"
        port.apply_verdict = "confirmed"
        core.sessions.begin_turn("next", session_id="s")
        assert {i.value for i in port.applied[-1]} == {"override", "terse"}
    finally:
        core.db.close()


def test_global_edit_during_native_apply_is_not_stamped_as_already_applied(tmp_path):
    core, profile, port = world(tmp_path)
    original = port.apply
    def apply_then_edit(plan, desired):
        result = original(plan, desired)
        core.profiles.set_facet_values("during-apply", profile_id=profile["profile_id"],
            expected_version=profile["version"],
            values=[{"facet_id": "model", "item_id": "choice", "value": "b"}])
        return result
    port.apply = apply_then_edit
    try:
        result = core.sessions.begin_turn("first", session_id="s")
        assert result["receipt"]["profile_revision"] == profile["current_revision"]
        assert {i.value for i in port.applied[-1]} == {"a", "terse"}
        port.apply = original
        core.sessions.begin_turn("next", session_id="s")
        assert {i.value for i in port.applied[-1]} == {"b", "terse"}
    finally:
        core.db.close()


def test_global_edit_during_planning_refuses_before_native_effect(tmp_path):
    core, profile, port = world(tmp_path)
    original = port.plan
    def plan_then_edit(target, desired, operation_key):
        result = original(target, desired, operation_key)
        core.profiles.set_facet_values("during-plan", profile_id=profile["profile_id"],
            expected_version=profile["version"],
            values=[{"facet_id": "model", "item_id": "choice", "value": "b"}])
        return result
    port.plan = plan_then_edit
    try:
        with pytest.raises(ProfileError, match="changed during preparation"):
            core.sessions.begin_turn("first", session_id="s")
        assert port.applied == []
        port.plan = original
        core.sessions.begin_turn("retry", session_id="s")
        assert {i.value for i in port.applied[-1]} == {"b", "terse"}
    finally:
        core.db.close()


def test_native_full_target_keeps_omitted_items_as_retained_base(tmp_path):
    """FR-02/FR-03: the target Profile's item mask decides the plan.  An
    item the target omits produces **no** intent at all — the retained
    effective native base keeps it — while an explicitly declared removal
    of the same item still compiles a reset (G08)."""
    core, _, port = world(tmp_path)
    try:
        target = core.profiles.create('target', harness_id='pi', display_name='Target')
        core.profiles.set_facet_values('target-values', profile_id=target['profile_id'], expected_version=1,
            values=[{'facet_id': 'model', 'item_id': 'choice', 'value': 'a'}])
        core.sessions.select_profile('select-target', session_id='s', profile_id=target['profile_id'])
        core.sessions.begin_turn('switch', session_id='s')
        intents = {(i.facet_id, i.item_id): i for i in port.applied[-1]}
        assert intents[('model', 'choice')].op == 'set'
        assert intents[('model', 'choice')].value == 'a'
        # Omission is not a removal.  This port re-applies the *whole*
        # chosen target (P11), so the omitted item travels with its
        # retained effective value — never as a reset.
        assert intents[('style', 'choice')].op == 'set'
        assert intents[('style', 'choice')].value == 'terse'
        # and the omitted item keeps its confirmed effective value
        config = core.sessions.session_config('s')
        items = {(i['facet_id'], i['item_id']): i for i in config['items']}
        assert items[('style', 'choice')]['value'] == 'terse'
        assert items[('style', 'choice')]['source'] == 'retained_base'

        # the same item, removed on purpose: a real reset reaches the port
        core.sessions.begin_turn('declared', session_id='s',
                                 declared_removals=frozenset({('style', 'choice')}))
        intents = {(i.facet_id, i.item_id): i for i in port.applied[-1]}
        assert intents[('style', 'choice')].op == 'reset'
    finally:
        core.db.close()


@pytest.mark.parametrize('verdict,state', [('rejected', 'pending'), ('unknown', 'needs_recovery')])
def test_native_same_profile_failed_application_retains_overlay_and_records_no_turn(tmp_path, verdict, state):
    core, profile, port = world(tmp_path)
    try:
        core.sessions.set_overlay('overlay', session_id='s', facet_id='model', item_id='choice', value='override')
        core.sessions.select_profile('select-current', session_id='s', profile_id=profile['profile_id'])
        port.apply_verdict = verdict
        with pytest.raises(ProfileError):
            core.sessions.begin_turn('refused', session_id='s')
        assert {i.value for i in port.applied[-1]} == {'a', 'terse'}
        config = core.sessions.session_config('s')
        assert config['switch_state'] == state
        assert {i['value'] for i in config['items']} == {'override', 'terse'}
        assert core.sessions.turns('s') == []
        assert config['evidence']['receipt'] is None
    finally:
        core.db.close()
