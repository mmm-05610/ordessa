"""Resolve supported exact identities through public repositories in one UoW.

This is not the missing E5 ResolvedRefGraph: it does not invent approvals,
submissions or repository-baseline authorities, nor reinterpret latest heads.
"""
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef, SubmissionRef)
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.consent import NoticeRef
from ordessa_engineering.application.contracts.errors import ApplicationError


def resolve_exact(uow, ref):
    if type(ref) is NoticeRef:
        if ref.scope != uow.scope:
            raise ApplicationError("SCOPE_MISMATCH")
        return uow.authorization.get_notice(ref)
    if type(ref) not in (ArtifactRevisionRef, ProposalRef, ReviewRef, ApprovalRef, SubmissionRef, RepositorySnapshotRef, ImplementationPackageRef):
        raise ApplicationError("REFERENCE_OWNER_UNAVAILABLE")
    if (ref.realm_id, ref.project_id) != (uow.scope.realm_id, uow.scope.project_id):
        raise ApplicationError("SCOPE_MISMATCH")
    if type(ref) is ArtifactRevisionRef:
        return uow.engineering.resolve_revision(ref)
    if type(ref) is ProposalRef:
        return uow.proposals.get_proposal(ref)
    if type(ref) is ApprovalRef:
        return uow.authorization.get_grant(ref)
    if type(ref) is SubmissionRef:
        try:
            repository = uow.submissions
        except ApplicationError as exc:
            if exc.code == 'SUBMISSION_SCHEMA_REQUIRED':
                raise ApplicationError('REFERENCE_OWNER_UNAVAILABLE') from exc
            raise
        return repository.resolve(ref)
    if type(ref) is RepositorySnapshotRef:
        return uow.implementation.resolve_repository_baseline(ref)
    if type(ref) is ImplementationPackageRef:
        return uow.implementation.resolve_package(ref)
    return uow.reviews.get_review(ref)
