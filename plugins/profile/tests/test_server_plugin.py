import pytest

from ordessa_profile.core import StaticHarnessCatalog
from ordessa_profile.server_plugin import ProfileServerPlugin, project
from server_plugin_api import ServerPluginContext, WireError


def build(tmp_path):
    plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({"pi": frozenset()}))
    registration = plugin.build(ServerPluginContext("ordessa.profile", tmp_path))
    handlers = {m.method_id.removeprefix("profiles.v2."):
                (lambda params, handler=m.handler: handler(params)["data"])
                for m in registration.methods}
    return plugin, registration, handlers


def test_real_store_mutations_are_idempotent_and_survive_restart(tmp_path):
    plugin, registration, calls = build(tmp_path)
    params = dict(operationKey="create-1", realm="local", harnessId="pi", displayName="Development")
    profile = calls["createProfile"](params)
    assert calls["createProfile"](params) == profile
    assert calls["listProfiles"]({}) == [profile]
    assert calls["configuredHarnesses"]({}) == ["pi"]
    calls["archiveProfile"](dict(operationKey="archive-1", profileId=profile["profileId"], expectedVersion=1))
    assert calls["listProfiles"]({}) == []
    registration.disposal()
    assert plugin.core is None
    _, registration, calls = build(tmp_path)
    assert len(calls["listProfiles"]({"includeArchived": True})) == 1
    registration.disposal()


def test_gateway_preserves_refusal_code_and_never_advertises_fake_application(tmp_path):
    _, registration, calls = build(tmp_path)
    with pytest.raises(WireError) as error:
        calls["createProfile"](dict(operationKey="bad", realm="local", harnessId="missing", displayName="x"))
    assert error.value.details["internalCode"] == "HARNESS_UNKNOWN"
    assert "beginTurnApplication" not in calls
    assert "cloneProfile" not in calls
    with pytest.raises(WireError):
        calls["listProfiles"]({"includeArchived": "false"})
    registration.disposal()


def test_projection_does_not_rewrite_user_values_or_schema_properties():
    assert project({"profile_id": "p", "value_schema": {"some_key": {}},
                    "value": {"model_id": "unchanged"}}) == {
        "profileId": "p", "valueSchema": {"some_key": {}}, "value": {"model_id": "unchanged"}}


def test_product_registers_management_routes_and_unload_removes_them(tmp_path):
    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app
    from fastapi.testclient import TestClient

    runtime = build_runtime(tmp_path / "product")
    try:
        runtime.start()
        assert runtime.wire.dispatch("profiles.v2.listProfiles", {}) == {"data": []}
        assert runtime.wire.dispatch("profiles.v2.configuredHarnesses", {}) == {"data": []}
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            response = client.post("/wire/v1/profiles.v2.listProfiles", headers={"Authorization": f"Bearer {runtime.token}"},
                json={"jsonrpc": "2.0", "id": "profile-list-001",
                      "method": "profiles.v2.listProfiles", "params": {}})
            assert response.status_code == 200
            assert response.json()["result"] == {"data": []}
        runtime.start()
        runtime.plugin_host.deactivate("ordessa.profile")
        with pytest.raises(WireError):
            runtime.wire.dispatch("profiles.v2.listProfiles", {})
    finally:
        runtime.stop()
