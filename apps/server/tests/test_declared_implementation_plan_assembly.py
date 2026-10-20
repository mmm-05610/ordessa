"""Declared report-only plans cross the real selected-owner assembly boundary.

Temporary original Product and Library owners are real. No Unit is created,
no native process/model is started, and no credential or historical root is read.
The absent plan/runner bodies remain explicit refusals, never fake evidence.
"""
import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_server.composition.engineering_method_unit_assembly import method_unit_application_ports_factory
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts, EngineeringWireBinding
from .test_selected_unit_shutdown import _build_selected_runtime


class _ReportOnlyPlans:
    def __init__(self, factory):
        self.factory = factory

    def implementation_plan(self, *_args, **_kwargs):
        raise AssertionError('Assembly must not request a review plan')


@pytest.mark.parametrize('selection', ['report_only', 'source_callable', 'foreign_factory',
    'missing_producer', 'direct_foreign_factory', 'direct_missing_producer'])
def test_selected_method_unit_assembly_accepts_original_report_plan_port_only(tmp_path, selection):
    runtime, _environment = _build_selected_runtime(tmp_path)
    # This existing method-unit assembly's native reviewer authority supports
    # schema15. Testing the plan-carrier seam does not qualify schema17 review.
    library = EngineeringLibrary.create((tmp_path / 'declared-review.sqlite').resolve(),
        library_id='declared-review-assembly', schema_version=15)
    try:
        factory = SQLiteUoWFactory(library)
        owner = runtime.unit_execution_owner
        seen = {}

        def no_author(*_args):
            raise AssertionError('Assembly must not select an author Unit')

        def no_invocation(*_args, **_kwargs):
            raise AssertionError('Assembly must not start or query a native invocation')

        def selected_ports(actual_factory, _access, _scope, **_owners):
            assert actual_factory is factory
            if selection == 'source_callable':
                def plans(*_args, **_kwargs):
                    raise AssertionError('Assembly must not request a source plan')
            elif selection in {'missing_producer', 'direct_missing_producer'}:
                plans = object()
            else:
                plans = _ReportOnlyPlans(object() if selection in {
                    'foreign_factory', 'direct_foreign_factory'} else actual_factory)
            seen['plans'] = plans
            return EngineeringApplicationPorts(review_plan_factory=plans, review_run=no_invocation)

        construct = method_unit_application_ports_factory(
            unit_owner=owner, proposal_ref=None, phases=None,
            author_unit_resolver=no_author, invocation_resolver=no_invocation,
            unit_query_factory=no_invocation, base_ports_factory=selected_ports)

        def ports_factory(actual_factory, access, scope):
            assert actual_factory is factory
            if selection.startswith('direct_'):
                # Wire independently checks trusted direct port factories too.
                return selected_ports(actual_factory, access, scope)
            return construct(actual_factory, access, scope)

        if selection in {'foreign_factory', 'missing_producer',
                         'direct_foreign_factory', 'direct_missing_producer'}:
            with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
                EngineeringWireBinding(factory, runtime.wire.identity_authority,
                    scope=owner.permission.scope, application_ports_factory=ports_factory)
        else:
            binding = EngineeringWireBinding(factory, runtime.wire.identity_authority,
                scope=owner.permission.scope, application_ports_factory=ports_factory)
            assert binding.service._implementation_results.plans is seen['plans']
            assert binding.service._review_change_steps.runnable is (selection == 'source_callable')
            # No declared submission bindings/runner were produced by these
            # assembly-only peers. Merely accepting a port must not enable it.
            assert binding.service._implementation_results.runnable is False
            assert 'independently-review-report' not in binding.service._work_step_capabilities()
    finally:
        library.close()
        if runtime.stop_state == 'idle':
            runtime.stop()
