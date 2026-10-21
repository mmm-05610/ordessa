"""Controlled offline fixtures demonstrate mechanisms, never real model quality."""
from dataclasses import dataclass
from datetime import datetime, timezone
from ordessa_decision.definitions import *
from .build import load_assignment_policy, build_assignment_flow
from ordessa_decision.evidence import MemoryEvidenceSink

class OfflineProvider:
    settings_digest=digest('descriptor',{'provider':'controlled_offline'})
    binding_ref='controlled_offline'
    def __init__(self, answer='pass'): self.answer=answer; self.calls=0
    async def decide(self,question,model_context):
        model_context.claim(question,self.settings_digest); self.calls+=1
        value=self.answer if question.question_id.startswith('task-gate.') else 'proposal_0'
        return DecisionAnswer(question.question_id,'choice',value,{'quality':'not_evaluated'})

class OfflineCandidates:
    def __init__(self,candidates,complete=True): self.candidates=tuple(candidates); self.complete=complete
    async def list_candidates(self,*args,cursor=None,**kw): return CandidateBatch(self.candidates,self.complete)

class OfflineComposer:
    def __init__(self,proposals): self.proposals=tuple(proposals)
    async def compose(self,*args): return ProposalCandidateBatch(self.proposals,True)

class OfflineValidator:
    """Controlled receipt for port testing only, no real native capability claim."""
    async def validate(self,draft,basis,context):
        return ValidationReceipt('offline','1',draft.proposal_digest,'valid',tuple(
            ObligationResult(o.obligation_id,'passed',o.validator_kind,o.version_constraint,
                {'descriptor':'1'},('controlled-offline-evidence',)) for o in draft.required_validation_obligations),
            datetime.now(timezone.utc).isoformat(),'controlled_offline_only')

def offline_case(*, alternate=False, action='continue', unclear=False, limits=None, no_delegation=False):
    facts={'source_ref':'controlled-task-boundary','source_version':'1','evidence_refs':['controlled-read-only-facts'],'requires_confirmation':False,'task_category':'read_only_review'}
    policy=load_assignment_policy(task_gate_facts=facts)
    if no_delegation:
        p=plain(policy); p['selection']['no_delegation']['enabled']=True; policy=freeze(p)
    flow=build_assignment_flow(policy,alternate=alternate)
    task=TaskBrief('offline-task','1','' if unclear else 'Review the supplied source and return one risk report.',
        boundaries=() if unclear else ('mainAgentHandlingAllowed', 'read_only'),acceptance_criteria=() if unclear else ('One report with source evidence.',))
    request=DecisionRequest('offline-request',task,flow.ref,limits or RunLimits())
    ref=ExternalRef('controlled-unit',{'id':'unit-1','revision':'1'})
    checks={k:{'status':'passed','source_version':'1','evidence_refs':['controlled-owner-fact'],'subject_ref':ref.to_dict(),'checker_id':k,'checker_version':'1'} for k in policy['selection']['required_checks'][action]}
    claims={'action':action,'cost_status':'known','hard_checks':checks}
    obs=VersionedObservation('controlled-observation',ref,'1',digest('descriptor',claims),datetime.now(timezone.utc).isoformat(),{},'current',evidence_refs=('controlled-observation',))
    candidate=CandidateOffer(ref,'unit',obs,claims)
    taskref=ExternalRef('task',{'id':task.task_id,'revision':task.task_revision})
    conditions=(Precondition('task_revision','task_revision',taskref,task.task_revision,None,'must','task_revision','1'),)+tuple(
        Precondition(k,k,ref,'1',None,'must',k,'1') for k in checks)
    proposal=ProposalDraft('offline-proposal','agent.assignment/1',{'action':action,'configuration_kind':'controlled.new.kind','configuration':{'ratio':0.7}},
        (obs.observation_id,),conditions,required_validation_obligations=(ValidationObligation('configuration',ref,'must','owner.read','1'),))
    context=ReadContext(object(),'offline')
    sink=MemoryEvidenceSink(read_context=context); provider=OfflineProvider()
    services=DecisionServices(None,OfflineCandidates((candidate,)),OfflineComposer((proposal,)),OfflineValidator(),provider,sink,policy,context,flow.policy_refs)
    return request,flow,services

async def run_offline(**kwargs):
    from ordessa_decision.runtime import run_decision
    request,flow,services=offline_case(**kwargs)
    return await run_decision(request,flow=flow,services=services)
