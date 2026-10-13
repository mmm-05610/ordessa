"""Pure implementation-authorization closure; all identities are synthetic."""
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef, NoticeRef
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, ImplementationAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, PathRule, RepositoryScope,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.models import (
    CheckKey, CriterionSetRef, ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet


SCOPE = Scope('synthetic-implementation-realm', 'synthetic-implementation-project')
METHOD = MethodRef('synthetic-method', '1.0.0', 1, Digest('sha256', 'a' * 64))
CREATED = '2026-10-11T12:00:00.000000Z'


def _digest(text):
    return Digest('sha256', hashlib.sha256(text.encode()).hexdigest())


def _values():
    target = ArtifactRevisionRef(*SCOPE.__dict__.values(), 'design-doc', 'revision-1', _digest('design'))
    proposal = ProposalRef(*SCOPE.__dict__.values(), 'change-1', 'proposal-1', _digest('proposal'))
    changes = ChangeSet((proposal,))
    baseline = RepositorySnapshotRef(*SCOPE.__dict__.values(), 'repo-1', 'none', None,
                                     _digest('tree'), None)
    action_scope = ActionScope(
        SCOPE.project_id,
        (RepositoryScope('repo-1', (PathRule('src', 'subtree', ('modify',)),)),),
        (), (), (), 'implementation-intent-1',
    )
    spec = ImplementationIntentSpec(
        'implementation-intent-1', ('generate_package', 'edit_repository'), action_scope,
        (baseline,), (), ('Use only the approved proposal.',),
    )
    targets = TargetSet((Target('primary', target), Target('support', proposal)))
    requirement = ReviewRequirement(
        SCOPE, 'implementation-review', 1, 'quality', targets, METHOD,
        CriterionSetRef('synthetic-criteria', 1, _digest('criteria')),
        (CheckKey(Target('primary', target), 'criterion-design'),
         CheckKey(Target('support', proposal), 'criterion-proposal')),
        ('synthetic-reviewer',), 'quality_review',
    )
    notice = NoticeRef(SCOPE, 'synthetic-notice', _digest('notice'))
    policy = ConsentPolicyRef('synthetic-policy', 1, _digest('policy'))
    supporting_review = ReviewRef(*SCOPE.__dict__.values(), 'synthetic-review', _digest('review'))
    return target, proposal, baseline, action_scope, spec, changes, requirement, notice, policy, supporting_review


def _intent(**changes):
    (target, proposal, baseline, action_scope, spec, change_set, requirement,
     notice, policy, review) = _values()
    values = dict(
        scope=SCOPE,
        intent_id='implementation-authorization-1',
        change_set=change_set,
        targets=(target,),
        method_ref=METHOD,
        notice_ref=notice,
        policy_ref=policy,
        implementation_spec=spec,
        required_review_requirements=(requirement,),
        supporting_review_refs=(review,),
        scope_by_action=(('generate_package', action_scope), ('edit_repository', action_scope)),
        action_budgets=(ActionBudgetSlot('generate_package', 2), ActionBudgetSlot('edit_repository', 1)),
        request_summary='Synthetic fixture; this does not represent human confirmation.',
        not_before=CREATED,
        expires_at='2026-10-12T12:00:00.000000Z',
        actions=('generate_package', 'edit_repository'),
    )
    values.update(changes)
    return ImplementationAuthorizationIntent(**values)


def _reject(call, code):
    with pytest.raises(ReferenceError) as caught:
        call()
    assert caught.value.code == code


def test_closed_implementation_intent_and_synthetic_consent_context():
    intent = _intent()
    assert intent.intent_kind == 'implementation'
    assert intent.digest == _intent().digest
    assert intent.actions == ('generate_package', 'edit_repository')
    assert intent.supporting_review_refs[0].kind == 'review'
    # Synthetic refs and a summary are only pure test values, not consent.
    assert 'does not represent human confirmation' in intent.request_summary


def test_actions_must_be_spec_subset_and_cannot_promote_accept_or_apply():
    _reject(lambda: _intent(actions=('deploy',)), 'UNSUPPORTED_AUTHORIZATION_ACTION')
    _reject(lambda: _intent(actions=('apply_change',)), 'UNSUPPORTED_AUTHORIZATION_ACTION')
    _reject(lambda: _intent(actions=('generate_package', 'generate_package')),
            'UNSUPPORTED_AUTHORIZATION_ACTION')


def test_scope_and_budget_keys_must_exactly_cover_actions():
    (target, _, _, action_scope, _, _, _, _, _, _) = _values()
    _reject(lambda: _intent(scope_by_action=(('generate_package', action_scope),)), 'INVALID_ACTION_SCOPE')
    altered_scope = replace(action_scope, implementation_intent_id='another-intent')
    _reject(lambda: _intent(scope_by_action=(('generate_package', altered_scope),
                                              ('edit_repository', action_scope))),
            'INVALID_ACTION_SCOPE')
    _reject(lambda: _intent(action_budgets=(ActionBudgetSlot('generate_package', 1),)),
            'INVALID_AUTHORIZATION_BUDGET')
    _reject(lambda: ActionBudgetSlot('apply_change', 1), 'INVALID_AUTHORIZATION_BUDGET')
    _reject(lambda: ActionBudgetSlot('edit_repository', 0), 'INVALID_AUTHORIZATION_BUDGET')


def test_targets_require_exact_scope_and_all_design_targets_require_review_coverage():
    other = Scope('synthetic-other-realm', 'synthetic-other-project')
    foreign_target = ArtifactRevisionRef(*other.__dict__.values(), 'design-doc', 'revision-1', _digest('design'))
    _reject(lambda: _intent(targets=(foreign_target,)), 'INVALID_AUTHORIZATION_TARGETS')
    (_, proposal, _, _, _, _, requirement, _, _, _) = _values()
    only_proposal = replace(requirement, expected_targets=TargetSet((Target('support', proposal),)),
                            required_check_keys=(CheckKey(Target('support', proposal), 'criterion-proposal'),))
    _reject(lambda: _intent(required_review_requirements=(only_proposal,)),
            'INVALID_AUTHORIZATION_REQUIREMENTS')


def test_spec_baselines_and_requirements_must_bind_exact_domain_context():
    (target, proposal, baseline, action_scope, spec, change_set, requirement,
     notice, policy, review) = _values()
    changed_spec = replace(spec, instruction_constraints=('Different approved instruction.',))
    object.__setattr__(changed_spec, 'digest', _digest('forged'))
    _reject(lambda: _intent(implementation_spec=changed_spec), 'INVALID_IMPLEMENTATION_INTENT')
    foreign_baseline = replace(baseline, realm_id='synthetic-other-realm', project_id='synthetic-other-project')
    _reject(lambda: ImplementationIntentSpec(spec.implementation_intent_id, spec.requested_actions,
        spec.scope, (foreign_baseline,), spec.acceptance_requirement_refs, spec.instruction_constraints),
        'INVALID_IMPLEMENTATION_BASELINE')
    _reject(lambda: _intent(required_review_requirements=()), 'INVALID_SCHEMA')
    _reject(lambda: _intent(supporting_review_refs=(replace(review, project_id='synthetic-other-project'),)),
            'INVALID_AUTHORIZATION_REQUIREMENTS')


def test_reference_kinds_are_not_implicitly_authorized_by_synthetic_ids():
    intent = _intent()
    assert all(ref.kind == 'proposal' for ref in intent.change_set.proposal_refs)
    assert all(ref.kind == 'artifact_revision' for ref in intent.targets)
    # ApprovalRef is an identity only. The implementation intent deliberately
    # contains no grant or proof field that could manufacture permission.
    assert not hasattr(intent, 'approval_ref')
    assert not hasattr(intent, 'binding_proof')
    assert ApprovalRef(*SCOPE.__dict__.values(), 'synthetic-approval', _digest('grant')).kind == 'approval'
