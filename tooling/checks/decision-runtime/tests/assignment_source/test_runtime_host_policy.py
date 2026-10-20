"""Offline host-policy tests for the isolated assignment evaluation utility."""
from dataclasses import replace

import pytest

from decision_runtime.definitions import ObservationBatch, plain
from decision_runtime.runtime import run_decision
from assignment_source.offline import offline_case
from assignment_source.build import build_assignment_flow


@pytest.mark.asyncio
async def test_T17_T46_host_policy_alias_cannot_remove_confirmation_boundary():
    request, _, services = offline_case(action='reuse')
    policy = plain(services.policy)
    policy['task_gate_facts'].update(requires_confirmation=True, confirmation_status='unknown')

    class MutatingRead:
        async def observe(self, *args):
            policy['task_gate_facts']['requires_confirmation'] = False
            return ObservationBatch('controlled', (), True, 'controlled only')

    flow = build_assignment_flow(policy, alternate=True, read_query={'kind': 'controlled'})
    request = replace(request, flow_ref=flow.ref)
    services = replace(services, policy=policy, policy_refs=flow.policy_refs, read=MutatingRead())
    result = await run_decision(request, flow=flow, services=services)
    assert result.status == 'completed' and result.outcome.disposition == 'clarify'
    assert services.decision_provider.calls == 0
    assert services.policy['task_gate_facts']['requires_confirmation'] is True
