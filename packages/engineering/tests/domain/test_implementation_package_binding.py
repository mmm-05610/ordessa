"""Pure binding checks over synthetic identities; no production consent is implied."""
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.domain.approvals.consent import (
    ApprovalGrant, ConsentPolicyRef, ConversationEvidence, ConversationSource, NoticeRef,
)
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, ImplementationAuthorizationIntent,
)
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, EffectLimit, EnvironmentRef, PathRule, RepositoryScope,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.baselines import RepositorySnapshotRef
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.binding import bind_implementation_package
from ordessa_engineering.domain.packages.models import (
    ImplementationPackage, ImplementationPackagePayload, PackageCoverage,
    PackageDerivation, PackageFile, package_manifest_digest,
)
from ordessa_engineering.domain.reviews.models import (
    CheckKey, CriterionSetRef, ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.reviews.requirements import ReviewRequirementTemplateRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet


SCOPE = Scope('synthetic-package-realm', 'synthetic-package-project')
METHOD = MethodRef('synthetic-package-method', '1.0.0', 1, Digest('sha256', 'a' * 64))
NOW = '2026-10-11T12:00:00.000000Z'
ACTOR = ActorRef('synthetic-actor', 'agent', 'synthetic-fixture')


def _digest(value):
    return Digest('sha256', hashlib.sha256(value.encode()).hexdigest())


def _blob(value, object_id):
    raw = value.encode()
    return BlobRef(_digest(value), len(raw), 'text/plain', object_id)


def _records(*, intent=None, package_changes=None):
    target = ArtifactRevisionRef(SCOPE.realm_id, SCOPE.project_id, 'design', 'rev-1', _digest('design'))
    proposal = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-1', 'proposal-1', _digest('proposal'))
    change_set = ChangeSet((proposal,))
    baseline = RepositorySnapshotRef(SCOPE.realm_id, SCOPE.project_id, 'repo-1', 'none', None,
                                     _digest('tree'), None)
    environment = EnvironmentRef('synthetic-env', 'synthetic-profile', _digest('profile'))
    action_scope = ActionScope(
        SCOPE.project_id,
        (RepositoryScope('repo-1', (PathRule('src', 'subtree', ('modify',)),)),),
        (environment,),
        (EffectLimit('run_checks', 'synthetic-check-target', _digest('check-bound')),),
        (),
        'implementation-intent-1',
    )
    acceptance_ref = ReviewRequirementTemplateRef(SCOPE, 'acceptance-template', 1, _digest('template'))
    spec = ImplementationIntentSpec(
        'implementation-intent-1', ('generate_package', 'edit_repository', 'run_checks'),
        action_scope, (baseline,), (acceptance_ref,), ('Do only the proposed work.',),
    )
    targets = TargetSet((Target('primary', target), Target('support', proposal)))
    requirement = ReviewRequirement(
        SCOPE, 'implementation-requirement', 1, 'quality', targets, METHOD,
        CriterionSetRef('synthetic-criteria', 1, _digest('criteria')),
        (CheckKey(Target('primary', target), 'design-check'),
         CheckKey(Target('support', proposal), 'proposal-check')),
        ('synthetic-reviewer',), 'quality_review',
    )
    supporting_review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'supporting-review', _digest('review'))
    notice = NoticeRef(SCOPE, 'synthetic-notice', _digest('notice'))
    policy = ConsentPolicyRef('synthetic-policy', 1, _digest('policy'))
    if intent is None:
        intent = ImplementationAuthorizationIntent(
            SCOPE, 'implementation-authorization', change_set, (target,), METHOD, notice, policy,
            spec, (requirement,), (supporting_review,),
            (('generate_package', action_scope), ('edit_repository', action_scope), ('run_checks', action_scope)),
            (ActionBudgetSlot('generate_package', 2), ActionBudgetSlot('edit_repository', 1),
             ActionBudgetSlot('run_checks', 3)),
            'Synthetic request only; no human confirmation is represented.', NOW,
            '2026-10-12T12:00:00.000000Z', ('generate_package', 'edit_repository', 'run_checks'),
        )
    # This domain fixture exercises type/binding logic only. Its attestation
    # fields and identities are synthetic and do not authenticate a human.
    evidence = ConversationEvidence(
        'synthetic-evidence', 'Synthetic question?', 'Synthetic context.', 'Synthetic answer.',
        ConversationSource('synthetic://conversation', ('synthetic-message-1',),
                           'Synthetic test source, not production consent.', 'synthetic-attestor', NOW),
        intent.policy_ref, intent.digest, intent.notice_ref, 'confirm',
    )
    grant = ApprovalGrant('synthetic-grant', intent, 'synthetic-challenge', evidence, NOW)
    file = PackageFile('repo-1', 'src/example.py', 'modify', _digest('before'), None,
                       (proposal,), 'synthetic implementation')
    manifest = (file,)
    instruction = _blob('synthetic instructions', 'instructions-object')
    derivation = PackageDerivation(intent.digest, (_blob('proposal input', 'input-object'),),
                                   'synthetic-generator', 'v1', package_manifest_digest(manifest))
    payload_values = dict(
        implementation_intent_id=spec.implementation_intent_id,
        change_set=change_set,
        design_targets=(target,),
        authorization_refs=(grant.ref,),
        method_ref=METHOD,
        required_review_refs=(supporting_review,),
        baseline_snapshots=(baseline,),
        resolved_file_manifest=manifest,
        instructions_ref=instruction,
        skill_snapshot_refs=(),
        execution_profile_ref=environment,
        allowed_actions=('generate_package', 'edit_repository'),
        acceptance_requirements=(acceptance_ref,),
        proposal_coverage=(PackageCoverage(proposal, (instruction,), ('src/example.py',),
                                           (acceptance_ref,), (target,)),),
        method_content=None,
        derivation=derivation,
    )
    if package_changes:
        payload_values.update(package_changes)
    package = ImplementationPackage(SCOPE, 'synthetic-package', NOW, ACTOR,
                                    ImplementationPackagePayload(**payload_values))
    return intent, grant, package, baseline, supporting_review, action_scope


