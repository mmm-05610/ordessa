"""Trusted native graph assembly. Business repair is an upstream graph edge."""
from dataclasses import dataclass, field
from pathlib import Path
import json
from pydantic_graph import GraphBuilder, StepContext
from ordessa_decision.contracts import *
from ordessa_decision.runtime import TrustedFlow, flow_digest, reviewed_code_digest
from .task_gate import assess_task, compile_task_gate, load_task_gate_policy, GateResult
from .selection import assignment_round, validate_policy, AssignmentRound

@dataclass
class AssignmentState:
    gate: GateResult | None = None
    round: AssignmentRound | None = None
    feedback: object = None
    previous_progress: str | None = None
    trace: list = field(default_factory=list)

def load_assignment_policy(*, task_gate=None, selection=None, task_gate_facts=None):
    task_gate=task_gate or load_task_gate_policy()
    if selection is None:
        selection=json.loads(Path(__file__).with_name('selection_policy.json').read_text())
    return freeze({'task_gate':plain(task_gate),'selection':plain(selection),'task_gate_facts':plain(task_gate_facts or {})})

def assignment_policy_refs(policy):
    return (PolicyRef(policy['task_gate']['policy_id'],policy['task_gate']['version'],digest('policy',policy['task_gate'])),
            PolicyRef('selection',policy['selection']['version'],digest('policy',policy['selection'])),
            PolicyRef('assignment.host-facts','1',digest('policy',policy['task_gate_facts'])))

def build_assignment_flow(policy, *, alternate=False, read_query=None):
    """Policy and optional registered read query are explicitly host assembled.

    Alternate flow reads immutable facts before model assessment; default flow
    completes task assessment first. Neither flow applies or starts any work.
    """
    policy=freeze(plain(policy)); refs=assignment_policy_refs(policy)
    code=reviewed_code_digest(*sorted(Path(__file__).parent.glob('*.py')))
    query_digest=digest('descriptor',plain(read_query)) if read_query is not None else None
    code=digest('flow',{'source':code,'alternate':alternate,'read_query_digest':query_digest})
    flow_ref=FlowRef('agent.assignment.alternate' if alternate else 'agent.assignment','1',flow_digest(code,refs))
    g=GraphBuilder(name=flow_ref.flow_id,state_type=AssignmentState,input_type=DecisionRequest,output_type=BusinessOutcome,auto_instrument=False)
    async def enter(ctx,name):
        await ctx.deps.enter_node(name); ctx.state.trace.append(name)
    @g.step
    async def check_policy(ctx:StepContext[AssignmentState,object,DecisionRequest])->DecisionRequest:
        await enter(ctx,'CheckPolicy')
        if ctx.deps.services.policy!=policy: raise ContractError('policy_binding_mismatch')
        validate_policy(policy['selection'])
        compile_task_gate(ctx.deps.request.task,ctx.deps,policy['task_gate'])
        return ctx.deps.request
    @g.step
    async def task_gate(ctx:StepContext[AssignmentState,object,DecisionRequest])->GateResult:
        await enter(ctx,'HardTaskGate')
        ctx.state.gate=await assess_task(ctx.deps.request.task,ctx.deps,policy['task_gate'])
        return ctx.state.gate
    @g.step
    async def read_facts(ctx)->DecisionRequest:
        await enter(ctx,'ReadFacts')
        if read_query is not None:
            if ctx.deps.services.read is None: raise ContractError('read_port_missing')
            value=await ctx.deps.services.read.observe(read_query,ctx.deps.services.read_context)
            if not isinstance(value,ObservationBatch): raise ContractError('read_protocol_invalid')
            # No global snapshot claim or mutable source state retained.
            ctx.state.trace.append('read:'+value.query_ref)
        return ctx.deps.request
    @g.step
    async def finish_gate(ctx)->BusinessOutcome:
        await enter(ctx,'FinishBusiness')
        return BusinessOutcome(ctx.state.gate.status,issues=ctx.state.gate.issues)
    @g.step
    async def select(ctx)->AssignmentRound:
        await enter(ctx,'SelectAssignment')
        ctx.state.round=await assignment_round(ctx.deps.request.task,ctx.deps,policy['selection'],
            feedback=ctx.state.feedback,previous_progress_digest=ctx.state.previous_progress)
        return ctx.state.round
    @g.step
    async def repair(ctx)->DecisionRequest:
        await enter(ctx,'Repair'); await ctx.deps.enter_repair()
        ctx.state.feedback=ctx.state.round.repair_feedback
        ctx.state.previous_progress=ctx.state.round.progress_digest
        return ctx.deps.request
    @g.step
    async def finish(ctx)->BusinessOutcome:
        await enter(ctx,'FinishReady' if ctx.state.round.outcome.disposition=='ready' else 'FinishBusiness')
        return ctx.state.round.outcome
    # Only upstream GraphBuilder determines node routing.
    if alternate:
        g.add(g.edge_from(g.start_node).to(check_policy),g.edge_from(check_policy).to(read_facts),g.edge_from(read_facts).to(task_gate))
        passed=select
    else:
        g.add(g.edge_from(g.start_node).to(check_policy),g.edge_from(check_policy).to(task_gate),g.edge_from(read_facts).to(select))
        passed=read_facts
    g.add(g.edge_from(task_gate).to(g.decision(node_id='task-disposition')
        .branch(g.match(GateResult,matches=lambda r:r.status=='gate_pass').to(passed))
        .branch(g.match(GateResult).to(finish_gate))))
    g.add(g.edge_from(select).to(g.decision(node_id='repair-route')
        .branch(g.match(AssignmentRound,matches=lambda r:r.repair_feedback is not None).to(repair))
        .branch(g.match(AssignmentRound).to(finish))))
    g.add(g.edge_from(repair).to(select),g.edge_from(finish).to(g.end_node),g.edge_from(finish_gate).to(g.end_node))
    return TrustedFlow(flow_ref,g.build(),lambda request:AssignmentState(),refs,code,'specs/031-JD009-reviewed')
