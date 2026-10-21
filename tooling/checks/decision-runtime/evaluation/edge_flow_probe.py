"""Finite synthetic edge cases through the original assignment graph, no native use."""
import argparse
import asyncio
from dataclasses import replace
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time

import httpx2
from ordessa_decision.definitions import (TaskBrief, ConfigurationOffer, CandidateBatch,
    DecisionRequest, DecisionAnswer, DecisionQuestion, DecisionServices, ReadContext,
    RunLimits, FlowRef, ValidationReceipt, ObligationResult, digest, plain, freeze)
from assignment_source.build import build_assignment_flow, load_assignment_policy
from assignment_source.composition import DeterministicProposalSource, RegisteredTemplate, check_schema
from assignment_source.proposals import check_proposal_basis
from assignment_source.selection import validate_policy
from ordessa_decision.evidence import FileEvidenceSink, MemoryEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_decision.runtime import run_decision, reviewed_code_digest, flow_digest

_spec = importlib.util.spec_from_file_location('edge_reference_helpers', Path(__file__).with_name('reference_flow_probe.py'))
reference = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(reference)
live = reference.live; EvaluationError = live.EvaluationError
EXPECTED = {
    'regular': {'disposition': 'ready', 'action': 'reuse', 'issue_code': None, 'candidate_reads': 1, 'compose': 1, 'validate': 1},
    'empty_complete': {'disposition': 'clarify', 'action': None, 'issue_code': 'no_evidenced_candidate', 'candidate_reads': 1, 'compose': 0, 'validate': 0},
    'main_agent': {'disposition': 'ready', 'action': 'noDelegation', 'issue_code': None, 'candidate_reads': 0, 'compose': 0, 'validate': 0},
    'configuration_unverifiable': {'disposition': 'clarify', 'action': None, 'issue_code': 'proposal_unverifiable', 'candidate_reads': 1, 'compose': 1, 'validate': 1}}


def validate(plan, *, binding_digest=None):
    try:
        if set(plan) != {'version','synthetic_only','scope_id','settings','limits','task','policy','fixture','expected'}: raise ValueError()
        if plan['version'] != 'jev-edge-flow/1' or plan['synthetic_only'] is not True: raise ValueError()
        if type(plan['scope_id']) is not str or not plan['scope_id'] or len(plan['scope_id']) > 128: raise ValueError()
        settings = JevProviderSettings(**plan['settings'])
        if (settings.base_url+'/v1/systemone' != live.ENDPOINT or settings.model != 'jev-1.13-free'
                or settings.accepted_response_models != ('jev-1.13-free',) or settings.timeout_seconds > 30): raise ValueError()
        bounds = plan['limits']
        if set(bounds) != {'max_http_requests','max_model_attempts','wall_timeout_seconds'}: raise ValueError()
        for key in ('max_http_requests','max_model_attempts'):
            if type(bounds[key]) is not int or not 6 <= bounds[key] <= 16: raise ValueError()
        wall = bounds['wall_timeout_seconds']
        if type(wall) not in (int,float) or not math.isfinite(wall) or not 0 < wall <= 90: raise ValueError()
        task = TaskBrief.from_dict(plan['task']); policy = freeze(plan['policy']); fixture = plan['fixture']; kind = fixture['kind']
        if kind not in EXPECTED or plan['expected'] != EXPECTED[kind]: raise ValueError()
        if any(type(plan['expected'][key]) is not type(value) for key,value in EXPECTED[kind].items()): raise ValueError()
        selection = validate_policy(policy['selection']); baseline = plain(load_assignment_policy()['selection'])
        if kind == 'main_agent':
            if not selection['no_delegation']['enabled'] or selection['no_delegation']['boundary'] not in task.boundaries: raise ValueError()
            baseline['no_delegation'] = plain(selection['no_delegation'])
        if plain(selection) != baseline: raise ValueError()
        candidate, drafts = reference._fixture(task, policy); draft = drafts[0]; offer = None
        if kind == 'configuration_unverifiable':
            if set(fixture) != {'kind','template_id','offer','configuration'} or type(fixture['template_id']) is not str or not fixture['template_id']: raise ValueError()
            offer = ConfigurationOffer.from_dict(fixture['offer'])
            if (offer.support_status != 'unknown' or offer.descriptor_revision is None or not offer.evidence_refs
                    or 'reuse' not in offer.supported_actions or check_schema(fixture['configuration'], offer.input_schema) != 'valid'): raise ValueError()
            claims = plain(candidate.capability_claims); claims['configuration_offer_refs'] = [plain(offer.offer_ref)]
            candidate = replace(candidate, capability_claims=claims,
                observation=replace(candidate.observation, content_digest=digest('descriptor', claims)))
            draft = replace(draft, payload={**plain(draft.payload), 'configuration_kind': offer.configuration_kind,
                'configuration': fixture['configuration']})
        elif set(fixture) != {'kind'}: raise ValueError()
        check_proposal_basis(draft, candidate, task, selection['required_checks']['reuse'], selection['required_validation']['reuse'])
        if binding_digest is not None and (type(binding_digest) is not str or len(binding_digest)!=71 or not binding_digest.startswith('sha256:') or any(c not in '0123456789abcdef' for c in binding_digest[7:])): raise ValueError()
        original = build_assignment_flow(policy)
        code = digest('flow', {'original_graph_code': original.reviewed_code_digest,
            'probe_helpers': reviewed_code_digest(__file__, Path(__file__).with_name('reference_flow_probe.py'), Path(__file__).with_name('live_acceptance.py')),
            'plan': digest('policy', plan)})
        if binding_digest is not None: code=digest('flow',{'edge_code':code,'trusted_port_binding_digest':binding_digest})
        flow = replace(original, ref=FlowRef('agent.assignment.synthetic-edge','1',flow_digest(code,original.policy_refs)),
            reviewed_code_digest=code, review_ref=plan['scope_id']); flow.validate()
        request = DecisionRequest('edge',task,flow.ref,RunLimits(max_model_attempts=bounds['max_model_attempts'],
            max_node_entries=40,max_repair_rounds=0,max_inflight_model_calls=1,wall_timeout_seconds=wall,cleanup_timeout_seconds=2))
        return settings,policy,kind,candidate,draft,offer,flow,request
    except Exception:
        raise EvaluationError('plan_invalid') from None


