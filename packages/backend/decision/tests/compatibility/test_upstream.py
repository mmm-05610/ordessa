import asyncio
import pytest
import httpx2
from pydantic_graph import GraphBuilder, StepContext
from typesafe_sdk import AsyncTypeSafeClient, Choice, RetryPolicy

@pytest.mark.asyncio
async def test_T03_T30_T20_real_graph():
    g=GraphBuilder(name='jd001-feedback',state_type=dict,input_type=int,output_type=int,auto_instrument=False)
    @g.step
    async def step(ctx:StepContext[dict,None,int])->int:
        ctx.state['entries']=ctx.state.get('entries',0)+1
        return ctx.inputs+1
    g.add(g.edge_from(g.start_node).to(step))
    g.add(g.edge_from(step).to(g.decision().branch(g.match(int, matches=lambda x:x<3).to(step)).branch(g.match(int).to(g.end_node))))
    assert await g.build().run(state={},inputs=0)==3
    bad=GraphBuilder(name='bad')
    with pytest.raises(Exception): bad.build()

@pytest.mark.asyncio
async def test_T30_cancel_real_graph():
    g=GraphBuilder(name='jd001-cancel',output_type=int,auto_instrument=False)
    entered=asyncio.Event(); cancelled=asyncio.Event()
    @g.step
    async def wait(ctx)->int:
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
        return 1
    g.add(g.edge_from(g.start_node).to(wait),g.edge_from(wait).to(g.end_node))
    task=asyncio.create_task(g.build().run()); await entered.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert cancelled.is_set()

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[200,429,500])
async def test_T33_T37_sdk_http_count(status):
    calls=[]
    async def transport(req):
        calls.append(req)
        return httpx2.Response(status,json={'model':'jev-1.13.0','usage':{},'answers':{'q':{'type':'choice','choice':'pass','confidence':0.9,'probabilities':{'pass':0.9,'fail':0.1}}}})
    async with AsyncTypeSafeClient(api_key='offline-only',model='jev-1.13.0',retry=RetryPolicy(max_retries=0),transport=httpx2.MockTransport(transport)) as client:
        if status==200:
            res=await client.system_one({'task':'data'},{'q':Choice(criteria={'pass':'yes','fail':'no'})})
            assert res.choices['q'].choice=='pass'
            assert abs(sum(res.choices['q'].probabilities.values())-1)<1e-6
        else:
            with pytest.raises(Exception): await client.system_one({}, {'q':Choice(criteria={'a':None,'b':None})})
    assert len(calls)==1
