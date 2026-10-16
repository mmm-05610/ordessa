"""One method selection node on the original public Decision runner.

Provider, evidence and read authority are supplied by the process root. This
adapter makes no provider, credential, permission or durable selection state.
Its transient native result is returned only after original evidence commit.
"""
from pathlib import Path

from decision_runtime import (
    BusinessOutcome, DecisionRequest, DecisionServices, FlowRef, RunContext, RunLimits,
    TrustedFlow, flow_digest, reviewed_code_digest, run_decision,
)
from pydantic_graph import GraphBuilder

from ..application.contracts.errors import ApplicationError


async def run_method_profile_selection(selection, context, task, *, services,
                                       request_id, review_ref, limits):
    """Return (native ProfileRef, DecisionAnswer, DecisionResult) for one run.

    On an original failed/budget-exhausted/cancelled terminal the first two
    values are None and the original DecisionResult is returned. Cancellation
    and EvidenceUnknown exceptions propagate without retry. Successful choice
    is not Unit authorization or Engineering acceptance. ``review_ref`` binds
    the host's reviewed flow declaration; it is not a human grant.
    """
    if not isinstance(limits, RunLimits) or limits.max_model_attempts != 1:
        raise ApplicationError('PROFILE_SELECTION_LIMITS_INVALID')
    if type(review_ref) is not str or not review_ref:
        raise ApplicationError('PROFILE_SELECTION_FLOW_UNREVIEWED')
    if (not isinstance(services, DecisionServices)
            or not callable(getattr(services.decision_provider, 'decide', None))
            or any(not callable(getattr(services.evidence, name, None))
                   for name in ('start', 'append_durable', 'finish', 'read'))):
        raise ApplicationError('PROFILE_SELECTION_SERVICES_UNAVAILABLE')
    policy = selection.policy_ref(context)
    native = []
    builder = GraphBuilder(name='engineering.method-profile-selection/1',
        state_type=dict, deps_type=RunContext, input_type=DecisionRequest,
        output_type=BusinessOutcome, auto_instrument=False)

    @builder.step(node_id='choose-fixed-method-profile')
    async def choose(ctx):
        await ctx.deps.enter_node('choose-fixed-method-profile')
        selected, answer = await selection.select(context, ctx.inputs.task,
            gateway=ctx.deps.gateway, request_id=ctx.inputs.request_id)
        native.append((selected, answer))
        return BusinessOutcome('clarify', issues=({
            'code': 'profile_selected', 'answer_digest': answer.answer_digest},))

    builder.add(builder.edge_from(builder.start_node).to(choose))
    builder.add(builder.edge_from(choose).to(builder.end_node))
    code = reviewed_code_digest(__file__, Path(__file__).with_name('profile_method.py'),
                                Path(__file__).with_name('execution_profiles.py'))
    flow = TrustedFlow(FlowRef('engineering.method-profile-selection', '1',
        flow_digest(code, (policy,))), builder.build(), lambda request: {},
        (policy,), code, review_ref)
    request = DecisionRequest(request_id, task, flow.ref, limits=limits)
    result = await run_decision(request, flow=flow, services=services)
    if result.status != 'completed':
        return None, None, result
    if len(native) != 1:
        raise ApplicationError('PROFILE_SELECTION_RESULT_UNAVAILABLE')
    selected, answer = native[0]
    return selected, answer, result


__all__ = ['run_method_profile_selection']
