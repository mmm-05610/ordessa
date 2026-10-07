"""Pure selection tests: controlled public ports, no model/network/effects."""
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from pacthold.decision.contracts import *
from pacthold.decision.flows.agent_assignment.selection import assignment_round, decide_assignment
from pacthold.decision.flows.agent_assignment.composition import DeterministicProposalSource, RegisteredTemplate, check_schema, DIALECT

pytestmark=pytest.mark.asyncio


def policy(**changes):
    path=Path(__file__).parents[3]/'src/pacthold/decision/flows/agent_assignment/selection_policy.json'
    result=json.loads(path.read_text()); result.update(changes); return freeze(result)


def task(): return TaskBrief('task','v1','review',acceptance_criteria=('clear findings',))


def candidate(action='reuse',identity='c', p=None, **overrides):
    p=p or policy(); ref=ExternalRef('test.candidate',{'id':identity})
    checks={key:{'status':'passed','source_version':'v1','evidence_refs':['evidence:'+key],
        'subject_ref':ref.to_dict(),'checker_id':key,'checker_version':'1'}
        for key in p['required_checks'][action]}
    claims={'action':action,'cost_status':'known','hard_checks':checks}; claims.update(overrides)
    obs=VersionedObservation(identity,ref,'v1',digest('descriptor',claims),
        '2026-10-05T00:00:00Z',{},freshness='current',evidence_refs=('source-evidence',))
    return CandidateOffer(ref,'unit',obs,claims)


def proposal(c, id='p', p=None, configuration=None):
    p=p or policy(); t=task(); subject=ExternalRef('task',{'id':t.task_id,'revision':t.task_revision})
    pre=[Precondition('task_revision','task_revision',subject,t.task_revision,None,'must','task_revision','1')]
    for key in p['required_checks'][c.capability_claims['action']]:
        pre.append(Precondition(key,key,c.candidate_ref,'v1',None,'must',key,'1'))
    payload={'action':c.capability_claims['action']}
    if configuration is not None: payload.update(configuration_kind='brand.new.kind',configuration=configuration)
    return ProposalDraft(id,'agent.assignment/1',payload,
        basis_observation_ids=(c.observation.observation_id,),preconditions=tuple(pre),
        required_validation_obligations=(ValidationObligation('owner',c.candidate_ref,'must','owner.read','1'),))


def receipt(draft,status='valid',issues=(),obligations=True):
    results=(ObligationResult('owner','passed','owner.read','1',{'revision':'v1'},('owner-evidence',)),) if obligations else ()
    return ValidationReceipt('owner.read','1',draft.proposal_digest,status,results,'2026-10-05T00:00:00Z','pure_read',issues=issues)


class Context:
    def __init__(self,p,candidates=(),proposals=None,*,complete=True,answer='proposal_0',validator=None):
        self.limits=RunLimits(); self.nodes=[]; self.model_calls=[]; self.source_calls=[]; self.compose_calls=[]
        self.policy_ref=PolicyRef('selection',p['version'],digest('policy',p))
        parent=self
        class Candidates:
            async def list_candidates(self,*args,**kw):
                parent.source_calls.append(kw.get('cursor'))
                return CandidateBatch(tuple(candidates),complete)
        class Composer:
            async def compose(self,*args):
                parent.compose_calls.append(args)
                values=proposals if proposals is not None else tuple(proposal(c,p=p,id='p'+str(i)) for i,c in enumerate(candidates))
                return ProposalCandidateBatch(values,True)
        class Validator:
            async def validate(self,draft,basis,context):
                return validator(draft,basis) if validator else receipt(draft)
        class Gateway:
            async def decide(self,q):
                parent.model_calls.append(q)
                if answer=='tie': return DecisionAnswer(q.question_id,'choice',None,{'selection_status':'tie'})
                return DecisionAnswer(q.question_id,'choice',answer,{})
        self.services=SimpleNamespace(candidate_source=Candidates(),proposal_source=Composer(),validator=Validator(),
            read_context=ReadContext(object(),'test'),policy_refs=(self.policy_ref,))
        self.gateway=Gateway()
    async def enter_node(self,name): self.nodes.append(name)