class Candidates:
    def __init__(self, kind, candidate, row, save): self.kind,self.candidate,self.row,self.save = kind,candidate,row,save
    async def list_candidates(self,*args,**kwargs):
        self.row['candidate_reads'] += 1; self.save()
        return CandidateBatch(() if self.kind == 'empty_complete' else (self.candidate,),True)


class Composer:
    def __init__(self, kind, draft, offer, fixture, row, save):
        self.kind,self.draft,self.offer,self.fixture,self.row,self.save = kind,draft,offer,fixture,row,save
    async def compose(self,*args):
        if self.row['compose_calls']: raise EvaluationError('unexpected_composition')
        self.row['compose_calls'].append({'proposal_digest': self.draft.proposal_digest,
            'offer': plain(self.offer), 'configuration': plain(self.draft.payload['configuration']), 'scope':'controlled_non_native'})
        self.save()
        async def handler(task, candidate_refs, offer_refs, constraints, context):
            if self.offer is not None and plain(offer_refs) != [plain(self.offer.offer_ref)]: raise EvaluationError('offer_binding_invalid')
            return (self.draft,)
        # The real registered composer checks the externally supplied structural schema.
        schema = self.offer.input_schema if self.offer else {'type':'object','additionalProperties':True}
        source = DeterministicProposalSource((RegisteredTemplate(self.fixture.get('template_id','controlled-regular'),
            handler,self.draft.payload['configuration_kind'],schema),))
        return await source.compose(*args)


class Validator:
    def __init__(self, kind, row, save): self.kind,self.row,self.save = kind,row,save
    async def validate(self,draft,basis,context):
        if self.kind != 'configuration_unverifiable':
            return await reference.ControlledValidator(False,self.row,self.save).validate(draft,basis,context)
        receipt = ValidationReceipt('controlled.edge','1',draft.proposal_digest,'unverifiable',
            tuple(ObligationResult(o.obligation_id,'unknown',o.validator_kind,o.version_constraint,
                {'descriptor':'1'},('controlled-semantic-validator-absent',)) for o in draft.required_validation_obligations),
            reference.STAMP,'controlled_non_native',issues=({'code':'semantic_validator_absent'},))
        self.row['validate_calls'].append(plain(receipt)); self.save(); return receipt


