"""Formal human disposition on actual 2.4/schema10 review and mechanical owners.

The human policy/attestor and Q&A are explicit synthetic test ports. Passing
these tests demonstrates wiring and counterexamples, not a production human
confirmation source or implementation Grant.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

import pytest
from ordessa_infrastructure.encoding import canonical_bytes

from test_method_per_claim import ROOT, published, revision, binding
from test_method_control_admission import TestManagement, context
from test_proposal_usecases import SCOPE, ACTOR, CREATED_AT, SyntheticAccess
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest
from ordessa_engineering.application.contracts.manual_reviews import ManualReviewReply, VerifiedHumanDisposition
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.application.orchestration.human_review import (
    human_review_observations, human_review_presentation_digest,
)
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.reviews.mechanical import MechanicalReviewCheckSource
from ordessa_engineering.application.usecases.reviews.human import (
    EngineeringHumanReviewAdmission, encode_human_review_response,
)
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.domain.approvals.consent import ConversationSource
from ordessa_engineering.domain.artifacts.models import Artifact
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.provenance import (
    SourceRef, SourceLocator, ExcerptCapture, EvidenceLink,
)
from ordessa_engineering.domain.common.models.selection import ContentSelector
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import ReviewSetKey, observations_digest
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.orchestration.method_answers import nominal_criterion_answer


_CANDIDATE = ROOT / 'candidates/2.4.0'
_POLICY = (_CANDIDATE / 'policies/product-chat-human-review.v1.yaml').read_bytes()


def _reply(plan, *, answer='I reviewed each displayed source check and the cited evidence supports the stated claim.',
           omit=None):
    source = ConversationSource('conversation://synthetic-test/thread-1', ('message-1',),
        'Synthetic Q&A fixture; not an authenticated platform message.', 'synthetic-main-agent',
        '2026-10-11T12:00:00.000000Z')
    answers = tuple(CriterionAnswer(key, 'satisfied', (), 'synthetic explicit review answer')
                    for key in plan.check_keys if key != omit)
    return ManualReviewReply('Does this source and claim set meet the frozen review?',
        'The full exact source-review plan and all three displayed checks.', answer, source, answers)


class _SyntheticHumanAuthority:
    """Synthetic external policy/source owner; never authenticates a real user."""
    def __init__(self, scope, *, policy_bytes=_POLICY, epoch=1, on_guard=None):
        self.scope, self.policy_bytes, self.epoch = scope, policy_bytes, epoch
        self.on_guard = on_guard
        self.depth = 0

    @contextmanager
    def guard_disposition(self, ctx, plan, frozen, raw_ref, reply, *, standard,
                          mechanical_answers, expected=None):
        assert ctx.scope == self.scope and frozen.plan_digest == plan.plan_digest
        callback, self.on_guard = self.on_guard, None
        if callback is not None:
            callback()
        observations = human_review_observations(plan, standard, reply, self.policy_bytes,
                                                 mechanical_answers)
        evidence = VerifiedReviewerEvidence(self.scope,
            ActorRef('synthetic-user', 'human', 'synthetic-main-agent'), ('reviewer',),
            'synthetic-configured-main-agent', '1', self.epoch, plan.request_digest,
            raw_ref.digest, observations_digest(observations),
            Digest('sha256', hashlib.sha256(self.policy_bytes).hexdigest()))
        verified = VerifiedHumanDisposition(self.policy_bytes, evidence, True,
            human_review_presentation_digest(plan, reply, self.policy_bytes))
        self.depth += 1
        try:
            yield verified
        finally:
            self.depth -= 1


@pytest.fixture
def human_case(tmp_path, request):
    options = getattr(request, 'param', {})
    release = options.get('release', '2.4.0')
    no_links = options.get('no_links', False)
    library = EngineeringLibrary.create((tmp_path / 'human.sqlite').resolve(),
                                        library_id='human-review-test', schema_version=10)
    try:
        snapshot = published(library, ROOT / 'candidates' / release)
        if release == '2.4.0':
            assert snapshot.ref.snapshot_digest == 'fa51512abd24167856217ee58b4ba26903247a4f6e319ed9d80d20dc4c8c800c'
            assert hashlib.sha256(_POLICY).hexdigest() == '833be965ff8e43b0fec817e205a4d2f7817f45b7b36777a405a905fff44ec008'
        factory = SQLiteUoWFactory(library)
        store = SQLiteSnapshotStore(library)
        methods = MethodUseCases(factory, SyntheticAccess(), store, TestManagement())
        method = MethodRef(snapshot.ref.method_id, snapshot.ref.release_version,
                           snapshot.ref.schema_version, Digest('sha256', snapshot.ref.snapshot_digest))
        methods.adopt(method, context('human-adopt'), expected_version=0)
        controls = SQLiteMethodControl(factory, store)
        blobs = SQLiteBlobStore(library)

        raw_source = b'Captured source text for mechanical integrity fixture.'
        blob = blobs.put_verified(raw_source, Digest('sha256', hashlib.sha256(raw_source).hexdigest()), 'text/plain')
        capture = SourceRef('source-human', 'code',
            SourceLocator('code', repository_id='repo', path='README.md'),
            ExcerptCapture(blob, blob.digest, ContentSelector('whole_capture')),
            CREATED_AT, ACTOR, 'text/plain', len(raw_source))
        original = revision()
        claims = original.claims[:1]
        material = replace(original, claims=claims, sources=(capture,), evidence_links=(() if no_links else
            (EvidenceLink(claims[0].claim_id, capture, ContentSelector('whole_capture'),
                          'supports', 'synthetic fixture association'),)))
        with factory.begin(SCOPE) as uow:
            uow.engineering.create(Artifact(SCOPE, material.artifact_id, 'plan', CREATED_AT))
            verify_material(material, uow.engineering.validated_budget())
            uow.engineering.append_revision(material, expected_version=0)
            uow.commit()

        bindings = replace(binding((material,)),phase_key='source_review',workflow_node_id='source_review',
                           input_slots=('proposal_ref','source_captures','claim_bindings'))
        bridge = MethodBridge()
        requirement = next(r for r in bridge.review_requirements(snapshot, bindings, revisions=(material,))
                           if r.criterion_set_ref.criterion_set_id == 'source-review')
        plan = bridge.review_plan(snapshot, bindings, requirement, 'human-review', revisions=(material,))
        standard = next(s for s in snapshot.program.standard_definitions if s.standard_id == 'source-review')
        assert len(plan.check_keys) == 3

        mechanical = MechanicalReviewCheckSource(factory, controls, blobs)
        authority = _SyntheticHumanAuthority(SCOPE)
        class OriginalBindingsFixture:
            def resolve_bindings(self,*args):return bindings
        owner=OriginalBindingsFixture()
        admission = EngineeringHumanReviewAdmission(factory, controls, owner, authority,
            blobs=blobs, mechanical_source=mechanical)
        reviews = ReviewUseCases(factory, SyntheticAccess(), admission, blobs=blobs)
        request_result = reviews.plan(plan, context('human-request'))
        request_value = request_result.result['request']
        frozen = FrozenCheckRequest(plan.plan_digest, request_value['version'], request_value['fence'])
        mechanical_keys = tuple(k for k in plan.check_keys
            if k.criterion_id in {'source_integrity', 'claim_coverage'})
        proof = mechanical.capture_proof(context('human-proof'), plan, frozen,
                                         standard=standard, check_keys=mechanical_keys)
        yield dict(library=library, factory=factory, controls=controls, blobs=blobs,
            method=method, methods=methods, plan=plan, requirement=requirement, standard=standard,
            bindings=owner, mechanical=mechanical, authority=authority, admission=admission,
            reviews=reviews, request=request_value, frozen=frozen, proof=proof,
            mechanical_keys=mechanical_keys, no_links=no_links, release=release)
    finally:
        library.close()


def _record(case, *, answer=None, omit=None, answer_mode='per_check'):
    reply = _reply(case['plan'], answer=answer or _reply(case['plan']).user_answer, omit=omit)
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], reply, case['proof'], answer_mode=answer_mode)
    result = case['reviews'].record_response(case['plan'].review_id, raw, context('human-record'),
        expected_request_version=case['request']['version'], fence=case['request']['fence'])
    return result, reply


def test_actual_24_human_disposition_records_all_pass_but_no_grant(human_case):
    case = human_case
    result, _ = _record(case)
    assert result.status == 'completed'
    gate = case['reviews'].gate(case['requirement'], context('human-gate'))
    assert gate.satisfied
    with case['factory'].begin(SCOPE, 'read') as uow:
        snap = uow.reviews.read_set(ReviewSetKey.for_requirement(case['requirement']))
        assert len(snap.reviews) == 1
        record = snap.reviews[0].record
        assert record.complete and record.verdict == 'pass'
        assert {o.result for o in record.observations} == {'pass'}
        assert uow.engineering.access.execute(
            'SELECT COUNT(*) FROM eng_approval_grants WHERE realm_id=? AND project_id=?',
            (SCOPE.realm_id, SCOPE.project_id)).fetchone()[0] == 0


def test_automatic_jev_nominal_answer_stays_manual_without_evaluation(human_case):
    case = human_case
    key = next(k for k in case['plan'].check_keys if k.criterion_id == 'claim_support')
    criterion = next(c for c in case['standard'].criteria if c.criterion_id == 'claim_support')
    result = nominal_criterion_answer(case['plan'], case['standard'], key,
        selected_option='supported', selection_status='unique', answer_complete=True, input_truncated=False)
    assert result.answer.status == 'satisfied'
    assert result.quality_disposition == 'manual'


def test_explicit_complete_checklist_answer_is_formal_review_not_grant(human_case):
    result,_=_record(human_case,answer='这些审核项全部通过',answer_mode='whole_plan')
    assert result.status=='completed'
    assert human_case['reviews'].gate(human_case['requirement'],context('whole-plan-gate')).satisfied


@pytest.mark.parametrize('status,verdict',[('violated','fail'),('insufficient','fail'),('unknown','indeterminate')])
def test_human_semantic_status_uses_selected_external_policy(human_case,status,verdict):
    case=human_case;reply=_reply(case['plan'])
    reply=replace(reply,check_answers=tuple(replace(a,status=status) if a.check_key.criterion_id=='claim_support'
                  else a for a in reply.check_answers))
    raw=encode_human_review_response(case['plan'],case['request']['version'],case['request']['fence'],reply,case['proof'])
    result=case['reviews'].record_response(case['plan'].review_id,raw,context('human-semantic-'+status),
                expected_request_version=case['request']['version'],fence=case['request']['fence'])
    assert result.status=='completed'
    with case['factory'].begin(SCOPE,'read') as uow:
        record=uow.reviews.read_set(ReviewSetKey.for_requirement(case['requirement'])).reviews[0].record
    assert record.verdict==verdict


def test_pure_projection_does_not_hardcode_satisfied_to_pass(human_case):
    # Pure mechanism counterexample, not an admitted mutation of Method2.4.
    from ordessa_engineering.methods.definitions.models.compiled import thaw_value,freeze_value
    case=human_case;policy=_POLICY.replace(b'satisfied: pass',b'satisfied: manual')
    digest='sha256:'+hashlib.sha256(policy).hexdigest()
    criteria=[]
    for criterion in case['standard'].criteria:
        data=thaw_value(criterion.checks[0].bindings)
        if 'human_review_admission' in data:
            data['human_review_admission']['policy_digest']=digest
            data['human_review_admission']['status_dispositions']['satisfied']='manual'
            criterion=replace(criterion,checks=(replace(criterion.checks[0],bindings=freeze_value(data)),))
        criteria.append(criterion)
    standard=replace(case['standard'],criteria=tuple(criteria))
    mechanical=case['mechanical'].verify_checks(context('map-proof'),case['plan'],case['frozen'],case['proof'],
                    standard=case['standard'],check_keys=case['mechanical_keys'])
    obs=human_review_observations(case['plan'],standard,_reply(case['plan']),policy,mechanical.answers)
    assert all(o.result=='indeterminate' for o in obs if o.check_key.criterion_id!='source_integrity')
    # Actual pinned Method2.4 still refuses these changed policy bytes.
    case['authority'].policy_bytes=policy
    with pytest.raises(ApplicationError,match='HUMAN_REVIEW_POLICY_BINDING_MISMATCH'):
        _record(case)


@pytest.mark.parametrize('mutation,code',[
    ('not-explicit','HUMAN_REVIEW_ANSWER_PENDING'),
    ('presentation','HUMAN_REVIEW_PRESENTATION_CHANGED'),
    ('checker','UNTRUSTED_REVIEWER'),
])
def test_actual_source_verification_facts_are_required(human_case,mutation,code):
    case=human_case;original=case['authority'].guard_disposition
    @contextmanager
    def changed(*args,**kwargs):
        with original(*args,**kwargs) as verified:
            if mutation=='not-explicit':verified=replace(verified,explicit_answer=False)
            elif mutation=='presentation':verified=replace(verified,presentation_digest=Digest('sha256','a'*64))
            else:verified=replace(verified,reviewer_evidence=replace(verified.reviewer_evidence,
                         reviewer=ActorRef('checker','checker','synthetic-not-human')))
            yield verified
    case['authority'].guard_disposition=changed
    with pytest.raises(ApplicationError,match=code):_record(case)
    with case['factory'].begin(SCOPE,'read') as uow:
        assert uow.reviews.get_request(case['plan'].review_id).state=='requested'
        assert not uow.reviews.read_set(ReviewSetKey.for_requirement(case['requirement'])).reviews


def test_human_reply_cannot_replace_the_mechanical_integrity_answer(human_case):
    case=human_case;reply=_reply(case['plan'])
    reply=replace(reply,check_answers=tuple(replace(a,status='violated') if a.check_key.criterion_id=='source_integrity'
                    else a for a in reply.check_answers))
    raw=encode_human_review_response(case['plan'],case['request']['version'],case['request']['fence'],reply,case['proof'])
    with pytest.raises(ApplicationError,match='HUMAN_REVIEW_MECHANICAL_CONFLICT'):
        case['reviews'].record_response(case['plan'].review_id,raw,context('human-replace-integrity'),
                    expected_request_version=case['request']['version'],fence=case['request']['fence'])


def test_missing_human_owner_policy_mismatch_and_old_23_declaration_refuse(human_case):
    case = human_case
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], _reply(case['plan']), case['proof'])
    absent = EngineeringHumanReviewAdmission(case['factory'], case['controls'], case['bindings'],
        None, blobs=case['blobs'], mechanical_source=case['mechanical'])
    with pytest.raises(ApplicationError, match='HUMAN_REVIEW_AUTHORITY_UNAVAILABLE'):
        absent.verify_response(context('missing-human-owner'), case['plan'], None, None)

    wrong = _SyntheticHumanAuthority(SCOPE,
        policy_bytes=_POLICY.replace(b'chat-attested-human-review', b'different-human-review'))
    admission = EngineeringHumanReviewAdmission(case['factory'], case['controls'], case['bindings'],
        wrong, blobs=case['blobs'], mechanical_source=case['mechanical'])
    case['reviews'].admission = admission
    with pytest.raises(ApplicationError, match='HUMAN_REVIEW_POLICY_BINDING_MISMATCH'):
        case['reviews'].record_response(case['plan'].review_id, raw, context('wrong-policy'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])


@pytest.mark.parametrize('answer,mode', [('', 'per_check'), ('继续实施', 'whole_plan'), ('可以干', 'per_check')])
def test_empty_or_implementation_only_reply_remains_pending(human_case, answer, mode):
    case = human_case
    reply = _reply(case['plan'], answer=answer)
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], reply, case['proof'], answer_mode=mode)
    with pytest.raises(ApplicationError, match='HUMAN_REVIEW_ANSWER_PENDING'):
        case['reviews'].record_response(case['plan'].review_id, raw, context('pending-human-answer'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])
    with case['factory'].begin(SCOPE, 'read') as uow:
        assert uow.reviews.get_request(case['plan'].review_id).state == 'requested'
        assert uow.commands.get(context('pending-human-answer').key) is None


def test_missing_full_plan_key_and_policy_not_declared_in_23_are_rejected(human_case):
    case = human_case
    reply = _reply(case['plan'], omit=case['plan'].check_keys[-1])
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], reply, case['proof'])
    with pytest.raises(ApplicationError, match='MANUAL_REVIEW_REPLY_INCOMPLETE'):
        case['reviews'].record_response(case['plan'].review_id, raw, context('missing-human-check'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])


@pytest.mark.parametrize('human_case', [{'release': '2.3.0'}], indirect=True)
def test_human_disposition_is_unavailable_for_23_without_declaration(human_case):
    case = human_case
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], _reply(case['plan']), case['proof'])
    with pytest.raises(ApplicationError, match='HUMAN_REVIEW_NOT_ADMITTED'):
        case['reviews'].record_response(case['plan'].review_id, raw, context('undeclared-23-human'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])


@pytest.mark.parametrize('human_case', [{'no_links': True}], indirect=True)
def test_human_satisfaction_cannot_wash_mechanical_insufficiency(human_case):
    case = human_case
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], _reply(case['plan']), case['proof'])
    with pytest.raises(ApplicationError, match='HUMAN_REVIEW_MECHANICAL_CONFLICT'):
        case['reviews'].record_response(case['plan'].review_id, raw, context('human-wash-attempt'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])


def test_current_attestor_epoch_is_rechecked_after_record(human_case):
    case = human_case
    _record(case)
    case['authority'].epoch = 2
    with pytest.raises(ApplicationError, match='UNTRUSTED_REVIEWER'):
        case['reviews'].gate(case['requirement'], context('attestor-revoked'))


def test_request_withdrawn_during_guard_prevents_review_record_commit(human_case):
    case = human_case
    def withdraw():
        result = case['reviews'].withdraw(case['plan'].review_id, context('withdraw-during-human-guard'),
            expected_request_version=case['request']['version'], fence=case['request']['fence'])
        assert result.status == 'completed'
    case['authority'].on_guard = withdraw
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], _reply(case['plan']), case['proof'])
    result = case['reviews'].record_response(case['plan'].review_id, raw, context('withdrawn-human-record'),
        expected_request_version=case['request']['version'], fence=case['request']['fence'])
    assert result.status == 'rejected'
    assert b'REVIEW_REQUEST_CHANGED' in result.result_bytes
    with case['factory'].begin(SCOPE, 'read') as uow:
        assert not uow.reviews.read_set(ReviewSetKey.for_requirement(case['requirement'])).reviews
        assert uow.commands.get(context('withdrawn-human-record').key).state == 'rejected'


def test_mechanical_and_attestor_guards_remain_held_through_original_run_commit(human_case, monkeypatch):
    case = human_case
    original_run = case['reviews']._run
    reached = []
    def guarded_run(*args, **kwargs):
        assert case['authority'].depth == 1
        assert case['library']._method_guard_fences.values
        reached.append(True)
        return original_run(*args, **kwargs)
    monkeypatch.setattr(case['reviews'], '_run', guarded_run)
    result, _ = _record(case)
    assert result.status == 'completed' and reached == [True]
    assert case['authority'].depth == 0 and not case['library']._method_guard_fences.values

