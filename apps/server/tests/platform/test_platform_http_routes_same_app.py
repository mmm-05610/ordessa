"""T012 family (d): plugin HTTP routes on the SAME live App.

C3: the transport is a frozen route snapshot — path/methods/owner/auth/
request signature; an unmounted or re-shaped route is a typed refusal, never
an App swap or a silent rebind, and the request path resolves the endpoint
from the live registry so retiring a capability is observable immediately.
These are the platform/ counterexamples beside the existing gates (which
stay untouched); a contribution carrier that let a plugin's half-round routes
go live, or that dodged the route freeze, fails these.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server_plugin_api import (
    DuplicateHttpRouteError,
    HttpRouteDescriptor,
    HttpRouteShapeChangedError,
    HttpRouteUnmountedError,
    ServerPluginRegistration,
)

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app

from contribution_fakes import ContribPlugin, RecordingHandler, contribution

PATH = "/api/v1/platform-fake/echo"
POINT = "test.route"


class _RoutePlugin(ContribPlugin):
    """A contribution-capable plugin whose registration also owns one POST
    route; `endpoint_factory(plugin_id)` lets one test swap the request
    signature between builds."""

    def __init__(self, plugin_id, *, path=PATH, endpoint_factory=None, **flags):
        super().__init__(plugin_id, **flags)
        self._path = path
        self._endpoint_factory = endpoint_factory or (lambda marker: _echo_endpoint(marker))

    def build(self, context):
        registration = super().build(context)
        endpoint = self._endpoint_factory(self._descriptor.id)
        return ServerPluginRegistration(
            methods=registration.methods,
            stream_routes=registration.stream_routes,
            http_routes=(HttpRouteDescriptor(
                path=self._path, methods=frozenset({"POST"}), endpoint=endpoint,
                owner=self._descriptor.id),),
            provided_ports=registration.provided_ports,
            disposal=registration.disposal,
            contributions=registration.contributions,
        )


def _echo_endpoint(marker):
    def echo(body: dict):
        return {"echo": body, "marker": marker}
    return echo


def _drifted_endpoint(marker):
    def echo(body: dict, extra: int):  # a new required parameter: shape drift
        return {"echo": body, "marker": marker}
    return echo


def test_two_plugins_one_app_one_path_a_typed_duplicate_and_the_owner_keeps_serving(tmp_path):
    """First owner is mounted and serving on the live App; the second
    plugin's activation — same path+method — is a typed duplicate refusal
    naming both owners. The first keeps serving, the second never became
    active and its wire row is gone. Delete the overlap guard and FastAPI
    would answer with a registration-order race instead."""
    first = _RoutePlugin("fake.route.a", methods=("fake.a.method",))
    runtime = build_runtime(tmp_path / "data", server_plugins=[first])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert client.post(PATH, json={"n": 1}, headers=headers).json()["marker"] \
            == "fake.route.a"
        second = _RoutePlugin("fake.route.b", methods=("fake.b.method",))
        with pytest.raises(DuplicateHttpRouteError) as refused:
            runtime.plugin_host.activate(second)
        assert refused.value.path == PATH
        assert "fake.route.a" in str(refused.value) and "fake.route.b" in str(refused.value)
        assert second.builds == 1 and not runtime.plugin_host.is_active("fake.route.b")
        assert "fake.b.method" not in runtime.plugin_host.methods.handler_view()
        # the same App, still live, still serves exactly the first owner
        assert client.post(PATH, json={"n": 2}, headers=headers).json()["marker"] \
            == "fake.route.a"
    finally:
        runtime.stop()


def test_a_contribution_carrying_plugin_with_an_unmounted_route_refuses_whole(tmp_path):
    """The frozen set admits no new route after the App exists — and the
    refusal is the WHOLE plugin: its wire method and its staged contribution
    are rolled back with it, so no consumer can reach a capability whose
    HTTP half silently never serves."""
    runtime = build_runtime(tmp_path / "data", server_plugins=[])
    try:
        handler = RecordingHandler()
        runtime.plugin_host.register_contribution_point(POINT, "v1", handler=handler)
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            late = _RoutePlugin("fake.late", path="/api/v1/platform-fake/late",
                                methods=("fake.late.method",),
                                contributions=(contribution(POINT),))
            with pytest.raises(HttpRouteUnmountedError) as refused:
                runtime.plugin_host.activate(late)
            assert refused.value.plugin_id == "fake.late"
            assert not runtime.plugin_host.is_active("fake.late")
            assert handler.names("commit") == [], "the batch never published"
            assert "fake.late.method" not in runtime.plugin_host.methods.handler_view()
            assert client.post("/api/v1/platform-fake/late", json={},
                               headers={"Authorization": f"Bearer {runtime.token}"}
                               ).status_code == 404
            assert runtime.plugin_host.state == "open"
    finally:
        runtime.stop()


def test_a_retired_route_is_gone_on_the_same_app_immediately(tmp_path):
    """The request path takes its endpoint from the live registry: unload
    is observable on the SAME client without an App swap — the honest
    retirement is instant, not 'on the next restart'. A mounted wrapper
    that captured the endpoint (or never checked the owner) keeps serving
    the retired capability and fails this."""
    plugin = _RoutePlugin("fake.retire", methods=("fake.retire.method",))
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        runtime.start()
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        assert client.post(PATH, json={}, headers=headers).status_code == 200
        runtime.plugin_host.deactivate("fake.retire")
        assert client.post(PATH, json={}, headers=headers).status_code == 404
    finally:
        runtime.stop()


def test_a_reactivated_route_with_a_drifted_signature_refuses_and_never_rebinds(tmp_path):
    """Unload, then re-activate with a drifted request signature: typed
    refusal, no App swap, no silent rebind — the same App object keeps
    serving the shape it mounted. Only after that refusal a same-shape
    re-activation resumes service on the SAME app, answering from the live
    registry (the current build), never a captured stale reference."""
    builds = {"drift": False}

    def factory(marker):
        return _drifted_endpoint(marker) if builds["drift"] else _echo_endpoint(marker)

    plugin = _RoutePlugin("fake.shape", endpoint_factory=factory)
    runtime = build_runtime(tmp_path / "data", server_plugins=[plugin])
    headers = {"Authorization": f"Bearer {runtime.token}"}
    try:
        app = create_app(runtime)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            assert client.post(PATH, json={}, headers=headers).status_code == 200
            runtime.plugin_host.deactivate("fake.shape")
            builds["drift"] = True
            with pytest.raises(HttpRouteShapeChangedError) as refused:
                runtime.plugin_host.activate(
                    _RoutePlugin("fake.shape", endpoint_factory=factory))
            assert refused.value.plugin_id == "fake.shape"
            assert not runtime.plugin_host.is_active("fake.shape")
            # no App swap, no rebind: while the owner is inactive nobody serves
            assert client.post(PATH, json={}, headers=headers).status_code == 404
            # a same-shape re-activation resumes on the SAME app object and
            # the SAME client, serving the current registration
            builds["drift"] = False
            runtime.plugin_host.activate(
                _RoutePlugin("fake.shape", endpoint_factory=factory,
                             methods=("fake.shape.method",)))
            answer = client.post(PATH, json={"again": True}, headers=headers)
            assert answer.status_code == 200
            assert answer.json()["marker"] == "fake.shape"
            assert "fake.shape.method" in runtime.plugin_host.methods.handler_view()
    finally:
        runtime.stop()
