"""Host-free offline example of the public Manager and historical read path."""
import asyncio

from pydantic_graph import GraphBuilder

from decision_runtime import (
    BusinessOutcome, DecisionManager, DecisionRequest, DecisionServices,
    FlowRef, MemoryEvidenceSink, PolicyRef, ReadContext, RunContext,
    TaskBrief, TrustedFlow, flow_digest, reviewed_code_digest,
)


class OfflineProvider:
    """Binding for a graph that never invokes a model/provider call."""
    binding_ref = 'example-offline-provider'


async def main():
    policy = PolicyRef('example-policy', '1', 'sha256:example-policy')
    context = ReadContext(object(), 'example-manager')
    code = reviewed_code_digest(__file__)
    policies = (policy,)
    ref = FlowRef('example-manager-flow', '1', flow_digest(code, policies))
    builder = GraphBuilder(name='example-manager-flow', state_type=dict,
        deps_type=RunContext, input_type=DecisionRequest,
        output_type=BusinessOutcome, auto_instrument=False)

    @builder.step(node_id='finish-offline')
    async def finish(ctx):
        await ctx.deps.enter_node('finish-offline')
        return BusinessOutcome('clarify')

    builder.add(
        builder.edge_from(builder.start_node).to(finish),
        builder.edge_from(finish).to(builder.end_node),
    )
    flow = TrustedFlow(ref, builder.build(), lambda _request: {}, policies,
        code, 'example-manager')
    request = DecisionRequest('example-request', TaskBrief('example-task', '1', 'offline example'), ref)
    services = DecisionServices(None, None, None, None, OfflineProvider(),
        MemoryEvidenceSink(read_context=context), {}, context, policies)

    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    result = await run.result()
    snapshot = await run.snapshot()
    events = await run.evidence()
    historical = await manager.get(run.run_id).result()
    print({
        'run_id': run.run_id,
        'result_status': result.status,
        'snapshot_status': snapshot['status'],
        'event_count': len(events),
        'historical_result_matches': historical.to_dict() == result.to_dict(),
        'provider_calls': 0,
    })
    await manager.close()


if __name__ == '__main__':
    asyncio.run(main())
