"""Synthetic graph-binding fixtures; these do not represent a real dispatch or grant."""
from dataclasses import replace
from hashlib import sha256

import pytest

from ordessa_engineering.domain.approvals.consent import (
    ApprovalGrant, ConsentPolicyRef, ConversationEvidence, ConversationSource, NoticeRef,
)
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, ImplementationAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.scope import ActionScope, EffectLimit, PathRule, RepositoryScope
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.repository_baseline import RepositoryFile, seal_repository_baseline
from ordessa_engineering.domain.changes.submission import (
    EffectObservation, EffectTargetRef, ExecutionRecordRef, FileChange, Submission,
    SubmissionCoverage, TestEvidence,
)
from ordessa_engineering.domain.changes.submission_binding import validate_submission_graph
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, ImplementationPackagePayload, PackageCoverage,
    PackageDerivation, PackageFile, package_manifest_digest,
)
from ordessa_engineering.domain.packages.binding import bind_implementation_package
from ordessa_engineering.domain.reviews.models import CheckKey, CriterionSetRef, ReviewRequirement
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.requirements import ReviewRequirementTemplateRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet


SCOPE = Scope('synthetic-binding-realm', 'synthetic-binding-project')
ACTOR = ActorRef('fixture-actor', 'service', 'synthetic-test-fixture')
NOW = '2026-10-11T12:00:00.000000Z'
LATER = '2026-10-12T12:00:00.000000Z'


def digest(label):
    return Digest('sha256', sha256(label.encode()).hexdigest())


def blob(label):
    raw = label.encode()
    return BlobRef(digest(label), len(raw), 'application/octet-stream', 'synthetic-blob-' + label)


def fixture(*, operation='add', baseline_files=(), extra_result=False,
            duplicate_submission_path=False, omit_coverage_file=False, test_result=None):
    """Build typed, internally consistent pure values without issuing authority."""
    proposal = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-a', 'proposal-a', digest('proposal'))
    change_set = ChangeSet((proposal,))
    before_map = dict(baseline_files)
    before = seal_repository_baseline(SCOPE, 'repo-a', 'none', None,
        tuple(RepositoryFile(path, ref) for path, ref in sorted(before_map.items())))

    if operation == 'add':
        path, source = 'src/new.py', None
        prior = None
    elif operation == 'rename':
        path, source = 'src/new.py', 'src/old.py'
        prior = before_map[source].digest
    elif operation in {'modify', 'delete'}:
        path, source = 'src/existing.py', None
        prior = before_map[path].digest
    else:
        raise AssertionError(operation)
    after_ref = blob('after-' + operation)
    package_file = PackageFile('repo-a', path, operation, prior, source, (proposal,), 'fixture plan')
    after_map = dict(before_map)
    if operation in {'delete', 'rename'}:
        del after_map[source or path]
    if operation != 'delete':
        after_map[path] = after_ref
    if extra_result:
        after_map['src/unreported.py'] = blob('unreported')
    after = seal_repository_baseline(SCOPE, 'repo-a', 'none', None,
        tuple(RepositoryFile(name, ref) for name, ref in sorted(after_map.items())))

    effect_constraint = digest('effect-constraint')
    environment = _environment()
    path_scope = ActionScope(SCOPE.project_id,
        (RepositoryScope('repo-a', (PathRule('src', 'subtree', ('add','modify','delete','rename')),)),),
        (environment,), (EffectLimit('deploy','target-a',effect_constraint),), (), 'intent-a')
    acceptance = ReviewRequirementTemplateRef(SCOPE, 'acceptance-a', 1, digest('acceptance-template'))
    actions = ('generate_package','edit_repository','run_checks','deploy')
    spec = ImplementationIntentSpec('intent-a', actions,
        path_scope, (before.ref,), (acceptance,), ('Fixture instruction only.',))
    method = MethodRef('fixture-method','1.0.0',1,digest('method'))
    design = ArtifactRevisionRef(SCOPE.realm_id,SCOPE.project_id,'design-a','rev-a',digest('design'))
    target = Target('primary',design)
    requirement = ReviewRequirement(SCOPE,'review-a',1,'quality',TargetSet((target,)),method,
        CriterionSetRef('criteria-a',1,digest('criteria')),(CheckKey(target,'criterion-a'),),('fixture-reviewer',),'quality')
    notice = NoticeRef(SCOPE,'notice-a',digest('notice'))
    policy = ConsentPolicyRef('policy-a',1,digest('policy'))
    review_ref = ReviewRef(SCOPE.realm_id,SCOPE.project_id,'review-ref-a',digest('review'))
    intent = ImplementationAuthorizationIntent(SCOPE,'auth-intent-a',change_set,(design,),method,
        notice,policy,spec,(requirement,),(review_ref,),
        tuple((action,path_scope) for action in actions),
        tuple(ActionBudgetSlot(action,1) for action in actions),
        'Synthetic fixture; no human confirmation is represented.',NOW,LATER,
        actions)
    conversation = ConversationSource('synthetic fixture context',(), 'No real conversation is represented.',
        'fixture-attestor', NOW)
    evidence = ConversationEvidence('evidence-a','Synthetic confirmation question','Synthetic context',
        'Synthetic answer only.',conversation,policy,intent.digest,notice,'confirm')
    grant = ApprovalGrant('grant-a',intent,'challenge-a',evidence,NOW)

    coverage = PackageCoverage(proposal,(blob('instructions'),),(path,),(acceptance,), (design,))
    payload = ImplementationPackagePayload('intent-a',change_set,(design,),(grant.ref,),method,(review_ref,),
        (before.ref,),(package_file,),blob('package-instructions'),(),
        environment,
        ('generate_package','edit_repository','run_checks','deploy'),(acceptance,),(coverage,),None,
        PackageDerivation(intent.digest,(blob('generator-input'),),'fixture-generator','1',
                          package_manifest_digest((package_file,))))
    package = ImplementationPackage(SCOPE,'package-a',NOW,ACTOR,payload)

    file_change = FileChange('file-change-a','repo-a',path,operation,
        prior,None if operation == 'delete' else after_ref.digest,source,(proposal,))
    file_changes = (file_change,)
    if duplicate_submission_path:
        file_changes += (replace(file_change, change_id='file-change-b'),)
    file_ids = () if omit_coverage_file else tuple(change.change_id for change in file_changes)
    sub_coverage = SubmissionCoverage(proposal,(),file_ids,(),'implemented')
    execution = ExecutionRecordRef('synthetic-environment','synthetic-unit',b'{"fixture":"true"}',
        'source-revision-a','operation-a',digest('prompt-input'),blob('captured-observation'))
    tests = ()
    if test_result is not None:
        tests = (TestEvidence('check-a','acceptance-a',after.ref,execution,test_result,blob('test-observation'),
                             'synthetic-checker/1',NOW),)
    effects = (EffectObservation('effect-a','deploy',EffectTargetRef('target-a',effect_constraint),
                                 'unknown',(blob('effect-observation'),),True),)
    submission = Submission(SCOPE,'submission-a',NOW,ACTOR,change_set,(grant.ref,),package.ref,execution,
        (before.ref,),(after.ref,),(),file_changes,(),tests,effects,(sub_coverage,),())
    return submission,package,grant,(before,),(after,)


