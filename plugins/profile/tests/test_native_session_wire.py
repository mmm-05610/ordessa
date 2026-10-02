"""Controlled native registration; real Profile store and production wire DTOs."""
from dataclasses import asdict
from types import SimpleNamespace
import pytest
from ordessa_profile.contracts import SessionRef
from ordessa_profile.core import StaticHarnessCatalog
from ordessa_profile.errors import ProfileError
from ordessa_profile.server_plugin import ProfileServerPlugin, project
from server_plugin_api import ServerPluginContext, WireError
from profile_harness_doubles import ScriptedProvider, ScriptedV2Provider, ScriptedConfigPort


@pytest.mark.parametrize('override_model', [None, 'a', 'b'])
def test_first_native_submit_same_selected_profile_applies_complete_choice(tmp_path, override_model):
    """Desired registration is not a native receipt; explicit reselect uses the blueprint."""
    from ordessa_harness_api import ApplicationTarget

    ref = SessionRef('local', 'pi', 'native-first', 'backend-first')
    choice = {'harnessId': 'pi', 'providerConfigId': 'provider', 'modelId': 'a'}

    class RequiredChoicePort(ScriptedConfigPort):
        native_turn_application = True

        def plan(self, target, desired, operation_key):
            if len(desired) != 1 or desired[0].facet_id != 'assets.model-provider':
                raise ProfileError('SWITCH_BLOCKED', 'One complete model choice required', status=409)
            return super().plan(target, desired, operation_key)

    port = RequiredChoicePort()

    def factory(core):
        core.config_port = port

        def register(*, connection_id, native_session_id, profile_id):
            assert connection_id == 'channel' and native_session_id == ref.native_session_key
            core.sessions.open_session('registered', session_id=ref.session_uid, session_uid=ref.session_uid,
                native_session_key=ref.native_session_key, realm=ref.realm,
                harness_id=ref.harness_id, profile_id=profile_id)
            return SimpleNamespace(session_ref=ref,
                snapshot=SimpleNamespace(target=ApplicationTarget('server', ref.session_uid, connection_id, 1)))

        def require_registered(value):
            assert value == ref

        return SimpleNamespace(register=register, require_registered=require_registered)

    plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({'pi': frozenset()}),
                                 native_registration_factory=factory)
    registration = plugin.build(ServerPluginContext('ordessa.profile', tmp_path))
    calls = {m.method_id.split('.')[-1]: m.handler for m in registration.methods}
    try:
        plugin.core.register_v2_provider(ScriptedV2Provider('assets.model-provider',
            (('choice', {'type': 'object'}),), capability_rule='yes'), owner_plugin_id='controlled-model-provider')
        profile = calls['createProfile']({'operationKey': 'profile', 'realm': 'local',
            'harnessId': 'pi', 'displayName': 'First'})['data']['profileId']
        calls['saveProfile']({'operationKey': 'save', 'profileId': profile, 'expectedVersion': 1,
            'patches': [{'facetId': 'assets.model-provider', 'itemId': 'choice', 'op': 'set', 'value': choice}]})
        registered = calls['registerNativeSession']({'connectionId': 'channel',
            'nativeSessionId': ref.native_session_key, 'profileId': profile})['data']
        params = {'sessionRef': registered['sessionRef']}
        assert calls['inspectSessionConfig'](params)['data']['evidence']['receipt'] is None
        if override_model is not None:
            calls['setSessionOverride']({**params, 'operationKey': 'override',
                'facetId': 'assets.model-provider', 'itemId': 'choice',
                'value': {**choice, 'modelId': override_model}})
        calls['selectForSession']({**params, 'operationKey': 'select', 'profileId': profile})
        assert port.counters['apply'] == port.counters['plan'] == 0
        result = calls['beginTurnApplication']({**params, 'operationKey': 'first-send'})['data']
        assert result['receipt']['profileId'] == profile
        assert len(port.applied) == 1 and len(port.applied[0]) == 1
        assert port.applied[0][0].value == choice
        config = calls['inspectSessionConfig'](params)['data']
        assert config['switchState'] == 'settled' and config['pending'] is None
        assert config['items'][0]['source']['kind'] == 'profile'
        assert config['items'][0]['value'] == choice
    finally:
        registration.disposal()


