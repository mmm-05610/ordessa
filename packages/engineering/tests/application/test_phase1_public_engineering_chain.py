"""Controlled end-to-end Engineering chain through the original SQLite owners.

The method, reviewer, access, conversation-attestor and user-answer sources in
this fixture are synthetic authority ports. No real human, product admission,
Unit, or model run is claimed. Grant/receipt/review/package persistence and all
business closure/evaluation paths remain the original implementations.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import asyncio
import hashlib
from pathlib import Path
import runpy
from urllib.parse import urljoin

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.approvals.consent import (
    ConsentPolicyRef, ConversationSource, ConversationNotice, ConversationEvidence,
)
from ordessa_engineering.domain.approvals.implementation import ImplementationAuthorizationIntent
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodPayload, MethodContent
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.codec import encode_revision
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.changes.models import Proposal, Change, ChangeSet, Mutation
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.codec import decode_package_ref
from ordessa_engineering.domain.packages.models import package_manifest_digest
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, ReviewPlan, ReviewSetKey,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, TemplateCheck, TemplateTarget, SubjectSelector,
)
from ordessa_engineering.application.usecases.proposal_closure import validate_create
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_review_usecases import SyntheticAccess, SyntheticAdmission, _context as _review_context
from submission_wait_business_fixture import _frozen_method
import test_conversation_approvals as conversation


ROOT = Path(__file__).resolve().parents[4]
POLICY_PATH = ROOT / 'methods/incremental-engineering/policies/product-chat-confirmation.v1.yaml'
NOW = '2026-10-13T12:00:00.000000Z'


@pytest.fixture
def chain(tmp_path):
    # Use the established pure record fixture only as typed construction data;
    # its synthetic Grant is never persisted or used as authority here.
    domain = runpy.run_path(str(Path(__file__).parents[1] / 'domain/test_submission_binding.py'))
    _submission, seed_package, seed_grant, before_seed, _after_seed = domain['fixture']()
    scope, actor = seed_package.scope, seed_package.created_by
    library = EngineeringLibrary.create((tmp_path / 'phase1-public-chain.sqlite').resolve(),
        library_id='phase1-public-chain', schema_version=15)
    factory = SQLiteUoWFactory(library)
    blobs = SQLiteBlobStore(library)
    access = SyntheticAccess()
    snapshot, method_ref, store = _frozen_method(tmp_path, library)
    raw_policy = POLICY_PATH.read_bytes()
    policy = ConsentPolicyRef('ordessa.product.v1.chat-attested-confirmation', 1,
        Digest('sha256', hashlib.sha256(raw_policy).hexdigest()))

    def ctx(request_id, received=NOW):
        return CommandContext(scope, 'controlled-fixture-principal', actor, request_id, received,
            'phase1-public-chain')

    def actual_blob(ref):
        raw = ref.storage_object_id.removeprefix('synthetic-blob-').encode()
        assert Digest('sha256', hashlib.sha256(raw).hexdigest()) == ref.digest
        return blobs.put_verified(raw, ref.digest, ref.media_type)

    # Persist actual immutable baseline bytes; no package/grant is inserted.
    from ordessa_engineering.domain.changes.repository_baseline import RepositoryFile, seal_repository_baseline
    before = tuple(seal_repository_baseline(scope, old.ref.repository_id, old.ref.vcs,
        old.ref.commit_id, tuple(RepositoryFile(f.path, actual_blob(f.blob_ref)) for f in old.files))
        for old in before_seed)
    # The frozen method's document schema is the authoritative source of the
    # MethodContent used by both the Proposal's exact revision and Package.
    doc = next(d for d in snapshot.program.document_definitions if d.document_type == 'test-document')
    resource = next(r for r in snapshot.resources if r.resource_id == doc.schema_resource.resource_id)
    exact = ExactMethodResourceRef(method_ref, resource.logical_path, Digest('sha256', resource.digest), resource.resource_id)
    method_content = MethodContent.from_value(exact, {'statement': 'Frozen proposal summary/document.'})
    schema_location = 'https://ordessa.invalid/method/' + exact.logical_path
    schema_id = schema_location
    design = ArtifactRevision(scope, 'phase1-design', 'phase1-design-r1', NOW, actor,
        MethodPayload('application/json', schema_id, method_content),
        schema_version=2, method_refs=(method_ref,))
    with factory.begin(scope) as uow:
        uow.engineering.create(Artifact(scope, design.artifact_id, 'plan', NOW))
        verify_material(design, uow.engineering.validated_budget())
        uow.engineering.append_revision(design, expected_version=0)
        for baseline in before:
            uow.implementation.create_repository_baseline(baseline)
        uow.commit()
    old_design = design
    design = ArtifactRevision(scope, 'phase1-design', 'phase1-design-r2', NOW, actor,
        MethodPayload('application/json', schema_id, method_content),
        schema_version=2, method_refs=(method_ref,))
    with factory.begin(scope) as uow:
        verify_material(design, uow.engineering.validated_budget())
        uow.engineering.append_revision(design, expected_version=1)
        uow.commit()

    # The Proposal uses original frozen template semantics and the real
    # proposal_closure resolver to produce the review requirements.
    seed_spec = seed_grant.intent.implementation_spec
    from ordessa_engineering.domain.reviews.models import CriterionSetRef
    standards = {s.purpose: s for s in snapshot.program.standard_definitions}
    def template(purpose, phase, selector, role, version=1):
        standard = standards[purpose]
        target = TemplateTarget(role, selector)
        return ReviewRequirementTemplate(scope, 'phase1-' + purpose, version, purpose, (target,), method_ref,
            CriterionSetRef(standard.standard_id, 1, Digest('sha256', standard.resource_ref.sha256)),
            (TemplateCheck(target, 'criterion-a'),), ('reviewer',), phase)
    quality = template('quality', 'quality_review', SubjectSelector('proposed_mutation', 0), 'proposed', version=2)
    acceptance = template('acceptance', 'acceptance_review',
        SubjectSelector('result_of_intent', implementation_intent_id=seed_spec.implementation_intent_id), 'output')
    spec = replace(seed_spec, expected_baselines=tuple(b.ref for b in before),
        acceptance_requirement_refs=(acceptance.ref,))
    proposal = Proposal(scope, 'phase1-proposal', NOW, actor, 'phase1-change',
        'Controlled implementation proposal', 'Synthetic test-only scope.',
        (Mutation(design.artifact_id, 'create', None, design.ref),), (), (), (),
        method_ref, (quality, acceptance), spec)
    with factory.begin(scope) as uow:
        uow.proposals.create_change(Change(scope, proposal.change_id, NOW))
        budget = uow.proposals.validated_budget()
        requirements = validate_create(proposal, uow.proposals, budget)
        uow.proposals.create_proposal(proposal, expected_version=0, budget=budget, requirements=requirements)
        uow.commit()
    change_set = ChangeSet((proposal.ref,))

    # All review requests and schema-2 responses go through existing use cases.
    review_port = SyntheticAdmission(library, blobs)
    reviews = ReviewUseCases(factory, access, review_port, blobs=blobs)
    plans = []
    for index, requirement in enumerate(requirements):
        policies = tuple(CheckPolicy(key, required=True, blocking=True) for key in requirement.required_check_keys)
        plan = ReviewPlan('phase1-review-' + str(index), requirement, policies,
            AggregationPolicy(), ('reviewer',))
        requested = reviews.request({'plan': __import__('dataclasses').asdict(plan)},
            ctx('review-request-' + str(index)))
        assert requested.status == 'completed'
        reviews.record_response(plan.review_id, b'{"answer":"controlled synthetic review"}',
            ctx('review-response-' + str(index)), expected_request_version=0, fence=1)
        plans.append(plan)
    review_refs = []
    with factory.begin(scope, 'read') as uow:
        for requirement in requirements:
            snapshot_reviews = uow.reviews.read_set(ReviewSetKey.for_requirement(requirement))
            assert len(snapshot_reviews.reviews) == 1
            review_refs.append(snapshot_reviews.reviews[0].record.ref)

    source = ConversationSource('controlled-fixture/conversation', (),
        'Synthetic test answer; no platform message or independent human authentication.',
        'controlled-fixture-principal', NOW)
    notice = ConversationNotice(scope, 'phase1-notice', (design.ref,), design.ref,
        'The exact proposal document and requested implementation scope.', source, policy)
    intent = ImplementationAuthorizationIntent(scope, 'phase1-implementation-intent', change_set,
        (design.ref,), method_ref, notice.ref, policy, spec, requirements, tuple(review_refs),
        tuple((action, spec.scope) for action in seed_grant.intent.actions),
        seed_grant.intent.action_budgets, 'Synthetic confirmation of this exact implementation request.',
        '2026-10-13T00:00:00.000000Z', '2026-10-14T00:00:00.000000Z', seed_grant.intent.actions)

    @contextmanager
    def attestor_guard(context, policy_ref):
        assert not library._connection.in_transaction
        assert context.principal_id == 'controlled-fixture-principal' and policy_ref == policy
        yield
    @contextmanager
    def intent_guard(context, candidate):
        assert not library._connection.in_transaction
        assert (type(candidate) is ImplementationAuthorizationIntent
            and candidate.scope == scope and candidate.method_ref == method_ref)
        yield
    admission = conversation.ConversationAdmission(raw_policy, policy,
        attestor_guard=attestor_guard, intent_guard=intent_guard)
    facade = EngineeringService(factory, access, review_admission=review_port, blobs=blobs,
        conversation_admission=admission)
    def execute(operation, parameters, request_id):
        return asyncio.run(facade.execute(operation, parameters, ctx(request_id)))

    try:
        yield locals()
    finally:
        library.close()


def _public_approval(env):
    run = env['execute']
    assert run('engineering.notices.publish', {'notice': asdict(env['notice'])}, 'publish-notice').status == 'completed'
    intent = env['intent']
    assert run('engineering.approvals.prepare_intent', {'intent': asdict(intent)}, 'prepare-intent').status == 'completed'
    challenge = run('engineering.approvals.request', {'intent_id': intent.intent_id,
        'intent_digest': asdict(intent.digest)}, 'request-intent')
    evidence = ConversationEvidence('phase1-answer', 'Confirm this exact implementation request?',
        intent.request_summary, 'Yes, I confirm this exact scope for the controlled test.',
        env['source'], env['policy'], intent.digest, env['notice'].ref, 'confirm')
    granted = run('engineering.approvals.record_conversation', {
        'challenge_id': challenge.result['challenge']['challenge_id'], 'expected_version': 0,
        'nonce': challenge.result['nonce'], 'evidence': asdict(evidence)}, 'record-answer')
    assert granted.result['state'] == 'granted'
    from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
    ref = decode_approval_ref(granted.result['approval_ref'])
    with env['factory'].begin(env['scope'], 'read') as uow:
        grant = uow.authorization.get_grant(ref)
    assert grant.intent == intent and grant.evidence == evidence
    return grant


def test_public_implementation_approval_and_package_freeze_capture_exact_document(chain):
    env = chain
    _public_approval(env)
    seed = runpy.run_path(str(Path(__file__).parents[1] / 'domain/test_submission_binding.py'))['fixture']()[1]
    package = seed
    # This schema-1 artifact package is a historical fixture. New package
    # preparation must use the source-pinned envelope covered by the public
    # external-record chain test; the old artifact mirror has no write path.
    with pytest.raises(ApplicationError, match='IMPLEMENTATION_ENVELOPE_UNAVAILABLE'):
        env['execute']('engineering.packages.freeze', {
            'record': decode_json(__import__('ordessa_engineering.domain.packages.codec',
                fromlist=['encode_package']).encode_package(package)),
        }, 'freeze-package')
    assert env['library']._connection.execute(
        'SELECT COUNT(*) FROM eng_packages WHERE realm_id=? AND project_id=?',
        (env['scope'].realm_id,env['scope'].project_id)).fetchone()[0] == 0
    with env['factory'].begin(env['scope'], 'read') as uow:
        assert uow.proposals.get_proposal(env['proposal'].ref) == env['proposal']


def test_public_approval_rejects_prior_review_revision_for_current_requirement(chain):
    env = chain
    requirement = env['requirements'][0]
    old_targets = tuple(Target(target.role,
        env['old_design'].ref if target.ref.artifact_id == env['design'].artifact_id else target.ref)
        for target in requirement.expected_targets.targets)
    old_ref_by_original = {target.ref: old_targets[index].ref
        for index, target in enumerate(requirement.expected_targets.targets)}
    old_keys = tuple(CheckKey(Target(key.target.role, old_ref_by_original[key.target.ref]), key.criterion_id)
        for key in requirement.required_check_keys)
    old_requirement = replace(requirement, requirement_version=1, expected_targets=TargetSet(old_targets),
        required_check_keys=old_keys)
    plan = ReviewPlan('phase1-stale-review', old_requirement,
        tuple(CheckPolicy(key, required=True, blocking=True) for key in old_requirement.required_check_keys),
        AggregationPolicy(), ('reviewer',))
    env['reviews'].request({'plan': asdict(plan)}, env['ctx']('stale-review-request'))
    env['reviews'].record_response(plan.review_id, b'{"answer":"old requirement"}',
        env['ctx']('stale-review-response'), expected_request_version=0, fence=1)
    # Bind the implementation intent to this old-ref review only. The original
    # Proposal resolver and gate must reject it against the current target ref.
    with env['factory'].begin(env['scope'], 'read') as uow:
        stale_set = uow.reviews.read_set(ReviewSetKey.for_requirement(old_requirement))
    stale_ref = next(item.record.ref for item in stale_set.reviews
        if item.record.plan.review_id == plan.review_id)
    stale_intent = replace(env['intent'], supporting_review_refs=(stale_ref,))
    with pytest.raises(ApplicationError, match='REVIEW_STALE'):
        env['execute']('engineering.approvals.prepare_intent', {'intent': asdict(stale_intent)},
            'prepare-with-stale-review')
