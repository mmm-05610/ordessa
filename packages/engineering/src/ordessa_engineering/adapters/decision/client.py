"""Finite review selection through decision-job/1 rules, zero model calls.

Engineering owns ReviewPolicy and its interpretation. Decision owns bounded job
execution and summary evidence. This adapter issues no approvals or grants.
"""
from typing import Any
from decision_runtime import DecisionRunner,RulesOutcome,DecisionError,check_summary
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.reviews.library_judgements import ReviewVerdict
from ordessa_engineering.domain.reviews.judgement_policy import ReviewFacts,ReviewPolicy
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict,content_digest


class _ReviewRules:
    engine_id='engineering-review-policy/1'
    def __init__(self,policy):self.policy=policy
    def validate(self,payload):
        if payload!={'operation':'select-review-verdict'}:raise DecisionError('invalid_payload')
    def evaluate(self,payload,facts):
        verdict=self.policy._select(facts['input']['facts'])
        return RulesOutcome(values={'verdict':verdict},disposition='passed')
    def close(self):pass


def select_review(facts:ReviewFacts,*,policy_material:dict[str,Any],policy_ref,evidence_refs:tuple[str,...])->dict[str,Any]:
    if type(facts) is not ReviewFacts or type(evidence_refs) is not tuple or any(type(v) is not str or not v for v in evidence_refs):
        raise EngineeringError('review_facts_invalid')
    policy=ReviewPolicy(tuple(policy_material.get('precedence',())),policy_material.get('rules',{}))
    ref=material_ref_to_dict(policy_ref)
    job={'spec_version':'decision-job/1','job_id':'engineering-review','version':1,
        'input':{'facts':facts.as_dict(),'policy_ref':ref,'policy_digest':content_digest(policy_material),
            'evidence_refs':list(evidence_refs)},
        'limits':{'max_model_calls':0,'max_steps':1,'max_value_bytes':65536,'timeout_seconds':10.0},
        'steps':[{'id':'select-review-verdict','type':'rules','engine':None,'when':{'fact':'input.policy_digest','op':'eq','value':content_digest(policy_material)},
            'payload':{'operation':'select-review-verdict'}}],
        'result':{'from':'select-review-verdict','path':['values','verdict']}}
    result=DecisionRunner(default_engine=_ReviewRules(policy)).run(job)
    if result.status!='completed' or result.data is None or result.data.get('result') not in ReviewVerdict.ALL:
        raise EngineeringError('decision_review_unavailable')
    summary=check_summary(result.evidence)
    verdict=result.data['result']
    answer={'schema_version':'engineering-review-rules-answer/1','verdict':verdict,
        'policy_ref':ref,'policy_digest':job['input']['policy_digest'],
        'facts_digest':content_digest(facts.as_dict()),'evidence_refs':list(evidence_refs),
        'job_digest':summary['job_digest'],'result_digest':summary['result_digest']}
    return {'verdict':verdict,'decision_run':{'schema_version':'engineering-review-job-result/1',
        'status':result.status,'data':result.data,'job':job},'decision_evidence':summary,
        'answer':answer,'answer_digest':content_digest(answer),'policy_ref':ref}
