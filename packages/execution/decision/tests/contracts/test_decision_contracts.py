import dataclasses
import pytest
from ordessa_decision.definitions import *

def ref(ns='local'): return ExternalRef(ns,{'id':'same','revision':'1'})
def proposal():
    return ProposalDraft('p','agent.assignment/1',{'action':'create','configuration':{'new.kind':0.7}},required_validation_obligations=(ValidationObligation('config',ref(),'must','owner','1'),))
def receipt(p, results=()):
    return ValidationReceipt('v','1',p.proposal_digest,'valid',results,'2026-10-05T00:00:00Z','pure_read')

def test_T01_finite_json_and_freeze():
    task=TaskBrief('t','1','',inputs=({'value':[0.7]},))
    assert canonical(task)
    with pytest.raises(TypeError): task.inputs[0]['value']=3
    for v in ({1:'a'},{'x':float('nan')},{'x':object()}):
        with pytest.raises(ContractError): canonical(v)
    with pytest.raises(ContractError): decode(b'{"a":1,"a":2}')
    with pytest.raises(ContractError): decode(b'{"x":Infinity}')
    with pytest.raises(ContractError): canonical({'x':[[[[[]]]]]},max_bytes=2)

def test_T02_T66_vectors_and_domains():
    assert canonical({'b':0.7,'a':'中文'})=='{"a":"中文","b":0.7}'.encode()
    assert digest('request',{'a':1,'b':2})==digest('request',{'b':2,'a':1})
    assert digest('proposal',ref())!=digest('proposal',ref('other'))
    assert digest('proposal',{})!=digest('result',{})
    f=FlowRef('flow','1','sha256:x'); l=RunLimits()
    assert RunManifest('req',f,(PolicyRef('p','1','a'),),l,'fake').manifest_digest!=RunManifest('req',f,(PolicyRef('p','1','b'),),l,'fake').manifest_digest

def test_T07_terminal_union():
    args=dict(run_id='r',request_id='q',task_revision='1',flow_ref=FlowRef('f','1','d'),run_manifest_digest='d',effective_policy_refs=())
    with pytest.raises(ContractError): DecisionResult(**args,status='failed',outcome=BusinessOutcome('clarify'),error_code='e')
    with pytest.raises(ContractError): BusinessOutcome('ready')
    with pytest.raises(ContractError): DecisionResult(**args,status='budget_exhausted')

def test_T08_T65_receipt_coverage():
    p=proposal()
    with pytest.raises(ContractError): validate_ready(p,receipt(p))
    r=receipt(p,(ObligationResult('config','passed','owner','1',{'source':'1'},('owner-evidence',)),))
    validate_ready(p,r)
    with pytest.raises(ContractError): validate_ready(dataclasses.replace(p,payload={'action':'create','value':0.8}),r)
    for status in ('unknown','failed','notApplicable'):
        with pytest.raises(ContractError): validate_ready(p,receipt(p,(ObligationResult('config',status,'owner','1'),)))

def test_T09_T10_T17_T18_unknown():
    assert ObservationBatch('q',(),False,'filtered').complete is False
    with pytest.raises(ContractError): ReadContext(None,'scope')
    req=dict(request_id='q',task=TaskBrief('t','1',''),flow_ref=FlowRef('f','1','d'))
    with pytest.raises(ContractError): DecisionRequest.from_dict({**req,'principal':'root'})
    c=Precondition('c','version',ref(),None,'sha256:x','must','owner','1')
    with pytest.raises(ContractError): CheckBatch((ObligationResult('c','passed','owner','1',{'c':'1'}),),True).require((c,))
    p=dataclasses.replace(proposal(),preconditions=(c,))
    with pytest.raises(ContractError): validate_ready(p,receipt(p,(ObligationResult('config','passed','owner','1',{},('e',)),)))


def _sized_question(size):
    def build(filler):
        return DecisionQuestion('q','1','choice',{'filler':filler},'Choose the finite option.',
            options={'a':'A','b':'B'}, allowed_answer_ids=('a','b'),
            policy_ref=PolicyRef('p','1','d'))
    base=len(canonical(build(''),max_string=524288,max_bytes=524288))
    return build('x'*(size-base))

def test_T67_complete_question_budget_is_512kib_at_its_own_boundary():
    limit=524288
    question=_sized_question(limit)
    assert len(canonical(question,max_string=limit,max_bytes=limit))==limit
    with pytest.raises(ContractError,match='json_size'): _sized_question(limit+1)

def test_T68_shared_codec_defaults_stay_64kib_string_and_256kib_object():
    assert canonical({'text':'x'*65536})
    with pytest.raises(ContractError,match='string_size'): canonical({'text':'x'*65537})
    payload={f'k{i}':'x'*60000 for i in range(5)}
    with pytest.raises(ContractError,match='json_size'): canonical(payload)
    assert canonical(payload,max_bytes=524288)
    assert canonical({'text':'x'*100000},max_string=524288)
    assert digest('request',{'a':1})==digest('request',{'a':1},max_string=65536,max_bytes=2097152)
    # the widened question budget is not handed to any other DTO
    with pytest.raises(ContractError,match='string_size'): TaskBrief('t','1','',inputs=({'text':'x'*65537},))

def test_T69_only_the_complete_question_widens_the_budget_and_binds_its_digest():
    question=_sized_question(524288)
    assert question.question_digest==digest('question',question,max_string=524288,max_bytes=524288)
    with pytest.raises(ContractError,match='string_size'): digest('question',question)
    with pytest.raises(ContractError,match='string_size'): canonical(question)
    # five <64KiB strings: the DTO admits ~300KiB, the shared 256KiB object default still refuses
    widened=DecisionQuestion('q','1','choice',{'filler':{f'k{i}':'x'*60000 for i in range(5)}},
        'Choose the finite option.',options={'a':'A','b':'B'},allowed_answer_ids=('a','b'),
        policy_ref=PolicyRef('p','1','d'))
    with pytest.raises(ContractError,match='json_size'): canonical(widened)
