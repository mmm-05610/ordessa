"""Real HTTP entry behavior at the injected system-access host boundary.

These tests use the published ``HttpHostView``/``create_app`` entry and real
wire/1 requests. The small host and Unit canary below observe resource lifetime;
they do not model Unit admission, Engineering policy, or the product assembly.
"""
from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from ordessa_interfaces.http import HttpHostView, create_app
from ordessa_interfaces.system_access.contracts.transport import AccessError
from ordessa_system_access_client import ClientError, Service, WireClient


class _Authority:
    def authenticate(self, authorization):
        if authorization != "Bearer local-test-token":
            raise AccessError("invalid test credential")
        return "local-machine"

    @contextmanager
    def guard_legacy(self, principal):
        yield principal

    def verify(self, principal):
        if principal != "local-machine":
            raise AccessError("stale test principal")


class _StreamRoutes:
    def resolve(self, _name, _route_id):
        return None


class _UnitLifetimeCanary:
    """A host-owned resource whose close is observable, not a Unit fake API."""

    def __init__(self):
        self.open = True
        self.close_calls = 0

    def close(self):
        self.open = False
        self.close_calls += 1


class _Wire:
    def __init__(self, authority, unit):
        self.identity_authority = authority
        self.acp_admission_gate = None
        self.stream_routes = _StreamRoutes()
        self.unit = unit
        self.dispatch_calls = []

    def dispatch(self, method, params, *, caller=None):
        self.dispatch_calls.append((method, params, caller))
        if method == "units.observe_lifetime":
            return {"open": self.unit.open, "caller": caller}
        if method == "units.apply_effect":
            return {"open": self.unit.open, "applied": True, "caller": caller}
        return {"method": method, "params": params, "caller": caller}


class _Host:
    """Minimal host view; only its own stop owns the canary's lifetime."""

    def __init__(self, *, plugin_host=None):
        self.unit = _UnitLifetimeCanary()
        self.wire = _Wire(_Authority(), self.unit)
        self.plugin_host = plugin_host
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.started = True

    def stop(self):
        self.stop_calls += 1
        self.started = False
        self.unit.close()


class _EmptyRoutes:
    def descriptors(self):
        return ()


class _RouteFreezeFailure:
    http_routes = _EmptyRoutes()

    def freeze_http_routes(self, _routes):
        raise RuntimeError("controlled route-freeze failure")


def _wire_request(client, method, params, request_id):
    return client.post(
        f"/wire/v1/{method}",
        headers={"Authorization": "Bearer local-test-token"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def test_one_injected_http_host_owns_start_stop_and_survives_finished_client_calls():
    host = _Host()
    assert isinstance(host, HttpHostView)
    app = create_app(host)

    # The context manager is the one process/app-lifespan owner. Each short
    # lived TestClient below is an independent caller that closes its client
    # connection before the next caller arrives.
    with TestClient(app, base_url="http://127.0.0.1"):
        assert host.start_calls == 1
        first_client = TestClient(app, base_url="http://127.0.0.1")
        first = _wire_request(first_client, "units.observe_lifetime", {}, "observe-1")
        first_client.close()
        assert first.status_code == 200
        assert first.json()["result"] == {"open": True, "caller": "local-machine"}

        # Closing one client's transport does not transfer ownership of the
        # backend Unit resource to that client or stop the app host.
        second_client = TestClient(app, base_url="http://127.0.0.1")
        second = _wire_request(second_client, "units.observe_lifetime", {}, "observe-2")
        second_client.close()
        assert second.status_code == 200
        assert second.json()["result"]["open"] is True
        assert host.unit.close_calls == 0
        assert host.start_calls == 1
        assert host.stop_calls == 0

    # The app lifespan, rather than a request/client exchange, owns shutdown.
    assert host.stop_calls == 1
    assert host.unit.close_calls == 1
    assert not host.unit.open


def test_post_start_route_freeze_failure_still_stops_the_host_once():
    host = _Host(plugin_host=_RouteFreezeFailure())
    app = create_app(host)

    with pytest.raises(RuntimeError, match="controlled route-freeze failure"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pytest.fail("route-freeze failure must abort app startup")

    assert host.start_calls == 1
    assert host.stop_calls == 1
    assert host.unit.close_calls == 1
    assert not host.unit.open


def test_on_bound_failure_after_start_still_stops_the_host_once():
    host = _Host()

    def fail_announcement():
        raise RuntimeError("controlled announcement failure")

    app = create_app(host, on_bound=fail_announcement)
    with pytest.raises(RuntimeError, match="controlled announcement failure"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pytest.fail("on_bound failure must abort app startup")

    assert host.start_calls == 1
    assert host.stop_calls == 1
    assert host.unit.close_calls == 1
    assert not host.unit.open


def test_lost_effectful_wire_response_is_unknown_once_and_leaves_host_running():
    host = _Host()
    app = create_app(host)
    wire_client = WireClient(Service("test", "http://127.0.0.1", "local-test-token"), timeout=0.01)

    with TestClient(app, base_url="http://127.0.0.1") as server_client:
        original_open = wire_client.opener.open
        sends = []

        def dispatch_then_lose_response(request, *, timeout):
            # Exercise the actual ASGI route/authority/dispatcher, then model a
            # network timeout after the effect may have committed. No retry is
            # safe because the caller did not observe its receipt.
            path = urlsplit(request.full_url).path
            response = server_client.request(
                request.get_method(), path, content=request.data,
                headers=dict(request.header_items()),
            )
            sends.append(response)
            raise TimeoutError("controlled response loss")

        wire_client.opener.open = dispatch_then_lose_response
        try:
            with pytest.raises(ClientError) as unknown:
                wire_client.call(
                    "units.apply_effect", {"requestId": "stable-request"},
                    "transport-id-1", effectful=True,
                )
        finally:
            wire_client.opener.open = original_open

        assert unknown.value.code == "OUTCOME_UNKNOWN"
        assert unknown.value.exit_code == 6
        assert len(sends) == 1
        assert sends[0].status_code == 200
        assert len(host.wire.dispatch_calls) == 1
        assert host.unit.open
        assert host.unit.close_calls == 0
        assert host.stop_calls == 0

        # A later observation remains possible; clients do not own Unit close.
        observer = TestClient(app, base_url="http://127.0.0.1")
        observed = _wire_request(observer, "units.observe_lifetime", {}, "observe-after-loss")
        observer.close()
        assert observed.status_code == 200
        assert observed.json()["result"]["open"] is True

    assert host.stop_calls == 1
    assert host.unit.close_calls == 1
