"""Replay ACKs and ambiguous remote attempts must not permit completion/retry."""
from dataclasses import replace
import pytest
from pacthold.decision.contracts import *
from pacthold.decision.evidence import MemoryEvidenceSink
from pacthold.decision.runtime import run_decision, RuntimeFailure
from test_runtime import Provider, build_flow, compose, question, READ

class DurableMemory(MemoryEvidenceSink):
    durable = True
    async def start(self, meta):
        ack = await super().start(meta)
        self.started_ack = DurabilityAck(ack.seq, ack.digest, 'durable')
        return self.started_ack
    async def append_durable(self, event):
        ack = await super().append_durable(event)
        return DurabilityAck(ack.seq, ack.digest, 'durable')
    async def finish(self, value):
        ack = await super().finish(value)
        return DurabilityAck(ack.seq, ack.digest, 'durable')

@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['intent', 'response', 'finish'])
async def test_T21_T22_T25_replayed_start_ack_never_dispatches_or_completes(stage):
    class Replay(DurableMemory):
        async def append_durable(self, event):
            if stage in ('intent','response') and event['type'] == 'call.'+stage: return self.started_ack
            return await super().append_durable(event)
        async def finish(self, value):
            if stage == 'finish': return self.started_ack
            return await super().finish(value)
    sink = Replay(read_context=READ); provider = Provider(); flow = build_flow()
    req, svc = compose(flow, sink=sink, provider=provider)
    with pytest.raises(RuntimeFailure): await run_decision(req, flow=flow, services=svc)
    assert len(provider.calls) == (0 if stage == 'intent' else 1)
    assert all(entry['terminal'] is None for entry in sink._runs.values())

@pytest.mark.asyncio
async def test_T13_T37_unknown_remote_failure_cannot_be_caught_and_retried():
    class UnknownProvider(Provider):
        async def decide(self, q, context):
            context.claim(q, self.settings_digest); self.calls.append(context)
            raise OSError('unknown_after_dispatch')
    async def catches(ctx):
        for _ in range(2):
            try: await ctx.deps.gateway.decide(question())
            except RuntimeFailure: pass
        return None
    provider = UnknownProvider(); flow = build_flow(action=catches)
    sink = DurableMemory(read_context=READ); req, svc = compose(flow, sink=sink, provider=provider)
    result = await run_decision(req, flow=flow, services=svc)
    assert result.status == 'failed' and result.error_code == 'provider_failed'
    assert len(provider.calls) == 1
    evidence = await sink.read(result.run_id, READ)
    assert evidence['call_evidence'] == 'unknown'

@pytest.mark.asyncio
async def test_T17_T46_host_policy_alias_cannot_remove_confirmation_boundary():
    from pacthold.decision.offline import offline_case
    from pacthold.decision.flows.agent_assignment.build import build_assignment_flow
    req, _, svc = offline_case(action='reuse')
    policy = plain(svc.policy)
    policy['task_gate_facts'].update(requires_confirmation=True, confirmation_status='unknown')
    class MutatingRead:
        async def observe(self, *args):
            policy['task_gate_facts']['requires_confirmation'] = False
            return ObservationBatch('controlled', (), True, 'controlled only')
    flow = build_assignment_flow(policy, alternate=True, read_query={'kind':'controlled'})
    req = replace(req, flow_ref=flow.ref)
    svc = replace(svc, policy=policy, policy_refs=flow.policy_refs, read=MutatingRead())
    result = await run_decision(req, flow=flow, services=svc)
    assert result.status == 'completed' and result.outcome.disposition == 'clarify'
    assert svc.decision_provider.calls == 0
    assert svc.policy['task_gate_facts']['requires_confirmation'] is True


@pytest.mark.asyncio
async def test_T17_caught_question_policy_failure_cannot_become_completed():
    async def catches(ctx):
        bad=replace(question(),policy_ref=PolicyRef('foreign','1',digest('policy',{})))
        try: await ctx.deps.gateway.decide(bad)
        except RuntimeFailure: pass
        return BusinessOutcome('clarify')
    provider=Provider(); flow=build_flow(action=catches)
    req,svc=compose(flow,provider=provider)
    result=await run_decision(req,flow=flow,services=svc)
    assert result.status=='failed' and result.error_code=='question_policy_invalid'
    assert provider.calls==[]


@pytest.mark.asyncio
async def test_T25_correctly_shaped_finish_ack_without_terminal_is_unknown():
    class NoCommit(DurableMemory):
        async def finish(self,value):
            return DurabilityAck(len(self._runs[value['run_id']]['events'])+1,
                value['terminal_digest'],'durable')
    sink=NoCommit(read_context=READ); provider=Provider(); flow=build_flow()
    req,svc=compose(flow,sink=sink,provider=provider)
    with pytest.raises(RuntimeFailure): await run_decision(req,flow=flow,services=svc)
    assert len(provider.calls)==1
    assert all(row['terminal'] is None for row in sink._runs.values())
