"""Adapter contract tests: real Engineering/SQLite/access, explicit Records fixture.

No actual Unit, native peer, external model, production role selector or method
output decoder is qualified by these fixtures.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
from types import SimpleNamespace

import pytest
import test_engineering_jev_source as existing
from test_engineering_jev_source import original_work
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.reviewer_admission import CriterionAnswer
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_units.records import UnitRecords
from ordessa_server.composition.engineering_unit_reviewer_source import (
    OriginalUnitReviewerSource, RecordedUnitReview, UNIT_REVIEW_SOURCE_CAPABILITY,
    encode_recorded_unit_review, unit_review_prompt_binding,
)


@pytest.fixture(autouse=True)
def source_capability(monkeypatch):
    monkeypatch.setattr(existing, 'OPERATIONS', existing.OPERATIONS + (UNIT_REVIEW_SOURCE_CAPABILITY,))


@pytest.fixture
def specimen(original_work):
    library, factory, access, authority, caller, admitted, plan, request, reviews, admission = original_work
    blobs = SQLiteBlobStore(library)
    unit = {'environmentNamespace':'controlled-unit-env', 'unitId':'reviewer',
            'ownerProviderRef':{'fixture':'explicit'}, 'sourceRevision':'sha256:'+'1'*64}
    author = {**unit, 'unitId':'author'}
    params = {'sessionId':'fixture-session', 'prompt':[{'type':'text', 'text':
        unit_review_prompt_binding(plan, request.version, request.fence, author, unit)}]}
    prompt = UnitRecords.acp_prompt_input_digest(unit, params)
    receipt = {'contractVersion':'unit-acp-turn/1', 'unitRef':unit, 'operationRef':'review-op',
        'inputDigest':prompt, 'input':{'unitRef':unit, 'params':params},
        'revision':3, 'state':'completed', 'summary':{'text':'method fixture answers',
        'stopReason':'end_turn', 'successfulRpcResponse':True}}
    class ExplicitRecords:
        acp_prompt_input_digest = staticmethod(UnitRecords.acp_prompt_input_digest)
        acp_turn_query_digest = staticmethod(UnitRecords.acp_turn_query_digest)
        def query_acp_turn(self, *args, **kwargs):
            return receipt
    records = ExplicitRecords()
    def query(context=None, run=None):
        return SimpleNamespace(facts={'inputDigest': records.acp_turn_query_digest(unit,'review-op',prompt)})
    observation = capture_execution_observation(records,blobs,authority_id=blobs.authority_id,
        unit_ref=unit,operation_ref='review-op',expected_prompt_digest=prompt,query_invocation=query())
    run = RecordedUnitReview(plan.review_id,plan.plan_digest,request.version,request.fence,
        canonical_bytes(author),canonical_bytes(unit),canonical_bytes(params),observation)
    raw = encode_recorded_unit_review(run)
    raw_ref = blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
    policy = {'reject':False, 'held':False}
    @contextmanager
    def guard(context, snapshot, selected_plan, selected_run):
        if policy['reject']:
            raise ApplicationError('METHOD_REVIEWER_CONSTRAINT_FAILED')
        policy['held'] = True
        try: yield
        finally: policy['held'] = False
    def decode(selected_plan, standard, text):
        assert policy['held'] and text == 'method fixture answers'
        return tuple(CriterionAnswer(key,'unknown',(),'Fixture method decoder') for key in plan.check_keys)
    source = OriginalUnitReviewerSource(records=records,blobs=blobs,access=access,scope=existing.SCOPE,
        method_control=admission.methods,runs=(run,),query_factory=query,
        decode_answers=decode,policy_guard=guard,roles=('reviewer',))
    with admitted('engineering.reviews.record','unit-source-specimen') as context:
        with admission.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            standard = next(s for s in snapshot.program.standard_definitions
                if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id)
        yield SimpleNamespace(source=source,run=run,raw_ref=raw_ref,context=context,
            plan=plan,request=request,standard=standard,policy=policy,receipt=receipt,blobs=blobs)


def test_recorded_source_projects_complete_keys_without_grant(specimen):
    s=specimen
    response=s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)
    assert {a.check_key for a in response.answers} == set(s.plan.check_keys)
    assert response.reviewer_evidence.reviewer.actor_kind == 'agent'
    assert not s.policy['held']


def test_stale_request_refuses_before_query(specimen):
    s=specimen
    with pytest.raises(ApplicationError,match='REVIEW_REQUEST_CHANGED'):
        s.source.verify_response(s.context,s.plan,replace(s.request,version=s.request.version+1),s.raw_ref,standard=s.standard)


@pytest.mark.parametrize('state',['unknown','failed','possibly-written'])
def test_noncomplete_never_becomes_review(specimen,state):
    s=specimen; s.receipt['state']=state
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
        s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)


def test_selected_method_policy_can_refuse_actual_identities(specimen):
    s=specimen; s.policy['reject']=True
    with pytest.raises(ApplicationError,match='METHOD_REVIEWER_CONSTRAINT_FAILED'):
        s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)


def test_missing_method_decoder_refuses(specimen):
    s=specimen;s.source.decoder=None
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_AUTHORITY_UNAVAILABLE'):
        s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)


def test_source_cannot_choose_subset(specimen):
    s=specimen; s.source.decoder=lambda *args: ()
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
        s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)


def test_prompt_target_change_refuses(specimen):
    s=specimen;s.receipt['input']={'unitRef':s.receipt['unitRef'],'params':{'sessionId':'different','prompt':[]}}
    with pytest.raises(ApplicationError,match='REVIEW_SOURCE_INCOMPLETE'):
        s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)


def test_current_trust_holds_method_policy_until_consumer_commit(specimen):
    s=specimen
    verified=s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)
    record=SimpleNamespace(plan=s.plan,raw_response_ref=s.raw_ref,
        reviewer_evidence=verified.reviewer_evidence,ref=ReviewRef(s.plan.scope.realm_id,s.plan.scope.project_id,s.plan.review_id,Digest('sha256','f'*64)))
    with s.source.guard_trust(s.context,(record,)) as current:
        assert s.policy['held']
        assert len(current)==1
    assert not s.policy['held']


def test_historical_record_does_not_require_request_still_requested(specimen):
    s=specimen
    verified=s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)
    record=SimpleNamespace(plan=s.plan,raw_response_ref=s.raw_ref,
        reviewer_evidence=verified.reviewer_evidence,ref=ReviewRef(s.plan.scope.realm_id,s.plan.scope.project_id,s.plan.review_id,Digest('sha256','f'*64)))
    # No requested-state projection is passed to historical current-trust read.
    with s.source.guard_trust(s.context,(record,)) as current:
        assert current[0].trust_version==verified.reviewer_evidence.trust_version


def test_changed_current_policy_rejects_old_captured_evidence(specimen):
    s=specimen
    verified=s.source.verify_response(s.context,s.plan,s.request,s.raw_ref,standard=s.standard)
    record=SimpleNamespace(plan=s.plan,raw_response_ref=s.raw_ref,
        reviewer_evidence=verified.reviewer_evidence,ref=ReviewRef(s.plan.scope.realm_id,s.plan.scope.project_id,s.plan.review_id,Digest('sha256','f'*64)))
    s.policy['reject']=True
    with pytest.raises(ApplicationError,match='METHOD_REVIEWER_CONSTRAINT_FAILED'):
        with s.source.guard_trust(s.context,(record,)):
            pytest.fail('revoked method selection admitted')
