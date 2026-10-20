"""Build original Engineering review ports over one selected Unit owner."""

from ordessa_engineering.adapters.review_sources import (
    ConfiguredMaterialSubmission,
    SQLiteReviewAuthorshipSource,
    SQLiteReviewBindings,
    SQLiteUnitReviewBindings,
    SQLiteUnitReviewerAuthority,
)
from ordessa_engineering.application.assembly import (
    build_review_check_admission,
    build_reviewer_assignment_usecases,
)
from ordessa_engineering.application.api import ApplicationError
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
from ordessa_units.assembly import LocalUnitOwner, UnitRunPermission

from .engineering_mixed_review import OriginalCompositeReviewerAuthority


def build_engineering_review_ports(
    factory,
    access,
    scope,
    *,
    unit_owner,
    method_control,
    blobs,
    proposal_ref,
    phases,
    author_unit_resolver,
    invocation_resolver,
    unit_query_factory,
    material_submissions=(),
):
    """Create the original review/assignment owners on the selected graph.

    All owner objects and resolvers are trusted composition inputs. This does
    not select a Proposal/phase/reviewer, issue a Grant, invoke a Unit, or
    replace the Engineering Service.
    """
    if not all(callable(value) for value in (
            author_unit_resolver, invocation_resolver, unit_query_factory)):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if (type(material_submissions) is not tuple
            or any(type(item) is not ConfiguredMaterialSubmission
                   for item in material_submissions)):
        raise ApplicationError("REVIEW_AUTHOR_SOURCE_UNAVAILABLE")
    if (type(unit_owner) is not LocalUnitOwner
            or type(access) is not EngineeringCommandAccess
            or type(scope) is not WireScope
            or type(getattr(unit_owner, "permission", None)) is not UnitRunPermission):
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    if (getattr(method_control, "factory", None) is not factory
            or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)
            or getattr(unit_owner.permission, "access_authority", None)
                is not getattr(access, "authority", None)
            or (unit_owner.permission.scope.realm_id, unit_owner.permission.scope.project_id)
                != (scope.realm_id, scope.project_id)):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")
    try:
        access.authority.verify(unit_owner.permission.principal)
        records = unit_owner.records
    except Exception as error:
        raise ApplicationError("UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE") from error
    if records is None:
        raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")

    owner_scope = access.owner_scope(scope)
    review_bindings = SQLiteReviewBindings(
        factory, method_control, scope=owner_scope,
        proposal_ref=proposal_ref, phases=phases,
    )
    authorship_source = SQLiteReviewAuthorshipSource(
        factory, method_control, review_bindings=review_bindings,
        material_submissions=material_submissions,
    )
    assignments = build_reviewer_assignment_usecases(
        factory, method_control=method_control, records=records,
        expected_access=access, expected_scope=scope,
        unit_query_factory=unit_query_factory,
        author_unit_resolver=author_unit_resolver,
        authorship_source=authorship_source,
    )
    unit_review_bindings = SQLiteUnitReviewBindings(
        factory, method_control, records, review_bindings=review_bindings,
        invocation_resolver=invocation_resolver,
        author_unit_resolver=author_unit_resolver,
        authorship_source=authorship_source,
    )
    unit_reviewer_authority = SQLiteUnitReviewerAuthority(
        factory, expected_access=access, expected_scope=scope,
        assignments=assignments, method_control=method_control,
        unit_records=records, unit_query_factory=unit_query_factory,
        author_unit_resolver=author_unit_resolver,
        authorship_source=authorship_source,
    )
    composite_reviewer_authority = OriginalCompositeReviewerAuthority(
        access, scope=scope, principal_id=access.authority.principal_id,
        roles=("reviewer",),
    )
    admission = build_review_check_admission(
        factory, method_control=method_control, blobs=blobs,
        review_bindings=review_bindings, records=records,
        unit_review_bindings=unit_review_bindings,
        unit_reviewer_authority=unit_reviewer_authority,
        composite_reviewer_authority=composite_reviewer_authority,
        expected_access=access, expected_scope=scope,
    )
    return EngineeringApplicationPorts(
        blobs=blobs,
        review_admission=admission,
        reviewer_assignments=assignments,
    )


__all__ = ["build_engineering_review_ports"]
