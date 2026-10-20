"""Bind Engineering Work reads to the selected original Unit owner.

This module creates no Unit, records owner, manager, Engineering service,
method catalog, or permission. It only wires the already selected objects.
"""
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.application.assembly import build_method_run_bindings
from ordessa_engineering.application.api import ApplicationError, DispatchBinding
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_units.assembly import LocalUnitOwner
from ordessa_units.records import UnitRecords


def build_engineering_work_bindings(
        factory, access, scope, *, method_control, blobs, review_bindings,
        phase_bindings=(), records=None, execution_query_factory=None):
    """Build the original Work source and its run bindings exactly once.

    Callers pass the same objects already used by the Engineering review and
    report assembly. Native reads are enabled only when both original records
    and their actual query-authority callback are present.
    """
    if (type(access) is not EngineeringCommandAccess or type(scope) is not WireScope
            or (records is None) != (execution_query_factory is None)):
        raise ApplicationError("WORK_SOURCE_AUTHORITY_MISMATCH")
    from ordessa_engineering.adapters.registry import load_registry
    work_source = SQLitePersistedMethodWorkSource(
        factory, method_control, phase_bindings=phase_bindings, blobs=blobs,
        review_bindings=review_bindings, execution_records=records,
        execution_query_factory=execution_query_factory,
    )
    return build_method_run_bindings(
        factory, method_control=method_control,
        work_condition_source=work_source, registry_loader=load_registry,
    )


def original_dispatch_query_factory(unit_owner, *, request_factory, records=None):
    """Return a query callback over one selected LocalUnitOwner and UnitRecords.

    The trusted root supplies a RequestKey from the actual incoming operation;
    this callback will not derive one from the dispatch operation or digest.
    UnitRecords recomputes the original query digest before the owner issues
    its read-only invocation. The callback never creates a Unit or queries
    records directly.
    """
    if type(unit_owner) is not LocalUnitOwner or not callable(request_factory):
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
    if getattr(unit_owner, "acp_turn_opt_in", None) is not True:
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
    try:
        original_records = unit_owner.records
    except Exception as error:
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE") from error
    if (type(original_records) is not UnitRecords
            or records is not None and records is not original_records
            or original_records.acp_turn_available is not True
            or original_records.journal.acp_turn_opt_in is not True
            or not callable(getattr(unit_owner, "authorize_acp_turn_query", None))
            or not callable(getattr(unit_owner, "authorization", None))):
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")

    def query(binding):
        if type(binding) is not DispatchBinding:
            raise ApplicationError("WORK_NATIVE_BINDING_INVALID")
        try:
            unit_ref = decode_json(binding.unit_ref_bytes)
            expected_prompt_digest = "sha256:" + binding.prompt_input_digest.hex
            request = request_factory(binding)
            if (type(request) is not RequestKey
                    or request.environment_namespace != unit_owner.admission.environment_namespace
                    or request.principal_scope != unit_owner.permission.principal_scope):
                raise ValueError("actual selected request identity required")
            expected_query_digest = original_records.acp_turn_query_digest(
                unit_ref, binding.execution_operation_ref, expected_prompt_digest)
        except ApplicationError:
            # A trusted request-context producer's refusal is meaningful
            # admission evidence. Do not disguise it as malformed binding.
            raise
        except Exception as error:
            raise ApplicationError("WORK_NATIVE_BINDING_INVALID") from error
        if expected_query_digest != binding.expected_query_digest:
            raise ApplicationError("WORK_NATIVE_BINDING_MISMATCH")
        if unit_ref.get("environmentNamespace") != unit_owner.admission.environment_namespace:
            raise ApplicationError("WORK_NATIVE_BINDING_MISMATCH")
        try:
            invocation = unit_owner.authorize_acp_turn_query(
                unit_owner.authorization(), request, unit_ref,
                binding.execution_operation_ref,
                expected_prompt_input_digest=expected_prompt_digest,
            )
        except Exception as error:
            raise ApplicationError("WORK_NATIVE_QUERY_REFUSED") from error
        facts = getattr(invocation, "facts", None)
        if (invocation is None or not hasattr(facts, "get")
                or facts.get("inputDigest") != expected_query_digest):
            raise ApplicationError("WORK_NATIVE_QUERY_INVALID")
        return invocation

    return query


