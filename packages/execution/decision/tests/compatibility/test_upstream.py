import asyncio
import pytest
from pydantic_graph import GraphBuilder, StepContext

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
