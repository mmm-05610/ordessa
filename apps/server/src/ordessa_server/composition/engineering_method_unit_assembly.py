"""Bind Engineering's original Work/review readers to the selected Unit owner.

This is trusted product assembly only. It selects no method, phase, Unit,
reviewer, invocation, grant, publication, or effect.
"""
from dataclasses import replace

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.application.api import ApplicationError
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_units.assembly import LocalUnitOwner, UnitRunPermission

from .engineering_review_assembly import build_engineering_review_ports
from .engineering_work_assembly import (
    admitted_dispatch_query_factory, build_engineering_work_bindings,
    original_dispatch_query_factory,
)
from .engineering_submission_assembly import attach_method_unit_submission_ports
from .engineering_admission import assemble_engineering_admission
from .engineering_method_management import OriginalMethodManagement


def method_unit_application_ports_factory(
    *,
    unit_owner,
    proposal_ref,
    phases,
    phase_bindings=(),
    author_unit_resolver,
    invocation_resolver,
    unit_query_factory,
    execution_query_factory=None,
    execution_request_factory=None,
    base_ports_factory=None,
    confirmation_options=None,
    material_submissions=(),
    report_phase_key=None,
    runtime=None,
    dispatch_prompt_parameters=None,
    workspace_scope_guard=None,
):
    """Return the trusted `(factory, access, scope)` application-port factory.

    `unit_owner` and callbacks come only from trusted product composition. If a
    base factory is supplied, it receives the already selected original graph:
    `(factory, access, scope, *, method_control, blobs, method_run_bindings)`.
    It may contribute report/dispatch ports, but cannot replace this graph.
    """
    if (not callable(author_unit_resolver)
            or not callable(invocation_resolver)
            or not callable(unit_query_factory)):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if base_ports_factory is not None and not callable(base_ports_factory):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
    if (workspace_scope_guard is not None
            and (not callable(workspace_scope_guard)
                 or dispatch_prompt_parameters is None)):
        raise ApplicationError('DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE')
    if type(unit_owner) is not LocalUnitOwner:
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if type(phase_bindings) is not tuple:
        raise ApplicationError("WORK_SOURCE_BINDING_INVALID")
    if type(material_submissions) is not tuple:
        raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
    if report_phase_key is not None and (
            type(report_phase_key) is not str or not report_phase_key):
        raise ApplicationError("SUBMISSION_REPORT_AUTHORITY_MISMATCH")
    if dispatch_prompt_parameters is not None:
        if (not callable(dispatch_prompt_parameters)
                or execution_request_factory is not None
                or execution_query_factory is not None
                or report_phase_key is None):
            raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
        if runtime is None:
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
    if execution_request_factory is not None:
        if (not callable(execution_request_factory)
                or execution_query_factory is not None):
            raise ApplicationError('WORK_NATIVE_SOURCE_UNAVAILABLE')
    if confirmation_options is not None:
        if (type(confirmation_options) is not dict
                or not {'policy_bytes', 'policy_ref', 'conversation_locator'}
                    <= set(confirmation_options)
                or set(confirmation_options) - {'policy_bytes', 'policy_ref',
                    'conversation_locator', 'intent_guard_factory', 'presentation_binding'}):
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        confirmation_options = dict(confirmation_options)

    def construct(factory, access, scope):
        permission = getattr(unit_owner, "permission", None)
        if (type(access) is not EngineeringCommandAccess
                or type(permission) is not UnitRunPermission
                or type(scope) is not WireScope
                or getattr(access, "authority", None) is not permission.access_authority
                or (permission.scope.realm_id, permission.scope.project_id)
                    != (scope.realm_id, scope.project_id)):
            raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
        try:
            access.authority.verify(permission.principal)
            records = unit_owner.records
        except Exception as error:
            raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE") from error
        if records is None:
            raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")
        query_factory = execution_query_factory
        dispatch_selection = dispatch_sources = None
        if dispatch_prompt_parameters is not None:
            if (getattr(runtime, "unit_execution_owner", None) is not unit_owner
                    or getattr(runtime, "units", None) is not unit_owner.manager
                    or getattr(unit_owner, "acp_turn_opt_in", None) is not True):
                raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
            from ordessa_engineering.adapters.native_records import build_local_dispatch_bindings
            dispatch_selection, dispatch_sources, query_factory = build_local_dispatch_bindings(
                unit_owner, access, prompt_parameters=dispatch_prompt_parameters,
                workspace_scope_guard=workspace_scope_guard)
        elif execution_request_factory is not None:
            query_factory = original_dispatch_query_factory(
                unit_owner, records=records,
                request_factory=execution_request_factory)
        elif query_factory is None and report_phase_key is not None:
            query_factory = admitted_dispatch_query_factory(
                unit_owner, access, records=records)

        library = getattr(factory, "library", None)
        if library is None:
            raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
        snapshots = SQLiteSnapshotStore(library)
        methods = SQLiteMethodControl(factory, snapshots)
        blobs = SQLiteBlobStore(library)
        review_ports = build_engineering_review_ports(
            factory, access, scope, unit_owner=unit_owner,
            method_control=methods, blobs=blobs, proposal_ref=proposal_ref,
            phases=phases, author_unit_resolver=author_unit_resolver,
            invocation_resolver=invocation_resolver,
            unit_query_factory=unit_query_factory,
            material_submissions=material_submissions,
        )
        review_admission = review_ports.review_admission
        review_bindings = review_admission.bindings
        assignments = review_ports.reviewer_assignments
        method_run_bindings = build_engineering_work_bindings(
            factory, access, scope, method_control=methods, blobs=blobs,
            review_bindings=review_bindings, phase_bindings=phase_bindings,
            records=records if query_factory is not None else None,
            execution_query_factory=query_factory,
        )

        base_ports = EngineeringApplicationPorts()
        if confirmation_options is not None:
            original_action = assemble_engineering_admission(
                factory, access, scope,
                management=OriginalMethodManagement(access, scope),
                bindings=review_bindings,
                reviewer_source=review_admission.source,
                method_control=methods, blobs=blobs,
                review_admission=review_admission,
                **confirmation_options,
            )
            base_ports = original_action.application_ports
        if base_ports_factory is not None:
            selected_base = base_ports_factory(
                factory, access, scope, method_control=methods,
                blobs=blobs, method_run_bindings=method_run_bindings,
            )
            if type(selected_base) is not EngineeringApplicationPorts:
                raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
            if (selected_base.review_run is not None
                    and not callable(selected_base.review_run)):
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
            selected_plan = selected_base.review_plan_factory
            declared_plan = callable(getattr(selected_plan, 'implementation_plan', None))
            if (selected_plan is not None and (
                    not callable(selected_plan) and not declared_plan
                    or declared_plan and getattr(selected_plan, 'factory', None) is not factory)):
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
            if confirmation_options is not None:
                if (selected_base.conversation_admission is not None
                        and selected_base.conversation_admission
                            is not base_ports.conversation_admission):
                    raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
                if (base_ports.acceptance_admission is not None
                        and selected_base.acceptance_admission is not None
                        and selected_base.acceptance_admission
                            is not base_ports.acceptance_admission):
                    raise ApplicationError('INTENT_ADMISSION_AUTHORITY_MISMATCH')
                selected_base = replace(selected_base,
                    conversation_admission=base_ports.conversation_admission,
                    acceptance_admission=(base_ports.acceptance_admission
                        if base_ports.acceptance_admission is not None
                        else selected_base.acceptance_admission))
            base_ports = selected_base
            if (base_ports.blobs is not None and base_ports.blobs is not blobs
                    or base_ports.current_wait_bindings is not None
                    and base_ports.current_wait_bindings is not method_run_bindings
                    or base_ports.reviewer_assignments is not None
                    and base_ports.reviewer_assignments is not assignments
                    or base_ports.execution_records is not None
                    and base_ports.execution_records is not records
                    or base_ports.execution_query_factory is not None
                    and base_ports.execution_query_factory is not query_factory):
                raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
        if dispatch_selection is not None:
            if base_ports.execution_dispatch_binder is not None:
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
            from .engineering_native_dispatch_assembly import bind_engineering_native_dispatch
            services = dispatch_selection.services

            def dispatch_binder(service):
                return bind_engineering_native_dispatch(
                    service, runtime, services=services, records=records, blobs=blobs,
                    query_factory=query_factory, selection=dispatch_selection,
                    source_snapshots=dispatch_sources, history_sources=dispatch_sources)

            base_ports = replace(base_ports, execution_dispatch_binder=dispatch_binder)
        if report_phase_key is not None:
            base_ports = attach_method_unit_submission_ports(
                base_ports, factory=factory, method_control=methods, blobs=blobs,
                method_runs=method_run_bindings,
                review_bindings=review_bindings, phase_key=report_phase_key,
                execution_records=records, execution_query_factory=query_factory,
            )
        return replace(
            base_ports,
            blobs=blobs,
            review_admission=review_admission,
            current_wait_bindings=method_run_bindings,
            reviewer_assignments=assignments,
        )

    return construct


__all__ = ["method_unit_application_ports_factory"]