def admitted_dispatch_query_factory(unit_owner, access, *, records=None):
    """Derive the native read key from the currently admitted real request.

    This binds a read to the exact Server admission context. It never invents
    a request suffix or accepts a caller-supplied principal/request key.
    """
    if (type(unit_owner) is not LocalUnitOwner
            or type(access) is not EngineeringCommandAccess
            or getattr(access, "authority", None)
                is not getattr(getattr(unit_owner, "permission", None),
                               "access_authority", None)):
        raise ApplicationError("WORK_NATIVE_SOURCE_UNAVAILABLE")
    permission = unit_owner.permission

    def request_for(binding):
        try:
            context = access.current_context()
            if (type(binding) is not DispatchBinding
                    or binding.scope != context.scope
                    or (context.scope.realm_id, context.scope.project_id)
                        != (permission.scope.realm_id, permission.scope.project_id)):
                raise ApplicationError("WORK_NATIVE_BINDING_MISMATCH")
            return RequestKey(
                unit_owner.admission.environment_namespace,
                permission.principal_scope,
                context.request_id,
            )
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError("WORK_NATIVE_BINDING_INVALID") from error

    return original_dispatch_query_factory(
        unit_owner, request_factory=request_for, records=records)


def original_submission_author_unit_resolver(
        factory, unit_owner, submission_ref, *, review_bindings,
        unit_query_factory, records=None):
    """Resolve a post-execution author from its exact persisted Submission.

    This only supports the acceptance review of the exact submission selected
    by trusted composition. Proposal/source reviews have no persisted Unit
    association and are refused; ActorRef is never translated into a UnitRef.
    """
    if type(unit_owner) is not LocalUnitOwner:
        raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
    if getattr(submission_ref, "kind", None) != "submission":
        raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
    try:
        original_records = unit_owner.records
    except Exception as error:
        raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE") from error
    if (type(original_records) is not UnitRecords
            or records is not None and records is not original_records
            or getattr(review_bindings, "factory", None) is not factory
            or not callable(getattr(review_bindings, "resolve_review_submission", None))
            or not callable(unit_query_factory)):
        raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")

    def resolve(context, plan):
        try:
            requirement = plan.requirement
            if (plan.scope != context.scope or requirement.scope != context.scope
                    or requirement.purpose != "acceptance"):
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            selected_ref = review_bindings.resolve_review_submission(
                context, requirement.method_ref, requirement.phase_key)
            if selected_ref is None or selected_ref != submission_ref:
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            with factory.begin(context.scope, "read") as uow:
                request = uow.reviews.get_request(plan.review_id)
                submission = uow.submissions.resolve(submission_ref)
            if submission.ref != submission_ref or submission.scope != context.scope:
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            execution = submission.execution_ref
            unit_ref = {
                "environmentNamespace": execution.environment_namespace,
                "unitId": execution.unit_id,
                "ownerProviderRef": decode_json(execution.owner_provider_ref_bytes),
                "sourceRevision": execution.source_revision,
            }
            if unit_ref["environmentNamespace"] != unit_owner.admission.environment_namespace:
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            query = unit_query_factory(context, unit_ref, plan, request, purpose="author")
            if type(query) is not tuple or len(query) != 2:
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            invocation, input_digest = query
            original = original_records.resolve_unit_reference(
                unit_ref, invocation, input_digest=input_digest)
            if canonical_bytes(original.public_ref) != canonical_bytes(unit_ref):
                raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            return unit_ref
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE") from error

    return resolve


__all__ = [
    "build_engineering_work_bindings",
    "original_submission_author_unit_resolver",
    "original_dispatch_query_factory",
    "admitted_dispatch_query_factory",
]
