"""Original ReviewPolicy via real current job runner; no model/Grant/UoW claim."""
import itertools,json,shutil,subprocess,sys
from pathlib import Path
import pytest
from decision_runtime import check_summary,DecisionError,validate_job
from ordessa_engineering.adapters.decision.client import select_review
from ordessa_engineering.domain.reviews.judgement_policy import ReviewFacts,ReviewPolicy
from ordessa_engineering.domain.reviews.library_judgements import ReviewVerdict
from ordessa_engineering.domain.artifacts.library_materials import MaterialRef
from ordessa_engineering.domain.artifacts.library_material_codec import content_digest

ROOT=Path(__file__).parents[3]
RULES={'conflict':'CONFLICT','unknown':'INDETERMINATE','gap':'REVISION_REQUIRED','all_checks_pass':'CLEAR'}
POLICY={'precedence':list(ReviewVerdict.ALL),'rules':RULES}
REF=MaterialRef('fixture','review-policy','policy',1,'sha256:'+'a'*64)


def test_original_policy_full_status_matrix_current_job_summary_and_zero_calls():
    policy=ReviewPolicy(tuple(POLICY['precedence']),RULES)
    for source,standard,summary,unavailable in itertools.product(
        ('SUPPORTED','NEEDS_EVIDENCE','CONFLICT','INDETERMINATE','INVALID'),
        ('SATISFIED','NEEDS_EVIDENCE','GAP','CONFLICT','INDETERMINATE','INVALID'),
        ('FAITHFUL','CONFLICT','INDETERMINATE','INVALID'),(False,True)):
        facts=ReviewFacts(source,standard,summary,unavailable)
        value=select_review(facts,policy_material=POLICY,policy_ref=REF,evidence_refs=('existing-check:1',))
        assert value['verdict']==policy._select(facts.as_dict())
        job=validate_job(value['decision_run']['job'])
        assert job.limits['max_model_calls']==0 and {s['type'] for s in job.steps}=={'rules'}
        evidence=check_summary(value['decision_evidence'])
        assert evidence['answers']=={} and evidence['usage']=={} and evidence['receipt']=={}
        assert value['answer_digest']==content_digest(value['answer'])
        assert value['answer']['job_digest']==evidence['job_digest']
        assert value['answer']['result_digest']==evidence['result_digest']
        assert value['policy_ref']==value['answer']['policy_ref']


def test_review_receipt_binds_original_policy_facts_and_evidence_no_raw_report():
    args={'facts':ReviewFacts('SUPPORTED','SATISFIED','FAITHFUL'),'policy_material':POLICY,'policy_ref':REF,'evidence_refs':('check:1',)}
    first=select_review(**args)
    for changed in ({'facts':ReviewFacts('CONFLICT','SATISFIED','FAITHFUL')},
        {'policy_ref':MaterialRef('fixture','review-policy','policy',2,'sha256:'+'b'*64)},
        {'evidence_refs':('check:2',)}, {'policy_material':{**POLICY,'precedence':list(reversed(POLICY['precedence']))}}):
        result=select_review(**{**args,**changed})
        assert result['answer_digest']!=first['answer_digest']
    with pytest.raises(DecisionError):check_summary({**first['decision_evidence'],'response':'must-not-be-captured'})
    assert 'pydantic_graph' not in sys.modules


def test_one_current_registry_with_archived_c09_data_and_drift_refusal(tmp_path,monkeypatch):
    # Build local own source only; no pip/install and no fake external metadata.
    stage=tmp_path/'decision';stage.mkdir()
    for name in ('pyproject.toml','README.md'):shutil.copy2(ROOT/'packages/execution/decision'/name,stage/name)
    shutil.copytree(ROOT/'packages/execution/decision/src',stage/'src',ignore=shutil.ignore_patterns('__pycache__','*.egg-info'))
    built=subprocess.run([sys.executable,'-c','import setuptools.build_meta as b;b.build_wheel("wheel")'],cwd=stage,capture_output=True,text=True,timeout=20)
    assert built.returncode==0,built.stderr
    monkeypatch.syspath_prepend(str(next((stage/'wheel').glob('*.whl'))))
    from ordessa_engineering.adapters.registry import loading
    import importlib.util
    current=loading.load_registry()
    older=json.loads((ROOT/'docs/migration/engineering-c09-retirement-20261019/operation_registry.v1.json').read_bytes())
    assert older['registry_digest']==content_digest({k:v for k,v in older.items() if k!='registry_digest'})
    assert len(older['operations'])==9 and len(current['operations'])==23
    assert set(older['operations']).isdisjoint(current['operations'])
    for name in ('workflow','registry','fixture','resources','models'):
        assert importlib.util.find_spec('ordessa_engineering.'+name) is None
    assert current['implementation']['decision_contract_version']=='decision-job/1'
    assert current['implementation']['decision_primitives']==['rules','ask']
    assert 'pydantic_graph_version' not in current['implementation']
    changed=json.loads(json.dumps(current));changed['implementation']['decision_primitives']=['ask']
    changed['implementation_digest']=content_digest(changed['implementation'])
    changed['registry_digest']=content_digest({k:v for k,v in changed.items() if k!='registry_digest'})
    monkeypatch.setattr(loading,'_manifest',lambda:changed)
    with pytest.raises(Exception,match='operation_registry_source_drift'):loading.load_registry()
