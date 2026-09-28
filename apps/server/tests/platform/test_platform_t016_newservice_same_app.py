"""T016 (SC-002/SC-004): a controlled NEW service plugin joins the SAME app
as the default product, with zero host-source modification.

The rest of T016's task text — same-App auth/signature/owner/mount-order/
dual-exception — is already owned by `test_platform_http_routes_same_app.py`
(T012/T013 era) and is deliberately NOT re-implemented here. What this file
adds is the genuinely missing case: a plugin that is NOT part of the product
selection, written only against the published wall (`server_plugin_api`),
composed next to the product trio on one live App — its `pacthold.contributions`
v1 batch committed into the composition's Core snapshot, its route served
behind the host bearer auth — and a duplicate/typed-conflict from that new
plugin refused typed while the first owner keeps serving.

The wheel-install / second-venv / bare-host halves of T016 are evidenced
OUTSIDE pytest (real fresh venvs under /tmp; `sys.modules` monkeypatching is
forbidden by the quickstart and is not used here): see the run evidence
referenced in reports/B.md — bare-host pip list + import-all + the exact
SERVER_PRODUCT_MISSING refusal, and the product-venv deployment probe.
"""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient
from server_plugin_api import (
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
    SERVER_PLUGIN_API_VERSION,
    Contribution,
    ContributionBatch,
    DuplicateHttpRouteError,
    HttpRouteDescriptor,
    ServerMethodDescriptor,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app

NEW_PLUGIN_ID = "t016.test-controlled-service"
NEW_ROUTE_PATH = "/api/v1/t016-test/echo"
NEW_METHOD_ID = "t016test.echo"


@dataclasses.dataclass(frozen=True)
class _DemoItem:
    contract_id: str = "t016.test-item@1"


class _DemoProvider:
    """C1 ResourceProvider shape: the four callables, descriptor id valid."""

    supported_contract_ids = frozenset({"t016.test-item@1"})

    def describe(self):
        from pacthold.public import ReconcileSupport, ResourceProviderDescriptor
        return ResourceProviderDescriptor(
            id="t016.test-provider", display_name="T016 test provider",
            version="1", reconcile_support=ReconcileSupport.SUPPORTED)

    def acquire(self, request):
        return _DemoItem()

    def release(self, item):
        return True

    def reconcile(self, lease):
        return True


def _echo_endpoint(marker):
    def echo(payload: dict):
        return {"echo": payload, "marker": marker}
    return echo


class ControlledNewPlugin:
    """A service plugin written ONLY against the published wall; the host
    knows nothing about it — that is the point of the gate."""

    def __init__(self, plugin_id=NEW_PLUGIN_ID, *, path=NEW_ROUTE_PATH, method_id=NEW_METHOD_ID):
        self._id = plugin_id
        self._path = path
        self._method_id = method_id
        self.provider = _DemoProvider()

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=self._id, display_name="T016 controlled new service",
            version="1", api_version=SERVER_PLUGIN_API_VERSION)

    def build(self, context) -> ServerPluginRegistration:
        return ServerPluginRegistration(
            methods=(ServerMethodDescriptor(
                method_id=self._method_id,
                required_params=frozenset({"requestId"}), optional_params=frozenset(),
                handler=lambda params: {"ok": NEW_METHOD_ID}, owner=self._id),),
            http_routes=(HttpRouteDescriptor(
                path=self._path, methods=frozenset({"POST"}),
                endpoint=_echo_endpoint(self._id), owner=self._id),),
            provided_ports={f"{self._id}.service": self.provider},
            contributions=ContributionBatch((
                Contribution(
                    point_id=PACTHOLD_CONTRIBUTIONS_POINT_ID,
                    api_version=PACTHOLD_CONTRIBUTIONS_API_VERSION,
                    payload={"contracts": (_DemoItem,),
                             "resource_providers": (self.provider,)},
                    required=True),
            )),
        )


def _product_plugins():
    from ordessa_server_product.composition import create_composition
    return tuple(create_composition().compatibility_plugins())


def test_a_controlled_new_plugin_composes_with_the_default_product_with_no_host_change(tmp_path):
    """The product trio plus one unknown-to-the-host plugin on ONE runtime
    and ONE app: its wire method registers, its route serves behind the
    host bearer auth, and its pacthold.contributions v1 batch is committed
    into THIS composition's Core snapshot — no host module edited for any
    of it (the wheel/venv half of that proof is the /tmp second-venv run)."""
    first = ControlledNewPlugin()
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=_product_plugins() + (first,))
    try:
        runtime.start()
        assert runtime.plugin_host.active_ids() == (
            "ordessa.workspace", "ordessa.server-compat", "ordessa.harness.acp",
            NEW_PLUGIN_ID)
        assert NEW_METHOD_ID in runtime.plugin_host.methods.handler_view()
        snapshot = runtime.core_binding.snapshot()
        assert "t016.test-item@1" in snapshot.contract_ids
        assert "t016.test-provider" in snapshot.resource_provider_ids
        assert runtime.plugin_host.provided_port(f"{NEW_PLUGIN_ID}.service") is first.provider
        headers = {"Authorization": f"Bearer {runtime.token}"}
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        with client:
            served = client.post(NEW_ROUTE_PATH, json={"n": 1}, headers=headers)
            assert served.status_code == 200
            assert served.json()["marker"] == NEW_PLUGIN_ID
            assert client.post(NEW_ROUTE_PATH, json={}).status_code in (401, 403)
            # the product's own HTTP surface keeps answering on the SAME app
            assert client.get("/api/v1/workspaces", headers=headers).status_code == 200
    finally:
        runtime.stop()


def test_the_new_plugin_route_claimed_twice_is_refused_typed_and_the_owner_keeps_serving(tmp_path):
    """Duplicate from the NEW plugin (different owner id, same path+method):
    a typed refusal naming both owners — never a silent override; the live
    first owner keeps serving on the SAME app, and the refused activation
    leaves its method out of the registry (zero half-commit)."""
    first = ControlledNewPlugin()
    runtime = build_runtime(tmp_path / "data",
                            server_plugins=_product_plugins() + (first,))
    try:
        runtime.start()
        headers = {"Authorization": f"Bearer {runtime.token}"}
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        # The duplicate is refused BEFORE the transport's route freeze: the
        # typed route-duplicate gate is what names both owners (after the
        # freeze a foreign-owner row is a typed UNMOUNTED refusal instead —
        # also covered, also typed; never a silent override either way).
        twin = ControlledNewPlugin("t016.test-clone", path=NEW_ROUTE_PATH,
                             method_id="t016testClone.echo")
        with pytest.raises(DuplicateHttpRouteError) as refused:
            runtime.plugin_host.activate(twin)
        assert NEW_PLUGIN_ID in str(refused.value)
        assert "t016.test-clone" in str(refused.value)
        assert not runtime.plugin_host.is_active("t016.test-clone")
        assert "t016testClone.echo" not in runtime.plugin_host.methods.handler_view()
        with client:
            again = client.post(NEW_ROUTE_PATH, json={"n": 2}, headers=headers)
            assert again.status_code == 200
            assert again.json()["marker"] == NEW_PLUGIN_ID
            assert runtime.plugin_host.state == "open"
    finally:
        runtime.stop()
