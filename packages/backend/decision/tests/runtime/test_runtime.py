"""Real pydantic-graph with controlled providers; no network/model calls."""
import asyncio
from dataclasses import replace
from pathlib import Path
import time
import pytest
from pydantic_graph import GraphBuilder, StepContext
from ordessa_decision.contracts import *
from ordessa_decision.runtime import *

POLICY = PolicyRef('test-policy','1','sha256:policy')
READ = ReadContext(object(),'test-read')

class Sink:
    durable = True
    def __init__(self, fail=None):
        self.events, self.terminals = [], {}
        self.fail = fail
    async def start(self, meta):
        if self.fail == 'start': raise OSError('sensitive exception')
        self.events.append(meta)
        return DurabilityAck(len(self.events),'sha256:ack','durable')
    async def append_durable(self, event):
        if self.fail == event['type']: raise OSError('sensitive exception')
        self.events.append(event)
        return DurabilityAck(len(self.events),'sha256:ack','durable')
    async def finish(self, terminal):
        old = self.terminals.get(terminal['run_id'])
        if old and old != terminal: raise ValueError('terminal_conflict')
        self.terminals[terminal['run_id']] = terminal
        if self.fail == 'lost_ack': raise OSError('lost_ack')
        return DurabilityAck(len(self.events)+1,'sha256:ack','durable')
    async def read(self, run_id, read_context):
        assert read_context is READ
        return {'status':'completed','terminal':self.terminals[run_id]} if run_id in self.terminals else {'status':'unknown'}

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
    flow = build_flow(rounds=2)
    req, svc = compose(flow)
    results = await asyncio.gather(*(run_decision(req,flow=flow,services=svc) for _ in range(2)))
    assert results[0].run_id != results[1].run_id
    assert all(r.consumed['node_entries']==2 for r in results)
    assert len(svc.evidence.terminals) == 2

@pytest.mark.parametrize('field,value', [('review_ref',''),('reviewed_code_digest','name-only'),('parallel_state_writes',True)])
def test_T16_T29_untrusted_flow_rejected(field,value):
    with pytest.raises(ContractError): replace(build_flow(),**{field:value}).validate()

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['start','call.intent','call.response'])
async def test_T21_T22_T26_persistence_failure(failure):
    flow = build_flow()
    req, svc = compose(flow,sink=Sink(failure))
    with pytest.raises(EvidenceUnknown): await run_decision(req,flow=flow,services=svc)
    assert len(svc.decision_provider.calls) == (1 if failure=='call.response' else 0)

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