@pytest.mark.parametrize('action',['continue','reuse','restore','wait','reconfigure','create'])
async def test_T49_six_evidenced_proposal_paths(action):
    p=policy(); c=candidate(action,p=p); ctx=Context(p,(c,))
    outcome=await decide_assignment(task(),ctx,p)
    assert outcome.disposition=='ready' and outcome.proposals[0].payload['action']==action
    assert ctx.model_calls==[]
    assert set(p['required_checks'][action]) <= {v.condition_id for v in outcome.proposals[0].preconditions}
    validate_ready(outcome.proposals[0],outcome.receipts[0])


async def test_T49_noDelegation_only_explicit_policy_boundary_zero_ports():
    p=policy(no_delegation={'enabled':True,'boundary':'mainAgentHandlingAllowed'})
    ctx=Context(p)
    t=dataclasses.replace(task(),boundaries=('mainAgentHandlingAllowed',))
    outcome=await decide_assignment(t,ctx,p)
    assert outcome.disposition=='ready' and outcome.proposals[0].payload['action']=='noDelegation'
    assert not ctx.source_calls and not ctx.compose_calls and not ctx.model_calls
    assert (await decide_assignment(task(),Context(p),p)).disposition=='clarify'


@pytest.mark.parametrize('defect',['failed','unknown','missing','cost','stale','context'])
async def test_T50_T51_hard_checks_prevent_selection(defect):
    p=policy(); c=candidate('continue',p=p)
    claims=plain(c.capability_claims)
    if defect in ('failed','unknown'): claims['hard_checks']['same_native_context']['status']=defect
    elif defect=='missing': claims['hard_checks'].pop('same_native_context')
    elif defect=='cost': claims['cost_status']='unknown'
    elif defect=='context': claims['hard_checks']['same_native_context']['evidence_refs']=[]
    c=dataclasses.replace(c,capability_claims=claims)
    if defect=='stale': c=dataclasses.replace(c,observation=dataclasses.replace(c.observation,freshness='stale'))
    ctx=Context(p,(c,)); outcome=await decide_assignment(task(),ctx,p)
    assert outcome.disposition=='clarify' and not ctx.model_calls and not ctx.compose_calls


async def test_T52_busy_shared_reconfigure_and_wait_deadline_unknown():
    p=policy()
    for action,key in [('reconfigure','occupancy_compatible'),('wait','wait_deadline')]:
        c=candidate(action,p=p); claims=plain(c.capability_claims); claims['hard_checks'][key]['status']='unknown'
        ctx=Context(p,(dataclasses.replace(c,capability_claims=claims),))
        assert (await decide_assignment(task(),ctx,p)).disposition=='clarify'
        assert not ctx.compose_calls


async def test_T53_empty_incomplete_and_create_incomplete_refused():
    p=policy()
    for candidates in [(),(candidate('create',p=p),)]:
        ctx=Context(p,candidates,complete=False)
        out=await decide_assignment(task(),ctx,p)
        assert out.disposition=='clarify' and out.issues[0]['code']=='candidate_catalog_incomplete'
        assert not ctx.compose_calls


async def test_T53_external_order_changes_selected_action():
    p=policy(priorities=['create','reconfigure','wait','restore','reuse','continue'])
    candidates=(candidate('reuse','r',p),candidate('create','c',p))
    selected=proposal(candidates[1],p=p)
    ctx=Context(p,candidates,proposals=(selected,))
    out=await decide_assignment(task(),ctx,p)
    assert out.proposals[0].payload['action']=='create'


@pytest.mark.parametrize('answer',['tie','none_suitable','insufficient_evidence'])
async def test_T54_T68_rejection_and_tie_never_payload(answer):
    p=policy(); candidates=(candidate('reuse','a',p),candidate('reuse','b',p))
    ctx=Context(p,candidates,answer=answer)
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='clarify' and not out.proposals
    assert {'none_suitable','insufficient_evidence'}<=set(ctx.model_calls[0].options)


