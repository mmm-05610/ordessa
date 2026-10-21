"""Reproduce finite historical codec vectors; no Graph, sink, runner or model."""
from dataclasses import asdict
from pathlib import Path
from hashlib import sha256
import json
from ordessa_decision.historical.models import (BusinessOutcome, DecisionAnswer, DecisionQuestion,
    DecisionRequest, DecisionResult, FlowRef, PolicyRef, RunLimits, RunManifest, TaskBrief)
from ordessa_decision.historical.codec import record, terminal
from ordessa_decision.historical.values import canonical, digest

HERE = Path(__file__).parent
RUN = '12345678-1234-4234-8234-123456789abc'
policy = PolicyRef('source-review-binding', '2', 'sha256:' + 'a' * 64)
input_policy = PolicyRef('engineering-source-review-input/1', '1', 'sha256:' + 'b' * 64)
policies = (policy, input_policy)
provenance = json.loads((HERE / 'provenance.json').read_text())
for name, selected in [('single', ['source_reviewer.py']), ('sections', ['source_reviewer.py', 'source_sections.py'])]:
    h = sha256(b'decision.reviewed-code/1\n')
    for item in sorted(selected):
        raw = (HERE / (item + '.txt')).read_bytes()
        h.update(str(len(raw)).encode() + b'\n' + raw + b'\n')
    assert 'sha256:' + h.hexdigest() == provenance['reviewed_code_digests'][name]
flow = FlowRef('engineering.source-review', '3', digest('flow', {
    'reviewed_code_digest': provenance['reviewed_code_digests']['sections'], 'policy_refs': policies}))
request = DecisionRequest('history-source-request', TaskBrief('historical-review', '0', 'Frozen review vector'),
                          flow, RunLimits(max_model_attempts=8, max_node_entries=1, wall_timeout_seconds=240, cleanup_timeout_seconds=2))
manifest = RunManifest(request.request_digest, flow, policies, request.limits, 'controlled-frozen-provider/1')
questions = tuple(DecisionQuestion('check-' + str(i), '2', 'choice', {}, 'Frozen check',
    options={'passed': 'Passed', 'not_passed': 'Not passed'}, policy_ref=policy) for i in range(8))
answers = tuple(DecisionAnswer(q.question_id, 'choice', 'passed', {'selection_status': 'unique'}) for q in questions)
result = DecisionResult(RUN, request.request_id, '0', flow, manifest.manifest_digest, policies, 'completed',
    outcome=BusinessOutcome('revise', issues=tuple({'code': 'source-review-answer', 'check_id': a.question_id,
        'answer': a.to_dict()} for a in answers)), call_evidence='recorded')
payloads = [{'type': 'run.started', 'run_id': RUN, 'request_digest': request.request_digest,
             'flow_digest': flow.content_digest, 'manifest_digest': manifest.manifest_digest}]
for attempt, (q, a) in enumerate(zip(questions, answers), 1):
    payloads.extend([{'type': 'call.intent', 'run_id': RUN, 'call_id': 'call-' + str(attempt),
                     'attempt': attempt, 'question_digest': q.question_digest},
                    {'type': 'call.response', 'run_id': RUN, 'call_id': 'call-' + str(attempt),
                     'attempt': attempt, 'answer_digest': a.answer_digest}])
events = []
for payload in payloads:
    events.append(record(payload, len(events) + 1, events[-1]['digest'] if events else None, 65536))
safe, td = terminal({'run_id': RUN, 'status': 'completed', 'result': result.to_dict(),
                     'result_digest': result.result_digest})
envelope = {'terminal': safe, 'expected_last_seq': len(events), 'last_digest': events[-1]['digest'],
            'terminal_digest': td}
envelope['digest'] = digest('event', envelope)
events.append(record({'type': 'terminal.commit', 'run_id': RUN, 'result_digest': td,
                      'terminal_record_digest': envelope['digest']}, len(events) + 1, events[-1]['digest'], 65536))
vector = {'run_id': RUN, 'request': request.to_dict(), 'questions': [q.to_dict() for q in questions],
          'policies': [asdict(p) for p in policies], 'provider_binding': 'controlled-frozen-provider/1',
          'events_jsonl': ''.join(canonical(e).decode() + '\n' for e in events),
          'terminal_json': canonical(envelope).decode()}
(HERE / 'historical-vector.json').write_text(json.dumps(vector, indent=2) + '\n')
