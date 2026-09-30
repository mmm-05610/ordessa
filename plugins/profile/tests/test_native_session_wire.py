"""Controlled native registration; real Profile store and production wire DTOs."""
from dataclasses import asdict
from types import SimpleNamespace
import pytest
from ordessa_profile.contracts import SessionRef
from ordessa_profile.core import StaticHarnessCatalog
from ordessa_profile.errors import ProfileError
from ordessa_profile.server_plugin import ProfileServerPlugin, project
from server_plugin_api import ServerPluginContext, WireError


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
        with plugin.core.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) FROM profile_applied_receipts").fetchone()[0] == 0
        with pytest.raises(WireError):
            calls["selectForSession"]({**params, "operationKey": "forged", "sessionRef": {**params["sessionRef"], "sessionUid": "forged"}})
        with pytest.raises(WireError):
            calls["inspectSessionConfig"]({"sessionRef": {**params["sessionRef"], "target": "untrusted"}})
        assert seen
    finally:
        registration.disposal()
