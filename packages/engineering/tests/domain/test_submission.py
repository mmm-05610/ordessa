"""Explicit domain-shape fixtures only; no real execution, grant, or persistence claim."""
from dataclasses import replace

import pytest

from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositoryId
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.repository_baseline import seal_repository_baseline
from ordessa_engineering.domain.changes.submission import (
    CommitRef, EffectObservation, EffectTargetRef, ExecutionRecordRef, FileChange,
    Submission, SubmissionCoverage, TestEvidence,
)
from ordessa_engineering.domain.changes.submission_codec import encode_submission, decode_submission
from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef


def d(char='a'):
    return Digest('sha256', char * 64)


def blob(char='b'):
    return BlobRef(d(char), 2, 'application/json', 'fixture-object')


def record(result='unknown'):
    scope = Scope('realm', 'project')
    proposal = ProposalRef('realm', 'project', 'change', 'proposal-a', d('c'))
    cs = ChangeSet((proposal,))
    baseline = seal_repository_baseline(scope, 'repo', 'none', None, ()).ref
    execution = ExecutionRecordRef('fixture-env', 'fixture-unit', b'{"provider":"fixture"}', 'source-v1', 'operation-1', d('d'), blob())
    evidence = TestEvidence('check-a', 'requirement-a', baseline, execution, result, blob('e'), 'fixture-tool/1', '2026-10-11T00:00:00.000000Z')
    effect = EffectObservation('effect-a', 'apply_change', EffectTargetRef('target-a', d('f')), 'unknown', (blob('1'),), True)
    coverage = SubmissionCoverage(proposal, (), (), (), 'not_implemented', 'Fixture does not assert implementation.')
    return Submission(scope, 'submission-a', '2026-10-11T00:00:00.000000Z', ActorRef('fixture-actor','service','fixture'), cs,
        (ApprovalRef('realm','project','fixture-approval',d('2')),), ImplementationPackageRef('realm','project','fixture-package',d('3')),
        execution, (baseline,), (), (), (), (), (evidence,), (effect,), (coverage,), ())


def test_submission_roundtrip_preserves_unknown_failed_and_not_run_facts():
    for result in ('pass', 'fail', 'unknown', 'not_run'):
        value = record(result)
        decoded = decode_submission(encode_submission(value))
        assert decoded == value
        assert decoded.test_evidence[0].result == result
        assert decoded.ref.digest == value.digest
        assert decoded.coverage[0].disposition == 'not_implemented'


def test_codec_rejects_mutated_payload_even_when_old_digest_is_retained():
    raw = encode_submission(record())
    from ordessa_infrastructure.encoding import canonical_bytes, decode_json
    value = decode_json(raw)
    value['submission_id'] = 'mutated-id'
    with pytest.raises(ReferenceError):
        decode_submission(canonical_bytes(value))


def test_owner_provider_identity_must_be_canonical_json_object_within_bound():
    with pytest.raises(ReferenceError):
        ExecutionRecordRef('env','unit',b'{ "provider":"p" }','rev','op',d(),blob())
    with pytest.raises(ReferenceError):
        ExecutionRecordRef('env','unit',b'[]','rev','op',d(),blob())
    with pytest.raises(ReferenceError):
        ExecutionRecordRef('env','unit',b'{"p":"' + b'x' * 4100 + b'"}','rev','op',d(),blob())


def test_coverage_requires_exactly_one_item_per_change_proposal():
    value = record()
    with pytest.raises(ReferenceError):
        replace(value, coverage=())


def test_two_proposals_each_get_explicit_coverage_and_may_share_an_output():
    value = record()
    first, = value.change_set.proposal_refs
    second = ProposalRef('realm','project','change','proposal-b',d('4'))
    output = blob('5')
    changed = replace(value, change_set=ChangeSet((first, second)),
        output_refs=(output,),
        coverage=(SubmissionCoverage(first,(output,),(),(),'implemented'),
                  SubmissionCoverage(second,(output,),(),(),'implemented')))
    assert len(decode_submission(encode_submission(changed)).coverage) == 2
    with pytest.raises(ReferenceError):
        replace(changed, coverage=(changed.coverage[0], changed.coverage[0]))


def test_file_change_operation_requires_consistent_before_after_and_rename_source():
    proposal = ProposalRef('realm','project','change','p',d())
    with pytest.raises(ReferenceError):
        FileChange('f','repo','a.py','add',d(),d(),None,(proposal,))
    with pytest.raises(ReferenceError):
        FileChange('f','repo','b.py','rename',d(),d(),None,(proposal,))


def test_effect_unknown_is_kept_as_a_fact_not_converted_to_reverted():
    value = record()
    roundtripped = decode_submission(encode_submission(value))
    assert roundtripped.effect_observations[0].observed_state == 'unknown'
    assert roundtripped.checkpoint_ref is None