class CaptureProvider:
    binding_ref = 'controlled-edge-capture'
    settings_digest = digest('descriptor',{'provider':'controlled-edge-capture'})
    def __init__(self): self.questions = []
    async def decide(self,question,context):
        context.claim(question,self.settings_digest); self.questions.append(question)
        return DecisionAnswer(question.question_id,'choice','pass',{'scope':'offline_capture_only'})


def _row(): return {'id':'edge','answers':[],'candidate_reads':0,'compose_calls':[],'validate_calls':[],
    'graph_trace':[],'quality_pass':False,'technical_status':'NOT_RUN'}


def _services(values, fixture, provider, sink, context, row, save, mode):
    _,policy,kind,candidate,draft,offer,flow,_ = values
    return DecisionServices(None,Candidates(kind,candidate,row,save),
        Composer(kind,draft,offer,fixture,row,save),
        Validator(kind,row,save),provider,sink,policy,context,flow.policy_refs,mode=mode)


async def prepare(plan, *, binding_digest=None, services_factory=None):
    if (services_factory is None)!=(binding_digest is None) or (services_factory is not None and not callable(services_factory)):
        raise EvaluationError('port_binding_unreviewed')
    values = validate(plan,binding_digest=binding_digest); _,policy,kind,candidate,draft,offer,flow,request = values
    provider = CaptureProvider(); context = ReadContext(object(),'offline-edge-capture'); sink = MemoryEvidenceSink(read_context=context)
    row = _row(); state = flow.new_state(request); flow = replace(flow,new_state=lambda _:state)
    factory=services_factory or _services
    services = factory(values,plan['fixture'],provider,sink,context,row,lambda:None,'offline')
    try: result = await run_decision(request,flow=flow,services=services)
    finally: await sink.close()
    if result.status != 'completed' or not _matches(result,row,plan['expected']) or len(provider.questions) != 6:
        raise EvaluationError('edge_capture_failed')
    if any(not q.question_id.startswith('task-gate.') for q in provider.questions): raise EvaluationError('edge_capture_failed')
    for q in provider.questions: JevDecisionProvider._map_question(q)
    return {'status':'PREPARED_NOT_RUN','port_binding_digest':binding_digest,'port_binding':row.get('port_binding'),'input_hash':digest('policy',plan),'scope_id':plan['scope_id'],'plan':plain(plan),
        'flow':plain(flow.ref),'reviewed_code_digest':flow.reviewed_code_digest,'policy_refs':plain(flow.policy_refs),'request':plain(request),
        'candidate':plain(candidate),'proposal':plain(draft),'configuration_offer':plain(offer),'questions':plain(provider.questions),
        'question_digests':[q.question_digest for q in provider.questions],'preparation_graph_trace':list(state.trace),
        'preparation_quality':'not_evaluated; controlled offline capture only','maximum_http_requests':6,
        'fixture_scope':'controlled synthetic ports; structural schema does not prove native semantic support',
        'credential_reads':0,'real_model_requests':0}


def _matches(result,row,expected):
    if result.status != 'completed': return False
    outcome = result.outcome; action = outcome.proposals[0].payload['action'] if outcome.proposals else None
    codes = [i.get('code') for i in outcome.issues]
    return (outcome.disposition == expected['disposition'] and action == expected['action']
        and (expected['issue_code'] in codes if expected['issue_code'] else not codes)
        and row['candidate_reads'] == expected['candidate_reads'] and len(row['compose_calls']) == expected['compose']
        and len(row['validate_calls']) == expected['validate'])


