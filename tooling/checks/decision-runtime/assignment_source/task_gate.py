"""Finite task review. Policies and host facts supply all business decisions.

This module neither generates tasks nor grants authority. Model answers select
catalogue codes; explanations come exclusively from trusted safe templates.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
from decision_runtime.definitions import (TaskBrief, PolicyRef, DecisionQuestion,
    DecisionAnswer, ExternalRef, canonical, digest, freeze, plain)
from decision_runtime.runtime import RuntimeFailure

class PolicyInvalid(RuntimeFailure):
    def __init__(self): super().__init__('policy_invalid')

@dataclass(frozen=True)
class GateResult:
    status: str
    issues: tuple = ()
    def __post_init__(self):
        if self.status not in ('gate_pass','clarify','revise','blocked'):
            raise RuntimeFailure('gate_status_invalid')
        object.__setattr__(self,'issues',freeze(plain(self.issues)))
        if self.status == 'gate_pass' and self.issues:
            raise RuntimeFailure('gate_pass_with_issues')

@dataclass(frozen=True)
class GatePlan:
    signature: str
    policy_ref: PolicyRef
    policy: Mapping
    facts: Mapping
    questions: tuple
    hard_result: GateResult | None

@dataclass(frozen=True)
class GateReview:
    run_id: str
    signature: str
    result: GateResult

def load_task_gate_policy():
    return freeze(json.loads(Path(__file__).with_name('task_gate_policy.json').read_text()))

def _policy(policy):
    try:
        value = freeze(plain(policy))
        if set(value) - {'input_projection'} != {'schema_version','policy_id','version','applicable_task_categories',
            'max_rounds','aggregate_precedence','dimensions','hard_checks','fact_checks',
            'code_catalog','templates'}: raise ValueError()
        if value['schema_version'] != 'task-gate/1': raise ValueError()
        if not value['policy_id'] or not value['version'] or not value['applicable_task_categories']:
            raise ValueError()
        projection = value.get('input_projection')
        if projection is not None:
            if (set(projection) != {'version','fields','max_entries','max_text_bytes','trust_classifications','reference_identity_fields'}
                    or projection['version'] != 'task-input-summary/1'
                    or not {'source_ref','description','trust_classification'} <= set(projection['fields'])
                    or set(projection['fields']) - {'source_ref','source_version','description','trust_classification','content_summary','requirement_ids'}
                    or len(set(projection['fields'])) != len(projection['fields'])
                    or any(type(projection[k]) is not int or projection[k] <= 0 for k in ('max_entries','max_text_bytes'))
                    or not projection['trust_classifications']
                    or any(type(v) is not str or not v for v in projection['trust_classifications'])
                    or not projection['reference_identity_fields']
                    or any(type(v) is not str or not v for v in projection['reference_identity_fields'])):
                raise ValueError()
        if type(value['max_rounds']) is not int or not 1 <= value['max_rounds'] <= 16:
            raise ValueError()
        if tuple(value['aggregate_precedence']) != ('fatalBusinessBlock','clarify','revise','gate_pass'):
            raise ValueError()
        dimensions = value['dimensions']
        if len(dimensions) != 6 or len({d['id'] for d in dimensions}) != 6:
            raise ValueError()
        catalog, templates = value['code_catalog'], value['templates']
        for code, entry in catalog.items():
            if not code or entry['status'] not in ('clarify','revise','blocked') or entry['remedy_actor'] not in ('main_agent','user','owner'):
                raise ValueError()
            if entry['status'] == 'blocked' and entry.get('fatal_business_block') is not True:
                raise ValueError()
            template = templates[entry['template_id']]
            if not isinstance(template,str) or len(template)>2048 or '{' in template or '}' in template:
                raise ValueError()
            if tuple(entry['allowed_template_params']) != ('dimension_label',):
                raise ValueError()
        for dimension in dimensions:
            if set(dimension) != {'id','label','required','question_text','answers'}:
                raise ValueError()
            if not isinstance(dimension['label'],str) or not 0 < len(dimension['label']) <= 128:
                raise ValueError()
            if type(dimension['required']) is not bool or not isinstance(dimension['question_text'],str):
                raise ValueError()
            if set(dimension['answers']) != {'pass','fail','unknown'}:
                raise ValueError()
            if dimension['answers']['pass']['code'] is not None:
                raise ValueError()
            for answer in ('fail','unknown'):
                if dimension['answers'][answer]['code'] not in catalog:
                    raise ValueError()
            if dimension['required'] and catalog[dimension['answers']['unknown']['code']]['status'] != 'clarify':
                raise ValueError()
        for hard in value['hard_checks']:
            if hard['field'] not in ('goal','boundaries','acceptance_criteria') or hard['code'] not in catalog:
                raise ValueError()
        for code in value['fact_checks'].values():
            if code not in catalog: raise ValueError()
        return value
    except Exception:
        raise PolicyInvalid() from None

def _facts(ctx, facts):
    if facts is None:
        facts = ctx.services.policy.get('task_gate_facts', {})
    try:
        value = freeze(plain(facts))
        allowed = {'source_ref','source_version','evidence_refs','task_category',
            'known_goal_present','submitted_goal_matches','requires_confirmation',
            'confirmation_status','known_business_conflict','affected_requirement_ids'}
        if not isinstance(value,Mapping) or set(value)-allowed: raise ValueError()
        for field in ('known_goal_present','submitted_goal_matches','requires_confirmation','known_business_conflict'):
            if field in value and type(value[field]) is not bool: raise ValueError()
        if value.get('confirmation_status','unknown') not in ('confirmed','unknown','refused'):
            raise ValueError()
        for field in ('evidence_refs','affected_requirement_ids'):
            if field in value and (not isinstance(value[field],tuple) or any(not isinstance(v,str) or not v or len(v)>256 for v in value[field])):
                raise ValueError()
        # Facts without a source/version/evidence are unknown, never authority.
        if value and (not value.get('source_ref') or not value.get('source_version') or not value.get('evidence_refs')):
            raise ValueError()
        return value
    except Exception:
        raise RuntimeFailure('task_gate_facts_invalid') from None

def _issue(policy, code, dimension_id, facts, *, fact_based=False):
    try:
        entry = policy['code_catalog'][code]
        dimension = next(d for d in policy['dimensions'] if d['id'] == dimension_id)
        if entry['status'] == 'blocked' and (not fact_based or facts.get('known_business_conflict') is not True):
            raise PolicyInvalid()
        # Template parameters are trusted labels, never task/response text.
        params = {'dimension_label':dimension['label']}
        return freeze({'code':code, 'dimension_id':dimension_id,
            'affected_requirement_ids':facts.get('affected_requirement_ids',()),
            'remedy_actor':entry['remedy_actor'], 'template_id':entry['template_id'],
            'template_params':params, 'evidence_refs':facts.get('evidence_refs',()),
            'explanation':policy['templates'][entry['template_id']]})
    except (KeyError,StopIteration):
        raise PolicyInvalid() from None

def _aggregate(policy, issues):
    statuses = {policy['code_catalog'][issue['code']]['status'] for issue in issues}
    if 'blocked' in statuses: return GateResult('blocked',tuple(issues))
    if 'clarify' in statuses: return GateResult('clarify',tuple(issues))
    if 'revise' in statuses: return GateResult('revise',tuple(issues))
    return GateResult('gate_pass')

def _input_context(task, policy):
    """Project explicit safe summaries as data; never resolve their references.

    Opaque/display input is not new task evidence. Structured source summaries
    are included in both questions and the review signature, including revisions.
    Their trust labels never become the host's confirmation or authority facts.
    """
    config = policy.get('input_projection')
    if config is None:
        return {}
    sensitive = {'apikey','password','accesstoken','authorization','privatekey','clientsecret',
                 'token','cookie','secret','credentials','credential','bearer','refreshtoken'}
    def norm(value): return value.lower().replace('_','').replace('-','')
    def reference(value):
        ref = ExternalRef.from_dict(plain(value))
        for key, child in ref.identity.items():
            if norm(key) in sensitive:
                raise RuntimeFailure('task_input_sensitive')
            if key not in config['reference_identity_fields'] or type(child) not in (str,int,type(None)):
                raise RuntimeFailure('task_input_ref_unsupported')
            if isinstance(child,str):
                url = urlsplit(child) if '://' in child else None
                if child.lower().startswith('bearer ') or (url and (url.username or url.password
                        or any(norm(k) in sensitive for k,_ in parse_qsl(url.query)))):
                    raise RuntimeFailure('task_input_sensitive')
        canonical(ref,max_bytes=config['max_text_bytes'])
        return plain(ref)
    inputs = []
    for item in task.inputs:
        if not isinstance(item, Mapping) or item.get('purpose') == 'display':
            continue
        if item.get('purpose','task_evidence') != 'task_evidence':
            raise RuntimeFailure('task_input_purpose_unknown')
        if not {'source_ref','description','trust_classification'} <= set(item):
            if 'purpose' in item or {'source_ref','content_summary','trust_classification'} & set(item):
                raise RuntimeFailure('task_input_incomplete')
            # Generic extension/display metadata is not a source-backed summary.
            continue
        if item['trust_classification'] not in config['trust_classifications']:
            raise RuntimeFailure('task_input_trust_unknown')
        projected = {k:plain(item[k]) for k in config['fields'] if k in item}
        projected['source_ref'] = reference(item['source_ref'])
        for key in ('description','content_summary'):
            if key in projected and (type(projected[key]) is not str
                    or len(projected[key].encode('utf-8')) > config['max_text_bytes']):
                raise RuntimeFailure('task_input_size')
        if 'source_version' in projected and projected['source_version'] is not None and (type(projected['source_version']) is not str or not projected['source_version']):
            raise RuntimeFailure('task_input_version')
        if 'requirement_ids' in projected and (not isinstance(projected['requirement_ids'],list)
                or any(type(v) is not str or not v for v in projected['requirement_ids'])):
            raise RuntimeFailure('task_input_requirements')
        canonical(projected,max_bytes=config['max_text_bytes'])
        inputs.append(projected)
    contexts = [reference(value) for value in task.context_refs]
    if len(inputs)>config['max_entries'] or len(contexts)>config['max_entries']:
        raise RuntimeFailure('task_input_size')
    return {'role':'task_data_not_authority','inputs':inputs,'context_refs':contexts,
            'continuation_ref':reference(task.continuation_ref) if task.continuation_ref else None}

def compile_task_gate(task, ctx, policy, *, facts=None, policy_ref=None):
    """Pure compile stage for separate HardTaskGate and AssessTask nodes."""
    if not isinstance(task,TaskBrief): raise RuntimeFailure('task_gate_task_invalid')
    policy, facts = _policy(policy), _facts(ctx,facts)
    expected = PolicyRef(policy['policy_id'],policy['version'],digest('policy',policy))
    if policy_ref is None:
        policy_ref = next((ref for ref in ctx.services.policy_refs if ref == expected),None)
    if policy_ref != expected or policy_ref not in ctx.services.policy_refs:
        raise PolicyInvalid()
    category = facts.get('task_category','general')
    if category not in policy['applicable_task_categories']:
        raise PolicyInvalid()
    input_context = _input_context(task,policy)
    relevant = {'task_id':task.task_id,'task_revision':task.task_revision,'goal':task.goal,
        'boundaries':task.boundaries,'acceptance_criteria':task.acceptance_criteria,
        'policy_digest':digest('policy',policy),'facts':facts,'input_context':input_context}
    signature = digest('feedback',relevant)
    issues = []
    for check in policy['hard_checks']:
        value = getattr(task,check['field'])
        missing = not value.strip() if isinstance(value,str) else not value
        if missing:
            issues.append(_issue(policy,check['code'],check['dimension_id'],facts))
    checks = policy['fact_checks']
    if 'requires_confirmation' not in facts:
        issues.append(_issue(policy,checks['risk_facts_missing'],'risk_boundary',facts))
    if facts.get('known_goal_present') and facts.get('submitted_goal_matches') is False:
        issues.append(_issue(policy,checks['known_goal_omitted'],'goal_specificity',facts,fact_based=True))
    if facts.get('requires_confirmation') and facts.get('confirmation_status') != 'confirmed':
        issues.append(_issue(policy,checks['confirmation_missing'],'risk_boundary',facts,fact_based=True))
    if facts.get('known_business_conflict'):
        issues.append(_issue(policy,checks['known_business_conflict'],'scope_consistency',facts,fact_based=True))
    questions = []
    if not issues:
        for dimension in policy['dimensions']:
            options = {key:{'description':answer['description'],'code':answer['code']} for key,answer in dimension['answers'].items()}
            questions.append(DecisionQuestion('task-gate.'+dimension['id'],policy['version'],'choice',
                {'task':{'goal':task.goal,'boundaries':task.boundaries,'acceptance_criteria':task.acceptance_criteria},
                 'input_context':input_context,'facts':facts,'dimension_id':dimension['id'],'required':dimension['required']},
                dimension['question_text'],options=options,evidence_ids=facts.get('evidence_refs',()),policy_ref=policy_ref))
    return GatePlan(signature,policy_ref,policy,facts,tuple(questions),_aggregate(policy,issues) if issues else None)

def reduce_task_gate(plan, answers):
    """Validate the complete finite answer set and aggregate all defects."""
    if plan.hard_result is not None:
        if answers: raise RuntimeFailure('task_gate_unexpected_answers')
        return plan.hard_result
    if len(answers) != len(plan.questions): raise RuntimeFailure('task_gate_answer_set')
    issues = []
    for dimension,question,answer in zip(plan.policy['dimensions'],plan.questions,answers):
        if not isinstance(answer,DecisionAnswer) or answer.question_id!=question.question_id or answer.kind!='choice':
            raise RuntimeFailure('task_gate_answer_mismatch')
        if not isinstance(answer.value,str) or answer.value not in question.options:
            raise RuntimeFailure('task_gate_answer_code')
        code = dimension['answers'][answer.value]['code']
        if code is not None:
            issues.append(_issue(plan.policy,code,dimension['id'],plan.facts))
    return _aggregate(plan.policy,issues)

async def assess_task(task, ctx, policy, *, facts=None, prior=None, policy_ref=None):
    """One assessment per new relevant signature; no global/free rerun cache."""
    plan = compile_task_gate(task,ctx,policy,facts=facts,policy_ref=policy_ref)
    reviews = getattr(ctx,'_task_gate_reviews',None)
    if reviews is None:
        reviews = {}
        ctx._task_gate_reviews = reviews
    if prior is not None:
        if not isinstance(prior,GateReview) or prior.run_id!=ctx.run_id:
            raise RuntimeFailure('task_gate_prior_untrusted')
        if prior.signature == plan.signature: return prior.result
    if plan.signature in reviews: return reviews[plan.signature].result
    if len(reviews) >= plan.policy['max_rounds']:
        ctx.exhaust('max_repair_rounds')
    if reviews:
        await ctx.enter_repair()
    if plan.hard_result is not None:
        result = plan.hard_result
    else:
        answers = tuple([await ctx.gateway.decide(question) for question in plan.questions])
        result = reduce_task_gate(plan,answers)
    reviews[plan.signature] = GateReview(ctx.run_id,plan.signature,result)
    return result
