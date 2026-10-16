"""Real published fixture snapshot/standard; no production Unit/reviewer assertion."""
import json
from copy import deepcopy
from dataclasses import asdict, replace
import pytest
from test_method_control_admission import env, build_plan, context
from ordessa_engineering.application.orchestration.unit_review_answers import decode_unit_review_result
from ordessa_engineering.application.usecases.reviews.admission import review_observations
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.methods.definitions.models import MethodRef as SnapshotRef


@pytest.fixture
def review(env):
    _,method,_,_,controls=env
    plan,_=build_plan(env)
    snapshot=controls.snapshots.get(SnapshotRef(method.method_id,method.release_version,
                                               method.schema_version,method.snapshot_digest.hex))
    standard=next(s for s in snapshot.program.standard_definitions
                  if s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id)
    value={'schema_version':1,'document_type':'test-document','plan_digest':asdict(plan.plan_digest),
           'answers':[{'check_key':asdict(key),'status':'unknown','evidence_refs':[],
                       'rationale':'No independent proof for this item.'} for key in plan.check_keys]}
    return plan,standard,snapshot,value


def decode(review,value=None,text=None):
    plan,standard,snapshot,original=review
    return decode_unit_review_result(plan,standard,json.dumps(original if value is None else value) if text is None else text,
        snapshot=snapshot,document_type='test-document')


def test_full_exact_plan_preserves_unknown_and_canonicalizes_row_order(review):
    plan,standard,_,value=review
    value['answers'].reverse()
    answers=decode(review)
    assert tuple(a.check_key for a in answers)==plan.check_keys
    assert all(a.status=='unknown' and not a.evidence_refs for a in answers)
    assert all(o.result=='indeterminate' for o in review_observations(plan,standard,answers))


def test_semantic_satisfied_uses_actual_method_policy_not_automatic_pass(review):
    plan,standard,_,value=review
    for row in value['answers']: row['status']='satisfied'
    assert all(o.result=='indeterminate' for o in review_observations(plan,standard,decode(review)))


@pytest.mark.parametrize('mutation',[
    lambda v:v['plan_digest'].update(hex='a'*64),
    lambda v:v['answers'].pop(),
    lambda v:v['answers'].append(deepcopy(v['answers'][0])),
    lambda v:v['answers'].append({**deepcopy(v['answers'][0]),'status':'satisfied'}),
    lambda v:v['answers'][0]['check_key']['target']['ref'].update(revision_id='different-fixed-version'),
    lambda v:v['answers'][0]['check_key'].update(claim_id='foreign-claim'),
    lambda v:v['answers'][0]['check_key'].update(criterion_id='foreign-criterion'),
    lambda v:v.update(accepted=True),
    lambda v:v.update(document_type='caller-selected-schema'),
    lambda v:v.update(schema_version=True),
    lambda v:v['answers'][0].update(status='pass'),
    lambda v:v['answers'][0].update(rationale=''),
])
def test_wrong_plan_partial_duplicate_foreign_version_and_verdict_fields_refuse(review,mutation):
    value=deepcopy(review[3]);mutation(value)
    with pytest.raises(ApplicationError): decode(review,value=value)


def test_same_count_duplicate_key_with_different_status_refuses(review):
    value=deepcopy(review[3])
    if len(value['answers'])==1:
        value['answers'].append({**deepcopy(value['answers'][0]),'status':'satisfied'})
    else:
        value['answers'][1]={**deepcopy(value['answers'][0]),'status':'satisfied'}
    with pytest.raises(ApplicationError,match='UNIT_REVIEW_RESPONSE_INCOMPLETE'):
        decode(review,value=value)


def test_duplicate_json_property_truncation_and_bound_refuse(review):
    original=json.dumps(review[3])
    texts=[original[:-1],original.replace('"schema_version": 1','"schema_version": 1, "schema_version": 1'),
           'x'*262145]
    for text in texts:
        with pytest.raises(ApplicationError,match='UNIT_REVIEW_RESPONSE_INVALID'):
            decode(review,text=text)


def test_evidence_foreign_scope_and_duplicate_exact_refs_refuse(review):
    value=deepcopy(review[3]);ref=asdict(review[0].check_keys[0].target.ref)
    ref['project_id']='foreign-project';value['answers'][0]['evidence_refs']=[ref]
    with pytest.raises(ApplicationError,match='UNIT_REVIEW_EVIDENCE_SCOPE_MISMATCH'): decode(review,value=value)
    ref=asdict(review[0].check_keys[0].target.ref);value['answers'][0]['evidence_refs']=[ref,ref]
    with pytest.raises(ApplicationError,match='UNIT_REVIEW_EVIDENCE_SCOPE_MISMATCH'): decode(review,value=value)
