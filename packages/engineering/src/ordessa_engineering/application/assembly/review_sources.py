"""Compose the real check sources for one selected Engineering review owner."""

from ..contracts.errors import ApplicationError
from ..orchestration.check_capabilities import (
    bound_review_check_capabilities,
    invariant_review_check_capabilities,
    mechanical_review_check_capabilities,
)
from ..orchestration.decision_checks import GenericDecisionCheckSource, generic_decision_check_capability
from ..orchestration.unit_review import UnitReviewCheckSource
from ..usecases.reviews.admission import EngineeringReviewAdmission
from ..usecases.reviews.invariants import DeclaredInvariantReviewCheckSource
from ..usecases.reviews.mechanical import MechanicalReviewCheckSource
from ..usecases.reviews.mixed import MixedReviewerSource


def _require_methods(value, names, code):
    if value is None or any(not callable(getattr(value, name, None)) for name in names):
        raise ApplicationError(code)


def build_review_check_admission(
    factory,
    *,
    method_control,
    blobs,
    review_bindings,
    records,
    unit_review_bindings,
    unit_reviewer_authority,
    composite_reviewer_authority,
    expected_access,
    expected_scope,
) -> EngineeringReviewAdmission:
    """Build the original admission over exact typed check-source owners.

    This performs assembly association checks only. Current access, source,
    proof, reviewer and commit guards remain with their original authorities.
    """
    _require_methods(factory, ("begin",), "REVIEW_SOURCE_AUTHORITY_MISMATCH")
    _require_methods(method_control, ("guard_method",), "REVIEW_SOURCE_AUTHORITY_MISMATCH")
    _require_methods(blobs, ("read_verified", "put_verified"), "REVIEW_SOURCE_AUTHORITY_MISMATCH")
    _require_methods(review_bindings, ("resolve_bindings",), "REVIEW_SOURCE_AUTHORITY_MISMATCH")
    _require_methods(records, ("acp_turn_query_digest", "query_acp_turn"),
                     "UNIT_REVIEW_SOURCE_UNAVAILABLE")
    _require_methods(unit_review_bindings,
                     ("resolve_unit_review", "decode_response", "resolve_record_request"),
                     "UNIT_REVIEW_SOURCE_UNAVAILABLE")
    _require_methods(unit_reviewer_authority, ("guard_unit_reviewer",),
                     "UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE")
    _require_methods(composite_reviewer_authority, ("guard_verification",),
                     "MIXED_REVIEWER_AUTHORITY_UNAVAILABLE")

    if (getattr(method_control, "factory", None) is not factory
            or getattr(blobs, "authority_id", None) != getattr(factory, "authority_id", None)):
        raise ApplicationError("REVIEW_SOURCE_AUTHORITY_MISMATCH")

    mechanical = MechanicalReviewCheckSource(factory, method_control, blobs)
    invariants = DeclaredInvariantReviewCheckSource(factory, method_control, blobs)
    unit = UnitReviewCheckSource(factory, method_control, records, blobs,
        bindings=unit_review_bindings, reviewer_authority=unit_reviewer_authority)
    decision = GenericDecisionCheckSource(unit)

    sources = {
        "mechanical": mechanical,
        "invariants": invariants,
        "decision": decision,
    }
    descriptors = (
        mechanical_review_check_capabilities().capabilities
        + invariant_review_check_capabilities().capabilities
        + (generic_decision_check_capability(),)
    )
    mapping = {}
    for descriptor in descriptors:
        if descriptor.capability_id in {"ordessa.sources.integrity", "ordessa.claims.coverage"}:
            source_id = "mechanical"
        elif descriptor.capability_id in {"ordessa.schema.validate", "ordessa.submission.binding"}:
            source_id = "invariants"
        else:
            source_id = "decision"
        mapping[(descriptor.capability_id, descriptor.interface_version)] = source_id

    mixed = MixedReviewerSource(factory, method_control, blobs, sources=sources,
        source_for_capability=mapping, reviewer_authority=composite_reviewer_authority)
    admission = EngineeringReviewAdmission(factory, method_control, review_bindings, mixed)
    bound_review_check_capabilities(admission, expected_factory=factory,
        expected_access=expected_access, expected_scope=expected_scope)
    return admission