def test_pending_selection_uses_registered_reference_without_application(tmp_path):
    ref = SessionRef("local", "pi", "native", "backend-uid")
    seen = []
    def factory(core):
        def require_registered(value):
            seen.append(value)
            if value != ref:
                raise ProfileError("SESSION_NOT_FOUND", "Unknown reference", status=404)
        return SimpleNamespace(require_registered=require_registered)
    plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({"pi": frozenset()}),
                                 native_registration_factory=factory)
    registration = plugin.build(ServerPluginContext("ordessa.profile", tmp_path))
    calls = {m.method_id.split(".")[-1]: m.handler for m in registration.methods}
    try:
        first = plugin.core.profiles.create("first", realm="local", harness_id="pi", display_name="First")
        second = plugin.core.profiles.create("second", realm="local", harness_id="pi", display_name="Second")
        plugin.core.register_provider(ScriptedProvider("model", ("choice",), valid={"base", "override"}))
        plugin.core.profiles.set_facet_values("base", profile_id=first["profile_id"], expected_version=1,
            values=[{"facet_id": "model", "item_id": "choice", "value": "base"}])
        plugin.core.sessions.open_session("open", session_id=ref.session_uid, session_uid=ref.session_uid,
            native_session_key=ref.native_session_key, realm=ref.realm, harness_id=ref.harness_id,
            profile_id=first["profile_id"])
        params = {"operationKey": "select", "sessionRef": project(asdict(ref)), "profileId": second["profile_id"]}
        selected = calls["selectForSession"](params)["data"]
        assert selected == {"sessionRef": params["sessionRef"], "pendingProfileId": second["profile_id"],
                            "pendingSeq": 1, "switchState": "pending"}
        assert calls["selectForSession"](params)["data"] == selected
        config = calls["inspectSessionConfig"]({"sessionRef": params["sessionRef"]})["data"]
        assert config["sessionRef"] == params["sessionRef"]
        assert config["current"]["profileId"] == first["profile_id"]
        assert config["pending"]["profileId"] == second["profile_id"]
        override_params = {"operationKey": "override", "sessionRef": params["sessionRef"],
                           "facetId": "model", "itemId": "choice", "value": "override"}
        overridden = calls["setSessionOverride"](override_params)["data"]
        assert overridden["items"][0]["value"] == "override"
        assert overridden["items"][0]["source"]["kind"] == "session-overlay"
        assert overridden["items"][0]["state"] == "explicit"
        assert plugin.core.profiles.facet_values(first["profile_id"])[0]["value"] == "base"
        cleared = calls["clearSessionOverride"]({k: v for k, v in {**override_params, "operationKey": "clear"}.items() if k != "value"})["data"]
        assert cleared["items"][0]["value"] == "base"
        assert cleared["items"][0]["source"]["kind"] == "profile"
        with plugin.core.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM profile_applied_receipts").fetchone()[0] == 0
        port = ScriptedConfigPort(apply_verdict="unknown")
        port.native_turn_application = True
        plugin.core.config_port = port
        calls["selectForSession"]({**params, "operationKey": "back", "profileId": first["profile_id"]})
        with pytest.raises(WireError):
            calls["beginTurnApplication"]({"operationKey": "unknown", "sessionRef": params["sessionRef"]})
        recovered = calls["reconcile"]({"operationKey": "recover", "sessionRef": params["sessionRef"]})["data"]
        assert recovered["state"] == "confirmed-current"
        assert recovered["receipt"]["sessionRef"] == params["sessionRef"]
        assert port.counters["apply"] == 1
        with pytest.raises(WireError):
            calls["selectForSession"]({**params, "operationKey": "forged", "sessionRef": {**params["sessionRef"], "sessionUid": "forged"}})
        with pytest.raises(WireError):
            calls["inspectSessionConfig"]({"sessionRef": {**params["sessionRef"], "target": "untrusted"}})
        assert seen
    finally:
        registration.disposal()
