"""Public Engineering command/query gate and its request contracts.

Applications construct this service through ``application.assembly``. Request
callers supply an admitted context, an operation and its explicit parameters;
they do not choose source, reviewer, persistence or execution implementations.
"""
from .service import EngineeringService, SUPPORTED_COMMANDS, SUPPORTED_QUERIES
from ..contracts.commands import CommandContext, CommandResult, ReadSet
from ..contracts.method_work import (
    WorkReviewSelector, decode_work_review_selector, work_review_selector_projection,
)
from ..contracts.run_waits import ReviewReadiness, ReviewReadinessBindings
from ..contracts.snapshots import ResolvedReviewMaterial
from ..contracts.execution_dispatch import EXECUTION_DISPATCH
from ..contracts.errors import ApplicationError
from ..contracts.mixed_reviews import MixedReviewerAuthorityPort
from ...domain.changes.dispatch import DispatchBinding
from ...domain.common.models.refs import BlobRef
from ..orchestration.check_capabilities import bound_review_check_capabilities
from ..contracts.unit_review import (
    UnitReviewBinding, UnitReviewBindingResolver, UnitReviewerAuthority, NativeReviewInvocation,
)
from ..usecases.owner_operations import OwnerOperationResult
from ...domain.reviews.assignments import ReviewerAssignmentRef
from ..usecases.reviews.assignments import ASSIGN_REVIEWER, REVOKE_REVIEWER
from ..contracts.profile_selection import ProfileSelectionSource, ProfileChoicePort, ProfileUnitPort
from ..orchestration.profile_selection import select_method_profile, select_and_create_method_unit

__all__ = ["EngineeringService", "SUPPORTED_COMMANDS", "SUPPORTED_QUERIES", "CommandContext",
           "CommandResult", "ReadSet", "WorkReviewSelector", "decode_work_review_selector",
           "work_review_selector_projection", "EXECUTION_DISPATCH", "DispatchBinding", "BlobRef",
           "ApplicationError", "bound_review_check_capabilities",
           "OwnerOperationResult", "UnitReviewBinding", "UnitReviewBindingResolver",
           "UnitReviewerAuthority", "NativeReviewInvocation", "MixedReviewerAuthorityPort",
           "ReviewerAssignmentRef", "ASSIGN_REVIEWER", "REVOKE_REVIEWER",
           "ReviewReadiness", "ReviewReadinessBindings", "ResolvedReviewMaterial",
           "ProfileSelectionSource", "ProfileChoicePort", "ProfileUnitPort",
           "select_method_profile", "select_and_create_method_unit"]
