"""Execute trusted exact review questions on the original Decision runtime.

Questions and evidence refs come from the configured method/business owner,
never wire parameters. This module records answers; Engineering alone reduces
them to a verdict and the conversation owner alone records user acceptance.
"""
from dataclasses import asdict, dataclass

from pydantic_graph import GraphBuilder
from ordessa_decision.definitions import (
    BusinessOutcome, DecisionQuestion, DecisionRequest, DecisionServices,
    FlowRef, RunLimits, TaskBrief, plain,
)
from ordessa_decision.runtime import (
    RunContext, TrustedFlow, flow_digest, reviewed_code_digest, run_decision,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.methods.definitions.models.compiled import ChoiceVocabulary

from .engineering_reviewer_source import (
    JevCheckExecution, JevReviewRun, OriginalJevReviewerSource, frozen_input_digest,
    structured_jev_answer_complete,
)


@dataclass(frozen=True)
class ConfiguredJevQuestion:
    check_key: object
    question: DecisionQuestion
    evidence_refs: tuple
    input_digest: str | None = None
    input_truncated: bool | None = None


def review_binding(plan, request):
    if (request.scope != plan.scope or request.review_id != plan.review_id
            or request.state != 'requested'):
        raise ApplicationError('REVIEW_REQUEST_CHANGED')
    return {'scope':asdict(plan.scope), 'review_id':plan.review_id,
        'plan_request_digest':asdict(plan.request_digest),
        'request_version':request.version, 'fence':request.fence}


async def execute_jev_review(*, plan, request, questions, provider,
        evidence_sink, read_context, request_id, task_revision, review_ref,
        wall_timeout_seconds=120, standard=None, qualification_fixture=False,
        nominal_evidence_only=False):
    """One bounded original run; no retries or incomplete-check substitution.

    Returns (actual run binding, trusted flow, original DecisionResult). A failed
    or unknown run raises with its original result attached for inspection; no
    review response is manufactured and the caller must not resend it.
    """
    binding = review_binding(plan, request)
    if type(qualification_fixture) is not bool or standard is None and not qualification_fixture:
        raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
    if type(nominal_evidence_only) is not bool or nominal_evidence_only and standard is None:
        raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
    expected_keys = plan.check_keys
    if nominal_evidence_only:
        declared = OriginalJevReviewerSource._standard_criteria(plan, standard)
        expected_keys = tuple(key for key in plan.check_keys
            if type(declared[key.criterion_id].answer_vocabulary) is ChoiceVocabulary)
    if (type(questions) is not tuple or not questions
            or any(type(q) is not ConfiguredJevQuestion for q in questions)
            or len({q.check_key for q in questions}) != len(questions)
            or {q.check_key for q in questions} != set(expected_keys)
            or len({q.question.question_id for q in questions}) != len(questions)):
        raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
    criteria = (OriginalJevReviewerSource._standard_criteria(plan, standard, require_choice=True,
        check_keys=expected_keys)
        if standard is not None else None)
    for item in questions:
        expected = dict(binding, check_key=asdict(item.check_key))
        if criteria is not None:
            expected_input_digest = frozen_input_digest(item.question.bounded_state)
            if (type(item.input_digest) is not str
                    or item.input_digest != expected_input_digest
                    or type(item.input_truncated) is not bool):
                raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        if criteria is None:
            options = {'satisfied':'satisfied', 'violated':'violated',
                'insufficient':'insufficient', 'unknown':'unknown'}
        else:
            vocabulary = criteria[item.check_key.criterion_id].answer_vocabulary
            options = {option.option_id:option.description for option in vocabulary.options}
        if (item.question.kind != 'choice'
                or dict(item.question.options) != options
                or plain(item.question.bounded_state).get('engineering_review') != expected
                or type(item.evidence_refs) is not tuple):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
    policies = tuple(dict.fromkeys(q.question.policy_ref for q in questions))
    answers = []
    builder = GraphBuilder(name='ordessa-exact-engineering-review', state_type=dict,
        deps_type=RunContext, input_type=DecisionRequest, output_type=BusinessOutcome,
        auto_instrument=False)

    @builder.step
    async def evaluate(ctx) -> BusinessOutcome:
        await ctx.deps.enter_node('EvaluateFrozenReviewChecks')
        for item in questions:
            answer = await ctx.deps.gateway.decide(item.question)
            answers.append(JevCheckExecution(item.check_key, item.question,
                answer, item.evidence_refs, item.input_digest, item.input_truncated,
                structured_jev_answer_complete(item.question, answer)
                if item.input_digest is not None else None))
        # Completion records source output, never a product approval or grant.
        return BusinessOutcome('clarify', issues=({'code':'engineering_reduction_required'},))

    builder.add(builder.edge_from(builder.start_node).to(evaluate),
        builder.edge_from(evaluate).to(builder.end_node))
    code = reviewed_code_digest(__file__)
    ref = FlowRef('ordessa.product.exact-jev-review', '1', flow_digest(code, policies))
    flow = TrustedFlow(ref, builder.build(), lambda _: {}, policies, code, review_ref)
    flow.validate()
    decision_request = DecisionRequest(request_id,
        TaskBrief(plan.review_id, task_revision, 'Evaluate the exact frozen Engineering review checks.'),
        ref, RunLimits(max_model_attempts=len(questions), max_node_entries=2,
            max_repair_rounds=0, wall_timeout_seconds=wall_timeout_seconds),
        extensions={'ordessa.engineering.review':binding})
    result = await run_decision(decision_request, flow=flow,
        services=DecisionServices(None, None, None, None, provider, evidence_sink,
            {}, read_context, policies, mode='real'))
    if result.status != 'completed' or len(answers) != len(questions):
        error = ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        error.decision_result = result
        raise error
    run = JevReviewRun(plan.scope, plan.review_id, plan.request_digest,
        request.version, request.fence, result.run_id, decision_request, tuple(answers),
        evidence_only=nominal_evidence_only)
    return run, flow, result
