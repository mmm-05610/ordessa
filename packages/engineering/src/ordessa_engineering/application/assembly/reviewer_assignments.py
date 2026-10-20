"""Build the original reviewer-assignment use cases from selected owner ports."""
from ..usecases.reviews.assignments import ReviewerAssignmentUseCases


def build_reviewer_assignment_usecases(factory, *, method_control, records,
                                      expected_access, expected_scope,
                                      agent_query_factory, author_agent_resolver=None,
                                      author_identity_resolver=None,
                                      authorship_source=None):
    return ReviewerAssignmentUseCases(factory, method_control, records,
        expected_access=expected_access, expected_scope=expected_scope,
        agent_query_factory=agent_query_factory,
        author_agent_resolver=author_agent_resolver,
        author_identity_resolver=author_identity_resolver,
        authorship_source=authorship_source)


__all__ = ["build_reviewer_assignment_usecases"]