def _environment():
    from ordessa_engineering.domain.approvals.scope import EnvironmentRef
    return EnvironmentRef('environment-a','profile-a',digest('profile'))


def test_exact_added_file_diff_binds_against_package_and_full_resulting_tree():
    graph = fixture()
    assert validate_submission_graph(*graph) is graph[0]


def test_package_binding_is_only_a_synthetic_reference_proof():
    _, package, grant, _, _ = fixture()
    proof = bind_implementation_package(package,grant,control_state='granted',control_version=0,now=NOW)
    assert proof.package_ref == package.ref
    assert proof.approval_refs == (grant.ref,)


def test_undeclared_file_in_resulting_manifest_is_rejected():
    with pytest.raises(ReferenceError, match='SUBMISSION_TREE_DIFF_MISMATCH'):
        validate_submission_graph(*fixture(extra_result=True))


def test_two_submission_rows_touching_one_path_are_rejected_as_conflict():
    with pytest.raises(ReferenceError, match='SUBMISSION_FILE_CONFLICT'):
        validate_submission_graph(*fixture(duplicate_submission_path=True))


def test_rename_cannot_overwrite_an_existing_destination():
    source = blob('existing-source')
    destination = blob('existing-destination')
    with pytest.raises(ReferenceError, match='SUBMISSION_FILE_CONFLICT'):
        validate_submission_graph(*fixture(operation='rename', baseline_files=(
            ('src/old.py',source),('src/new.py',destination))))


def test_unknown_test_and_effect_observations_remain_unknown_after_graph_binding():
    graph = fixture(test_result='unknown')
    result = validate_submission_graph(*graph)
    assert result.test_evidence[0].result == 'unknown'
    assert result.effect_observations[0].observed_state == 'unknown'


def test_every_file_change_must_be_named_in_its_proposal_coverage():
    with pytest.raises(ReferenceError, match='INVALID_SUBMISSION_COVERAGE'):
        fixture(omit_coverage_file=True)

