import dataclasses
import pytest
from decision_runtime.definitions import *

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
