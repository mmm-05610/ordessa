"""Narrow source-review ports the declared Work steps call.

The declared steps need two things this application layer must not construct
itself: the plan for exactly this Work's pinned sources, and the native review
run. Both owners live outside (the plan factory is assembled by the composition
over the existing decision bindings; the run is the existing reviewer source).
The steps receive them as ports and never import an adapter.
"""

from typing import Any, Callable, Protocol, runtime_checkable

from ordessa_engineering.domain.reviews.models import ReviewPlan


@runtime_checkable
class DeclaredSourcePlanFactory(Protocol):
    """Build the released plan for one Work, from that Work's pinned sources."""

    def __call__(self, context, binding, *, review_id: str,
                 baseline, candidate) -> ReviewPlan: ...


DeclaredReviewRun = Callable[[Any, ReviewPlan, Any], Any]
"""`(context, plan, request) -> raw_response_ref`; the existing reviewer source."""

__all__ = ["DeclaredSourcePlanFactory", "DeclaredReviewRun"]
