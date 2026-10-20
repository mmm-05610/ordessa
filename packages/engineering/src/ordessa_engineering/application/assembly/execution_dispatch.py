"""Bind canonical native dispatch to one already-constructed Engineering service."""

from ..contracts.errors import ApplicationError
from ..contracts.execution_dispatch import ExecutionDispatchPort
from ..orchestration.steps.implementation_dispatch import ImplementationDispatch
from ..usecases.approvals.service import ApprovalUseCases
from ..usecases.changes.submissions import SubmissionUseCases
from ..usecases.owner_operations import EngineeringOwnerOperations
from ..usecases.packages.implementation import ImplementationUseCases
from ..usecases.changes.declared_report import DeclaredWorkReportSource
from ..api.service import EngineeringService


def _require_methods(owner, names, code):
    if owner is None or any(not callable(getattr(owner, name, None)) for name in names):
        raise ApplicationError(code)


def bind_execution_dispatch(
    service: EngineeringService,
    *,
    execution,
    selection,
    source_snapshots,
    history_sources,
    unit_ref_resolver=None,
    implementation_timeout=60,
    continuation_evidence=None,
    continuation_unit_resolver=None,
) -> ExecutionDispatchPort:
    """Attach the original owner-operation dispatcher once, before serving.

    This is trusted composition. It creates no use cases, authorities, stores,
    run state, or grants; the injected native execution ports retain their own
    owners and runtime guards.
    """
    if type(service) is not EngineeringService:
        raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
    if service._execution_dispatch is not None:
        raise ApplicationError("DISPATCH_ALREADY_BOUND")

    factory = service._factory
    access = service._access
    packages = service._packages
    submissions = service._submission_reports
    methods, materials = service._method_guard, service._source_materials
    records = service._execution_records
    blobs = service._blobs
    approvals = getattr(packages, "approvals", None)
    query_factory = service._execution_query_factory

    if (factory is None or access is None
            or not callable(getattr(factory, "begin", None))
            or not callable(getattr(access, "require", None))
            or type(packages) is not ImplementationUseCases
            or type(submissions) is not SubmissionUseCases
            or type(approvals) is not ApprovalUseCases):
        raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
    if (packages.factory is not factory or packages.access is not access
            or approvals.factory is not factory or approvals.access is not access
            or submissions.factory is not factory or submissions.access is not access
            or submissions.approvals is not approvals
            or getattr(methods, "factory", None) is not factory
            or any(not callable(getattr(methods, name, None))
                   for name in ("guard", "resource_ref", "read_resource"))
            or getattr(materials, "factory", None) is not factory
            or not callable(getattr(materials, "read", None))
            or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)
            or not callable(getattr(blobs, "read_verified", None))
            or not callable(getattr(blobs, "put_verified", None))
            or not callable(getattr(records, "acp_turn_query_digest", None))
            or not callable(getattr(records, "query_acp_turn", None))
            or not callable(query_factory)):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")

    _require_methods(access, ("handoff_effect_write", "consume_effect_write"),
                     "DISPATCH_EFFECT_AUTHORITY_UNAVAILABLE")
    _require_methods(execution, ("freeze_input", "query_digest", "guard_effect_handoff", "send", "capture"),
                     "DISPATCH_EXECUTION_UNAVAILABLE")
    if (getattr(execution, "records", None) is not records
            or getattr(execution, "query_factory", None) is not query_factory):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")
    _require_methods(selection, ("guard_work_selection", "guard_work_scope", "describe_work_profile"),
                     "DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE")
    # Continuation ports are optional, but when selected they must be the
    # original owners of THIS graph: the evidence reader over the same factory/
    # records/blobs, and a callable resolver that the server's own bootstrap
    # callback provides. Nothing is invented here and no default is applied.
    if continuation_evidence is not None and (
            service._continuation_evidence is not None
            or getattr(continuation_evidence, 'factory', None) is not factory
            or getattr(continuation_evidence, 'records', None) is not records
            or getattr(continuation_evidence, 'blobs', None) is not blobs
            or not callable(getattr(continuation_evidence, 'read_origin', None))):
        raise ApplicationError("CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE")
    if continuation_unit_resolver is not None and (
            service._continuation_unit_resolver is not None
            or not callable(continuation_unit_resolver)):
        raise ApplicationError("CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE")
    if (continuation_unit_resolver is not None) != (continuation_evidence is not None):
        # A resolver without its evidence reader (or the reverse) would let one
        # half of the continuation path run unverified.
        raise ApplicationError("CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE")

    dispatch = ImplementationDispatch(
        factory,
        access,
        approval_usecases=approvals,
        execution=execution,
        selection=selection,
        blobs=blobs,
        source_snapshots=source_snapshots,
        history_sources=history_sources,
        method_guard=service._method_guard,
        source_materials=service._source_materials,
    )
    owner = EngineeringOwnerOperations(
        factory,
        packages=packages,
        dispatch=dispatch,
        submissions=submissions,
        records=records,
        blobs=blobs,
        access=access,
        unit_ref_resolver=unit_ref_resolver,
        implementation_timeout=implementation_timeout,
    )
    if (owner.factory is not factory or owner.access is not access
            or owner.packages is not packages or owner.submissions is not submissions
            or owner.records is not records or owner.blobs is not blobs
            or owner.dispatch is not dispatch):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")

    report_source = submissions.report_source
    if report_source is None:
        report_source = DeclaredWorkReportSource(factory, methods, blobs)
    elif (type(report_source) is not DeclaredWorkReportSource
            or report_source.factory is not factory or report_source.methods is not methods
            or report_source.blobs is not blobs):
        raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')

    # Publish only after the entire original-owner graph has passed validation.
    submissions.report_source = report_source
    service._execution_dispatch = owner
    if continuation_evidence is not None:
        # The service reads these only through its own continuation flow; they
        # are the same-graph owners validated above, never a caller default.
        service._continuation_evidence = continuation_evidence
        service._continuation_unit_resolver = continuation_unit_resolver
    return owner


