"""Bind canonical native dispatch to one already-constructed Engineering service."""

from ..contracts.errors import ApplicationError
from ..contracts.execution_dispatch import ExecutionDispatchPort
from ..orchestration.method_runs import MethodRunBindings, MethodRunOrchestrator
from ..orchestration.steps.implementation_dispatch import ImplementationDispatch
from ..usecases.approvals.service import ApprovalUseCases
from ..usecases.changes.submissions import SubmissionUseCases
from ..usecases.owner_operations import EngineeringOwnerOperations
from ..usecases.packages.implementation import ImplementationUseCases
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
    work = service._work
    bindings = getattr(work, "bindings", None)
    records = service._execution_records
    blobs = service._blobs
    approvals = getattr(packages, "approvals", None)
    query_factory = service._execution_query_factory

    if (factory is None or access is None
            or not callable(getattr(factory, "begin", None))
            or not callable(getattr(access, "require", None))
            or type(packages) is not ImplementationUseCases
            or type(submissions) is not SubmissionUseCases
            or type(work) is not MethodRunOrchestrator
            or type(bindings) is not MethodRunBindings
            or type(approvals) is not ApprovalUseCases):
        raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
    if (packages.factory is not factory or packages.access is not access
            or approvals.factory is not factory or approvals.access is not access
            or submissions.factory is not factory or submissions.access is not access
            or submissions.approvals is not approvals
            or submissions.method_runs is not bindings
            or bindings.factory is not factory
            or getattr(bindings.methods, "factory", None) is not factory
            or any(not callable(getattr(bindings.methods, name, None))
                   for name in ("guard_method", "guard_selected"))
            or getattr(bindings.source, "factory", None) is not factory
            or any(not callable(getattr(bindings.source, name, None))
                   for name in ("guard_start", "guard_condition", "guard_step_completion"))
            or not callable(bindings.registry_loader)
            or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)
            or not callable(getattr(blobs, "read_verified", None))
            or not callable(getattr(blobs, "put_verified", None))
            or not callable(getattr(records, "acp_turn_query_digest", None))
            or not callable(getattr(records, "query_acp_turn", None))
            or not callable(query_factory)):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")

    _require_methods(execution, ("freeze_input", "query_digest", "send", "capture"),
                     "DISPATCH_EXECUTION_UNAVAILABLE")
    if (getattr(execution, "records", None) is not records
            or getattr(execution, "query_factory", None) is not query_factory):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")
    _require_methods(selection, ("guard_selection",), "DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE")
    _require_methods(source_snapshots, ("guard_commit_snapshot",),
                     "DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE")
    _require_methods(history_sources, ("guard_history_read",),
                     "DISPATCH_HISTORY_SOURCE_AUTHORITY_UNAVAILABLE")

    dispatch = ImplementationDispatch(
        factory,
        access,
        approval_usecases=approvals,
        execution=execution,
        selection=selection,
        blobs=blobs,
        registry_loader=bindings.registry_loader,
        source_snapshots=source_snapshots,
        history_sources=history_sources,
        method_runs=bindings,
    )
    owner = EngineeringOwnerOperations(
        factory,
        packages=packages,
        dispatch=dispatch,
        submissions=submissions,
        records=records,
        blobs=blobs,
        access=access,
    )
    if (owner.factory is not factory or owner.access is not access
            or owner.packages is not packages or owner.submissions is not submissions
            or owner.records is not records or owner.blobs is not blobs
            or owner.dispatch is not dispatch):
        raise ApplicationError("DISPATCH_OWNER_BINDING_MISMATCH")

    # Publish only after the entire original-owner graph has passed validation.
    service._execution_dispatch = owner
    return owner
