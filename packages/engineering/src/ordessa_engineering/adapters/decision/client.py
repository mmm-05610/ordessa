"""Finite ReviewJudgement selection through the public decision_runtime API."""
from __future__ import annotations
import asyncio
import inspect
from typing import Any
import uuid
from decision_runtime import BusinessOutcome, DecisionAnswer, DecisionQuestion, DecisionRequest, DecisionServices, FlowRef, MemoryEvidenceSink, PolicyRef, ReadContext, RunContext, RunLimits, TaskBrief, TrustedFlow, flow_digest, reviewed_code_digest, run_decision
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.domain.reviews.library_judgements import ReviewVerdict
from ordessa_engineering.domain.reviews.judgement_policy import ReviewFacts, ReviewPolicy
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_to_dict

class _LocalReviewProvider:
    """Deterministic local selector; it never contacts a model or harness."""
    binding_ref = 'ordessa-engineering/local-review-selector/1'
    settings_digest = 'sha256:' + '0' * 64

    def __init__(self, precedence: tuple[str, ...], rules: dict[str, str]):
        self.policy = ReviewPolicy(precedence, rules)
        self.answer: DecisionAnswer | None = None

    async def decide(self, question: DecisionQuestion, _context: Any) -> DecisionAnswer:
        if question.question_id != 'engineering.review-judgement' or question.kind != 'choice':
            raise EngineeringError('review_question_mismatch')
        selected = self.policy._select(dict(question.bounded_state))
        if selected not in question.options:
            raise EngineeringError('review_verdict_not_offered')
        self.answer = DecisionAnswer(question.question_id, 'choice', selected, {'selection_status': 'selected', 'provider': self.binding_ref}, {'status': 'known'})
        return self.answer

def _flow(policy_ref: PolicyRef) -> TrustedFlow:
    from pydantic_graph import GraphBuilder
    builder = GraphBuilder(name='engineering.review-judgement/1', state_type=dict, deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome, auto_instrument=False)

    @builder.step(node_id='select-policy-bound-review-verdict')
    async def select_verdict(ctx):
        await ctx.deps.enter_node('select-policy-bound-review-verdict')
        state = dict(ctx.inputs.task.inputs[0])
        answer = await ctx.deps.gateway.decide(DecisionQuestion(question_id='engineering.review-judgement', version='1', kind='choice', bounded_state=state, question_text='Select the finite verdict for these computed checks.', options={verdict: verdict for verdict in ReviewVerdict.ALL}, evidence_ids=tuple(state.get('evidence_refs', ())), allowed_answer_ids=ReviewVerdict.ALL, policy_ref=policy_ref))
        return BusinessOutcome('revise', issues=({'code': 'review-judgement-selected', 'answer_digest': answer.answer_digest},))
    builder.add(builder.edge_from(builder.start_node).to(select_verdict))
    builder.add(builder.edge_from(select_verdict).to(builder.end_node))
    code = reviewed_code_digest(__file__, inspect.getfile(ReviewPolicy), inspect.getfile(ReviewVerdict))
    flow_ref = FlowRef('engineering.review-judgement', '1', flow_digest(code, (policy_ref,)))
    return TrustedFlow(flow_ref, builder.build(), lambda request: dict(request.task.inputs[0]), (policy_ref,), code, 'c09-reviewed-local-finite-selector/1')

def select_review(facts: ReviewFacts, *, policy_material: dict[str, Any], policy_ref, evidence_refs: tuple[str, ...]) -> dict[str, Any]:
    """Run an offline, bounded public Decision flow and retain its evidence."""
    precedence = tuple(policy_material.get('precedence', ()))
    rules = policy_material.get('rules', {})
    provider = _LocalReviewProvider(precedence, rules)
    read_context = ReadContext(object(), 'engineering.review-local')
    sink = MemoryEvidenceSink(read_context=read_context)
    runtime_policy = PolicyRef(policy_ref.stable_id, str(policy_ref.revision), policy_ref.digest)
    flow = _flow(runtime_policy)
    request = DecisionRequest(request_id='engineering-review-' + uuid.uuid4().hex, task=TaskBrief('engineering-review', '1', 'Choose a bounded review verdict from computed source, standard and summary facts.', inputs=({**facts.as_dict(), 'evidence_refs': evidence_refs},), boundaries=('offline-local', 'computed-facts-only'), acceptance_criteria=('Preserve an independent ReviewJudgement verdict.',)), flow_ref=flow.ref, limits=RunLimits(max_model_attempts=1, max_node_entries=1, wall_timeout_seconds=10, cleanup_timeout_seconds=2))
    services = DecisionServices(None, None, None, None, provider, sink, {'precedence': precedence}, read_context, (runtime_policy,), mode='offline')
    result = asyncio.run(run_decision(request, flow=flow, services=services))
    evidence = asyncio.run(sink.read(result.run_id, read_context))
    if result.status != 'completed' or result.outcome is None or provider.answer is None or (evidence.get('status') != 'completed'):
        raise EngineeringError('decision_review_unavailable')
    if not result.outcome.issues or result.outcome.issues[0].get('answer_digest') != provider.answer.answer_digest:
        raise EngineeringError('decision_answer_binding')
    verdict = provider.answer.value
    if verdict not in ReviewVerdict.ALL:
        raise EngineeringError('decision_verdict_invalid')
    return {'verdict': verdict, 'decision_run': result.to_dict(), 'decision_evidence': evidence, 'answer': provider.answer.to_dict(), 'answer_digest': provider.answer.answer_digest, 'policy_ref': material_ref_to_dict(policy_ref)}
