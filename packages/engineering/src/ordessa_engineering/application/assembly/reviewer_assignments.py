"""Build the original reviewer-assignment use cases from selected owner ports."""
from ..usecases.reviews.assignments import ReviewerAssignmentUseCases


def build_reviewer_assignment_usecases(factory, *, method_control, records,
                                      expected_access, expected_scope,
                                      unit_query_factory, author_unit_resolver=None,
                                      authorship_source=None):
    return ReviewerAssignmentUseCases(factory, method_control, records,
        expected_access=expected_access, expected_scope=expected_scope,
        unit_query_factory=unit_query_factory,
        author_unit_resolver=author_unit_resolver,authorship_source=authorship_source)


__all__ = ["build_reviewer_assignment_usecases"]