def _reject(call, code):
    with pytest.raises(ReferenceError) as caught:
        call()
    assert caught.value.code == code


def test_exact_package_binding_emits_non_authorizing_current_proof():
    intent, grant, package, _, _, _ = _records()
    proof = bind_implementation_package(package, grant, control_state='granted', control_version=0, now=NOW)
    assert proof.package_ref == package.ref
    assert proof.approval_refs == (grant.ref,)
    assert proof.intent_digest == intent.digest
    assert proof.evaluated_control_versions == ((grant.ref, 0),)
    assert proof.evaluator_contract_version == 'ordessa.package-binding/1'


def test_control_expiry_and_grant_kind_are_required():
    _, grant, package, *_ = _records()
    _reject(lambda: bind_implementation_package(package, grant, control_state='revoked',
                                                control_version=1, now=NOW), 'AUTHORIZATION_REVOKED')
    _reject(lambda: bind_implementation_package(package, grant, control_state='granted',
                                                control_version=0, now='2026-10-13T12:00:00.000000Z'),
            'AUTHORIZATION_EXPIRED')


def test_package_intent_baseline_review_action_and_scope_substitutions_fail():
    _, grant, _, baseline, review, _ = _records()
    _, _, base_package, *_ = _records()
    bad_derivation = replace(base_package.payload.derivation, intent_digest=_digest('wrong-intent'))
    bad_intent_package = replace(base_package, payload=replace(base_package.payload, derivation=bad_derivation))
    _reject(lambda: bind_implementation_package(bad_intent_package, grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_GRANT_BINDING_MISMATCH')

    foreign_baseline = replace(baseline, tree_digest=_digest('different-tree'))
    bad_baseline = replace(base_package, payload=replace(base_package.payload,
                                                          baseline_snapshots=(foreign_baseline,)))
    _reject(lambda: bind_implementation_package(bad_baseline, grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_GRANT_BINDING_MISMATCH')

    foreign_review = replace(review, digest=_digest('other-review'))
    bad_review = replace(base_package, payload=replace(base_package.payload,
                                                        required_review_refs=(foreign_review,)))
    _reject(lambda: bind_implementation_package(bad_review, grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_GRANT_BINDING_MISMATCH')

    bad_action = replace(base_package, payload=replace(base_package.payload, allowed_actions=('deploy',)))
    _reject(lambda: bind_implementation_package(bad_action, grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_GRANT_BINDING_MISMATCH')

    outside = PackageFile('repo-1', 'outside/file.py', 'modify', _digest('before'), None,
                          base_package.payload.change_set.proposal_refs, 'synthetic implementation')
    bad_scope = replace(base_package, payload=replace(
        base_package.payload, resolved_file_manifest=(outside,),
        proposal_coverage=(replace(base_package.payload.proposal_coverage[0],
                                   files=('outside/file.py',)),),
        derivation=replace(base_package.payload.derivation,
                           output_manifest_digest=package_manifest_digest((outside,))),
    ))
    _reject(lambda: bind_implementation_package(bad_scope, grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_SCOPE_MISMATCH')


def test_action_budget_is_bound_through_immutable_intent_digest():
    intent, grant, package, *_ = _records()
    changed = replace(intent, action_budgets=(ActionBudgetSlot('generate_package', 3),
                                              ActionBudgetSlot('edit_repository', 1),
                                              ActionBudgetSlot('run_checks', 3)))
    assert changed.digest != intent.digest
    assert package.payload.derivation.intent_digest == intent.digest
    # The proof binds the grant's complete intent digest; no independent mutable
    # package budget or local counter is accepted by this pure function.
    changed_evidence = replace(grant.evidence, intent_digest=changed.digest)
    changed_grant = replace(grant, intent=changed, evidence=changed_evidence)
    _reject(lambda: bind_implementation_package(package, changed_grant, control_state='granted',
                                                control_version=0, now=NOW), 'PACKAGE_GRANT_BINDING_MISMATCH')


def test_synthetic_grant_and_proof_do_not_claim_production_authentication():
    _, grant, package, *_ = _records()
    proof = bind_implementation_package(package, grant, control_state='granted', control_version=0, now=NOW)
    assert grant.evidence.source.trust_grade == 'agent-attested'
    assert grant.evidence.source.attestor_id == 'synthetic-attestor'
    assert proof.evaluator_contract_version == 'ordessa.package-binding/1'
    assert not hasattr(proof, 'dispatch_token')
