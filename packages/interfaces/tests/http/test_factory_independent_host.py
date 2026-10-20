"""The HTTP app factory must run against a minimal, independent host.

This proves ``create_app`` depends only on the declared ``HttpHostView`` ports
and not on the Server's concrete ``ServerRuntime``: the host below is a plain
class with a handful of members and imports nothing from ``ordessa_server``.
It is the acceptance test for the port inversion (no hidden runtime coupling).
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDisconnect

from ordessa_interfaces.http import HttpHostView, create_app
from ordessa_interfaces.system_access.contracts.transport import AccessError


class _Authority:
    def authenticate(self, authorization):
        if authorization != "Bearer good":
            raise AccessError("bad token")
        return "principal-local"

    @contextmanager
    def guard_legacy(self, principal):
        yield principal

    def verify(self, principal):
        if principal != "principal-local":
            raise AccessError("stale")


class _StreamRoutes:
    def resolve(self, name, route_id):
        return None


class _Wire:
    def __init__(self, authority):
        self.identity_authority = authority
        self.acp_admission_gate = None
        self.stream_routes = _StreamRoutes()

    def dispatch(self, method, params, *, caller=None):
        return {"echo": method, "params": params, "caller": caller}


class _Host:
    """A minimal host that satisfies ``HttpHostView`` structurally."""

    def __init__(self, *, authority=None):
        self.wire = _Wire(authority)
        self.plugin_host = None
        self.started = False
        self.started_calls = 0
        self.stopped_calls = 0

    def start(self):
        self.started = True
        self.started_calls += 1

    def stop(self):
        self.started = False
        self.stopped_calls += 1


def test_the_minimal_host_satisfies_the_declared_view():
    host = _Host(authority=_Authority())
    assert isinstance(host, HttpHostView)  # structural conformance, no concrete class


def test_factory_serves_live_wire_and_lifecycle_without_a_serverruntime():
    host = _Host(authority=_Authority())
    app = create_app(host)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/live").json() == {"status": "alive"}
        assert host.started_calls == 1  # lifespan start ran on the injected host

        unauth = client.post("/wire/v1/host.echo", json={
            "jsonrpc": "2.0", "id": 1, "method": "host.echo", "params": {}})
        assert unauth.status_code == 401

        ok = client.post("/wire/v1/host.echo", headers={"Authorization": "Bearer good"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "host.echo", "params": {"a": 1}})
        assert ok.status_code == 200
        assert ok.json()["result"] == {"echo": "host.echo", "params": {"a": 1}, "caller": "principal-local"}
        assert ok.headers["X-Wire-Version"] == "wire/1"

    assert host.stopped_calls == 1  # lifespan stop ran on the injected host


def test_round_gate_closes_the_business_stream_before_the_host_starts():
    host = _Host(authority=_Authority())  # lifespan never runs -> started stays False
    app = create_app(host)
    client = TestClient(app, base_url="http://127.0.0.1")
    with pytest.raises(WebSocketDisconnect) as refusal:
        with client.websocket_connect("/wire/v1/event-stream?sessionId=s1",
                                      headers={"Authorization": "Bearer good", "Host": "127.0.0.1"}):
            pass
    assert refusal.value.code == 4400


def test_loopback_wall_rejects_a_foreign_host():
    host = _Host(authority=_Authority())
    app = create_app(host)
    client = TestClient(app, base_url="http://127.0.0.1")
    rejected = client.get("/live", headers={"host": "example.com"})
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "LOOPBACK_POLICY_REJECTED"
