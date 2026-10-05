"""Prepare finite Jev questions without SDK, credentials or network calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from ordessa_decision.contracts import TaskBrief, PolicyRef, digest
from ordessa_decision.flows.agent_assignment.task_gate import compile_task_gate, load_task_gate_policy

def prepare():
    samples=json.loads(Path(__file__).with_name('jev-domain-samples.json').read_text())
    policy=load_task_gate_policy()
    ref=PolicyRef(policy['policy_id'],policy['version'],digest('policy',policy))
    facts={'source_ref':'synthetic-evaluator/1','source_version':'1','evidence_refs':('synthetic-labels/1',),
           'requires_confirmation':False,'task_category':'general'}
    ctx=SimpleNamespace(services=SimpleNamespace(policy={},policy_refs=(ref,)))
    cases=[]
    for sample in samples['samples']:
        task=TaskBrief(sample['id'],'1',sample['task'],boundaries=('只读评测，不授权任何实际操作。',),
                       acceptance_criteria=('按预先标签评估，不降低门槛。',))
        plan=compile_task_gate(task,ctx,policy,facts=facts,policy_ref=ref)
        cases.append({'id':sample['id'],'label':sample['label'],'question_digests':[q.question_digest for q in plan.questions],
                      'question_count':len(plan.questions),'hard_result':plan.hard_result.status if plan.hard_result else None})
    return {'status':'PREPARED_NOT_RUN','sample_digest':digest('policy',samples),'policy_ref':ref.to_dict(),
            'model':samples['model'],'cases':cases,'rubric_question_count':sum(c['question_count'] for c in cases),
            'real_model_requests':0,'credential_reads':0,'allowed_attempts':0,
            'note':'Synthetic question compilation only. Host risk facts here are evaluator fixtures, never authority for product tasks.'}

if __name__=='__main__': print(json.dumps(prepare(),ensure_ascii=False,indent=2))