async def test_T54_repair_feedback_and_same_progress_do_not_repeat_model():
    p=policy(); cs=(candidate('reuse','a',p),candidate('reuse','b',p))
    ctx=Context(p,cs,validator=lambda d,b:receipt(d,'invalid',({'code':'incompatible'},)))
    first=await assignment_round(task(),ctx,p)
    assert first.outcome.disposition=='clarify' and first.repair_feedback['issue_codes']==('incompatible',)
    assert len(ctx.model_calls)==1
    second=await assignment_round(task(),ctx,p,previous_progress_digest=first.progress_digest)
    assert second.outcome.issues[0]['code']=='selection_no_progress'
    assert len(ctx.model_calls)==1
    new=Context(p,(candidate('reuse','new',p),))
    next_round=await assignment_round(task(),new,p,feedback=first.repair_feedback)
    assert next_round.outcome.disposition=='ready' and next_round.progress_digest!=first.progress_digest


async def test_T58_exact_digest_and_obligations_and_all_preconditions():
    p=policy(); c=candidate('reuse',p=p)
    for validator in [lambda d,b:dataclasses.replace(receipt(d),proposal_digest='old'),lambda d,b:receipt(d,obligations=False)]:
        with pytest.raises(ContractError): await decide_assignment(task(),Context(p,(c,),validator=validator),p)
    draft=proposal(c,p=p)
    changed=dataclasses.replace(draft,preconditions=tuple(v for v in draft.preconditions if v.condition_id!='availability'))
    with pytest.raises(ContractError): await decide_assignment(task(),Context(p,(c,),proposals=(changed,)),p)


async def test_T67_dynamic_decimal_kind_through_registered_handler_and_owner():
    p=policy(); c=candidate('create',p=p); ctx=Context(p,(c,))
    draft=proposal(c,p=p,configuration={'temperature':0.7})
    async def handler(*args): return (draft,)
    schema={'$schema':DIALECT,'type':'object','properties':{'temperature':{'type':'number','minimum':0.1}},'required':['temperature'],'additionalProperties':False}
    ctx.services.proposal_source=DeterministicProposalSource((RegisteredTemplate('external',handler,'brand.new.kind',schema),))
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='ready' and out.proposals[0].payload['configuration']['temperature']==0.7
    assert out.receipts[0].obligation_results[0].checker_id=='owner.read'
    assert check_schema({'temperature':0.7},schema)=='valid'
    assert check_schema({'temperature':0.01},schema)=='invalid'
    assert check_schema({}, {'$schema':'unknown','type':'object'})=='unverifiable'
    assert check_schema({}, {'type':'object','oneOf':[]})=='unverifiable'


async def test_T53_pagination_preserves_incomplete_and_duplicate_cursor_refused():
    p=policy(); ctx=Context(p); page_calls=[]
    class Pages:
        async def list_candidates(self,*args,**kw):
            index=len(page_calls); page_calls.append(kw['cursor'])
            return CandidateBatch((candidate('create',str(index),p),),False,cursor='next')
    ctx.services.candidate_source=Pages()
    with pytest.raises(ContractError,match='candidate_cursor_repeated'):
        await decide_assignment(task(),ctx,p)
    assert page_calls==[None,'next']


async def test_T53_page_and_combination_bounds_are_intersection():
    p=policy(limits={**plain(policy()['limits']),'max_business_candidates':1})
    ctx=Context(p,(candidate('create','a',p),candidate('create','b',p)))
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='clarify' and not ctx.compose_calls
    called=[]
    async def handler(*args): called.append(1); return ()
    source=DeterministicProposalSource(tuple(RegisteredTemplate(str(i),handler,'new',{'type':'object'}) for i in range(3)),max_combinations=1)
    batch=await source.compose(task(),(),(),{'selection_policy':p},None,ReadContext(object(),'test'))
    assert len(called)==1 and not batch.complete


@pytest.mark.parametrize('change',['advisory','missing','wrong_subject','wrong_checker'])
async def test_T58_required_semantics_cannot_be_downgraded(change):
    p=policy(); c=candidate('reuse',p=p); d=proposal(c,p=p)
    o=d.required_validation_obligations[0]
    if change=='advisory': o=dataclasses.replace(o,requirement='advisory')
    elif change=='missing':
        o=dataclasses.replace(o,validator_kind='structural.only')
    elif change=='wrong_subject': o=dataclasses.replace(o,subject_ref=ExternalRef('unrelated',{'id':'other'}))
    else: o=dataclasses.replace(o,version_constraint='other')
    d=dataclasses.replace(d,required_validation_obligations=(o,))
    with pytest.raises(ContractError,match='proposal_basis_invalid'):
        await decide_assignment(task(),Context(p,(c,),proposals=(d,)),p)


