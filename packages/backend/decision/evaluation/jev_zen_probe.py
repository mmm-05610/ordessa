"""Explicit authorized free Zen evaluation via real Graph, gateway, SDK and evidence.

No automatic live execution: --authorize-live and --credential-file are mandatory.
No retry, account/model fallback, native effects, or application defaults changed.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import time

from pydantic_graph import GraphBuilder
import httpx2
from ordessa_decision.contracts import (DecisionQuestion,PolicyRef,FlowRef,TaskBrief,RunLimits,DecisionRequest,
    BusinessOutcome,DecisionServices,ReadContext,DecisionAnswer,digest,plain)
from ordessa_decision.providers.jev import JevDecisionProvider,JevProviderSettings
from ordessa_decision.runtime import TrustedFlow,RunContext,run_decision,reviewed_code_digest,flow_digest
from ordessa_decision.evidence import FileEvidenceSink
from laya_probe import plans

ENDPOINT='https://opencode.ai/zen/v1/systemone'

class AuditedTransport(httpx2.AsyncBaseTransport):
    def __init__(self,deadline,maximum):
        self.inner=httpx2.AsyncHTTPTransport(retries=0);self.deadline=deadline;self.maximum=maximum;self.requests=[]
    async def handle_async_request(self,request):
        if str(request.url)!=ENDPOINT or request.method!='POST' or time.monotonic()>=self.deadline or len(self.requests)>=self.maximum:
            raise RuntimeError('live_scope_refused')
        row={'attempt':len(self.requests)+1,'method':'POST','endpoint':ENDPOINT};self.requests.append(row)
        start=time.monotonic()
        try:
            response=await self.inner.handle_async_request(request)
            row['http_status']=response.status_code
            return response
        finally:row['seconds_to_headers']=round(time.monotonic()-start,4)
    async def aclose(self):await self.inner.aclose()

class RecordedProvider:
    def __init__(self,provider):
        self.provider=provider;self.binding_ref=provider.binding_ref;self.settings_digest=provider.settings_digest;self.answers=[];self.errors=[]
    async def decide(self,question,context):
        try:answer=await self.provider.decide(question,context)
        except Exception as exc:
            self.errors.append({'question_id':question.question_id,'code':getattr(exc,'code',type(exc).__name__)});raise
        self.answers.append(answer);return answer

async def main(args):
    if not args.authorize_live:raise RuntimeError('explicit_live_authorization_required')
    config_path=Path(__file__).with_name('opencode-zen-jev-settings.json')
    config=json.loads(config_path.read_text());settings=JevProviderSettings(**config['settings'])
    if settings.model!='jev-1.13-free' or settings.base_url+'/v1/systemone'!=ENDPOINT:raise RuntimeError('free_route_only')
    key=args.credential_file.read_text().strip()
    if not key or '\n' in key:raise RuntimeError('credential_format_invalid')
    inputs=[]
    for label,folder in [('smoke',args.smoke_inputs),('controls',args.control_inputs)]:
        data=json.loads(folder.read_text())
        for c in data['cases']:inputs.append({'source':label,**c})
    policy=PolicyRef('jev.synthetic.domain-eval','1',digest('policy',inputs))
    root=args.output/'durable';root.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(root,0o700)
    deadline=time.monotonic()+300;transport=AuditedTransport(deadline,min(args.max_requests,60 if args.resume_after_first else 63))  # prior minimal probe + three completed first-case calls => ceiling 64
    provider=JevDecisionProvider(settings,secret_resolver=lambda ref:key,transport=transport)
    recorded=RecordedProvider(provider);read_context=ReadContext(object(),'jev-synthetic-eval-only');sink=FileEvidenceSink(root,read_context=read_context)
    rows=[];gateplans={s['id']:p for s,p in plans()};started=time.monotonic()
    try:
        for case in inputs:
            if args.resume_after_first and case['source']=='smoke' and case['id']=='primitive-zh':
                rows.append({'source':'smoke','id':'primitive-zh','status':'COMPLETED_ANSWERS_NOT_RETAINED','http_requests':3,'quality_pass':False,'reason':'first evaluator failed on terminal field after three committed responses; no resend'})
                continue
            if time.monotonic()>=deadline:
                rows.append({'source':case['source'],'id':case['id'],'status':'NOT_RUN','reason':'global_deadline'});continue
            before=len(recorded.answers);before_error=len(recorded.errors);before_http=len(transport.requests)
            builder=GraphBuilder(name='jev-zen-synthetic-eval',state_type=dict,deps_type=RunContext,input_type=DecisionRequest,output_type=BusinessOutcome,auto_instrument=False)
            @builder.step
            async def evaluate(ctx)->BusinessOutcome:
                await ctx.deps.enter_node('EvaluateSyntheticCase')
                for qid,wire in case['questions'].items():
                    kwargs={'options':wire['criteria']} if wire['type']=='choice' else {'scale':tuple(wire['criteria'])} if wire['type']=='score' else {}
                    question=DecisionQuestion(qid,'1',wire['type'],wire.get('state',case['state']),wire['instructions'],policy_ref=policy,**kwargs)
                    await ctx.deps.gateway.decide(question)
                return BusinessOutcome('clarify',issues=({'code':'evaluation_only_no_proposal'},))
            builder.add(builder.edge_from(builder.start_node).to(evaluate),builder.edge_from(evaluate).to(builder.end_node))
            code=reviewed_code_digest(__file__,config_path)
            ref=FlowRef('jev.synthetic.domain-eval','1',flow_digest(code,(policy,)))
            flow=TrustedFlow(ref,builder.build(),lambda request:{},(policy,),code,'user-authorized-evaluation/2026-10-05')
            limits=RunLimits(max_model_attempts=max(1,len(case['questions'])),max_node_entries=2,max_repair_rounds=0,max_inflight_model_calls=1,wall_timeout_seconds=min(75,deadline-time.monotonic()),cleanup_timeout_seconds=2)
            request=DecisionRequest('eval-'+case['source']+'-'+case['id'],TaskBrief(case['id'],'1','合成领域评测；不执行真实操作。'),ref,limits)
            services=DecisionServices(None,None,None,None,recorded,sink,{},read_context,(policy,),mode='real')
            start=time.monotonic()
            result=await run_decision(request,flow=flow,services=services)
            evidence=await sink.read(result.run_id,read_context)
            if evidence.get('status')!='completed' or evidence['terminal']['terminal_digest']!=digest('result',result):raise RuntimeError('durable_terminal_unverified')
            answers=recorded.answers[before:];errors=recorded.errors[before_error:]
            row={'source':case['source'],'id':case['id'],'expected':case['expected'],'status':result.status,'run_id':result.run_id,'seconds':round(time.monotonic()-start,4),
                 'http_requests':len(transport.requests)-before_http,'answers':[plain(a) for a in answers],'provider_errors':errors,'result_digest':digest('result',result)}
            if result.status!='completed':row['quality_pass']=False
            elif not case['questions']:
                row.update(actual=case['hard_result'],quality_pass=case['hard_result']==case['expected'],quality_source='hard_rule_zero_model')
            elif case['id'].startswith('gate-'):
                from ordessa_decision.flows.agent_assignment.task_gate import reduce_task_gate
                aggregate=reduce_task_gate(gateplans[case['id'][5:]],answers);actual='pass' if aggregate.status=='gate_pass' else aggregate.status
                row.update(actual=actual,quality_pass=actual==case['expected'],issues=[i['code'] for i in aggregate.issues])
            elif case['id'].startswith('primitive-'):
                actual={a.question_id:a.value for a in answers};row.update(actual=actual,quality_pass=actual['department']=='billing' and actual['churn']>=0.5)
            else:
                actual={a.question_id:a.value for a in answers}
                passed=all(actual[k]>=v['min'] if isinstance(v,dict) and 'min' in v else actual[k]<=v['max'] if isinstance(v,dict) and 'max' in v else actual[k]==v for k,v in case['expected'].items())
                row.update(actual=actual,quality_pass=passed)
            rows.append(row)
            receipt={'status':'IN_PROGRESS','requested_model':settings.model,'elapsed_seconds':time.monotonic()-started,'http_requests':transport.requests,'rows':rows,
                     'sdk':'typesafe-sdk 0.7.2','execution':'original pydantic-graph + runtime gateway + local durable evidence','retry':0,'native_effects':0,'credential_reference':'opencode_zen'}
            text=json.dumps(receipt,ensure_ascii=False,indent=2)
            if key in text:raise RuntimeError('credential_output_blocked')
            (args.output/'receipt.json').write_text(text+'\n');print(case['source'],case['id'],row['status'],row.get('actual'),row.get('quality_pass'),flush=True)
    finally:
        (args.output/'http-audit.json').write_text(json.dumps({'http_requests':transport.requests,'no_retry':True},indent=2)+'\n')
        await provider.close();await sink.close()
    receipt['status']='EVALUATED_QUALITY_NOT_YET_ACCEPTED';receipt['total_http_requests_including_prior_probe']=len(transport.requests)+(4 if args.resume_after_first else 1)
    receipt['model_case_count']=sum(r.get('http_requests',0)>0 for r in rows);receipt['model_cases_matching_labels']=sum(r.get('quality_pass',False) and r.get('http_requests',0)>0 for r in rows)
    receipt['hard_rule_cases']=sum(r.get('quality_source')=='hard_rule_zero_model' for r in rows)
    receipt['quality_scope']='same frozen local Laya smoke/control labels; tiny synthetic sample only; graph completed is technical result, not model quality success'
    text=json.dumps(receipt,ensure_ascii=False,indent=2)
    if key in text:raise RuntimeError('credential_output_blocked')
    (args.output/'receipt.json').write_text(text+'\n')
    print('live evaluation complete:',receipt['model_cases_matching_labels'],'/',receipt['model_case_count'],'model cases',len(transport.requests),'HTTP',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--authorize-live',action='store_true');p.add_argument('--resume-after-first',action='store_true');p.add_argument('--max-requests',type=int,choices=range(1,64),default=63);p.add_argument('--credential-file',type=Path,required=True);p.add_argument('--smoke-inputs',type=Path,required=True);p.add_argument('--control-inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    try:asyncio.run(main(a))
    except Exception as exc:print('evaluation failed safely:',type(exc).__name__,flush=True);raise SystemExit(1)
