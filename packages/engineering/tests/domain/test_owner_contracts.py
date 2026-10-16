"""Closed business decoders and exact targets after common ownership migration."""
from dataclasses import asdict

import pytest

from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.artifacts.ref_codec import decode_artifact_ref
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.method_codec import decode_method_ref
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.baseline_codec import decode_repository_ref
from ordessa_engineering.domain.changes.errors import DomainError, DomainErrorCode
from ordessa_engineering.domain.reviews.refs import ReviewRef, SubmissionRef
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref, decode_target_set
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref


DIGEST = Digest('sha256', '0' * 64)
ARTIFACT = ArtifactRevisionRef('realm', 'project', 'artifact', 'revision', DIGEST)
PROPOSAL = ProposalRef('realm', 'project', 'change', 'proposal', DIGEST)
REVIEW = ReviewRef('realm', 'project', 'review', DIGEST)
APPROVAL = ApprovalRef('realm', 'project', 'approval', DIGEST)
SUBMISSION = SubmissionRef('realm', 'project', 'submission', DIGEST)
REPOSITORY = RepositorySnapshotRef('realm', 'project', 'repository', 'git',
                                   '0' * 40, DIGEST, None)
METHOD = MethodRef('method', 'release', 1, DIGEST)


@pytest.mark.parametrize('value,decode,code', (
    (ARTIFACT, decode_artifact_ref, 'INVALID_PARENT'),
    (PROPOSAL, decode_proposal_ref, 'INVALID_REVISION'),
    (REVIEW, decode_review_ref, 'INVALID_SCHEMA'),
    (APPROVAL, decode_approval_ref, 'INVALID_SCHEMA'),
    (REPOSITORY, decode_repository_ref, 'INVALID_REVISION'),
    (METHOD, decode_method_ref, 'INVALID_SCHEMA'),
))
def test_owner_decoder_roundtrip_and_exact_field_refusal(value, decode, code):
    wire = asdict(value)
    assert decode(wire) == value
    for bad in (None, [], {**wire, 'unexpected': 'field'}, {k: v for k, v in wire.items() if k != next(iter(wire))}):
        with pytest.raises(ReferenceError) as refused:
            decode(bad)
        assert refused.value.code == code


@pytest.mark.parametrize('value', (ARTIFACT, PROPOSAL, SUBMISSION, REPOSITORY))
def test_review_subject_union_remains_closed_and_roundtrips(value):
    wire = asdict(value)
    assert decode_subject_ref(wire) == value
    with pytest.raises(ReferenceError, match='INVALID_SCHEMA'):
        decode_subject_ref({**wire, 'kind': 'unregistered_business'})


@pytest.mark.parametrize('value', (REVIEW, APPROVAL, METHOD))
def test_existing_other_business_refs_do_not_become_review_subjects(value):
    with pytest.raises(ReferenceError, match='INVALID_SCHEMA'):
        decode_subject_ref(asdict(value))
    with pytest.raises(ReferenceError, match='INVALID_SCHEMA'):
        Target('primary', value)


def test_shared_shape_or_inheritance_never_admits_a_business_target_or_error_context():
    impostor = type(ArtifactRevisionRef.__name__, (),
                    {'__module__': ArtifactRevisionRef.__module__, **asdict(ARTIFACT)})()

    class DerivedArtifactRef(ArtifactRevisionRef):
        pass

    derived = DerivedArtifactRef('realm', 'project', 'artifact', 'revision', DIGEST)
    for value in (impostor, derived):
        with pytest.raises(ReferenceError, match='INVALID_SCHEMA'):
            Target('primary', value)
        with pytest.raises(ValueError, match='INVALID_DOMAIN_ERROR'):
            DomainError(DomainErrorCode.INVALID_SCHEMA, (value,))


def test_target_set_digest_and_scope_are_reverified_by_its_owner_decoder():
    targets = TargetSet((Target('primary', ARTIFACT), Target('support', PROPOSAL)))
    wire = asdict(targets)
    wire['targets'] = [asdict(value) for value in targets.targets]
    assert decode_target_set(wire) == targets
    with pytest.raises(ReferenceError, match='DIGEST_MISMATCH'):
        decode_target_set({**wire, 'digest': asdict(DIGEST)})
    foreign = ArtifactRevisionRef('realm', 'another-project', 'other', 'revision', DIGEST)
    with pytest.raises(ReferenceError, match='REALM_MISMATCH'):
        TargetSet((Target('primary', ARTIFACT), Target('support', foreign)))
