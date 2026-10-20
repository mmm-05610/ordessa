"""Candidate producer contract over an original SQLite Proposal/material graph.

These are source tests only in this task; no provider or model is invoked.
"""
from dataclasses import asdict, replace
import hashlib

import pytest

from decision_runtime.definitions import PolicyRef, digest
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
from ordessa_engineering.application.usecases.material_closure import verify_material, verify_sources
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.provenance import (
    Claim, ClaimRef, EvidenceLink, ExcerptCapture, SourceLocator, SourceRef,
)
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.common.models.values import Digest, UtcInstant
from ordessa_engineering.domain.changes.models import ProposalEvidenceLink
from ordessa_engineering.domain.reviews.models import ReviewRequestState
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, SubjectSelector, TemplateCheck, TemplateTarget,
)
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.methods.definitions.models.compiled import (
    DecisionSpec, QuestionSpec, CriterionRef, freeze_value, thaw_value,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

from ordessa_server.composition.engineering_jev_questions import build_nominal_jev_questions
from ordessa_server.composition.engineering_reviewer_source import frozen_input_digest
from test_method_per_claim import ROOT, published
from test_proposal_usecases import ACTOR, CREATED_AT, SCOPE, SyntheticAccess, _ctx, _proposal_ref


@pytest.fixture
def original_case(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'jev-question.sqlite').resolve(),
        library_id='jev-question-original-db', schema_version=10)
    factory = SQLiteUoWFactory(library)
    snapshot = published(library, ROOT / 'candidates/2.3.0')
    released = snapshot.ref
    method_ref = MethodRef(released.method_id, released.release_version,
        released.schema_version, Digest('sha256', released.snapshot_digest))

    blob_store = SQLiteBlobStore(library)
    support_raw = b'Frozen source supports this statement.'
    counter_raw = b'Frozen source contradicts this statement.'
    sources = tuple(_source(blob_store, name, raw) for name, raw in (
        ('source-support', support_raw), ('source-counter', counter_raw)))
    body = {'statement': 'The source claim under review.'}
    claim = Claim('claim-1', ContentSelector('json_pointer', pointer='/statement'),
        Digest('sha256', hashlib.sha256(__import__('ordessa_infrastructure.encoding',
            fromlist=['canonical_bytes']).canonical_bytes(body['statement'])).hexdigest()))
    links = tuple(EvidenceLink(claim.claim_id, source, ContentSelector('whole_capture'), relation,
        'Captured source relation retained as input.')
        for source, relation in zip(sources, ('supports', 'contradicts')))
    base = ArtifactRevision(SCOPE, 'jev-target', 'jev-base', CREATED_AT, ACTOR,
        InlinePayload.from_value('application/json', 'urn:test:jev-claim', {'statement': 'Previous claim.'}),
        schema_version=2)
    revision = ArtifactRevision(SCOPE, 'jev-target', 'jev-revision', CREATED_AT, ACTOR,
        InlinePayload.from_value('application/json', 'urn:test:jev-claim', body),
        parent_revision_refs=(base.ref,), schema_version=2, sources=sources,
        claims=(claim,), evidence_links=links)
    with factory.begin(SCOPE) as uow:
        uow.engineering.create(Artifact(SCOPE, revision.artifact_id, 'plan', CREATED_AT))
        verify_material(base, uow.engineering.validated_budget())
        base_ref = uow.engineering.append_revision(base, expected_version=0)
        verify_material(revision, uow.engineering.validated_budget())
        target_ref = uow.engineering.append_revision(revision, expected_version=1)
        assert target_ref == revision.ref
        uow.commit()

    bridge = MethodBridge()
    target = Target('proposed', target_ref)
    bindings = EngineeringTargetBindings(SCOPE, TargetSet((target,)), ((target, 'did'),),
        ('source_captures', 'claim_bindings', 'method_content', 'proposal_ref', 'implementation_intent'),
        ('reviewer',), 'jev-source-phase')
    requirements = bridge.review_requirements(snapshot, bindings, revisions=(revision,))
    template_target = TemplateTarget('proposed', SubjectSelector('proposed_mutation', 0))
    templates = tuple(ReviewRequirementTemplate(SCOPE, 'jev-template-' + requirement.criterion_set_ref.criterion_set_id,
        1, requirement.purpose, (template_target,), method_ref, requirement.criterion_set_ref,
        tuple(TemplateCheck(template_target, key.criterion_id, key.claim_id)
            for key in requirement.required_check_keys), requirement.eligible_reviewer_roles,
        requirement.phase_key) for requirement in requirements)
    claim_ref = ClaimRef(target_ref, claim.claim_id, claim.statement_digest)
    proposal_links = tuple(ProposalEvidenceLink(claim_ref, source,
        ContentSelector('whole_capture'), relation, 'Proposal retains every declared relation.')
        for source, relation in zip(sources, ('supports', 'contradicts')))
    draft = {
        'intent': 'Review a claim against captured evidence.',
        'rationale': 'The test fixture preserves original material references.',
        'mutations': [{'artifact_id': revision.artifact_id, 'operation': 'revise',
            'base_ref': asdict(base_ref), 'proposed_ref': asdict(target_ref)}],
        'basis_sources': [asdict(source) for source in sources],
        'claim_refs': [asdict(claim_ref)],
        'evidence_links': [asdict(link) for link in proposal_links],
        'method_ref': asdict(method_ref),
        'review_requirement_templates': [asdict(template) for template in templates],
        'implementation_intent': None, 'supersedes_refs': [],
    }
    created = ProposalUseCases(factory, SyntheticAccess()).create(
        {'change_id': None, 'expected_version': 0, 'draft': draft}, _ctx())
    proposal_ref = _proposal_ref(created.result['proposal_ref'])
    try:
        yield dict(library=library, factory=factory, snapshot=snapshot,
            method_ref=method_ref, proposal_ref=proposal_ref, revision=revision,
            sources=sources, claim=claim, blob_store=blob_store, bindings=bindings)
    finally:
        library.close()


