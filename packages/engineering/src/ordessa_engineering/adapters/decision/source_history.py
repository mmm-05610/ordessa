"""Explicit historical source-review proof using frozen decision/1 data/codec.

No Graph, writer, runner or new execution right exists here. Reviewed code
identities bind preserved original source bytes, never the current adapter.
"""
from dataclasses import dataclass
from collections.abc import Mapping

from ordessa_decision.historical.models import (DecisionAnswer, DecisionQuestion,
    DecisionRequest, DecisionResult, FlowRef, PolicyRef, RunLimits, RunManifest, TaskBrief)
from ordessa_decision.historical.values import digest
from ...application.contracts.errors import ApplicationError

FROZEN_CODE_DIGESTS = {
    'single': 'sha256:7f9554d36dc232214f4032f1181464bc57757cd43f62581f6c9e8a19f953de99',
    'sections': 'sha256:6b895263fe4173730dd7041277f950b46d4914a76761c3adbca6888d403075d6',
}


@dataclass(frozen=True)
class HistoricalFlowSelection:
    ref: FlowRef
    policy_refs: tuple


def historical_selection(request, *, contract_version):
    policies = tuple(PolicyRef(p.policy_id, p.version, p.content_digest) for p in request.policy_refs)
    code = FROZEN_CODE_DIGESTS['sections' if len(policies) == 2 else 'single']
    flow = HistoricalFlowSelection(FlowRef('engineering.source-review', contract_version,
        digest('flow', {'reviewed_code_digest': code, 'policy_refs': policies})), policies)
    questions = tuple(DecisionQuestion(q.question_id, q.version, q.kind, q.bounded_state,
        q.question_text, q.options, q.scale, q.evidence_ids, q.allowed_answer_ids,
        None if q.policy_ref is None else PolicyRef(q.policy_ref.policy_id,q.policy_ref.version,q.policy_ref.content_digest))
        for q in request.questions)
    # The historical brief bound original question digests, which differ from
    # decision-question/1 digests; never substitute current digest bytes.
    inputs = request.task.inputs
    if contract_version != '1':
        body = dict(inputs[0]); body['questions'] = tuple({'question_id':q.question_id,
            'version':q.version,'question_digest':q.question_digest} for q in questions)
        inputs = (body,)
    task = TaskBrief(request.task.task_id, request.task.task_revision, request.task.goal,
                     inputs=inputs, boundaries=request.task.boundaries)
    old = DecisionRequest(request.request_id, task, flow.ref,
        RunLimits(max_model_attempts=len(questions), max_node_entries=1,
                  wall_timeout_seconds=int(request.timeout_seconds), cleanup_timeout_seconds=2))
    return questions, flow, old


def _verified_native_result(native, run_id, request, flow, provider_binding):
    """Authenticate the public reader projection against this exact run selection."""
    if (not isinstance(native, Mapping) or native.get('status') != 'completed'
            or native.get('call_evidence') != 'recorded'):
        raise ApplicationError('REVIEW_SOURCE_UNAVAILABLE')
    terminal = native.get('terminal')
    events = native.get('events')
    if (not isinstance(terminal, Mapping) or not isinstance(events, (tuple, list))
            or not events or not isinstance(events[0], Mapping)):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    started = events[0].get('payload')
    raw_result = terminal.get('result')
    try:
        manifest = RunManifest(request.request_digest, flow.ref, flow.policy_refs,
            request.limits, provider_binding)
        result = DecisionResult.from_dict(raw_result)
    except Exception:
        raise ApplicationError('REVIEW_SOURCE_INVALID') from None
    terminal_digest = terminal.get('terminal_digest', terminal.get('result_digest'))
    if (not isinstance(started, Mapping)
            or started.get('type') != 'run.started'
            or started.get('run_id') != run_id
            or started.get('request_digest') != request.request_digest
            or started.get('flow_digest') != flow.ref.content_digest
            or started.get('manifest_digest') != manifest.manifest_digest
            or terminal.get('run_id') != run_id
            or terminal.get('status') != 'completed'
            or result.status != 'completed'
            or result.run_id != run_id
            or result.request_id != request.request_id
            or result.task_revision != request.task.task_revision
            or result.flow_ref != flow.ref
            or result.run_manifest_digest != manifest.manifest_digest
            or result.effective_policy_refs != tuple(flow.policy_refs)
            or ('result_digest' in terminal and terminal.get('result_digest') != terminal_digest)
            or terminal_digest != result.result_digest):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    return result



def historical_answers(native, run_id, request, flow, questions, provider, options):
    result = _verified_native_result(native, run_id, request, flow, provider[0])
    issues = result.to_dict().get('outcome', {}).get('issues', [])
    try:
        if len(issues) != len(questions) or any(issue.get('code') != 'source-review-answer' for issue in issues):
            raise ValueError()
        pairs = [(issue.get('check_id', questions[0].question_id),
                  DecisionAnswer.from_dict(issue['answer'])) for issue in issues]
        events = native['events']
        if any(not isinstance(e, Mapping) or not isinstance(e.get('payload'), Mapping) for e in events):
            raise ValueError()
        intents = [e['payload'] for e in events if e['payload'].get('type') == 'call.intent']
        responses = [e['payload'] for e in events if e['payload'].get('type') == 'call.response']
        if (len(intents) != len(questions) or len(responses) != len(questions)
                or any(type(i.get('call_id')) is not str or not i['call_id'] for i in intents + responses)
                or len({i['call_id'] for i in intents}) != len(questions)
                or len({i['call_id'] for i in responses}) != len(questions)
                or any(type(i.get('attempt')) is not int for i in intents)
                or sorted(i['attempt'] for i in intents) != list(range(1, len(questions) + 1))):
            raise ValueError()
    except Exception:
        raise ApplicationError('REVIEW_SOURCE_INVALID') from None
    checked = {}
    for attempt, question in enumerate(questions, 1):
        answers = [answer for key, answer in pairs if key == question.question_id]
        calls = [intent for intent in intents if intent.get('question_digest') == question.question_digest]
        if len(answers) != 1 or len(calls) != 1:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        answer, intent = answers[0], calls[0]
        replies = [response for response in responses if response['call_id'] == intent['call_id']]
        if len(replies) != 1:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        response = replies[0]
        if (intent.get('attempt') != attempt or response.get('attempt') != attempt
                or intent.get('run_id') != run_id or response.get('run_id') != run_id
                or response.get('answer_digest') != answer.answer_digest
                or answer.question_id != question.question_id or answer.kind != 'choice'
                or type(answer.value) is not str or answer.value not in options
                or ('question_digest' in answer.provider_receipt
                    and answer.provider_receipt['question_digest'] != question.question_digest)
                or ('provider_settings_digest' in answer.provider_receipt
                    and answer.provider_receipt['provider_settings_digest'] != provider[1])):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        checked[question.question_id] = answer
    return checked
