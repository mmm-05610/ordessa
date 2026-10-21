"""Manager facade contracts over the original runner and evidence port."""
import asyncio
from pathlib import Path

import pytest
from pydantic_graph import GraphBuilder

from ordessa_decision import (
    BusinessOutcome, DecisionManager, DecisionManagerError,
    DecisionRequest, DecisionServices, EvidenceUnknown, FlowRef, MemoryEvidenceSink,
    PolicyRef, ReadContext, RunContext, RunLimits, TaskBrief, TrustedFlow,
    flow_digest, reviewed_code_digest,
)


POLICY = PolicyRef('manager-policy', '1', 'sha256:manager-policy')
READ = ReadContext(object(), 'manager-test')


class Provider:
    binding_ref = 'test-provider'
    settings_digest = 'sha256:settings'

    async def decide(self, question, context):
        raise AssertionError('this flow does not call the provider')


def flow_for(action=None):
    builder = GraphBuilder(name='manager-flow', state_type=dict, deps_type=RunContext,
        input_type=DecisionRequest, output_type=BusinessOutcome, auto_instrument=False)

    @builder.step(node_id='manager-step')
    async def step(ctx):
        await ctx.deps.enter_node('manager-step')
        if action is not None:
            value = action(ctx)
            if hasattr(value, '__await__'):
                await value
        return BusinessOutcome('clarify')

    builder.add(builder.edge_from(builder.start_node).to(step))
    builder.add(builder.edge_from(step).to(builder.end_node))
    code = reviewed_code_digest(Path(__file__))
    ref = FlowRef('manager-flow', '1', flow_digest(code, (POLICY,)))
    return TrustedFlow(ref, builder.build(), lambda request: {}, (POLICY,), code, 'review:manager')


def compose(*, flow=None, sink=None, limits=None):
    selected = flow or flow_for()
    request = DecisionRequest('manager-request', TaskBrief('manager-task', '1', 'goal'),
        selected.ref, limits or RunLimits())
    services = DecisionServices(None, None, None, None, Provider(),
        sink or MemoryEvidenceSink(read_context=READ), {}, READ, (POLICY,))
    return request, selected, services


@pytest.mark.asyncio
async def test_submit_waits_for_verified_started_and_exposes_same_live_and_historical_result():
    request, flow, services = compose()
    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    assert run.run_id
    live = await run.result()
    assert live.status == 'completed'
    assert (await run.snapshot())['status'] == 'completed'
    assert await run.evidence()

    historical = manager.get(run.run_id)
    restored = await historical.result()
    assert restored.to_dict() == live.to_dict()
    assert services.evidence._closed is False
    assert await manager.close() is None


@pytest.mark.asyncio
async def test_submit_does_not_return_handle_when_started_readback_is_unknown():
    class UnknownStart(MemoryEvidenceSink):
        async def read(self, run_id, read_context):
            return {'status': 'unknown'}

    request, flow, services = compose(sink=UnknownStart(read_context=READ))
    manager = DecisionManager(services)
    with pytest.raises(EvidenceUnknown):
        await manager.submit(request, flow)
    await manager.close()


@pytest.mark.asyncio
async def test_cancelled_submit_does_not_leave_manager_task_unowned():
    entered = asyncio.Event()

    class BlockingStart(MemoryEvidenceSink):
        async def start(self, run_meta):
            entered.set()
            await asyncio.Event().wait()

    request, flow, services = compose(sink=BlockingStart(read_context=READ))
    manager = DecisionManager(services)
    submission = asyncio.create_task(manager.submit(request, flow))
    await entered.wait()
    submission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await submission
    with pytest.raises(DecisionManagerError, match='manager_active_runs'):
        await manager.close()
    pending = tuple(manager._active)
    assert pending
    done, still_pending = await asyncio.wait(pending, timeout=1)
    assert done and not still_pending
    await asyncio.sleep(0)  # run the ownership cleanup callback
    await manager.close()


@pytest.mark.asyncio
async def test_snapshot_preserves_unknown_and_evidence_does_not_hide_it_as_empty():
    class UnknownRead(MemoryEvidenceSink):
        async def read(self, run_id, read_context):
            return {'status': 'unknown'}

    _request, _flow, services = compose(sink=UnknownRead(read_context=READ))
    manager = DecisionManager(services)
    run = manager.get('00000000-0000-4000-8000-000000000001')
    assert await run.snapshot() == {'status': 'unknown'}
    with pytest.raises(EvidenceUnknown):
        await run.evidence()
    with pytest.raises(EvidenceUnknown):
        await run.result()
    await manager.close()