@pytest.mark.parametrize('change',['subject','checker_id','checker_version','duplicate'])
async def test_T58_check_identity_and_duplicate_conditions(change):
    p=policy(); c=candidate('reuse',p=p); d=proposal(c,p=p)
    conditions=list(d.preconditions); index=next(i for i,v in enumerate(conditions) if v.condition_id=='availability')
    old=conditions[index]
    if change=='subject': conditions[index]=dataclasses.replace(old,subject_ref=ExternalRef('other',{'id':'unrelated'}))
    elif change=='checker_id': conditions[index]=dataclasses.replace(old,checker_id='unrelated')
    elif change=='checker_version': conditions[index]=dataclasses.replace(old,checker_version='unrelated')
    else:
        conditions.append(old)
        with pytest.raises(ContractError,match='duplicate_precondition'):
            dataclasses.replace(d,preconditions=tuple(conditions))
        return
    d=dataclasses.replace(d,preconditions=tuple(conditions))
    with pytest.raises(ContractError,match='proposal_basis_invalid'):
        await decide_assignment(task(),Context(p,(c,),proposals=(d,)),p)


async def test_T50_expired_current_observation_rejected_before_model():
    p=policy(); c=candidate('reuse',p=p)
    c=dataclasses.replace(c,observation=dataclasses.replace(c.observation,valid_until='2000-01-01T00:00:00Z'))
    ctx=Context(p,(c,))
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='clarify' and not ctx.compose_calls and not ctx.model_calls


async def test_T50_expiry_rechecked_after_composition_and_owner_validation(monkeypatch):
    import pacthold.decision.flows.agent_assignment.selection as selection
    from datetime import datetime as NativeDatetime,timezone
    class Clock(NativeDatetime):
        expired=False
        @classmethod
        def now(cls,tz=None):
            return NativeDatetime(2099 if cls.expired else 2026,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr(selection,'datetime',Clock)
    p=policy(); c=candidate('reuse',p=p)
    c=dataclasses.replace(c,observation=dataclasses.replace(c.observation,valid_until='2098-01-01T00:00:00Z'))
    def validator(d,b):
        Clock.expired=True
        return receipt(d)
    ctx=Context(p,(c,),validator=validator)
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='clarify' and out.issues[0]['code']=='candidate_evidence_expired'
    Clock.expired=False; ctx=Context(p,(c,))
    class Composer:
        async def compose(self,*args):
            Clock.expired=True
            return ProposalCandidateBatch((proposal(c,p=p),),True)
    ctx.services.proposal_source=Composer()
    out=await decide_assignment(task(),ctx,p)
    assert out.disposition=='clarify' and not ctx.model_calls


async def test_T67_schema_enum_distinguishes_boolean_and_number():
    assert check_schema(True,{'type':'boolean','enum':[1]})=='invalid'
    assert check_schema(1,{'type':'number','enum':[True]})=='invalid'
    assert check_schema(1,{'type':'number','enum':[1.0]})=='valid'
    schema={'type':'object','enum':[{'value':True}]}
    assert check_schema({'value':1},schema)=='invalid'


async def test_T58_read_observations_bound_into_source_progress_and_validator():
    p=policy(); c=candidate('reuse',p=p); ctx=Context(p,(c,)); refs=(c.observation,)
    seen={}
    class Candidates:
        async def list_candidates(self,t,observations,*args,**kwargs):
            seen['source']=observations
            return CandidateBatch((c,),True)
    class Validator:
        async def validate(self,d,b,*args):
            seen['basis']=b
            return receipt(d)
    ctx.services.candidate_source=Candidates(); ctx.services.validator=Validator()
    first=await assignment_round(task(),ctx,p,observation_refs=refs)
    second=await assignment_round(task(),ctx,p,observation_refs=())
    assert seen['source']==()
    assert first.progress_digest!=second.progress_digest
    assert first.outcome.disposition=='ready'
    await assignment_round(task(),ctx,p,observation_refs=refs)
    assert seen['source']==refs
    assert seen['basis']['read_observations']==freeze(plain(refs))
