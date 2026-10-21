"""Finite policy outcomes and genuine new job evidence; no historical rewrite."""
from itertools import product
import pytest
from ordessa_decision import check_summary, digest_hex
from ordessa_engineering.adapters.decision.client import select_review
from ordessa_engineering.domain.artifacts.library_materials import MaterialRef
from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
from ordessa_engineering.domain.reviews.judgement_policy import ReviewFacts

POLICY={'precedence':['CONFLICT','INDETERMINATE','REVISION_REQUIRED','CLEAR'],
        'rules':{'conflict':'CONFLICT','unknown':'INDETERMINATE',
                 'gap':'REVISION_REQUIRED','all_checks_pass':'CLEAR'}}
REF=MaterialRef('original-library','review-policy','policy',7,'sha256:'+'a'*64)


@pytest.mark.parametrize('source,standard,summary,unavailable',product(
    ['SUPPORTED','NEEDS_EVIDENCE','CONFLICT','INDETERMINATE'],
    ['SATISFIED','NEEDS_EVIDENCE','CONFLICT','INDETERMINATE'],
    ['FAITHFUL','CONFLICT','INDETERMINATE'],[False,True]))
def test_native_rules_job_preserves_verdict_precedence_and_exact_evidence(source,standard,summary,unavailable):
    selected=select_review(ReviewFacts(source,standard,summary,unavailable),
        policy_material=POLICY,policy_ref=REF,evidence_refs=('original-check/1','original-check/2'))
    statuses=(source,standard,summary)
    expected=('CONFLICT' if 'CONFLICT' in statuses else
              'INDETERMINATE' if unavailable or 'INDETERMINATE' in statuses else
              'REVISION_REQUIRED' if 'NEEDS_EVIDENCE' in statuses else 'CLEAR')
    assert selected['verdict']==expected
    run=selected['decision_run'];summary=check_summary(selected['decision_evidence'])
    assert run['schema_version']=='engineering-review-job-result/1' and run['status']=='completed'
    assert run['job']['limits']['max_model_calls']==0
    assert summary['job_digest']==digest_hex(run['job'])
    assert summary['input_digest']==digest_hex(run['job']['input'])
    assert summary['result_digest']==digest_hex(expected)
    assert summary['answers']==summary['usage']==summary['receipt']=={}
    assert selected['answer']['schema_version']=='engineering-review-rules-answer/1'
    assert selected['answer']['evidence_refs']==['original-check/1','original-check/2']
    assert selected['answer_digest']==content_digest(selected['answer'])
    assert selected['policy_ref']['revision']==7 and selected['policy_ref']['digest']==REF.digest
    assert 'run_manifest_digest' not in run and 'terminal' not in summary


def test_explicit_authored_policy_precedence_is_preserved():
    policy={**POLICY,'precedence':['REVISION_REQUIRED','CONFLICT','INDETERMINATE','CLEAR']}
    result=select_review(ReviewFacts('CONFLICT','NEEDS_EVIDENCE','FAITHFUL'),
        policy_material=policy,policy_ref=REF,evidence_refs=())
    assert result['verdict']=='REVISION_REQUIRED'


def test_invalid_authored_policy_still_refuses():
    from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
    with pytest.raises(EngineeringError):
        select_review(ReviewFacts('SUPPORTED','SATISFIED','FAITHFUL'),
            policy_material={**POLICY,'precedence':['CLEAR']},policy_ref=REF,evidence_refs=())