def bind_agent_execution_dispatch(service, *, execution, selection, agent_ref_resolver,
                                  implementation_timeout=60):
    """Bind only the explicit Agent v2 first-attempt Work owner.

    Original consent/review/control/method/UoW authorities remain the Service's
    exact owners. No Unit report, continuation or execution permission is made.
    The host must select the actual SDK adapter and external workspace fence.
    """
    if type(service) is not EngineeringService:
        raise ApplicationError('DISPATCH_AUTHORITY_MISMATCH')
    if service._execution_dispatch is not None:
        raise ApplicationError('DISPATCH_ALREADY_BOUND')
    factory, access = service._factory, service._access
    packages, submissions = service._packages, service._submission_reports
    methods, materials, blobs = service._method_guard, service._source_materials, service._blobs
    approvals = getattr(packages, 'approvals', None)
    records, query = service._execution_records, service._execution_query_factory
    if (factory is None or access is None or not callable(getattr(factory, 'begin', None))
            or not callable(getattr(access, 'require', None))
            or type(packages) is not ImplementationUseCases or type(submissions) is not SubmissionUseCases
            or type(approvals) is not ApprovalUseCases):
        raise ApplicationError('DISPATCH_AUTHORITY_MISMATCH')
    if (packages.factory is not factory or packages.access is not access
            or approvals.factory is not factory or approvals.access is not access
            or submissions.factory is not factory or submissions.access is not access
            or submissions.approvals is not approvals
            or getattr(methods, 'factory', None) is not factory
            or getattr(materials, 'factory', None) is not factory
            or not callable(getattr(materials, 'read', None))
            or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
            or getattr(execution, 'blobs', None) is not blobs
            or getattr(execution, 'records', None) is not records
            or getattr(records, 'blob_store', None) is not blobs
            or getattr(execution, 'query_factory', None) is not query or not callable(query)
            or not callable(agent_ref_resolver)
            or type(implementation_timeout) not in (int,float) or not 0 < implementation_timeout <= 60):
        raise ApplicationError('DISPATCH_OWNER_BINDING_MISMATCH')
    _require_methods(methods, ('guard','resource_ref','read_resource'), 'DISPATCH_WORK_INPUT_AUTHORITY_UNAVAILABLE')
    _require_methods(blobs, ('read_verified','put_verified'), 'DISPATCH_OWNER_BINDING_MISMATCH')
    _require_methods(access, ('handoff_effect_write','consume_effect_write'), 'DISPATCH_EFFECT_AUTHORITY_UNAVAILABLE')
    _require_methods(execution, ('freeze_input','prepared_dispatch','send','capture'), 'DISPATCH_EXECUTION_UNAVAILABLE')
    _require_methods(records, ('capture_dispatch','read_agent_reference'), 'DISPATCH_EXECUTION_UNAVAILABLE')
    _require_methods(selection, ('guard_work_selection','guard_work_scope','describe_work_profile'),
                     'DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
    if getattr(selection, 'work_scope_ready', False) is not True:
        raise ApplicationError('DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE')
    dispatch = ImplementationDispatch(factory, access, approval_usecases=approvals,
        execution=execution, selection=selection, blobs=blobs,
        method_guard=methods, source_materials=materials)
    owner = EngineeringOwnerOperations(factory, packages=packages, dispatch=dispatch,
        submissions=submissions, records=records, blobs=blobs, access=access,
        agent_ref_resolver=agent_ref_resolver, implementation_timeout=implementation_timeout)
    from ..usecases.changes.agent_declared_report import DeclaredAgentWorkReportSource
    report_source = submissions.report_source
    if report_source is None:
        report_source = DeclaredAgentWorkReportSource(factory, methods, blobs, records, query)
    elif (type(report_source) is not DeclaredAgentWorkReportSource or report_source.factory is not factory
            or report_source.methods is not methods or report_source.blobs is not blobs
            or report_source.records is not records or report_source.query_factory is not query):
        raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
    # Both explicit Agent owners are published only after the entire graph is
    # validated. Continuation retains its separate, unavailable new contract.
    submissions.report_source = report_source
    service._execution_dispatch = owner
    return owner
