"""Real pydantic-graph with controlled providers; no network/model calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
import time
import uuid
import pytest
from pydantic_graph import GraphBuilder, StepContext
from ordessa_decision.contracts import *
from ordessa_decision.runtime import *
from ordessa_decision.evidence.codec import record

POLICY = PolicyRef('test-policy','1','sha256:policy')
READ = ReadContext(object(),'test-read')

class Sink:
    durable = True
    def __init__(self, fail=None):
        self.events, self.terminals, self.records = [], {}, []
        self.fail = fail
        self.uncertain = False
    async def start(self, meta):
        if self.fail == 'start': raise OSError('sensitive exception')
        self.events.append(meta)
        self.records.append(record(meta, 1, None, 65536))
        return DurabilityAck(1,self.records[-1]['digest'],'durable')
    async def append_durable(self, event):
        if self.fail == event['type']:
            self.uncertain = True
            raise OSError('sensitive exception')
        self.events.append(event)
        self.records.append(record(event,len(self.records)+1,self.records[-1]['digest'],65536))
        return DurabilityAck(self.records[-1]['seq'],self.records[-1]['digest'],'durable')
    async def finish(self, terminal):
        old = self.terminals.get(terminal['run_id'])
        if old and old != terminal: raise ValueError('terminal_conflict')
        self.terminals[terminal['run_id']] = terminal
        if self.fail == 'lost_ack': raise OSError('lost_ack')
        return DurabilityAck(len(self.events)+1,terminal['terminal_digest'],'durable')
    async def read(self, run_id, read_context):
        assert read_context is READ
        return {'status':'completed','terminal':self.terminals[run_id]} if run_id in self.terminals else ({'status':'unknown'} if self.uncertain or not self.records else {'status':'running','events':self.records})

class Provider:
    binding_ref = 'test-provider'
    settings_digest = 'sha256:settings'
    def __init__(self, delay=0, bad=False):
        self.calls, self.closed = [], 0
        self.delay, self.bad = delay, bad
        self.entered = asyncio.Event()
    async def decide(self, question, context):
        context.claim(question, self.settings_digest)
        self.calls.append(context)
        self.entered.set()
        await asyncio.sleep(self.delay)
        return DecisionAnswer(question.question_id, question.kind, 'outside' if self.bad else 'yes', {})
    async def close(self): self.closed += 1

def question(n=0):
    return DecisionQuestion('q-'+str(n),'1','choice',{'round':n},'Sensitive prompt',
        options={'yes':{},'no':{}}, policy_ref=POLICY)

def build_flow(action=None, *, rounds=1, order=None):
    builder = GraphBuilder(name='controlled-flow', state_type=dict, deps_type=RunContext,
        input_type=DecisionRequest, output_type=BusinessOutcome, auto_instrument=False)
    steps = []
    for number in range(rounds):
        async def step(ctx, number=number):
            await ctx.deps.enter_node('node-'+str(number))
            ctx.state.setdefault('visited', []).append(number)
            if order is not None: order.append(number)
            if action is not None:
                await action(ctx)
            else:
                await ctx.deps.gateway.decide(question(number))
            return BusinessOutcome('clarify')
        steps.append(builder.step(step, node_id='step-'+str(number)))
    builder.add(builder.edge_from(builder.start_node).to(steps[0]))
    for left, right in zip(steps, steps[1:]):
        builder.add(builder.edge_from(left).to(right))
    builder.add(builder.edge_from(steps[-1]).to(builder.end_node))
    code = reviewed_code_digest(Path(__file__))
    ref = FlowRef('controlled','1',flow_digest(code,(POLICY,)))
    return TrustedFlow(ref,builder.build(),lambda req:{},(POLICY,),code,'review:test-runtime')

def compose(flow, *, limits=None, sink=None, provider=None):
    request = DecisionRequest('request',TaskBrief('task','1','goal'),flow.ref,limits or RunLimits())
    services = DecisionServices(None,None,None,None,provider or Provider(),sink or Sink(),
        freeze({'test':True}),READ,(POLICY,))
    return request, services

@pytest.mark.asyncio
async def test_T03_T04_T20_real_graph_multiround_and_alternate():
    order = []
    flow = build_flow(rounds=3,order=order)
    req, svc = compose(flow)
    answer = await run_decision(req,flow=flow,services=svc)
    assert answer.status == 'completed' and answer.consumed['model_attempts'] == 3
    assert order == [0,1,2]
    alternate = build_flow(action=lambda ctx: asyncio.sleep(0))
    req, svc = compose(alternate)
    assert (await run_decision(req,flow=alternate,services=svc)).consumed['model_attempts'] == 0

@pytest.mark.asyncio
async def test_T03_actual_feedback_graph_loop():
    builder = GraphBuilder(name='feedback-loop',state_type=dict,deps_type=RunContext,
        input_type=DecisionRequest,output_type=BusinessOutcome,auto_instrument=False)
    @builder.step(node_id='feedback')
    async def feedback(ctx):
        await ctx.deps.enter_node('feedback')
        round_no = ctx.state.get('round',0)
        await ctx.deps.gateway.decide(question(round_no))
        ctx.state['round'] = round_no + 1
        return ctx.state['round'] if round_no < 2 else BusinessOutcome('clarify')
    branch = builder.decision(node_id='route').branch(builder.match(int).to(feedback)).branch(builder.match(BusinessOutcome).to(builder.end_node))
    builder.add(builder.edge_from(builder.start_node).to(feedback),builder.edge_from(feedback).to(branch))
    code = reviewed_code_digest(Path(__file__))
    ref = FlowRef('feedback','1',flow_digest(code,(POLICY,)))
    flow = TrustedFlow(ref,builder.build(),lambda req:{},(POLICY,),code,'review:feedback')
    req, svc = compose(flow)
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status == 'completed' and len(svc.decision_provider.calls) == 3

@pytest.mark.asyncio
@pytest.mark.parametrize('after_commit',[False,True])
async def test_T24_cancel_during_finish_never_opposes_terminal(after_commit):
    class RacingSink(Sink):
        def __init__(self):
            super().__init__()
            self.finishing = asyncio.Event()
            self.finish_calls = 0
        async def finish(self, terminal):
            self.finish_calls += 1
            if after_commit:
                await super().finish(terminal)
            self.finishing.set()
            await asyncio.Event().wait()
    sink = RacingSink()
    flow = build_flow()
    req, svc = compose(flow,sink=sink,limits=RunLimits(cleanup_timeout_seconds=.02))
    task = asyncio.create_task(run_decision(req,flow=flow,services=svc))
    await sink.finishing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert sink.finish_calls == 1
    if after_commit:
        assert list(sink.terminals.values())[0]['status'] == 'completed'
    else:
        assert not sink.terminals

@pytest.mark.asyncio
@pytest.mark.parametrize('dimension,value,expected', [('max_node_entries',1,1),('max_model_attempts',1,1)])
async def test_T05_T14_budget_technical_terminal(dimension,value,expected):
    flow = build_flow(rounds=3)
    req, svc = compose(flow,limits=replace(RunLimits(),**{dimension:value}))
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status == 'budget_exhausted' and result.outcome is None
    assert result.exhausted_dimension == dimension and len(svc.decision_provider.calls) == expected

@pytest.mark.asyncio
async def test_T06_concurrent_one_attempt():
    async def competing(ctx):
        values = await asyncio.gather(ctx.deps.gateway.decide(question()),ctx.deps.gateway.decide(question(1)),return_exceptions=True)
        assert sum(isinstance(v,DecisionAnswer) for v in values) == 1
        assert any(isinstance(v,BudgetExhausted) for v in values)
    flow = build_flow(competing)
    req, svc = compose(flow,limits=RunLimits(max_model_attempts=1))
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status == 'budget_exhausted' and result.outcome is None
    assert len(svc.decision_provider.calls) == 1

@pytest.mark.asyncio
async def test_T06_cancelled_slot_waiter_zero_dispatch():
    release = asyncio.Event()
    class BlockingProvider(Provider):
        async def decide(self,q,context):
            context.claim(q,self.settings_digest)
            self.calls.append(context)
            self.entered.set()
            await release.wait()
            return DecisionAnswer(q.question_id,q.kind,'yes',{})
    provider = BlockingProvider()
    async def action(ctx):
        first = asyncio.create_task(ctx.deps.gateway.decide(question(0)))
        await provider.entered.wait()
        waiting = asyncio.Event()
        async def queued():
            waiting.set()
            return await ctx.deps.gateway.decide(question(1))
        second = asyncio.create_task(queued())
        await waiting.wait()
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError): await second
        release.set()
        await first
    flow = build_flow(action)
    req,svc = compose(flow,provider=provider)
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status=='completed' and result.consumed['model_attempts']==1
    assert len(provider.calls)==1
    assert len([e for e in svc.evidence.events if e['type']=='call.intent'])==1

@pytest.mark.asyncio
async def test_T06_expired_slot_waiter_zero_dispatch():
    provider = Provider(delay=10)
    async def action(ctx):
        first = asyncio.create_task(ctx.deps.gateway.decide(question(0)))
        await provider.entered.wait()
        second = asyncio.create_task(ctx.deps.gateway.decide(question(1)))
        await asyncio.gather(first,second)
    flow = build_flow(action)
    req,svc = compose(flow,provider=provider,limits=RunLimits(wall_timeout_seconds=.04))
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status=='budget_exhausted' and result.exhausted_dimension=='wall_timeout_seconds'
    assert result.consumed['model_attempts']==1 and len(provider.calls)==1
    assert len([e for e in svc.evidence.events if e['type']=='call.intent'])==1

@pytest.mark.asyncio
async def test_T11_external_cancel_propagates_and_shared_provider_survives():
    flow = build_flow()
    req, svc = compose(flow,provider=Provider(delay=10))
    task = asyncio.create_task(run_decision(req,flow=flow,services=svc))
    await svc.decision_provider.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert svc.decision_provider.closed == 0
    assert list(svc.evidence.terminals.values())[0]['status'] == 'cancelled'

@pytest.mark.asyncio
async def test_T12_timeout():
    flow = build_flow()
    req, svc = compose(flow,limits=RunLimits(wall_timeout_seconds=.01),provider=Provider(delay=1))
    result = await run_decision(req,flow=flow,services=svc)
    assert result.status == 'budget_exhausted' and result.exhausted_dimension == 'wall_timeout_seconds'

@pytest.mark.asyncio
async def test_T13_invalid_answer_and_node_failure():
    flow = build_flow()
    req, svc = compose(flow,provider=Provider(bad=True))
    assert (await run_decision(req,flow=flow,services=svc)).status == 'failed'
    async def fail(ctx): raise RuntimeError('sensitive body')
    flow = build_flow(fail)
    req, svc = compose(flow)
    result = await run_decision(req,flow=flow,services=svc)
    assert result.error_code == 'graph_failed' and 'sensitive' not in str(svc.evidence.events)

@pytest.mark.asyncio
async def test_T15_runs_isolated():
    from ordessa_decision.evidence import MemoryEvidenceSink
    seen_states, calls = {}, []
    class Candidates:
        async def list_candidates(self,task,*args,**kwargs):
            ref = ExternalRef('test-candidate',{'task_id':task.task_id,'id':'candidate-'+task.goal})
            obs = VersionedObservation('obs-'+task.task_id,ref,'1','sha256:obs','2026-10-05T00:00:00Z',{},'current')
            return CandidateBatch((CandidateOffer(ref,'test',obs,{}),),True)
    class TrackingProvider(Provider):
        async def decide(self,q,context):
            calls.append((context,q))
            return await super().decide(q,context)
    async def action(ctx):
        task = ctx.deps.request.task
        if task.task_id in seen_states:
            assert seen_states[task.task_id] is ctx.state
            assert len(ctx.state['candidates'])==1
        else:
            seen_states[task.task_id]=ctx.state
            assert 'candidates' not in ctx.state
            ctx.state['candidates']=[]
        batch = await ctx.deps.services.candidate_source.list_candidates(task,(),POLICY,READ)
        candidate = batch.candidates[0].candidate_ref
        assert candidate.identity['task_id']==task.task_id
        ctx.state['candidates'].append(candidate)
        q=replace(question(len(ctx.state['candidates'])),bounded_state={'task_id':task.task_id,'goal':task.goal,'candidate':candidate.to_dict()})
        await asyncio.sleep(0)
        await ctx.deps.gateway.decide(q)
    flow = build_flow(action,rounds=2)
    req,svc = compose(flow,sink=MemoryEvidenceSink(read_context=READ),provider=TrackingProvider())
    svc=replace(svc,candidate_source=Candidates())
    req_a=replace(req,request_id='request-A',task=TaskBrief('task-A','1','alpha'))
    req_b=replace(req,request_id='request-B',task=TaskBrief('task-B','2','beta'))
    results = await asyncio.gather(*(run_decision(r,flow=flow,services=svc) for r in (req_a,req_b)))
    assert results[0].run_id != results[1].run_id and seen_states['task-A'] is not seen_states['task-B']
    for result,request in zip(results,(req_a,req_b)):
        assert result.status=='completed' and result.consumed['node_entries']==2 and result.consumed['model_attempts']==2
        own_calls=[(c,q) for c,q in calls if c.run_id==result.run_id]
        assert [c.attempt_no for c,q in own_calls]==[1,2]
        assert all(q.bounded_state['task_id']==request.task.task_id and q.bounded_state['goal']==request.task.goal for c,q in own_calls)
        read=await read_result(result.run_id,services=svc)
        assert read['status']=='completed'
        assert read['terminal']['result']['request_id']==request.request_id
        assert read['terminal']['result']['task_revision']==request.task.task_revision
        assert [e['seq'] for e in read['events']]==list(range(1,len(read['events'])+1))
        assert all(e['payload']['run_id']==result.run_id for e in read['events'])
        assert [e['payload']['question_digest'] for e in read['events'] if e['payload']['type']=='call.intent']==[q.question_digest for c,q in own_calls]

@pytest.mark.parametrize('field,value', [('review_ref',''),('reviewed_code_digest','name-only'),('parallel_state_writes',True)])
def test_T16_T29_untrusted_flow_rejected(field,value):
    with pytest.raises(ContractError): replace(build_flow(),**{field:value}).validate()

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['start','call.intent','call.response'])
async def test_T21_T22_T26_persistence_failure(failure):
    flow = build_flow()
    req, svc = compose(flow,sink=Sink(failure))
    with pytest.raises(EvidenceUnknown) as raised: await run_decision(req,flow=flow,services=svc)
    assert str(uuid.UUID(raised.value.run_id))==raised.value.run_id
    assert 'sensitive' not in str(raised.value)
    assert (await read_result(raised.value.run_id,services=svc))['status']=='unknown'
    assert len(svc.decision_provider.calls) == (1 if failure=='call.response' else 0)

@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['call.intent','call.response'])
async def test_T22_T26_caught_uncertainty_sticky_refuses_completion_and_future_dispatch(failure):
    caught=[]
    async def action(ctx):
        with pytest.raises(EvidenceUnknown) as initial:
            await ctx.deps.gateway.decide(question(0))
        caught.append(initial.value)
        # A trusted node's fallback cannot erase unknown evidence or retry.
        with pytest.raises(EvidenceUnknown) as later:
            await ctx.deps.gateway.decide(question(1))
        assert initial.value.run_id==later.value.run_id==ctx.deps.run_id
        with pytest.raises(EvidenceUnknown): await ctx.deps.enter_node('fallback')
        assert ctx.deps.evidence_unknown
        return BusinessOutcome('clarify')
    flow=build_flow(action)
    req,svc=compose(flow,sink=Sink(failure))
    with pytest.raises(EvidenceUnknown) as raised:
        await run_decision(req,flow=flow,services=svc)
    assert raised.value.run_id==caught[0].run_id
    assert len(svc.decision_provider.calls)==(1 if failure=='call.response' else 0)
    assert not svc.evidence.terminals

def test_T23_permit_replay_cross_run_digest_expiry():
    for kwargs in ({'run_id':'other'},{'question_digest':'different'},{'settings_digest':'different'}):
        permit = CallPermit('run','q','s',time.monotonic()+1)
        args = {'run_id':'run','question_digest':'q','settings_digest':'s'} | kwargs
        with pytest.raises(ContractError): permit.claim(**args)
    permit = CallPermit('run','q','s',time.monotonic()+1)
    permit.claim(run_id='run',question_digest='q',settings_digest='s')
    with pytest.raises(ContractError): permit.claim(run_id='run',question_digest='q',settings_digest='s')
    permit = CallPermit('run','q','s',time.monotonic()-1)
    with pytest.raises(ContractError): permit.claim(run_id='run',question_digest='q',settings_digest='s')

@pytest.mark.asyncio
async def test_T25_lost_finish_ack_query():
    flow = build_flow()
    req, svc = compose(flow,sink=Sink('lost_ack'))
    assert (await run_decision(req,flow=flow,services=svc)).status == 'completed'
    assert len(svc.evidence.terminals) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('mutation',['unknown','refused','unavailable','run_id','status','result','digest','conflicting_digest'])
async def test_T25_uncertain_or_mismatched_read_never_ready(mutation):
    class BadReadSink(Sink):
        async def read(self,run_id,read_context):
            response=await super().read(run_id,read_context)
            if response.get('status') != 'completed': return response
            response=plain(response)
            if mutation in ('unknown','refused','unavailable'):
                response['status']=mutation
            elif mutation=='run_id': response['terminal']['run_id']=str(uuid.uuid4())
            elif mutation=='status': response['terminal']['status']='cancelled'
            elif mutation=='result': response['terminal']['result']['request_id']='another-request'
            elif mutation=='digest': response['terminal']['terminal_digest']='sha256:other'
            elif mutation=='conflicting_digest': response['terminal']['result_digest']='sha256:other'
            return response
    flow=build_flow()
    req,svc=compose(flow,sink=BadReadSink('lost_ack'))
    with pytest.raises(EvidenceUnknown) as raised:
        await run_decision(req,flow=flow,services=svc)
    assert raised.value.run_id in svc.evidence.terminals
    assert len(svc.evidence.terminals)==1 and len(svc.decision_provider.calls)==1

@pytest.mark.asyncio
async def test_T28_hung_cancel_cleanup_bounded():
    class HungSink(Sink):
        async def finish(self, terminal): await asyncio.Event().wait()
    flow = build_flow()
    req, svc = compose(flow,sink=HungSink(),provider=Provider(delay=10),limits=RunLimits(cleanup_timeout_seconds=.02))
    task = asyncio.create_task(run_decision(req,flow=flow,services=svc))
    await svc.decision_provider.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task,.3)

@pytest.mark.asyncio
async def test_T28_cancellation_resistant_cleanup_bound_and_secondary_error():
    from ordessa_decision.runtime.runner import bounded
    released, suppressed, done = asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def resistant():
        try:
            try:
                await released.wait()
            except asyncio.CancelledError:
                suppressed.set()
                await released.wait()
        finally:
            done.set()
    began=time.monotonic()
    try:
        with pytest.raises(EvidenceUnknown): await bounded(resistant(),.02)
        assert time.monotonic()-began < .25
        await asyncio.wait_for(suppressed.wait(),.1)
        assert not done.is_set()
    finally:
        released.set()
        await asyncio.wait_for(done.wait(),.2)
    # No perpetual task is left for pytest/event-loop shutdown to cancel.

@pytest.mark.asyncio
async def test_T28_run_cancel_resistant_sink_preserves_original_cancel():
    class ResistantSink(Sink):
        def __init__(self):
            super().__init__()
            self.release,self.suppressed,self.done=asyncio.Event(),asyncio.Event(),asyncio.Event()
        async def finish(self,terminal):
            try:
                while not self.release.is_set():
                    try: await self.release.wait()
                    except asyncio.CancelledError: self.suppressed.set()
            finally:
                self.done.set()
    sink=ResistantSink()
    provider=Provider(delay=10)
    flow=build_flow()
    req,svc=compose(flow,sink=sink,provider=provider,limits=RunLimits(cleanup_timeout_seconds=.02))
    task=asyncio.create_task(run_decision(req,flow=flow,services=svc))
    await provider.entered.wait()
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(task,.3)
        assert str(uuid.UUID(raised.value.run_id))==raised.value.run_id
        if hasattr(raised.value,'add_note'):
            assert any('cleanup unconfirmed' in note for note in raised.value.__notes__)
        await asyncio.wait_for(sink.suppressed.wait(),.1)
        assert not sink.terminals and not sink.done.is_set() and provider.closed==0
    finally:
        sink.release.set()
        await asyncio.wait_for(sink.done.wait(),.2)

@pytest.mark.asyncio
async def test_T29_immutable_parallel_join():
    original = {'mutable':[1]}
    async def one(): return original
    values = await immutable_queries(one,one)
    original['mutable'].append(2)
    assert values[0]['mutable'] == (1,)
    with pytest.raises(TypeError): values[0]['mutable'] = ()

def test_T19_no_private_graph_api():
    source = '\n'.join(p.read_text() for p in Path(__file__).parents[2].joinpath('src/ordessa_decision/runtime').glob('*.py'))
    assert '_GraphIterator' not in source and '.run_sync(' not in source and 'asyncio.run(' not in source

def test_T30_graph_structure_and_explicit_name():
    with pytest.raises(Exception): GraphBuilder(name='invalid').build()
    graph = build_flow().graph
    graph.name = None
    with pytest.raises(ContractError): replace(build_flow(),graph=graph).validate()