def _source(blob_store, source_id, raw):
    blob = blob_store.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'text/plain')
    return SourceRef(source_id, 'chat_message',
        SourceLocator('chat_message', provider='test-provider', conversation_id='c1', message_id=source_id),
        ExcerptCapture(blob, Digest('sha256', hashlib.sha256(raw).hexdigest()),
            ContentSelector('whole_capture'), 'captured-v1'),
        UtcInstant(CREATED_AT), ACTOR, 'text/plain', len(raw))


def _run_builder(case, *, proposal_transform=None, snapshot=None, plan_transform=None,
        source_material_transform=None):
    with case['factory'].begin(SCOPE, 'read') as uow:
        budget = uow.proposals.validated_budget()
        proposal = uow.proposals.get_proposal(case['proposal_ref'], budget=budget)
        resolve_record(proposal, uow.proposals, budget)
        roots = tuple(m.proposed_ref for m in proposal.mutations) + tuple(
            m.base_ref for m in proposal.mutations if m.base_ref is not None) + tuple(
            c.owner_revision_ref for c in proposal.claim_refs)
        revisions = uow.proposals.resolve_revision_graph(roots, budget)
        owner = uow.engineering.get_artifact(proposal.mutations[0].artifact_id)
        if proposal.mutations[0].operation == 'create':
            owner = replace(owner, head_revision_id=None)
        requirements = MethodBridge().proposal_review_requirements(case['snapshot'],
            (case['bindings'],), proposal=proposal, artifacts=(owner,), revisions=revisions)
        requirement = next(r for r in requirements if r.criterion_set_ref.criterion_set_id == 'source-review')
        plan = MethodBridge().review_plan(case['snapshot'], case['bindings'], requirement,
            'jev-question-review', proposal=proposal, artifacts=(owner,), revisions=revisions,
            phase_bindings=(case['bindings'],))
        request = ReviewRequestState(SCOPE, plan.review_id, 'requested', 1, 0)
        if source_material_transform is not None:
            proposal, source_links = source_material_transform(proposal, budget)
            verify_sources(proposal.basis_sources, source_links, budget)
        if proposal_transform is not None:
            proposal = proposal_transform(proposal)
        if plan_transform is not None:
            plan = plan_transform(plan)
        return build_nominal_jev_questions(uow=uow, budget=budget, proposal=proposal,
            revisions=revisions, snapshot=case['snapshot'] if snapshot is None else snapshot,
            plan=plan, request=request,
            standard=next(s for s in case['snapshot'].program.standard_definitions
                if s.standard_id == 'source-review'),
            policy_ref=PolicyRef('test.nominal-policy', '1', digest('policy', {'fixture': True})))


