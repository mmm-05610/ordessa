"""Closeout regressions for bridging Server plugin ownership to Environment.

The host owns plugin ordering and duplicate admission; the product's
CoreBinding owns explicit Environment installation/enablement and retirement.
These tests exercise that bridge through the public host activation path.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from server_plugin_api import (
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
    SERVER_PLUGIN_API_VERSION,
    Contribution,
    ContributionBatch,
    DuplicateHttpRouteError,
    DuplicateMethodError,
    HttpRouteDescriptor,
    ServerMethodDescriptor,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.core_binding import CoreBinding
from ordessa_server.plugin_host import ServerPluginHost
from ordessa_server.plugin_host.host import OwnerLifecycleError
from ordessa_environment_api import GuaranteeUnavailableError
from pacthold.public import Environment, InstallationRecord


@dataclass
class _Plugin:
    descriptor_value: ServerPluginDescriptor
    route: HttpRouteDescriptor | None = None
    method_id: str | None = None
    payload: object | None = None

    def descriptor(self):
        return self.descriptor_value

    def build(self, _context):
        contributions = ()
        if self.payload is not None:
            contributions = (Contribution(
                point_id=PACTHOLD_CONTRIBUTIONS_POINT_ID,
                api_version=PACTHOLD_CONTRIBUTIONS_API_VERSION,
                payload=self.payload,
                required=True,
            ),)
        return ServerPluginRegistration(
            methods=(() if self.method_id is None else (ServerMethodDescriptor(
                method_id=self.method_id,
                required_params=frozenset(),
                optional_params=frozenset(),
                handler=lambda _params: {"owner": self.descriptor_value.id},
                owner=self.descriptor_value.id,
            ),)),
            http_routes=(() if self.route is None else (self.route,)),
            contributions=ContributionBatch(contributions),
        )


def _plugin(plugin_id: str, *, version: str = "1", route=None, method_id=None,
            payload=None) -> _Plugin:
    return _Plugin(
        ServerPluginDescriptor(
            id=plugin_id,
            display_name=plugin_id,
            version=version,
            api_version=SERVER_PLUGIN_API_VERSION,
        ),
        route=route,
        method_id=method_id,
        payload=payload,
    )


def _route(owner: str, path: str) -> HttpRouteDescriptor:
    def endpoint():
        return {"owner": owner}

    return HttpRouteDescriptor(
        path=path,
        methods=frozenset({"GET"}),
        endpoint=endpoint,
        owner=owner,
    )


def test_core_binding_host_activation_installs_and_explicitly_enables_one_owner(tmp_path):
    environment = Environment("host-owner")
    binding = CoreBinding(
        tmp_path / "unused.sqlite",
        environment_factory=lambda _path: environment,
    )
    host = ServerPluginHost()
    host.register_contribution_point(
        PACTHOLD_CONTRIBUTIONS_POINT_ID,
        PACTHOLD_CONTRIBUTIONS_API_VERSION,
        handler=binding,
    )
    owner = "controlled.owner"
    try:
        host.activate(_plugin(owner, payload={}))

        assert owner in environment.installed
        assert owner in environment.enabled
        assert host.is_active(owner)

        host.deactivate(owner)
        assert owner not in environment.enabled
        assert host.active_ids() == ()
    finally:
        binding.close()


@pytest.mark.parametrize("duplicate_kind", ("method", "http-route"))
def test_duplicate_method_or_route_refuses_before_environment_owner_is_enabled(
    tmp_path, duplicate_kind,
):
    environment = Environment("host-owner")
    binding = CoreBinding(
        tmp_path / "unused.sqlite",
        environment_factory=lambda _path: environment,
    )
    host = ServerPluginHost()
    host.register_contribution_point(
        PACTHOLD_CONTRIBUTIONS_POINT_ID,
        PACTHOLD_CONTRIBUTIONS_API_VERSION,
        handler=binding,
    )
    first = _plugin(
        "route.first",
        route=_route("route.first", "/same") if duplicate_kind == "http-route" else None,
        method_id="closeout.duplicate" if duplicate_kind == "method" else None,
    )
    host.activate(first)
    try:
        duplicate = _plugin(
            "route.second",
            route=_route("route.second", "/same") if duplicate_kind == "http-route" else None,
            method_id="closeout.duplicate" if duplicate_kind == "method" else None,
            payload={},
        )
        expected = (DuplicateHttpRouteError if duplicate_kind == "http-route"
                    else DuplicateMethodError)
        with pytest.raises(expected):
            host.activate(duplicate)

        assert "route.second" not in environment.installed
        assert "route.second" not in environment.enabled
        assert not host.is_active("route.second")
        assert host.is_active("route.first")
    finally:
        host.deactivate("route.first")
        binding.close()


def test_failed_core_stage_disables_only_the_owner_enabled_for_this_round(tmp_path):
    environment = Environment("host-owner")
    binding = CoreBinding(
        tmp_path / "unused.sqlite",
        environment_factory=lambda _path: environment,
    )
    host = ServerPluginHost()
    host.register_contribution_point(
        PACTHOLD_CONTRIBUTIONS_POINT_ID,
        PACTHOLD_CONTRIBUTIONS_API_VERSION,
        handler=binding,
    )
    # This is an unrelated, already-enabled owner. A failed plugin round must
    # never disable or retire it as cleanup for the candidate owner.
    environment.install(InstallationRecord("other.owner", "a" * 64))
    environment.enable("other.owner")
    try:
        with pytest.raises(TypeError):
            host.activate(_plugin("candidate.owner", payload={"not": "a contribution set"}))

        assert "candidate.owner" not in environment.enabled
        assert "other.owner" in environment.enabled
        assert not host.is_active("candidate.owner")
    finally:
        binding.close()


def test_core_binding_refuses_to_disable_owner_when_activation_retirement_is_pending(tmp_path):
    """The host must keep ownership attached to a live Environment blocker.

    This case is deliberately exercised via the host API: rollback/retirement
    cannot be replaced by owner-only unregister or swallowed as cleanup.
    """
    environment = Environment("host-owner")
    binding = CoreBinding(
        tmp_path / "unused.sqlite",
        environment_factory=lambda _path: environment,
    )
    host = ServerPluginHost()
    host.register_contribution_point(
        PACTHOLD_CONTRIBUTIONS_POINT_ID,
        PACTHOLD_CONTRIBUTIONS_API_VERSION,
        handler=binding,
    )
    owner = "blocked.owner"
    host.activate(_plugin(owner, payload={}))

    # Inject a truthful retirement refusal at the Environment boundary. The
    # exact activation ref is supplied by CoreBinding's staged handle; the
    # host must preserve its active owner and enabled state until retirement
    # succeeds.
    original_retire = environment.retire_activation
    attempts = []

    def pending_once(ref, closure_evidence=None):
        attempts.append(ref)
        if len(attempts) == 1:
            return "retire-pending", ("controlled-live-usage",)
        return original_retire(ref, closure_evidence)

    environment.retire_activation = pending_once
    try:
        with pytest.raises(OwnerLifecycleError) as refused:
            host.deactivate(owner)
        assert "retire-pending" in str(refused.value.error)

        assert host.is_active(owner)
        assert owner in environment.enabled
        with pytest.raises(GuaranteeUnavailableError, match="owner lifecycle retirement"):
            binding.close()

        host.deactivate(owner)
        assert len(attempts) == 2
        assert attempts[0] == attempts[1]
        assert not host.is_active(owner)
        assert owner not in environment.enabled
    finally:
        binding.close()
