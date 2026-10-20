"""Original host admission/retirement assertions on independent Harness roles."""
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from ordessa_execution_agents.harness.providers.registry.errors import CatalogAdmissionRefused
from ordessa_execution_agents.harness.providers.registry.errors import CatalogUnavailable
from ordessa_units.errors import UnitAdmissionRefused
from dataclasses import dataclass
import pytest
from server_plugin_api import (SERVER_PLUGIN_API_VERSION,Contribution,ContributionBatch,
    DuplicateHttpRouteError,DuplicateMethodError,HttpRouteDescriptor,ServerMethodDescriptor,
    ServerPluginDescriptor,ServerPluginRegistration)
from ordessa_server.composition.unit_runtime import UnitRuntimeOwner
from ordessa_server.composition.harness_registration import HarnessDefinitionHandler
from ordessa_server.composition.plugin_host import ServerPluginHost
from ordessa_server.composition.plugin_host.host import OwnerLifecycleError
from test_unit_governance_product import scope,declaration


def setup(tmp_path):
    runtime=UnitRuntimeOwner(tmp_path/'state/core.sqlite',environment_factory=scope)
    context=runtime.open()
    host=ServerPluginHost()
    handler=HarnessDefinitionHandler(runtime)
    host.register_contribution_point('execution.harness.definitions','harness-definition/1',handler=handler,exclusive=False)
    return runtime,context,host

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
                point_id='execution.harness.definitions',
                api_version='harness-definition/1',
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



def test_host_activation_admits_and_retires_exact_harness_owner(tmp_path):
    runtime,context,host=setup(tmp_path)
    owner='controlled.owner'
    try:
        host.activate(_plugin(owner,payload=(declaration(context.environment_id),)))
        assert context.harness_catalog.list()[0].owner_activation.plugin_id==owner
        assert host.is_active(owner)
        host.deactivate(owner)
        assert context.harness_catalog.list()==()
        assert host.active_ids()==()
    finally:
        runtime.close()

@pytest.mark.parametrize('duplicate_kind',('method','http-route'))
def test_duplicate_method_or_route_refuses_before_role_admission(tmp_path,duplicate_kind):
    runtime,context,host=setup(tmp_path)
    first=_plugin('route.first',route=_route('route.first','/same') if duplicate_kind=='http-route' else None,
        method_id='closeout.duplicate' if duplicate_kind=='method' else None)
    host.activate(first)
    try:
        duplicate=_plugin('route.second',route=_route('route.second','/same') if duplicate_kind=='http-route' else None,
            method_id='closeout.duplicate' if duplicate_kind=='method' else None,
            payload=(declaration(context.environment_id),))
        with pytest.raises(DuplicateHttpRouteError if duplicate_kind=='http-route' else DuplicateMethodError):
            host.activate(duplicate)
        assert context.harness_catalog.list()==()
        assert not host.is_active('route.second')
        assert host.is_active('route.first')
    finally:
        host.deactivate('route.first')
        runtime.close()


def test_failed_stage_does_not_retire_unrelated_admitted_owner(tmp_path):
    runtime,context,host=setup(tmp_path)
    host.activate(_plugin('other.owner',payload=(declaration(context.environment_id),)))
    try:
        with pytest.raises(CoreDTOError):
            host.activate(_plugin('candidate.owner',payload={'not':'a role tuple'}))
        assert not host.is_active('candidate.owner')
        assert host.is_active('other.owner')
        assert tuple(item.owner_activation.plugin_id for item in context.harness_catalog.list())==('other.owner',)
    finally:
        host.deactivate('other.owner')
        runtime.close()


def test_host_keeps_original_owner_when_retirement_is_pending(tmp_path,monkeypatch):
    runtime,context,host=setup(tmp_path)
    owner='blocked.owner'
    host.activate(_plugin(owner,payload=(declaration(context.environment_id),)))
    original=context.harness_catalog.retire
    attempts=[]
    def pending_once(owner_id,generation):
        attempts.append((owner_id,generation))
        if len(attempts)==1:
            raise CatalogUnavailable('controlled-live-usage retire-pending')
        return original(owner_id,generation)
    monkeypatch.setattr(context.harness_catalog,'retire',pending_once)
    try:
        with pytest.raises(OwnerLifecycleError) as refused:
            host.deactivate(owner)
        assert 'retire-pending' in str(refused.value.error)
        assert host.is_active(owner)
        with pytest.raises(CatalogAdmissionRefused):
            runtime.close()
        host.deactivate(owner)
        assert len(attempts)==2 and attempts[0]==attempts[1]
        assert not host.is_active(owner)
        assert context.harness_catalog.list()==()
    finally:
        runtime.close()
