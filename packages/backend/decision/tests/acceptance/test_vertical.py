"""Real graph, official SDK transport and public temporary core vertical checks."""
import asyncio
import dataclasses
import json
from pathlib import Path
import pytest
import httpx2
from ordessa_decision.contracts import *
from ordessa_decision.offline import *
from ordessa_decision.runtime import run_decision, EvidenceUnknown
from ordessa_decision.providers.jev import JevDecisionProvider, JevProviderSettings
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision.flows.agent_assignment.build import build_assignment_flow

@pytest.mark.parametrize('action',['continue','reuse','restore','wait','reconfigure','create','noDelegation'])
async def test_T49_T59_seven_paths_real_graph(action):
    request,flow,services=offline_case(action='continue' if action=='noDelegation' else action,no_delegation=action=='noDelegation')
    result=await run_decision(request,flow=flow,services=services)
    assert result.status=='completed' and result.outcome.disposition=='ready'
    assert result.outcome.proposals[0].payload['action']==action
    assert result.consumed['model_attempts']==6

async def test_T04_T59_alternate_graph_and_unclear_zero_calls():
    first=await run_offline(); second=await run_offline(alternate=True)
    assert first.flow_ref!=second.flow_ref
    request,flow,services=offline_case(unclear=True)
    r=await run_decision(request,flow=flow,services=services)
    assert r.outcome.disposition=='clarify' and services.decision_provider.calls==0

async def test_T03_T54_true_graph_three_round_repair():
    request,flow,services=offline_case(action='create')
    base=services.proposal_source.proposals[0]
    class Composer:
        calls=0
        async def compose(self,*args):
            self.calls+=1
            return ProposalCandidateBatch((dataclasses.replace(base,payload={**plain(base.payload),'configuration':{'ratio':[0.3,0.5,0.7][min(2,self.calls-1)]}}),),True)
    class Validator(OfflineValidator):
        calls=0
        async def validate(self,draft,basis,context):
            self.calls+=1
            receipt=await super().validate(draft,basis,context)
            return receipt if self.calls==3 else dataclasses.replace(receipt,status='invalid',issues=({'code':'ratio_needs_repair'},))
    composer=Composer(); validator=Validator(); services=dataclasses.replace(services,proposal_source=composer,validator=validator)
    result=await run_decision(request,flow=flow,services=services)
    assert result.status=='completed' and result.outcome.disposition=='ready'
    assert result.outcome.proposals[0].payload['configuration']['ratio']==0.7
    assert result.consumed['repair_rounds']==2 and composer.calls==validator.calls==3

async def test_T54_no_new_proposal_or_feedback_stops():
    request,flow,services=offline_case()
    class Invalid(OfflineValidator):
        async def validate(self,draft,basis,context):
            return dataclasses.replace(await super().validate(draft,basis,context),status='invalid',issues=({'code':'same_feedback'},))
    services=dataclasses.replace(services,validator=Invalid())
    result=await run_decision(request,flow=flow,services=services)
    assert result.status=='completed' and result.outcome.disposition=='clarify'
    assert result.outcome.issues[0]['code']=='selection_no_progress'

async def test_T33_T21_T22_real_sdk_graph_durable_evidence(tmp_path):
    calls=[]
    async def transport(req):
        payload=json.loads(req.content); calls.append(payload)
        answers={key:{'type':'choice','choice':'pass','confidence':0.9,'probabilities':{'pass':0.9,'fail':0.05,'unknown':0.05}} for key in payload['questions']}
        return httpx2.Response(200,json={'model':'jev-1.13.0','answers':answers,'usage':{}})
    request,flow,services=offline_case()
    provider=JevDecisionProvider(JevProviderSettings(),secret_resolver=lambda _: 'offline-only',transport=httpx2.MockTransport(transport))
    root=tmp_path/'evidence';root.mkdir(mode=0o700)
    sink=FileEvidenceSink(root,read_context=services.read_context)
    services=dataclasses.replace(services,decision_provider=provider,evidence=sink)
    try:
        result=await run_decision(request,flow=flow,services=services)
        read=await sink.read(result.run_id,services.read_context)
        assert result.outcome.disposition=='ready' and len(calls)==6
        assert read['status']=='completed'
        events=read['events']; assert events[0]['payload']['type']=='run.started'
        assert [e['payload']['type'] for e in events[1:]]==['call.intent','call.response']*6
        assert read['terminal']['terminal_digest']==result.result_digest
    finally: await provider.close();await sink.close()

async def test_T14_actual_assignment_budget_no_draft():
    request,flow,services=offline_case(limits=RunLimits(max_model_attempts=1))
    result=await run_decision(request,flow=flow,services=services)
    assert result.status=='budget_exhausted' and result.outcome is None and services.decision_provider.calls==1

async def test_T58_consumption_rechecks_every_must():
    result=await run_offline(); p=result.outcome.proposals[0]
    checks=tuple(ObligationResult(c.condition_id,'passed',c.checker_id,c.checker_version,{c.condition_id:c.expected_version},('read',)) for c in p.preconditions)
    CheckBatch(checks,True).require(p.preconditions)
    for c in p.preconditions:
        rows=tuple(dataclasses.replace(r,source_versions={c.condition_id:'changed'}) if r.obligation_id==c.condition_id else r for r in checks)
        with pytest.raises(ContractError): CheckBatch(rows,True).require(p.preconditions)
    with pytest.raises(ContractError): CheckBatch(checks[:-1],True).require(p.preconditions)

def test_T01_T02_contract_roundtrip_vectors():
    request,flow,services=offline_case()
    assert decode_request(canonical(request))==request
    with pytest.raises(ContractError): decode_request(canonical({**request.to_dict(),'allowWrite':True}))
    path=Path(__file__).parents[2]/'src/ordessa_decision/contracts/vectors.json'
    for v in json.loads(path.read_text()): assert digest(v['name'],decode(v['canonical'].encode()))==v['digest']

def test_T19_T55_boundary_scanner_positive_and_injected_private(tmp_path):
    import ast
    def violations(root):
        files=list(root.rglob('*.py'))
        if not files: raise ValueError('scanner source absent')
        found=[]
        for f in files:
            tree=ast.parse(f.read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.Attribute) and n.attr in {'_GraphIterator','_environment','_registry','provider'}: found.append((f,n.lineno))
                if isinstance(n,ast.ImportFrom) and n.module and n.module.startswith(('pydantic_graph._','pacthold.core','pacthold.environment')): found.append((f,n.lineno))
        return found
    root=Path(__file__).parents[2]/'src/ordessa_decision/integrations/ordessa'
    assert not violations(root)
    (tmp_path/'bad.py').write_text('from pydantic_graph._internal import _GraphIterator\nx=admitted.provider\n')
    assert len(violations(tmp_path))==2
