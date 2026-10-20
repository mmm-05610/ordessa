"""Original Service/Work/review identity at pre-Proposal Product construction.

Native installation and source callbacks are controlled inputs. This is no
qualification of reviewer provenance, a method publication, Unit or model run.
"""
from dataclasses import replace
import json
import time

import pytest

from ordessa_engineering.application.api import ApplicationError
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.engineering import EngineeringServerPlugin, DEFAULT_MACHINE_CAPABILITIES
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_system_access_bindings.engineering_wire import REVIEW_REQUEST_QUERY
from ordessa_units.assembly import UnitRunPermission
from test_pi_execution_selection import selection_inputs
from test_product_unbound_configuration import _configuration


def test_original_unbound_reader_is_retained_by_same_runtime_service_and_work(selection_inputs, tmp_path):
    selection, ports, calls, instance, root = selection_inputs
    scope = Scope(selection.profile_revision.environment_namespace, "test-project")
    actions = frozenset({"prepare", "start", "interaction", "stop", "release"})
    capabilities = tuple(dict.fromkeys((*DEFAULT_MACHINE_CAPABILITIES,
                                       REVIEW_REQUEST_QUERY)))

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope, tuple(dict.fromkeys((
            *("execution.units." + action for action in sorted(actions)), *capabilities,
        )))),))
        principal = authority.authenticate("Bearer " + runtime.token)
        return UnitRunPermission(
            access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity,
            root_directory=str(tmp_path / "local"), actions=actions,
            expires_at=time.time() + 60)

    def missing_native_source(*_args, **_kwargs):
        raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")

    runtime = build_product_runtime(
        root, pi_selection=selection, pi_ports=replace(ports, permission_factory=permission_factory),
        native_user_configuration=json.dumps(_configuration(selection)),
        method_unit_options={"proposal_ref": None, "phases": None,
                             "author_unit_resolver": missing_native_source,
                             "invocation_resolver": missing_native_source,
                             "unit_query_factory": missing_native_source},
        library_path=(tmp_path / "engineering.sqlite").resolve(),
        library_id="unbound-product-reader", scope=scope,
        create_library=True, schema_version=15, machine_capabilities=capabilities)
    try:
        plugin, = (item for item in runtime.plugin_selection
                   if type(item) is EngineeringServerPlugin)
        wire = plugin._binding_for(runtime.wire.identity_authority)
        bindings = runtime.engineering_review_bindings
        assert bindings is wire.ports.review_admission.bindings
        assert bindings is wire.ports.current_wait_bindings.source.review_bindings
        assert bindings.factory is plugin._factory
        assert wire.ports.current_wait_bindings.factory is bindings.factory
        method_runs = wire.ports.current_wait_bindings
        assert wire.service._work.bindings is method_runs
        assert wire.service._waits.bindings is method_runs
        assert wire.capabilities()["supports"]["work_projection"] is True
        assert runtime.units is runtime.unit_execution_owner.manager
        assert wire.ports.reviewer_assignments.records is runtime.unit_execution_owner.records
        assert runtime.units.list() == ()
        assert instance.snapshot.active_uses == 0
        principal = runtime.unit_execution_owner.permission.principal
        with wire.access.admit(principal, scope, REVIEW_REQUEST_QUERY,
                               request_id="unbound-reader", trace_id="unbound-reader") as context:
            with pytest.raises(ApplicationError, match="METHOD_SELECTION_UNAVAILABLE"):
                with method_runs.methods.guard_selected(context):
                    pass
            with pytest.raises(ApplicationError, match="METHOD_TARGET_BINDINGS_UNAVAILABLE"):
                bindings.resolve_bindings(context, None, "source_review")
        with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_UNAVAILABLE"):
            wire.ports.reviewer_assignments.unit_query_factory(None, None, None, None)
    finally:
        runtime.stop()
    assert instance.snapshot.active_uses == 0