@pytest.mark.asyncio
async def test_evidence_refusal_is_preserved_and_historical_result_rejects_wrong_run_binding():
    class RefusedRead(MemoryEvidenceSink):
        async def read(self, run_id, read_context):
            if run_id.endswith('2'):
                return {'status': 'refused'}
            return {
                'status': 'completed',
                'terminal': {
                    'run_id': '00000000-0000-4000-8000-000000000003',
                    'status': 'completed',
                    'result': {},
                },
            }

    _request, _flow, services = compose(sink=RefusedRead(read_context=READ))
    manager = DecisionManager(services)
    refused = manager.get('00000000-0000-4000-8000-000000000002')
    assert await refused.snapshot() == {'status': 'refused'}
    with pytest.raises(EvidenceUnknown):
        await refused.evidence()
    wrong_binding = manager.get('00000000-0000-4000-8000-000000000004')
    with pytest.raises(EvidenceUnknown):
        await wrong_binding.result()
    await manager.close()


@pytest.mark.asyncio
async def test_historical_result_rejects_terminal_status_mismatch():
    class MismatchedTerminalStatus(MemoryEvidenceSink):
        corrupt = False

        async def read(self, run_id, read_context):
            snapshot = await super().read(run_id, read_context)
            terminal = snapshot.get('terminal')
            if self.corrupt and isinstance(terminal, dict):
                terminal = dict(terminal, status='failed')
                snapshot = dict(snapshot, terminal=terminal)
            return snapshot

    sink = MismatchedTerminalStatus(read_context=READ)
    request, flow, services = compose(sink=sink)
    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    assert (await run.result()).status == 'completed'
    sink.corrupt = True
    with pytest.raises(EvidenceUnknown):
        await manager.get(run.run_id).result()
    await manager.close()


@pytest.mark.asyncio
async def test_fast_post_start_failure_returns_handle_with_failed_result():
    async def fail(_ctx):
        raise RuntimeError('bounded graph failure')

    flow = flow_for(fail)
    request, flow, services = compose(flow=flow)
    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    result = await run.result()
    assert result.status == 'failed'
    assert result.error_code == 'graph_failed'
    await manager.close()


@pytest.mark.asyncio
async def test_result_waiter_cancellation_is_shielded_and_does_not_cancel_run():
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(_ctx):
        entered.set()
        await release.wait()

    flow = flow_for(pause)
    request, flow, services = compose(flow=flow)
    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    waiter = asyncio.create_task(run.result())
    await entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert run._task is not None and not run._task.cancelled()
    release.set()
    assert (await run.result()).status == 'completed'
    await manager.close()


@pytest.mark.asyncio
async def test_cancel_is_scoped_to_submitting_manager_and_close_refuses_active_task():
    entered = asyncio.Event()

    async def pause(_ctx):
        entered.set()
        await asyncio.Event().wait()

    flow = flow_for(pause)
    request, flow, services = compose(flow=flow)
    first, second = DecisionManager(services), DecisionManager(services)
    run = await first.submit(request, flow)
    await entered.wait()
    with pytest.raises(DecisionManagerError, match='run_not_owned_or_active'):
        await second.cancel(run.run_id)
    with pytest.raises(DecisionManagerError, match='manager_active_runs'):
        await first.close()
    assert await first.cancel(run.run_id) is True
    with pytest.raises(asyncio.CancelledError):
        await run.result()
    snapshot = await first.get(run.run_id).snapshot()
    assert snapshot['terminal']['status'] == 'cancelled'
    assert (await first.get(run.run_id).result()).status == 'cancelled'
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_manager_projects_budget_exhaustion_without_new_state():
    async def exhaust(ctx):
        ctx.deps.exhaust('max_model_attempts')

    flow = flow_for(exhaust)
    request, flow, services = compose(flow=flow)
    manager = DecisionManager(services)
    run = await manager.submit(request, flow)
    result = await run.result()
    assert result.status == 'budget_exhausted'
    assert result.exhausted_dimension == 'max_model_attempts'
    await manager.close()
