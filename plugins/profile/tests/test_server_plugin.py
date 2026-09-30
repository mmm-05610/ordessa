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


def test_configuration_save_is_atomic_idempotent_and_clear_preserves_history(tmp_path):
    from conftest import ScriptedProvider
    plugin, registration, calls = build(tmp_path)
    plugin.core.register_provider(ScriptedProvider("test.config", ("model", "style")))
    profile = calls["createProfile"](dict(operationKey="new", realm="local", harnessId="pi", displayName="P"))
    params = dict(operationKey="save", profileId=profile["profileId"], expectedVersion=1, patches=[
        dict(facetId="test.config", itemId="model", op="set", value="m1"),
        dict(facetId="test.config", itemId="style", op="set", value="terse"),
    ])
    saved = calls["saveProfile"](params)
    assert saved["profile"]["version"] == 2
    assert calls["saveProfile"](params) == saved
    with pytest.raises(WireError):
        calls["saveProfile"]({**params, "operationKey": "stale"})
    calls["saveProfile"](dict(operationKey="clear", profileId=profile["profileId"], expectedVersion=2,
        patches=[dict(facetId="test.config", itemId="model", op="unset")]))
    values = plugin.core.profiles.facet_values(profile["profileId"])
    assert [(v["item_id"], v["value"]) for v in values] == [("style", "terse")]
    assert len(plugin.core.profiles.facet_values(profile["profileId"], config_revision=2)) == 2
    with pytest.raises(WireError):
        calls["saveProfile"](dict(operationKey="invalid", profileId=profile["profileId"], expectedVersion=3,
            patches=[dict(facetId="test.config", itemId="style", op="set", value="verbose"),
                     dict(facetId="test.config", itemId="missing", op="unset")]))
    assert plugin.core.profiles.get(profile["profileId"])["version"] == 3
    assert plugin.core.profiles.facet_values(profile["profileId"])[0]["value"] == "terse"
    registration.disposal()


@pytest.mark.parametrize("patches", [None, [], [{}],
    [dict(facetId="test.config", itemId="model", op={})],
    [dict(facetId="test.config", itemId="model", op="unset", value=None)],
    [dict(facetId="test.config", itemId="model", op="set")],
    [dict(facetId="test.config", itemId="model", op="set", value="m1", extra=True)],
    [dict(facetId="test.config", itemId="model", op="unset")] * 2])
def test_configuration_save_refuses_malformed_or_duplicate_patches(tmp_path, patches):
    plugin, registration, calls = build(tmp_path)
    with pytest.raises(WireError):
        calls["saveProfile"](dict(operationKey="bad", profileId="missing", expectedVersion=1, patches=patches))
    registration.disposal()


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


def test_native_registration_uses_injected_owner_and_projects_only_identity(tmp_path):
    from types import SimpleNamespace
    from ordessa_profile.contracts import SessionRef
    from ordessa_harness_api import ApplicationTarget

    seen = []
    def factory(core):
        def register(**params):
            seen.append(params)
            return SimpleNamespace(
                session_ref=SessionRef("local", "pi", params["native_session_id"], "backend-uid"),
                snapshot=SimpleNamespace(target=ApplicationTarget("incarnation", "backend-uid", "connection", 1)))
        return SimpleNamespace(register=register)
    plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({"pi": frozenset()}),
                                 native_registration_factory=factory)
    registration = plugin.build(ServerPluginContext("ordessa.profile", tmp_path))
    try:
        method = next(m for m in registration.methods if m.method_id == "profiles.v2.registerNativeSession")
        assert method.required_params == frozenset({"connectionId", "nativeSessionId", "profileId"})
        assert method.optional_params == frozenset()
        result = method.handler({"connectionId": "connection", "nativeSessionId": "native", "profileId": "profile"})
        assert result["data"]["sessionRef"]["sessionUid"] == "backend-uid"
        assert result["data"]["target"]["sessionId"] == "backend-uid"
        assert seen == [{"connection_id": "connection", "native_session_id": "native", "profile_id": "profile"}]
        assert "profile.native-sessions" in registration.provided_ports
        assert set(result["data"]) == {"sessionRef", "target"}
    finally:
        registration.disposal()


def test_failed_native_registration_factory_closes_profile_core(tmp_path):
    def fail(core):
        raise ValueError("controlled binding construction failed")
    plugin = ProfileServerPlugin(harnesses=StaticHarnessCatalog({"pi": frozenset()}),
                                 native_registration_factory=fail)
    with pytest.raises(ValueError, match="binding construction"):
        plugin.build(ServerPluginContext("ordessa.profile", tmp_path))
    assert plugin.core is None
    # A fresh activation can reuse the same store after failed construction.
    _, registration, _ = build(tmp_path)
    registration.disposal()