async def run_plan(plan,output,credential_file,authorize_live=False,*,ledger_path,transport=None,binding_digest=None,services_factory=None):
    values = validate(plan,binding_digest=binding_digest); frozen = await prepare(plan,binding_digest=binding_digest,services_factory=services_factory)
    if not authorize_live: raise EvaluationError('live_authorization_required')
    if ledger_path is None: raise EvaluationError('scope_ledger_required')
    ledger = live.ScopeLedger(ledger_path,plan)
    if 'edge' in ledger.data['cases']: ledger.close(); raise EvaluationError('case_already_claimed')
    settings,policy,kind,candidate,draft,offer,flow,request = values; output = Path(output); row = _row()
    receipt = {**frozen,'status':'IN_PROGRESS','rows':[row],'native_effects':0,'retry':0,'cost':'UNKNOWN',
        'evaluation_mode':'live_https' if transport is None else 'injected_test_transport'}
    def save(): live.atomic_write(output/'receipt.json',receipt)
    start = time.monotonic(); deadline = start+request.limits.wall_timeout_seconds; provider = sink = None
    state = flow.new_state(request)
    try:
        live.atomic_write(output/'frozen-inputs.json',frozen); save()
        (output/'durable').mkdir(parents=True,exist_ok=True,mode=0o700)
        context = ReadContext(object(),'controlled-edge-graph'); sink = FileEvidenceSink(output/'durable',read_context=context)
        receipt['credential_reads'] += 1; save(); key = Path(credential_file).read_text().strip()
        if not key or '\n' in key: raise EvaluationError('credential_invalid')
        audited = live.AuditedTransport(transport or httpx2.AsyncHTTPTransport(retries=0),ledger,deadline)
        provider = JevDecisionProvider(settings,secret_resolver=lambda _:key,transport=audited)
        ledger.begin('edge'); audited.case_id = 'edge'
        questions = tuple(DecisionQuestion.from_dict(q) for q in frozen['questions'])
        recorded = reference.FrozenQuestions(provider,row,save,questions)
        factory=services_factory or _services
        services = factory(values,plan['fixture'],recorded,sink,context,row,save,'real')
        flow = replace(flow,new_state=lambda _:state)
        async with asyncio.timeout_at(deadline): result = await run_decision(request,flow=flow,services=services)
        row.update(run_id=result.run_id,technical_status=result.status,result=plain(result),result_digest=digest('result',result))
        await live.verify_terminal(sink,result,context); row['terminal_verified'] = True
        row['quality_pass'] = _matches(result,row,plan['expected']) and len(row['answers']) == 6 and all(a['value']=='pass' for a in row['answers'])
        receipt['status'] = 'SCOPED_PASS' if row['quality_pass'] else 'PARTIAL'
    except TimeoutError as error:
        receipt['status']='PARTIAL'; row.update(technical_status='TIMEOUT_UNKNOWN',error='global_deadline_unknown')
        if getattr(error.__cause__,'run_id',None): row['run_id']=error.__cause__.run_id
    except asyncio.CancelledError as error:
        receipt['status']='PARTIAL'; row.update(technical_status='CANCELLED',error='cancelled_unknown')
        if getattr(error,'run_id',None): row['run_id']=error.run_id
        raise
    except Exception: receipt['status']='PARTIAL'; row['collection_error']='collection_failed'
    finally:
        row['graph_trace']=list(state.trace)
        receipt.update(elapsed_seconds=round(time.monotonic()-start,4),http_audit=ledger.data['requests'],
            transport_attempts=len(ledger.data['requests']),real_model_requests=len(ledger.data['requests']) if transport is None else 0,
            actual_http_requests=len(ledger.data['requests']) if transport is None else 0,
            model_quality_passes=int(row['quality_pass']) if transport is None else 0,
            controlled_label_matches=int(row['quality_pass']) if transport is not None else 0)
        receipt['usage']=[a['usage_evidence'] for a in row['answers']]
        receipt['usage_unknown_requests']=max(0,len(ledger.data['requests'])-sum(u.get('status')=='reported' for u in receipt['usage']))
        try: save()
        finally:
            try:
                if provider: await provider.close()
            finally:
                try:
                    if sink: await sink.close()
                finally: ledger.close()
    return receipt


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=('prepare','run'))
    parser.add_argument('--plan',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ledger',type=Path); parser.add_argument('--credential-file',type=Path)
    parser.add_argument('--authorize-live',action='store_true'); args=parser.parse_args()
    try:
        plan=json.loads(args.plan.read_text())
        if args.mode=='prepare': live.atomic_write(args.output/'prepared.json',asyncio.run(prepare(plan)))
        else:
            if args.ledger is None or args.credential_file is None: raise EvaluationError('live_arguments_required')
            asyncio.run(run_plan(plan,args.output,args.credential_file,args.authorize_live,ledger_path=args.ledger))
    except BaseException: print('evaluation_failed'); return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