def test_real_23_proposal_and_material_graph_build_full_nominal_choice_questions(original_case):
    case = original_case
    questions = _run_builder(case)
    assert len(questions) == 1
    item = questions[0]
    assert item.check_key.claim_id == 'claim-1'
    assert item.question.question_text == next(q.instructions
        for d in case['snapshot'].program.decision_definitions for q in d.questions
        if d.question_set_id == 'source-support')
    assert item.input_truncated is False
    assert item.input_digest == frozen_input_digest(item.question.bounded_state)
    state = item.question.bounded_state['nominal_question_input']
    assert state['input_complete'] is True and state['input_truncated'] is False
    inputs = state['inputs']
    # Original JSON-pointer selection preserves the canonical JSON scalar bytes.
    assert inputs['claim']['text'] == '"The source claim under review."'
    assert {entry['relation'] for entry in inputs['captured_sources']} == {'supports', 'contradicts'}
    assert {entry['selected_text'] for entry in inputs['captured_sources']} == {
        'Frozen source supports this statement.', 'Frozen source contradicts this statement.'}
    # Proposal and revision each freeze their own evidence-link declaration.
    assert len(inputs['captured_sources']) == 4
    assert len(inputs['counter_sources']) == 2
    assert {entry['selected_text'] for entry in inputs['counter_sources']} == {
        'Frozen source contradicts this statement.'}
    assert not hasattr(item, 'answer_complete')


def test_builder_rejects_unlinked_proposal_source(original_case):
    case = original_case
    orphan = replace(case['sources'][0], source_id='unlinked-source')
    with pytest.raises(ApplicationError, match='MATERIAL_CONTENT_INVALID'):
        _run_builder(case, proposal_transform=lambda proposal:
            replace(proposal, basis_sources=proposal.basis_sources + (orphan,)))


def test_original_material_closure_rejects_wrong_claim_digest(original_case):
    case = original_case
    bad_claim = replace(case['claim'], statement_digest=Digest('sha256', '0' * 64))
    with pytest.raises(ReferenceError, match='STATEMENT_DIGEST_MISMATCH'):
        replace(case['revision'], claims=(bad_claim,))


def test_builder_refuses_question_input_that_exceeds_bound(original_case):
    case = original_case
    oversized_source = _source(case['blob_store'], 'source-oversized', b'x' * (140 * 1024))

    def replace_sources(proposal, budget):
        ref = proposal.claim_refs[0]
        link = ProposalEvidenceLink(ref, oversized_source, ContentSelector('whole_capture'),
            'supports', 'Large but fully captured source for the bound refusal.')
        changed = replace(proposal, basis_sources=(oversized_source,), evidence_links=(link,))
        return changed, (link,)

    with pytest.raises(ApplicationError, match='MATERIAL_LIMIT'):
        _run_builder(case, source_material_transform=replace_sources)


def test_builder_rejects_mismatched_method_and_old_question_spec(original_case):
    case = original_case
    wrong_proposal_method = replace(case['method_ref'], release_version='2.2.0')
    with pytest.raises(ApplicationError, match='METHOD_SUBJECT_BINDING_MISMATCH'):
        _run_builder(case, proposal_transform=lambda proposal:
            replace(proposal, method_ref=wrong_proposal_method))

    old_standard = next(s for s in case['snapshot'].program.standard_definitions
        if s.standard_id == 'source-review')
    old_question = QuestionSpec('support', '1.0.0', 'choice',
        (CriterionRef(old_standard.resource_ref, 'claim_support'),), 'legacy',
        CriterionRef(old_standard.resource_ref, 'claim_support'),
        freeze_value({'kind': 'choice', 'options': []}))
    decision = next(d for d in case['snapshot'].program.decision_definitions
        if d.question_set_id == 'source-support')
    old_spec = DecisionSpec(decision.resource_ref, decision.question_set_id,
        decision.question_set_version, decision.input_contract, decision.input_mapping_version,
        decision.required_input_slots, decision.iteration, (old_question,),
        decision.result_contract, decision.truncation_policy, decision.missing_required_evidence,
        decision.evidence_order)
    with pytest.raises(TypeError, match='typed semantic value required'):
        replace(case['snapshot'].program, decision_definitions=(old_spec,))
